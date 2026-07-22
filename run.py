"""파이프라인 실행: RSS 수집 → 클러스터링 → 핫 분야 배분 → AI 라벨/요약 → 빌드.

사용법:
  python run.py          # 실제 파이프라인 (ANTHROPIC_API_KEY 필요)
  python run.py --mock   # API·네트워크 없이 예시 데이터로 사이트만 생성
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
from build_site import build

ROOT = Path(__file__).resolve().parent

BREAKING_RE = re.compile(r"\[\s*(속보|1보|긴급)\s*\]")
BREAKING_MAX_AGE_HOURS = 6
BREAKING_MAX = 10


def load_env_file() -> None:
    """루트의 .env 파일이 있으면 환경변수로 로드한다 (로컬 실행 편의용)."""
    import os

    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def detect_breaking(items: list[dict]) -> list[dict]:
    """[속보]/[1보]/[긴급] 말머리가 붙은 최근 기사를 골라낸다 (제목 원문 유지)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=BREAKING_MAX_AGE_HOURS)
    kst = timezone(timedelta(hours=9))
    breaking = [
        it for it in items if BREAKING_RE.search(it["title"]) and it["ts"] >= cutoff
    ]
    breaking.sort(key=lambda it: it["ts"], reverse=True)
    return [
        {
            "time": it["ts"].astimezone(kst).strftime("%H:%M"),
            "outlet": it["outlet"],
            "title": it["title"],
            "link": it["link"],
        }
        for it in breaking[:BREAKING_MAX]
    ]


def build_briefing() -> dict:
    from cluster import allocate_slots, cluster_items
    from fetch_feeds import fetch_headlines
    from fetch_policy import fetch_policy_news
    from summarize import label_clusters, summarize_policy

    items = fetch_headlines()
    print(f"헤드라인 {len(items)}건 수집 ({len(config.PRESS_FEEDS)}개 매체)")

    clusters = cluster_items(
        items, config.JACCARD_THRESHOLD, config.OVERLAP_THRESHOLD
    )[: config.CANDIDATE_ISSUES]
    print(f"클러스터 {len(clusters)}개 (라벨링 대상)")

    labels = label_clusters(clusters)

    issues_all = []
    for ci, cluster in enumerate(clusters):
        meta = labels.get(ci)
        if not meta:
            continue
        outlets = {m["outlet"] for m in cluster}
        bias = {"progressive": 0, "moderate": 0, "conservative": 0}
        for outlet in outlets:
            bias[config.OUTLET_BIAS.get(outlet, "moderate")] += 1
        issues_all.append(
            {
                **meta,
                "outlet_count": len(outlets),
                "bias": bias,
                "_links": [m["link"] for m in cluster],
                "latest_ts": max(m["ts"] for m in cluster),
                # 타임라인 UI용: 송고 시간순(1보 → 최신) 정렬, 최신 N건 유지
                "headlines": [
                    {
                        "outlet": m["outlet"],
                        "title": m["title"],
                        "link": m["link"],
                        "time": m["ts"].astimezone(timezone(timedelta(hours=9))).strftime("%H:%M"),
                    }
                    for m in sorted(cluster, key=lambda m: m["ts"])[
                        -config.MAX_HEADLINES_PER_ISSUE :
                    ]
                ],
            }
        )

    selected, heat, slots = allocate_slots(
        issues_all,
        config.TOP_ISSUES,
        config.MAX_ISSUES_PER_CATEGORY,
        config.HEAT_DECAY_HOURS,
        size_exponent=config.SIZE_EXPONENT,
        pin_top=config.TOP_PIN_COUNT,
    )
    print("분야별 슬롯:", slots)

    articles = fetch_policy_news()
    policy = summarize_policy(articles)
    print(f"정책 브리핑 {len(policy)}건")

    # 속보 → 해당 이슈 카드 매핑 (티커 클릭 시 카드로 스크롤)
    link_to_idx = {
        link: i for i, issue in enumerate(selected) for link in issue.get("_links", [])
    }
    breaking = detect_breaking(items)
    for entry in breaking:
        entry["issue_index"] = link_to_idx.get(entry["link"])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "heat": {c: round(h, 2) for c, h in sorted(heat.items(), key=lambda x: -x[1])},
        "slots": slots,
        "breaking": breaking,
        "issues": [
            {k: v for k, v in issue.items() if k not in ("latest_ts", "_links")}
            | {"latest_ts": issue["latest_ts"].isoformat()}
            for issue in selected
        ],
        "policy": policy,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="고른뉴스 생성")
    parser.add_argument("--mock", action="store_true", help="예시 데이터로 사이트만 생성")
    args = parser.parse_args()

    if args.mock:
        briefing = json.loads(
            (ROOT / "data" / "mock_briefing.json").read_text(encoding="utf-8")
        )
        community = json.loads(
            (ROOT / "data" / "mock_community.json").read_text(encoding="utf-8")
        )
        print("예시 데이터로 사이트를 생성합니다 (API 호출 없음).")
    else:
        load_env_file()
        briefing = build_briefing()
        from fetch_community import fetch_community

        community = fetch_community()

    out_path = build(briefing, community, ROOT / "site")
    (ROOT / "site" / "briefing.json").write_text(
        json.dumps(briefing, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "site" / "community.json").write_text(
        json.dumps(
            {"generated_at": briefing.get("generated_at"), "posts": community},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"생성 완료: {out_path}")


if __name__ == "__main__":
    main()
