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


# ── CLOVA Studio (HyperCLOVA X) ──────────────────────────────────────────


def clova_json(system: str, user: str, schema: dict) -> dict:
    """네이버 CLOVA Studio(HyperCLOVA X) 비스트리밍 호출로 JSON을 받는다.

    구조화 출력(responseFormat) 대신 프롬프트에 스키마를 명시하고 응답 content를
    파싱해, 모델·추론모드와 무관하게 동작한다(Gemini/Claude 경로와 동일 패턴).
    """
    import urllib.request
    import uuid

    api_key = os.environ.get("CLOVA_API_KEY")
    if not api_key:
        raise RuntimeError("CLOVA_API_KEY 미설정")
    auth = api_key if api_key.lower().startswith("bearer ") else f"Bearer {api_key}"

    prompt = (
        f"{user}\n\n다음 JSON 스키마를 정확히 따르는 JSON 객체만 출력하라:\n"
        + json.dumps(schema, ensure_ascii=False)
    )
    payload = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "topP": 0.8,
        "temperature": 0.3,
        "maxCompletionTokens": 16384,
        "repetitionPenalty": 1.1,
    }
    # HCX-007은 추론 모델 — 라벨링엔 최소 추론으로 비용·지연을 줄인다.
    if config.CLOVA_MODEL.upper().startswith("HCX-007"):
        payload["thinking"] = {"effort": "low"}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url = f"https://clovastudio.stream.ntruss.com/v3/chat-completions/{config.CLOVA_MODEL}"

    def call() -> dict:
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": auth,
                "X-NCP-CLOVASTUDIO-REQUEST-ID": uuid.uuid4().hex,
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",  # 비스트리밍 JSON 응답
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        status = data.get("status") or {}
        code = str(status.get("code") or "")
        if code and code != "20000":
            raise RuntimeError(f"CLOVA 오류 {code}: {status.get('message')}")
        result = data["result"]
        content = result["message"]["content"]
        finish = result.get("finishReason")
        if finish and finish not in ("stop", "end_turn"):
            print(f"[CLOVA] finishReason={finish}, content {len(content)}자 — 응답 잘림 의심")
        return _extract_json(content)

    return _with_backoff("CLOVA", call)


def clova_embed(text: str) -> list[float]:
    """CLOVA Studio 임베딩 v2로 단일 텍스트의 벡터를 반환한다."""
    import urllib.request
    import uuid

    api_key = os.environ.get("CLOVA_API_KEY")
    if not api_key:
        raise RuntimeError("CLOVA_API_KEY 미설정")
    auth = api_key if api_key.lower().startswith("bearer ") else f"Bearer {api_key}"
    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://clovastudio.stream.ntruss.com/v1/api-tools/embedding/v2",
        data=body,
        method="POST",
        headers={
            "Authorization": auth,
            "X-NCP-CLOVASTUDIO-REQUEST-ID": uuid.uuid4().hex,
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if str((data.get("status") or {}).get("code")) != "20000":
        raise RuntimeError(f"CLOVA 임베딩 오류: {data.get('status')}")
    return data["result"]["embedding"]


# ── 폴백 오케스트레이션 ─────────────────────────────────────────────────

_ENGINES = {"claude": claude_json, "gemini": gemini_json, "clova": clova_json}


def _available_engines() -> list[str]:
    """키·활성화 여부로 실제 사용 가능한 엔진만 config.LLM_PRIORITY 순으로 반환."""
    avail = {
        "clova": bool(os.environ.get("CLOVA_API_KEY")),
        "gemini": bool(os.environ.get("GEMINI_API_KEY")),
        "claude": config.ENABLE_CLAUDE,
    }
    ordered = [e for e in config.LLM_PRIORITY if avail.get(e)]
    ordered += [e for e in avail if avail[e] and e not in ordered]  # 목록 밖 엔진도 뒤에
    return ordered


def call_with_fallback(
    primary: str, system: str, user: str, schema: dict
) -> tuple[dict, str]:
    """사용 가능한 LLM을 config.LLM_PRIORITY 순으로 시도한다(무중단 폴백).

    primary 인자는 하위호환용이며, 실제 순서는 LLM_PRIORITY + 키 보유 여부로 정한다.
    반환: (결과 JSON, 실제 사용된 엔진 이름)
    """
    order = _available_engines()
    if not order:
        raise RuntimeError("사용 가능한 LLM 엔진이 없습니다 (CLOVA/Gemini/Claude 키·활성 없음).")
    last_error: Exception | None = None
    for engine in order:
        try:
            result = _ENGINES[engine](system, user, schema)
            if engine != order[0]:
                print(f"[폴백] {order[0]} → {engine} 우회 성공")
            return result, engine
        except Exception as e:
            print(f"[{engine}] 실패: {e}")
            last_error = e
    raise last_error  # type: ignore[misc]
