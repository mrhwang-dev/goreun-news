"""AI 단계 — 다중 모델(Multi-LLM) 라우팅.

1) 1차 분류 (Gemini 2.5 Flash, 폴백 Claude):
   후보 클러스터 전체를 대상으로 노이즈 필터링(만평·고정 코너 등 제외),
   분야 지정, 임시 라벨·요약 생성. 대규모 단순 분류라 가성비 모델에 할당.
2) 정밀 요약 (Claude, 폴백 Gemini):
   점수 상위 핫이슈(config.REFINE_TOP_ISSUES)만 제한 호출 —
   매체 성향 분포를 참고한 편향 교차 검증 + 최종 중립 3문장 리포트.
3) 정책뉴스 요약 (Claude, 폴백 Gemini): 공공누리 본문 기반 정밀 요약.

- 캐시(data/cache.json): 내용이 바뀌지 않은 클러스터·기사는 재호출하지 않는다.
- 개별 단계가 모두 실패해도 예외를 삼켜 파이프라인(전체 Actions)은 계속 돈다.
- 근거 데이터는 기존과 동일: 언론사 기사는 '제목'만, 정책뉴스만 본문 사용.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import config
from llm import call_with_fallback

CACHE_PATH = Path(__file__).resolve().parent / "data" / "cache.json"
CACHE_TTL_SECONDS = 3 * 24 * 3600

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "입력에 표시된 클러스터 번호"},
                    "keep": {
                        "type": "boolean",
                        "description": "뉴스 이슈면 true. 만평·운세·날씨 코너, 광고성, 의미 없는 묶음이면 false",
                    },
                    "label": {"type": "string", "description": "중립적 이슈 제목(명사형)"},
                    "summary": {"type": "string", "description": "2~3문장 중립 요약"},
                    "category": {"type": "string", "enum": config.ISSUE_CATEGORIES},
                },
                "required": ["id", "keep", "label", "summary", "category"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clusters"],
    "additionalProperties": False,
}

REFINE_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "입력에 표시된 이슈 번호"},
                    "label": {"type": "string", "description": "최종 중립 이슈 제목(명사형)"},
                    "summary": {"type": "string", "description": "편향 교차 검증을 거친 3문장 중립 리포트"},
                },
                "required": ["id", "label", "summary"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["issues"],
    "additionalProperties": False,
}

POLICY_SCHEMA = {
    "type": "object",
    "properties": {
        "briefs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "입력에 표시된 기사 번호"},
                    "summary": {"type": "string", "description": "2~3문장 핵심 요약"},
                },
                "required": ["id", "summary"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["briefs"],
    "additionalProperties": False,
}

SYSTEM_TRIAGE = """너는 뉴스 애그리게이터 '고른뉴스'의 1차 분류기다. 같은 사건을 다룬 여러 언론사의 기사 '제목'들이 클러스터로 묶여 주어진다.

각 클러스터에 대해:
- keep: 실제 뉴스 사건이면 true. 만평·오늘의운세·날씨 고정 코너, 부고·인사 단신 모음, 광고성 기사, 서로 무관한 제목이 잘못 묶인 경우는 false.
- label: 중립적인 이슈 제목을 명사형으로 새로 쓴다. 특정 매체의 제목을 그대로 옮기지 않는다.
- summary: 제목들에 공통으로 담긴 정보만으로 2~3문장 요약. 제목에 없는 사실을 추가하지 않는다. 감정적·평가적 표현을 걷어낸다.
- category: 지정된 분야 중 하나."""

SYSTEM_REFINE = """너는 '고른뉴스'의 최종 편집자다. 여러 언론사가 다룬 상위 핫이슈가 매체별 제목·매체 성향 분포(진보/중도/보수)와 함께 주어진다.

각 이슈에 대해:
- 성향이 다른 매체들의 제목을 교차 검증해, 특정 진영의 프레이밍이 아닌 공통 사실만 남긴다. 성향에 따라 서술이 엇갈리면 "…라는 보도와 …라는 보도가 엇갈린다"처럼 병기한다.
- label: 최종 중립 이슈 제목(명사형).
- summary: 정확히 3문장의 중립 리포트. 감정적·평가적 표현 금지, 제목에 없는 사실 추가 금지, 주체·행위·수치·일정 중심."""

SYSTEM_POLICY = """너는 '고른뉴스'의 정책 브리핑 편집자다. 대한민국 정책브리핑(korea.kr)의 정책뉴스 본문이 주어진다.

각 기사에 대해 국민 생활에 실제로 영향을 주는 핵심 정보(무엇이, 언제부터, 누구에게) 중심으로 1~2문장, 공백 포함 120자 이내로 요약한다. 홍보성 수식어는 걷어내고 사실만 남긴다."""


def _load_cache() -> dict:
    try:
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}
    for section in ("clusters", "refined", "policy"):
        cache.setdefault(section, {})
    return cache


def _save_cache(cache: dict) -> None:
    now = time.time()
    for section in ("clusters", "refined", "policy"):
        cache[section] = {
            k: v
            for k, v in cache.get(section, {}).items()
            if now - v.get("t", 0) < CACHE_TTL_SECONDS
        }
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def _cluster_key(titles: list[str]) -> str:
    return hashlib.md5("|".join(sorted(titles)).encode()).hexdigest()


# ── 1단계: Gemini 1차 분류 (노이즈 필터 + 분야 + 임시 라벨) ─────────────


def label_clusters(clusters: list[list[dict]]) -> dict[int, dict]:
    """클러스터별 {label, summary, category}를 반환한다. 노이즈는 제외된다."""
    cache = _load_cache()
    results: dict[int, dict] = {}
    keys: dict[int, str] = {}
    to_ask: list[int] = []

    for ci, cluster in enumerate(clusters):
        key = _cluster_key([m["title"] for m in cluster])
        keys[ci] = key
        hit = cache["clusters"].get(key)
        if hit:
            if hit.get("keep", True):
                results[ci] = {k: hit[k] for k in ("label", "summary", "category")}
        else:
            to_ask.append(ci)

    if to_ask:
        lines = []
        for ci in to_ask:
            heads = " / ".join(f"({m['outlet']}) {m['title']}" for m in clusters[ci][:8])
            lines.append(f"[{ci}] {heads}")
        user = (
            "다음 헤드라인 클러스터들을 분류하라. "
            f"분야는 {', '.join(config.ISSUE_CATEGORIES)} 중 하나.\n\n" + "\n".join(lines)
        )
        try:
            data, engine = call_with_fallback("gemini", SYSTEM_TRIAGE, user, TRIAGE_SCHEMA)
            print(f"[1차 분류] {len(to_ask)}개 클러스터 — {engine} 처리")
        except Exception as e:
            print(f"[경고] 1차 분류 전체 실패 — 신규 클러스터 건너뜀: {e}")
            return results
        asked = set(to_ask)
        for entry in data.get("clusters", []):
            ci = entry.get("id")
            if ci not in asked:
                continue
            keep = bool(entry.get("keep", True))
            meta = {
                "keep": keep,
                "label": entry.get("label", ""),
                "summary": entry.get("summary", ""),
                "category": entry.get("category")
                if entry.get("category") in config.ISSUE_CATEGORIES
                else "사회",
            }
            cache["clusters"][keys[ci]] = {**meta, "t": time.time()}
            if keep and meta["label"]:
                results[ci] = {k: meta[k] for k in ("label", "summary", "category")}
        _save_cache(cache)

    return results


# ── 2단계: Claude 정밀 요약 (상위 핫이슈 편향 교차 검증) ────────────────

BIAS_KO = {"progressive": "진보", "moderate": "중도", "conservative": "보수"}


def refine_top_issues(issues: list[dict], top_n: int | None = None) -> None:
    """점수 상위 이슈의 label/summary를 Claude 정밀 리포트로 교체한다 (in-place)."""
    top_n = top_n or config.REFINE_TOP_ISSUES
    targets = issues[:top_n]
    if not targets:
        return

    cache = _load_cache()
    to_ask: list[int] = []
    keys: dict[int, str] = {}
    for i, issue in enumerate(targets):
        key = _cluster_key([h["title"] for h in issue["headlines"]])
        keys[i] = key
        hit = cache["refined"].get(key)
        if hit:
            issue["label"], issue["summary"] = hit["label"], hit["summary"]
        else:
            to_ask.append(i)

    if not to_ask:
        return

    blocks = []
    for i in to_ask:
        issue = targets[i]
        bias = issue.get("bias", {})
        bias_line = ", ".join(f"{BIAS_KO[k]} {v}곳" for k, v in bias.items() if v)
        heads = "\n".join(
            f"  - ({h['outlet']}) {h['title']}" for h in issue["headlines"][:12]
        )
        blocks.append(f"[{i}] 매체 성향 분포: {bias_line or '정보 없음'}\n{heads}")
    user = "다음 상위 핫이슈들의 최종 중립 리포트를 작성하라.\n\n" + "\n\n".join(blocks)

    try:
        data, engine = call_with_fallback("claude", SYSTEM_REFINE, user, REFINE_SCHEMA)
        print(f"[정밀 요약] 상위 {len(to_ask)}개 이슈 — {engine} 처리")
    except Exception as e:
        print(f"[경고] 정밀 요약 실패 — 1차 분류 요약 유지: {e}")
        return

    asked = set(to_ask)
    for entry in data.get("issues", []):
        i = entry.get("id")
        if i not in asked or not entry.get("summary"):
            continue
        targets[i]["label"] = entry.get("label") or targets[i]["label"]
        targets[i]["summary"] = entry["summary"]
        cache["refined"][keys[i]] = {
            "label": targets[i]["label"],
            "summary": targets[i]["summary"],
            "t": time.time(),
        }
    _save_cache(cache)


# ── 3단계: 정책뉴스 요약 (공공누리 본문 기반) ───────────────────────────


def summarize_policy(articles: list[dict]) -> list[dict]:
    """정책뉴스 요약 [{title, summary, link}] (캐시 활용)."""
    cache = _load_cache()
    results: dict[int, str] = {}
    to_ask: list[int] = []

    for ai, art in enumerate(articles):
        hit = cache["policy"].get(art["id"])
        if hit:
            results[ai] = hit["summary"]
        else:
            to_ask.append(ai)

    if to_ask:
        blocks = []
        for ai in to_ask:
            art = articles[ai]
            blocks.append(f"[{ai}] 제목: {art['title']}\n본문: {art['body'][:1500]}")
        user = "다음 정책뉴스들을 요약하라.\n\n" + "\n\n".join(blocks)
        try:
            data, engine = call_with_fallback("claude", SYSTEM_POLICY, user, POLICY_SCHEMA)
            print(f"[정책 요약] {len(to_ask)}건 — {engine} 처리")
        except Exception as e:
            print(f"[경고] 정책 요약 실패 — 신규 기사 건너뜀: {e}")
            data = {"briefs": []}
        asked = set(to_ask)
        for entry in data.get("briefs", []):
            ai = entry.get("id")
            if ai not in asked or not entry.get("summary"):
                continue
            results[ai] = entry["summary"]
            cache["policy"][articles[ai]["id"]] = {
                "summary": entry["summary"],
                "t": time.time(),
            }
        _save_cache(cache)

    return [
        {"title": art["title"], "summary": results[ai], "link": art["link"]}
        for ai, art in enumerate(articles)
        if ai in results
    ]
