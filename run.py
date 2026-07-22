"""파이프라인 실행: RSS 수집 → 클러스터링 → 핫 분야 배분 → AI 라벨/요약 → 빌드.

사용법:
  python run.py          # 실제 파이프라인 (ANTHROPIC_API_KEY 필요)
  python run.py --mock   # API·네트워크 없이 예시 데이터로 사이트만 생성
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import config
import build_site
from build_site import build, build_archive_pages

ROOT = Path(__file__).resolve().parent

ARCHIVE_KEEP = 72  # 사이트에 렌더링할 최근 스냅샷 수 (3일치)
BIAS_STATE_PATH = ROOT / "data" / "bias_model_state.json"  # 히스테리시스용 직전 판정


def _load_snapshots() -> list[tuple[str, dict]]:
    """아카이브 스냅샷을 최신순으로 1회 로드한다 (성향 모델·렌더링 공용)."""
    snapshots: list[tuple[str, dict]] = []
    for f in sorted((ROOT / "archive").glob("*.json"), reverse=True)[:ARCHIVE_KEEP]:
        try:
            snapshots.append((f.stem, json.loads(f.read_text(encoding="utf-8"))))
        except json.JSONDecodeError:
            continue
    return snapshots


def build_tailwind_css(site_dir: Path) -> None:
    """빌드 타임에 Tailwind CLI로 정적 CSS 생성. 실패 시 CDN 폴백 주입."""
    try:
        subprocess.run(
            ["npx", "--yes", "tailwindcss@3.4.17",
             "-c", "tailwind.config.js", "-i", "tailwind.input.css",
             "-o", str(site_dir / "tailwind.css"), "--minify"],
            check=True, cwd=ROOT, capture_output=True, timeout=420,
        )
        print("Tailwind 정적 CSS 생성 완료")
        return
    except Exception as e:
        print(f"[경고] Tailwind CLI 실패 — CDN 폴백 주입: {e}")
    custom = "\n".join(
        line
        for line in (ROOT / "tailwind.input.css").read_text(encoding="utf-8").splitlines()
        if not line.startswith("@tailwind")
    )
    fallback = (
        '<script src="https://cdn.tailwindcss.com"></script>'
        '<script>tailwind.config={darkMode:"media"}</script>'
        f'<style type="text/tailwindcss">{custom}</style>'
    )
    for html_file in site_dir.rglob("*.html"):
        text = html_file.read_text(encoding="utf-8")
        text = re.sub(r'<link rel="stylesheet" href="[./]*tailwind\.css">', fallback, text)
        html_file.write_text(text, encoding="utf-8")

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


def _headline_time_label(ts) -> str:
    """타임라인 시간 라벨. 오늘은 HH:MM, 다른 날짜는 MM.DD HH:MM —
    날짜가 섞인 클러스터에서 시간이 뒤죽박죽으로 보이는 문제 방지."""
    kst = timezone(timedelta(hours=9))
    local = ts.astimezone(kst)
    if local.date() == datetime.now(kst).date():
        return local.strftime("%H:%M")
    return local.strftime("%m.%d %H:%M")


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


def build_briefing(bias_model: dict | None = None) -> dict:
    from bias_model import effective_bias
    from cluster import allocate_slots, cluster_items
    from fetch_feeds import fetch_headlines
    from fetch_policy import fetch_policy_news
    from summarize import label_clusters, refine_top_issues, summarize_policy

    items = fetch_headlines()
    print(f"헤드라인 {len(items)}건 수집 ({len(config.PRESS_FEEDS)}개 매체)")

    clusters = cluster_items(
        items, config.JACCARD_THRESHOLD, config.OVERLAP_THRESHOLD
    )[: config.CANDIDATE_ISSUES]
    print(f"클러스터 {len(clusters)}개 (라벨링 대상)")

    labels = label_clusters(clusters)

    from categorize import classify

    algo_overrides = 0
    issues_all = []
    for ci, cluster in enumerate(clusters):
        meta = labels.get(ci)
        if not meta:
            continue
        # 분야 분류: 알고리즘(키워드+전문지 사전확률)이 확신하면 LLM 분류를 교체
        algo_cat, _margin = classify(
            [m["title"] for m in cluster], [m["outlet"] for m in cluster]
        )
        if algo_cat and algo_cat != meta["category"]:
            meta = {**meta, "category": algo_cat}
            algo_overrides += 1
        elif algo_cat:
            meta = {**meta, "category": algo_cat}
        outlets = {m["outlet"] for m in cluster}
        # 앵커(통념) → 관측 모델 → 분류 없음 순으로 성향 결정 (bias_model.py)
        bias = {"progressive": 0, "moderate": 0, "conservative": 0, "unknown": 0}
        for outlet in outlets:
            bias[effective_bias(outlet, bias_model)] += 1
        from quality import rank_outlet_count

        issues_all.append(
            {
                **meta,
                "outlet_count": len(outlets),
                # 전재(우라까이) 클러스터는 랭킹용 매체 수를 감쇠 (표시는 그대로)
                "rank_outlet_count": rank_outlet_count(
                    len(outlets), [m["title"] for m in cluster]
                ),
                "bias": bias,
                "_links": [m["link"] for m in cluster],
                "latest_ts": max(m["ts"] for m in cluster),
                # 타임라인 UI용: 송고 시간순(1보 → 최신) 정렬, 최신 N건 유지
                "headlines": [
                    {
                        "outlet": m["outlet"],
                        "title": m["title"],
                        "link": m["link"],
                        "time": _headline_time_label(m["ts"]),
                        "bias": effective_bias(m["outlet"], bias_model),
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
        min_slots=config.MIN_SLOTS_PER_CATEGORY,
    )
    print(f"분야 알고리즘 교정: {algo_overrides}건")
    print("분야별 슬롯:", slots)

    # 상위 핫이슈만 Claude 정밀 요약 (편향 교차 검증, 실패 시 1차 요약 유지)
    refine_top_issues(selected)

    try:
        articles = fetch_policy_news()
        policy = summarize_policy(articles)
    except Exception as e:
        print(f"[경고] 정책 브리핑 단계 실패 — 건너뜀: {e}")
        policy = []
    print(f"정책 브리핑 {len(policy)}건")

    # 블라인드스팟: 한쪽 성향 매체만 보도한 이슈 (Ground News 방식)
    label_to_idx = {issue["label"]: i for i, issue in enumerate(selected)}

    def _blindspot_entry(issue):
        return {
            "label": issue["label"],
            "summary": issue["summary"],
            "outlet_count": issue["outlet_count"],
            "bias": issue["bias"],
            "headlines": issue["headlines"][:3],
            "link": issue["headlines"][0]["link"] if issue["headlines"] else "",
            "issue_index": label_to_idx.get(issue["label"]),
        }

    def _only(side_a, side_b):
        found = [
            i for i in issues_all
            if i["bias"].get(side_a, 0) >= 2 and i["bias"].get(side_b, 0) == 0
        ]
        found.sort(key=lambda i: i["outlet_count"], reverse=True)
        return [_blindspot_entry(i) for i in found[:12]]

    blindspot = {
        # 진보 매체가 다루지 않은(보수만 보도) 이슈 / 그 반대
        "progressive_missing": _only("conservative", "progressive"),
        "conservative_missing": _only("progressive", "conservative"),
    }

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
        "blindspot": blindspot,
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

    snapshots: list[tuple[str, dict]] = []
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
        # 성향 관측 모델: 기존 아카이브 스냅샷으로 추정 (매시간 갱신·자가 보정)
        from bias_model import compute_bias_model

        prev_snaps = _load_snapshots()
        try:
            prev_state = json.loads(BIAS_STATE_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            prev_state = {}
        bias_model = compute_bias_model(prev_snaps, prev_state)
        BIAS_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BIAS_STATE_PATH.write_text(
            json.dumps(bias_model, ensure_ascii=False), encoding="utf-8"
        )
        classified = sum(1 for r in bias_model.values() if r.get("lean"))
        print(f"성향 관측 모델: 표 축적 {len(bias_model)}개 매체, 분류 확정 {classified}개")

        briefing = build_briefing(bias_model)
        from fetch_community import fetch_community

        try:
            community = fetch_community()
        except Exception as e:
            print(f"[경고] 커뮤니티 단계 실패 — 건너뜀: {e}")
            community = []

        # 아카이브: 현재 브리핑을 저장소 archive/에 스냅샷 (워크플로우가 커밋)
        kst = timezone(timedelta(hours=9))
        stamp = datetime.now(kst).strftime("%Y-%m-%d-%H")
        archive_dir = ROOT / "archive"
        archive_dir.mkdir(exist_ok=True)
        (archive_dir / f"{stamp}.json").write_text(
            json.dumps(briefing, ensure_ascii=False), encoding="utf-8"
        )
        # 재로드 없이 기존 로드분 + 이번 스냅샷으로 구성 (이중 로드 제거)
        snapshots = ([(stamp, briefing)] + prev_snaps)[:ARCHIVE_KEEP]
        # 공유·RSS 영구 링크는 이번 시각의 스냅샷을 가리킨다
        punycode = config.SITE_DOMAIN.encode("idna").decode()
        build_site.set_share_base(f"https://{punycode}/archive/{stamp}/")

    out_path = build(
        briefing, community, ROOT / "site",
        archive_stamps=[s for s, _ in snapshots],
        snapshots=snapshots,
    )
    if snapshots:
        build_archive_pages(snapshots, ROOT / "site", datetime.now(ZoneInfo("Asia/Seoul")))
        print(f"아카이브 페이지 {len(snapshots)}개 렌더링")
    from build_site import build_search_assets

    build_search_assets(snapshots, ROOT / "site", datetime.now(ZoneInfo("Asia/Seoul")))
    build_tailwind_css(ROOT / "site")
    (ROOT / "site" / "briefing.json").write_text(
        json.dumps(briefing, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not args.mock:
        # 성향 모델 공개 (분류 근거 투명성)
        (ROOT / "site" / "bias-model.json").write_text(
            json.dumps(
                {
                    "generated_at": briefing.get("generated_at"),
                    "method": "앵커(통념 분류) 제목과의 어휘 중첩 반복 관측 — bias_model.py",
                    "anchors": config.OUTLET_BIAS,
                    "model": bias_model,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
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
