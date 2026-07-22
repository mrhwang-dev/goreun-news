"""수집한 기사 메타데이터를 Claude에 전달해 중립 브리핑을 생성한다.

기사 본문은 사용하지 않는다. 네이버 API가 제공한 제목·요약문만 근거로 삼고,
같은 사건을 다룬 여러 매체의 보도를 교차 확인해 공통 사실만 추린다.
"""

import json

import anthropic

import config

# 구조화 출력 스키마 — 모델 응답이 항상 이 JSON 형태로 오도록 강제한다.
ISSUES_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "이슈 제목. 명사형으로 간결하게.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "2~3문장의 중립 요약.",
                    },
                    "source_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "근거가 된 기사 번호 목록.",
                    },
                },
                "required": ["title", "summary", "source_ids"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["issues"],
    "additionalProperties": False,
}

SYSTEM = """너는 '오늘의 중립 브리핑'의 편집자다. 여러 언론사가 보도한 기사들의 제목과 요약문만을 근거로, 오늘의 주요 이슈를 골라 중립적인 브리핑을 작성한다.

원칙:
- 제공된 제목·요약문에 없는 사실을 추가하거나 추측하지 않는다.
- 감정적·평가적 표현(충격, 논란, 파문, 초유, 맹비난, 역대급 등)을 걷어내고 확인 가능한 사실만 쓴다.
- 같은 사건을 다룬 기사들은 하나의 이슈로 묶는다. 여러 매체가 공통으로 전한 내용을 우선하고, 매체 간 서술이 엇갈리면 "…라는 보도와 …라는 보도가 엇갈린다"처럼 병기한다.
- 특정 정파·기업·인물에 유리하거나 불리한 프레이밍을 쓰지 않는다. 주체와 행위, 수치, 일정 등 검증 가능한 정보 중심으로 쓴다.
- 이슈 제목은 명사형으로 간결하게, 요약은 2~3문장으로 쓴다.
- source_ids에는 해당 이슈의 근거가 된 기사 번호를 모두 담는다. 목록에 없는 번호를 만들지 않는다."""


def summarize_category(cat_name: str, items: list[dict], top_n: int) -> list[dict]:
    """카테고리 기사 목록에서 상위 이슈 top_n개의 중립 브리핑을 만든다."""
    client = anthropic.Anthropic()
    items = items[: config.MAX_ITEMS_FOR_SUMMARY]
    if not items:
        return []

    lines = [
        f"[{i}] ({it['outlet']}) {it['title']}"
        + (f" — {it['description']}" if it["description"] else "")
        for i, it in enumerate(items)
    ]
    user = (
        f"카테고리: {cat_name}\n"
        f"오늘 수집된 기사 목록 ({len(items)}건):\n" + "\n".join(lines) + "\n\n"
        f"이 중 가장 중요한 이슈 {top_n}개를 골라 브리핑을 작성하라. "
        f"가능하면 2개 이상의 매체가 함께 보도한 이슈를 우선하라."
    )

    resp = client.messages.create(
        model=config.MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": ISSUES_SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )

    if resp.stop_reason == "refusal":
        raise RuntimeError(f"[{cat_name}] 모델이 요청을 거부했습니다: {resp.stop_details}")

    text = next(b.text for b in resp.content if b.type == "text")
    data = json.loads(text)

    issues = []
    for issue in data["issues"][:top_n]:
        sources = [items[i] for i in issue["source_ids"] if 0 <= i < len(items)]
        if not sources:
            continue
        outlets = {s["outlet"] for s in sources}
        issues.append(
            {
                "title": issue["title"],
                "summary": issue["summary"],
                "cross_verified": len(outlets) >= 2,
                "sources": [
                    {"outlet": s["outlet"], "title": s["title"], "link": s["link"]}
                    for s in sources[:5]
                ],
            }
        )
    return issues
