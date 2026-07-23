"""spell_check_pipeline.py — 한국어 맞춤법·띄어쓰기 하이브리드 교정 파이프라인.

build_site.py 가 정적 HTML을 렌더링하기 전에, briefing.json 의 AI 요약문(요약·30초
브리핑 등)을 정제하기 위한 모듈. 다음 다단계 흐름을 따른다.

    1) 유효성 검사 + 규칙/경량 1차 교정(빠름·저비용)
       - PyKoSpacing(딥러닝 띄어쓰기) 또는 py-hanspell(맞춤법)이 설치돼 있으면 사용,
         없으면 내장 규칙 정규화(공백·문장부호 띄어쓰기)만 수행.
    2) LLM(문맥) 2차 심화 교정 — 어미·문체·의미를 바꾸지 못하도록 제한적 지시.
       - LLM 대신 KoBART 로컬 경량 모델로도 교체 가능하도록 백엔드를 추상화.
    3) 검증 필터 — 원본과 교정본의 글자 수 차이가 임계치를 넘으면(과교정·할루시네이션)
       모델 출력을 버리고 1차 결과를 최종 채택하는 방어 로직.

설계 원칙
    * 모든 외부 의존성은 선택적(optional import)이며, 어떤 단계가 실패해도 예외를 던지지
      않고 직전 단계(또는 원본)로 안전하게 폴백한다 — 빌드는 절대 멈추지 않는다.
    * 외부 API 키는 .env(config.py 경유)로 관리하며, 이 모듈은 기존 llm.py 를 재사용한다.
    * 사용법:  import spell_check_pipeline as scp;  scp.correct(text)
               scp.correct_briefing(briefing)   # 이슈 요약을 일괄 정제(in-place)
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Callable, Optional, Protocol

try:  # 설정은 있으면 쓰고, 없으면 환경변수/기본값으로 동작
    import config  # type: ignore
except Exception:  # pragma: no cover
    config = None  # type: ignore


# ─────────────────────────────────────────────────────────────────────────────
# 설정 헬퍼 (config.py > 환경변수 > 기본값)
# ─────────────────────────────────────────────────────────────────────────────
def _cfg(name: str, default):
    if config is not None and hasattr(config, name):
        return getattr(config, name)
    raw = os.environ.get(name)
    if raw is None:
        return default
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, float):
        try:
            return float(raw)
        except ValueError:
            return default
    return raw


def _enabled() -> bool:
    return bool(_cfg("ENABLE_SPELLCHECK", False))


def _max_delta() -> float:
    # 교정 전후 허용 글자 수 변화 비율(기본 15%). 초과 시 모델 출력 폐기.
    return float(_cfg("SPELLCHECK_MAX_DELTA", 0.15))


# ─────────────────────────────────────────────────────────────────────────────
# 1) 규칙/경량 1차 교정 백엔드 (추상화)
# ─────────────────────────────────────────────────────────────────────────────
class Corrector(Protocol):
    name: str

    def correct(self, text: str) -> str: ...


# 내장 규칙 정규화 — 의존성 없이 항상 동작하는 안전한 최소 교정.
# (문장 부호 주변 띄어쓰기, 중복 공백, 흔한 자명한 오타)
_MULTISPACE = re.compile(r"[ \t ]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.!?%)\]}·…])")
_NO_SPACE_AFTER_PUNCT = re.compile(r"([,.!?])(?=[^\s\d)\]}\"'’”.])")
_SPACE_INSIDE_OPEN = re.compile(r"([(\[{“‘])\s+")
# 매우 자명한 붙여쓰기 오류만(문맥 불필요, 과교정 위험 낮음)
_SAFE_TYPOS = [
    (re.compile(r"할수있"), "할 수 있"),
    (re.compile(r"할수없"), "할 수 없"),
    (re.compile(r"수있습니다"), "수 있습니다"),
    (re.compile(r"에대한"), "에 대한"),
    (re.compile(r"에대해"), "에 대해"),
    (re.compile(r"것으로보인다"), "것으로 보인다"),
]


class BuiltinCorrector:
    name = "builtin"

    def correct(self, text: str) -> str:
        s = text.replace("​", "").replace("\t", " ")
        s = _SPACE_BEFORE_PUNCT.sub(r"\1", s)
        s = _SPACE_INSIDE_OPEN.sub(r"\1", s)
        s = _NO_SPACE_AFTER_PUNCT.sub(r"\1 ", s)
        for pat, rep in _SAFE_TYPOS:
            s = pat.sub(rep, s)
        s = _MULTISPACE.sub(" ", s)
        return s.strip()


class PyKoSpacingCorrector:
    """딥러닝 기반 띄어쓰기 교정(pykospacing). 설치돼 있을 때만 사용."""

    name = "pykospacing"

    def __init__(self) -> None:
        from pykospacing import Spacing  # type: ignore  # 선택적 의존성

        self._spacing = Spacing()
        self._builtin = BuiltinCorrector()

    def correct(self, text: str) -> str:
        spaced = self._spacing(text)
        return self._builtin.correct(spaced)


class HanspellCorrector:
    """py-hanspell(맞춤법 검사). 설치돼 있을 때만 사용."""

    name = "hanspell"

    def __init__(self) -> None:
        from hanspell import spell_checker  # type: ignore  # 선택적 의존성

        self._checker = spell_checker
        self._builtin = BuiltinCorrector()

    def correct(self, text: str) -> str:
        # hanspell 은 길이 제한(약 500자)이 있어 문장 단위로 나눠 처리.
        out = []
        for chunk in _split_sentences(text):
            try:
                out.append(self._checker.check(chunk).checked)
            except Exception:
                out.append(chunk)
        return self._builtin.correct(" ".join(out))


@lru_cache(maxsize=1)
def _rule_corrector() -> Corrector:
    """설정된(또는 자동 감지된) 1차 교정 백엔드를 1회 생성해 캐시."""
    backend = str(_cfg("SPELLCHECK_RULE_BACKEND", "auto")).lower()
    order = (
        [backend]
        if backend in ("pykospacing", "hanspell", "builtin")
        else ["pykospacing", "hanspell", "builtin"]  # auto: 가능한 것부터
    )
    for name in order:
        try:
            if name == "pykospacing":
                return PyKoSpacingCorrector()
            if name == "hanspell":
                return HanspellCorrector()
            if name == "builtin":
                return BuiltinCorrector()
        except Exception as e:  # 미설치/로드 실패 → 다음 후보
            print(f"[spellcheck] 1차 백엔드 '{name}' 사용 불가: {e}")
    return BuiltinCorrector()


# ─────────────────────────────────────────────────────────────────────────────
# 2) 심화(문맥) 2차 교정 백엔드 — LLM 또는 KoBART (추상화)
# ─────────────────────────────────────────────────────────────────────────────
_SYSTEM = (
    "당신은 한국어 맞춤법·띄어쓰기 교정기입니다. 입력 문장의 맞춤법과 띄어쓰기 오류만 "
    "고치세요. 어미·문체·말투·의미·문장 수를 절대 변경하지 말고, 내용을 추가하거나 "
    "삭제하지 마세요. 설명이나 사족 없이, 맞춤법이 교정된 텍스트만 출력하세요."
)
_DEEP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"corrected": {"type": "string", "description": "맞춤법만 교정한 원문"}},
    "required": ["corrected"],
}


class LLMCorrector:
    """기존 llm.py(CLOVA/Gemini/Claude) 재사용. 제한적 지시로 문체 변경 차단."""

    name = "llm"

    def correct(self, text: str) -> Optional[str]:
        try:
            import llm  # type: ignore
        except Exception:
            return None
        try:
            result, _engine = llm.call_with_fallback("", _SYSTEM, text, _DEEP_SCHEMA)
        except Exception as e:  # 엔진 없음/네트워크 실패 등 → 2차 건너뜀
            print(f"[spellcheck] LLM 2차 교정 건너뜀: {e}")
            return None
        out = (result or {}).get("corrected")
        return out if isinstance(out, str) and out.strip() else None


class KoBARTCorrector:
    """(선택) KoBART 기반 한국어 맞춤법 전용 경량 모델 로컬 추론.

    transformers 가 설치되고 SPELLCHECK_KOBART_MODEL 이 지정된 경우에만 로드.
    LLM API 비용 없이 로컬에서 2차 교정을 수행하는 대체 인터페이스.
    """

    name = "kobart"

    def __init__(self) -> None:
        from transformers import pipeline  # type: ignore  # 선택적 의존성

        model = str(_cfg("SPELLCHECK_KOBART_MODEL", "")) or "cosmoquester/bart-ko-mini"
        self._pipe = pipeline("text2text-generation", model=model)

    def correct(self, text: str) -> Optional[str]:
        try:
            out = self._pipe(text, max_length=len(text) + 32, num_beams=2)
            gen = (out[0] or {}).get("generated_text")
            return gen if isinstance(gen, str) and gen.strip() else None
        except Exception as e:
            print(f"[spellcheck] KoBART 추론 실패: {e}")
            return None


@lru_cache(maxsize=1)
def _deep_corrector() -> Optional[object]:
    """2차(심화) 교정 백엔드. 'none'이면 비활성."""
    backend = str(_cfg("SPELLCHECK_MODEL_BACKEND", "llm")).lower()
    if backend in ("none", "off", ""):
        return None
    try:
        if backend == "kobart":
            return KoBARTCorrector()
        return LLMCorrector()
    except Exception as e:
        print(f"[spellcheck] 2차 백엔드 '{backend}' 사용 불가: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 3) 검증 필터 (과교정·할루시네이션 방지)
# ─────────────────────────────────────────────────────────────────────────────
def _within_delta(original: str, candidate: str, max_delta: float) -> bool:
    """맞춤법 교정은 글자 수가 크게 늘지 않는다. 임계 초과 시 후보를 폐기."""
    if not candidate or not candidate.strip():
        return False
    base = max(len(original), 1)
    delta = abs(len(candidate) - len(original)) / base
    if delta > max_delta:
        print(f"[spellcheck] 2차 결과 폐기(길이차 {delta:.0%} > {max_delta:.0%}) — 1차 채택")
        return False
    # 사족/메타 응답 방어: 지시문을 되풀이하거나 접두 설명을 붙인 경우
    lowered = candidate.strip()
    if lowered.startswith(("교정", "다음", "결과", "출력", "-", "•")):
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────────────────────
_SENT_SPLIT = re.compile(r"(?<=[.!?。])\s+")


def _split_sentences(text: str) -> list[str]:
    parts = [p for p in _SENT_SPLIT.split(text.strip()) if p]
    return parts or [text.strip()]


def correct(text: Optional[str], *, deep: Optional[bool] = None) -> str:
    """텍스트 1건을 교정해 반환. 어떤 경우에도 문자열을 안전하게 반환한다.

    deep=None 이면 config 설정(SPELLCHECK_MODEL_BACKEND)을 따르고,
    deep=False 면 1차(규칙/경량)까지만 수행한다.
    """
    if not text or not text.strip():
        return text or ""
    if not _enabled():
        return text  # 기능 비활성 시 원본 그대로(무해)

    return _correct_cached(text, deep if deep is not None else True)


@lru_cache(maxsize=2048)
def _correct_cached(text: str, deep: bool) -> str:
    # 1차: 규칙/경량
    try:
        stage1 = _rule_corrector().correct(text) or text
    except Exception as e:
        print(f"[spellcheck] 1차 교정 실패: {e}")
        stage1 = text

    # 2차: 문맥(LLM/KoBART) — 검증 필터 통과 시에만 채택
    if deep:
        corrector = _deep_corrector()
        if corrector is not None:
            try:
                candidate = corrector.correct(stage1)  # type: ignore[attr-defined]
            except Exception as e:
                print(f"[spellcheck] 2차 교정 실패: {e}")
                candidate = None
            if candidate and _within_delta(stage1, candidate, _max_delta()):
                return candidate
    return stage1


def correct_many(texts: list[str], *, deep: Optional[bool] = None) -> list[str]:
    return [correct(t, deep=deep) for t in texts]


# briefing.json 안에서 교정할 텍스트 필드 경로.
_ISSUE_TEXT_FIELDS = ("summary", "label")
_CONSTRUCTIVE_FIELDS = ("progressive_concern", "conservative_claim", "common_ground")


def correct_briefing(briefing: dict, *, deep: Optional[bool] = None) -> dict:
    """briefing dict 의 이슈 요약/30초 브리핑 텍스트를 in-place 로 정제해 반환.

    기능이 비활성(ENABLE_SPELLCHECK=off)이면 아무것도 하지 않고 그대로 반환한다.
    """
    if not _enabled() or not isinstance(briefing, dict):
        return briefing
    issues = briefing.get("issues") or []
    n = 0
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        for f in _ISSUE_TEXT_FIELDS:
            v = issue.get(f)
            if isinstance(v, str) and v.strip():
                fixed = correct(v, deep=deep)
                if fixed != v:
                    issue[f] = fixed
                    n += 1
        cons = issue.get("constructive")
        if isinstance(cons, dict):
            for f in _CONSTRUCTIVE_FIELDS:
                v = cons.get(f)
                if isinstance(v, str) and v.strip():
                    fixed = correct(v, deep=deep)
                    if fixed != v:
                        cons[f] = fixed
                        n += 1
    if n:
        print(f"[spellcheck] {n}개 텍스트 필드 교정 적용")
    return briefing
