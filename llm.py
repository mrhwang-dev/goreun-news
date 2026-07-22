"""다중 모델(Multi-LLM) 오케스트레이션 계층.

역할 분담 (작업 난이도 기반 동적 라우팅):
- Gemini 2.5 Flash: 대규모 단순 분류 — 후보 클러스터의 노이즈 필터링·분야 지정·
  임시 라벨 (가성비·속도 우선)
- Claude: 복잡한 추론·정교한 글쓰기 — 상위 핫이슈의 편향 교차 검증과 최종
  중립 요약, 정책 브리핑 (품질 우선, 제한 호출)

안정성:
- 지수 백오프 재시도 (1s → 2s → 4s), 레이트리밋·타임아웃·5xx 대응
- 무중단 폴백: 주 모델이 끝내 실패하면 즉시 보조 모델로 우회
- config.ENABLE_CLAUDE=False(기본)이면 Claude를 아예 호출하지 않고 전 구간
  Gemini 단독으로 동작한다. Anthropic 크레딧 확보 후 ENABLE_CLAUDE=1로 재활성화.
"""

from __future__ import annotations

import json
import os
import time
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

import config

BACKOFF_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1.0


_NON_RETRYABLE_MARKERS = (
    "404",
    "no longer available",
    "API key not valid",
    "invalid_request_error",
    "permission",
)


def _is_retryable(error: BaseException) -> bool:
    """레이트리밋(429)·타임아웃·5xx만 재시도. 4xx 계열은 즉시 폴백."""
    msg = str(error)
    if "429" in msg or "rate" in msg.lower():
        return True
    return not any(marker in msg for marker in _NON_RETRYABLE_MARKERS)


def _with_backoff(label: str, fn):
    """지수 백오프 재시도 (Tenacity)."""
    @retry(
        stop=stop_after_attempt(BACKOFF_ATTEMPTS),
        wait=wait_exponential(multiplier=BACKOFF_BASE_SECONDS, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
        before_sleep=lambda rs: print(f"[{label}] 시도 {rs.attempt_number} 실패: {rs.outcome.exception()} — 대기 후 재시도")
    )
    def wrapper():
        return fn()
    
    return wrapper()


def _extract_json(text: str) -> dict:
    """모델 응답에서 JSON 객체를 추출한다 (코드펜스 등 장식 허용)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


# ── Claude ──────────────────────────────────────────────────────────────


def claude_json(system: str, user: str, schema: dict) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    prompt = (
        f"{user}\n\n다음 JSON 스키마를 정확히 따르는 JSON 객체만 출력하라:\n"
        + json.dumps(schema, ensure_ascii=False)
    )

    def call() -> dict:
        resp = client.messages.create(
            model=config.MODEL,
            max_tokens=8192,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        if getattr(resp, "stop_reason", None) == "refusal":
            raise RuntimeError(f"Claude가 요청을 거부했습니다: {getattr(resp, 'stop_details', 'refusal')}")
        text = next(b.text for b in resp.content if b.type == "text")
        return _extract_json(text)

    return _with_backoff("Claude", call)


# ── Gemini ──────────────────────────────────────────────────────────────


def gemini_json(system: str, user: str, schema: dict) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY 미설정")

    import google.generativeai as genai

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(config.GEMINI_MODEL, system_instruction=system)
    # Gemini의 response_schema 포맷은 별도 규격이라, JSON 모드 + 프롬프트에
    # 스키마를 명시하는 방식으로 동일한 구조를 강제한다.
    prompt = (
        f"{user}\n\n다음 JSON 스키마를 정확히 따르는 JSON 객체만 출력하라:\n"
        + json.dumps(schema, ensure_ascii=False)
    )

    def call() -> dict:
        resp = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"},
            request_options={"timeout": 120},
        )
        return _extract_json(resp.text)

    return _with_backoff("Gemini", call)


# ── 폴백 오케스트레이션 ─────────────────────────────────────────────────


def call_with_fallback(
    primary: str, system: str, user: str, schema: dict
) -> tuple[dict, str]:
    """primary('claude'|'gemini') 실패 시 반대 모델로 무중단 우회.

    반환: (결과 JSON, 실제 사용된 엔진 이름)
    """
    engines = {"claude": claude_json, "gemini": gemini_json}
    # Claude 비활성(크레딧 미보유 등) 시 전 구간 Gemini 단독으로 우회한다.
    # primary가 'claude'라도 Gemini로 재지정되며, Claude 호출은 아예 시도하지 않는다.
    if not config.ENABLE_CLAUDE:
        engines.pop("claude", None)
        primary = "gemini"
    order = [primary] + [e for e in engines if e != primary]
    last_error: Exception | None = None
    for engine in order:
        try:
            result = engines[engine](system, user, schema)
            if engine != primary:
                print(f"[폴백] {primary} → {engine} 우회 성공")
            return result, engine
        except Exception as e:
            print(f"[{engine}] 최종 실패: {e}")
            last_error = e
    raise last_error  # type: ignore[misc]
