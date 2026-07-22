"""AI 단계: 클러스터 라벨링·중립 요약, 정책뉴스 요약.

- 이슈 클러스터: 언론사 RSS '제목'만 근거로 라벨·1~2문장 요약·분야를 생성한다.
  (제목은 저작물성이 부정되는 영역 — 본문·발췌는 절대 투입하지 않는다)
- 정책뉴스: 공공누리 제1유형(korea.kr) 본문을 근거로 상세 요약한다.
- 캐시(data/cache.json): 내용이 바뀌지 않은 클러스터·기사는 재호출하지 않아
  1시간 주기 실행에도 API 비용이 신규 이슈 분량만큼만 든다.
"""

import hashlib
import json
import time
from pathlib import Path

import anthropic

import config

CACHE_PATH = Path(__file__).resolve().parent / "data" / "cache.json"
CACHE_TTL_SECONDS = 3 * 24 * 3600

CLUSTERS_SCHEMA = {
    "type": "object",
    "properties": {
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "입력에 표시된 클러스터 번호"},
                    "label": {"type": "string", "description": "중립적 이슈 제목(명사형)"},
                    "summary": {"type": "string", "description": "1~2문장 중립 요약"},
                    "category": {"type": "string", "enum": config.ISSUE_CATEGORIES},
                },
                "required": ["id", "label", "summary", "category"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clusters"],
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

SYSTEM_CLUSTERS = """너는 '고른뉴스'의 편집자다. 같은 사건을 다룬 여러 언론사의 기사 '제목'들이 클러스터로 묶여 주어진다.

각 클러스터에 대해:
- label: 중립적인 이슈 제목을 명사형으로 새로 쓴다. 특정 매체의 제목을 그대로 옮기지 않는다.
- summary: 제목들에 공통으로 담긴 정보만으로 1~2문장 요약을 쓴다. 제목에 없는 사실을 추가·추측하지 않는다. 감정적·평가적 표현(충격, 논란, 파문, 맹비난 등)을 걷어낸다. 매체 간 서술이 엇갈리면 병기한다.
- category: 지정된 분야 중 가장 알맞은 하나를 고른다."""

SYSTEM_POLICY = """너는 '고른뉴스'의 정책 브리핑 편집자다. 대한민국 정책브리핑(korea.kr)의 정책뉴스 본문이 주어진다.

각 기사에 대해 국민 생활에 실제로 영향을 주는 핵심 정보(무엇이, 언제부터, 누구에게, 어떻게) 중심으로 2~3문장 요약을 쓴다. 홍보성 수식어는 걷어내고 사실만 남긴다."""


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"clusters": {}, "policy": {}}


def _save_cache(cache: dict) -> None:
    now = time.time()
    for section in ("clusters", "policy"):
        cache[section] = {
            k: v
            for k, v in cache.get(section, {}).items()
            if now - v.get("t", 0) < CACHE_TTL_SECONDS
        }
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def _call(system: str, user: str, schema: dict) -> dict:
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=config.MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=system,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": user}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"모델이 요청을 거부했습니다: {resp.stop_details}")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def label_clusters(clusters: list[list[dict]]) -> dict[int, dict]:
    """클러스터별 {label, summary, category}를 반환한다 (캐시 활용)."""
    cache = _load_cache()
    results: dict[int, dict] = {}
    keys: dict[int, str] = {}
    to_ask: list[int] = []

    for ci, cluster in enumerate(clusters):
        key = hashlib.md5(
            "|".join(sorted(m["title"] for m in cluster)).encode()
        ).hexdigest()
        keys[ci] = key
        hit = cache["clusters"].get(key)
        if hit:
            results[ci] = {k: hit[k] for k in ("label", "summary", "category")}
        else:
            to_ask.append(ci)

    if to_ask:
        lines = []
        for ci in to_ask:
            heads = " / ".join(f"({m['outlet']}) {m['title']}" for m in clusters[ci][:8])
            lines.append(f"[{ci}] {heads}")
        user = (
            "다음 헤드라인 클러스터들에 라벨·요약·분야를 붙여라. "
            f"분야는 {', '.join(config.ISSUE_CATEGORIES)} 중 하나.\n\n" + "\n".join(lines)
        )
        data = _call(SYSTEM_CLUSTERS, user, CLUSTERS_SCHEMA)
        asked = set(to_ask)
        for entry in data["clusters"]:
            ci = entry["id"]
            if ci not in asked:
                continue
            meta = {
                "label": entry["label"],
                "summary": entry["summary"],
                "category": entry["category"]
                if entry["category"] in config.ISSUE_CATEGORIES
                else "사회",
            }
            results[ci] = meta
            cache["clusters"][keys[ci]] = {**meta, "t": time.time()}
        _save_cache(cache)

    return results


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
        data = _call(SYSTEM_POLICY, user, POLICY_SCHEMA)
        asked = set(to_ask)
        for entry in data["briefs"]:
            ai = entry["id"]
            if ai not in asked:
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
