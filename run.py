"""파이프라인 실행: RSS 수집 → 클러스터링 → 핫 분야 배분 → AI 라벨/요약 → 빌드.

사용법:
  python run.py          # 실제 파이프라인 (ANTHROPIC_API_KEY 필요)
  python run.py --mock   # API·네트워크 없이 예시 데이터로 사이트만 생성
"""

from __future__ import annotations

import argparse
import json
import os
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
from db import get_connection


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
        '<script>tailwind.config={darkMode:"class"}</script>'
        f'<style type="text/tailwindcss">{custom}</style>'
    )
    for html_file in site_dir.rglob("*.html"):
        text = html_file.read_text(encoding="utf-8")
        text = re.sub(r'<link rel="stylesheet" href="[./]*tailwind\.css">', fallback, text)
        html_file.write_text(text, encoding="utf-8")

BREAKING_RE = re.compile(r"\[\s*(속보|1보|긴급)\s*\]")
BREAKING_MAX_AGE_HOURS = 3  # 속보는 기본 3시간 이내
BREAKING_FALLBACK_HOURS = 12  # 3시간 내 속보가 없을 때만 이 범위의 최신 속보로 보강(심야 공백 방지)
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
    """[속보]/[1보]/[긴급] 말머리가 붙은 최근 기사를 골라낸다 (제목 원문 유지).

    기본은 3시간 이내지만, 그 안에 속보가 하나도 없으면(심야 등) 티커가 비지
    않도록 12시간 이내의 최신 속보로 보강한다. 발행 시각이 추정값(피드에 날짜
    없음)인 기사는 표시 시각이 실제와 어긋나므로 제외한다.
    """
    now = datetime.now(timezone.utc)
    kst = timezone(timedelta(hours=9))
    candidates = sorted(
        (it for it in items
         if BREAKING_RE.search(it["title"]) and not it.get("ts_estimated")),
        key=lambda it: it["ts"], reverse=True,
    )
    fresh_cutoff = now - timedelta(hours=BREAKING_MAX_AGE_HOURS)
    fresh = [it for it in candidates if it["ts"] >= fresh_cutoff]
    if fresh:
        breaking = fresh
    else:
        fallback_cutoff = now - timedelta(hours=BREAKING_FALLBACK_HOURS)
        breaking = [it for it in candidates if it["ts"] >= fallback_cutoff]
    return [
        {
            "time": _headline_time_label(it["ts"]),
            "outlet": it["outlet"],
            "title": it["title"],
            "link": it["link"],
        }
        for it in breaking[:BREAKING_MAX]
    ]


# 대표 제목으로 부적절한 유형(의견·화보·영상). 한 매체의 논조가 이슈 제목으로
# 올라가 중립성을 해치는 것을 막는다.
_NON_NEWS_TITLE_MARKERS = (
    "[사설]", "[칼럼]", "[기고]", "[오피니언]", "[시론]", "[기자수첩]", "[데스크",
    "[사진]", "[포토]", "[화보]", "[영상]", "[만평]", "[인터뷰]", "[일문일답]", "[속보]",
)


def _representative_title(cluster: list[dict]) -> str:
    """무-API 라벨: 클러스터 대표 제목 = 길이 중앙값 제목.

    의견·화보성 제목([사설]·[포토] 등)은 후보에서 제외해(가능하면) 중립 뉴스
    헤드라인을 고르고, 속보 말머리만 남은 과도한 축약·군더더기 긴 제목의 양극단을
    길이 중앙값으로 피한다.
    """
    titles = [m["title"] for m in cluster]
    news = [t for t in titles if not any(mk in t for mk in _NON_NEWS_TITLE_MARKERS)]
    pool = sorted(news or titles, key=len)
    return pool[len(pool) // 2]


def _algorithmic_labels(clusters: list[list[dict]], have: set[int]) -> dict[int, dict]:
    """LLM이 라벨을 못 단 클러스터를 알고리즘만으로 라벨링한다 (무-API 폴백).

    - 제목: 대표 헤드라인 원문 (원래도 '제목 원문 그대로' 원칙과 부합)
    - 분야: categorize.best_guess (키워드 + 전문지 사전확률)
    - 요약: LLM 없이 생성 불가 → 매체 수 안내 문구로 대체
    노이즈 방지로 '2개 매체 이상' 보도한 클러스터만 채택한다(단독 잡글 제외).
    """
    from categorize import best_guess

    out: dict[int, dict] = {}
    for ci, cluster in enumerate(clusters):
        if ci in have:
            continue
        outlets = [m["outlet"] for m in cluster]
        n = len(set(outlets))
        if n < 2:
            continue
        out[ci] = {
            "label": _representative_title(cluster),
            "summary": f"{n}개 매체가 보도한 이슈입니다. 아래 ‘매체별 헤드라인’에서 원문을 확인하세요.",
            "category": best_guess([m["title"] for m in cluster], outlets),
        }
    return out


def build_briefing(bias_model: dict | None = None) -> dict:
    from bias_model import effective_bias
    from cluster import allocate_slots, cluster_items
    from fetch_feeds import fetch_headlines
    from fetch_policy import fetch_policy_news
    from summarize import label_clusters, refine_top_issues, summarize_policy

    items = fetch_headlines()
    print(f"헤드라인 {len(items)}건 수집 ({len(config.PRESS_FEEDS)}개 매체)")

    # 네이버 뉴스 검색 보강 (선택) — 링크 기준 중복 제거 후 병합
    if config.ENABLE_NAVER_SEARCH:
        try:
            from fetch_naver import fetch_naver_news

            existing = {it["link"] for it in items}
            added = [it for it in fetch_naver_news() if it["link"] not in existing]
            items += added
            print(f"네이버 검색 보강 후 총 {len(items)}건")
        except Exception as e:
            print(f"[경고] 네이버 검색 보강 실패 — 건너뜀: {e}")

    clusters = cluster_items(items, config.JACCARD_THRESHOLD, config.OVERLAP_THRESHOLD)

    # 의미 기반 병합(선택): 상위 클러스터 대표 제목을 임베딩해 어휘로는 못 묶는
    # '같은 사건, 다른 표현'을 합쳐 교차확인(매체 수) 정확도를 높인다.
    if config.ENABLE_EMBEDDING and os.environ.get("CLOVA_API_KEY"):
        try:
            from cluster import merge_by_embedding
            from embed import fetch_embeddings

            top = clusters[: config.EMBED_MERGE_TOP]
            reps = [c[0]["title"] for c in top]
            emb_map = fetch_embeddings(reps)
            embs = [emb_map.get(r) for r in reps]
            # 임계값 튜닝 진단: 상위 코사인 쌍과 구간별 개수 (같은 사건 vs 다른 사건 경계 파악)
            from cluster import _cosine

            pairs = []
            for a in range(len(embs)):
                if embs[a] is None:
                    continue
                for b in range(a + 1, len(embs)):
                    if embs[b] is not None:
                        c = _cosine(embs[a], embs[b])
                        if c >= 0.55:
                            pairs.append((c, reps[a], reps[b]))
            pairs.sort(reverse=True)
            for c, x, y in pairs[:8]:
                print(f"[임베딩 진단] {c:.3f} | {x[:24]} ↔ {y[:24]}")
            print(
                "[임베딩 진단] "
                + " ".join(f"≥{t}:{sum(1 for c, _, _ in pairs if c >= t)}" for t in (0.6, 0.7, 0.75, 0.8))
            )
            merged = merge_by_embedding(top, embs, config.EMBED_MERGE_THRESHOLD)
            clusters = merged + clusters[config.EMBED_MERGE_TOP :]
            print(f"[임베딩 병합] 상위 {len(top)}개 → {len(merged)}개 (병합 {len(top) - len(merged)}건)")
        except Exception as e:
            print(f"[경고] 임베딩 병합 실패 — 어휘 클러스터 유지: {e}")

    clusters = clusters[: config.CANDIDATE_ISSUES]
    print(f"클러스터 {len(clusters)}개 (라벨링 대상)")

    # 무-API 모드(config.ENABLE_LLM_LABELING=False)면 LLM을 아예 호출하지 않는다.
    labels = label_clusters(clusters) if config.ENABLE_LLM_LABELING else {}
    # LLM이 라벨링하지 못한 클러스터(무-API·할당량 소진·오류)는 알고리즘으로 채운다.
    algo = _algorithmic_labels(clusters, set(labels))
    if algo:
        labels.update(algo)
        print(f"[무-API 라벨] 알고리즘으로 {len(algo)}개 클러스터 라벨링")

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

    # 상위 핫이슈만 LLM 정밀 요약 (편향 교차 검증, 실패 시 1차 요약 유지).
    # 무-API 모드에선 추가 LLM 호출을 하지 않으므로 생략한다.
    if config.ENABLE_LLM_LABELING:
        refine_top_issues(selected)

    # 정책 브리핑도 LLM 요약이 필요하므로 무-API 모드에선 생략한다.
    policy = []
    if config.ENABLE_LLM_LABELING:
        try:
            articles = fetch_policy_news()
            policy = summarize_policy(articles)
        except Exception as e:
            print(f"[경고] 정책 브리핑 단계 실패 — 건너뜀: {e}")
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

    breaking = detect_breaking(items)

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
    parser.add_argument(
        "--app",
        action="store_true",
        help="모바일 앱(Capacitor) 빌드: 각 페이지에 capacitor.js·native.js 주입 "
        "(별도로 `npm run app:runtime`으로 capacitor.js 생성 필요)",
    )
    args = parser.parse_args()
    build_site.set_app_build(args.app)

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
        prev_state = {}
        try:
            with get_connection() as conn:
                row = conn.execute("SELECT value FROM bias_state WHERE key = 'all'").fetchone()
                if row:
                    prev_state = json.loads(row["value"])
        except Exception as e:
            print(f"[경고] 성향 관측 모델 상태 로드 실패: {e}")

        bias_model = compute_bias_model(prev_snaps, prev_state)
        
        try:
            with get_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO bias_state (key, value) VALUES ('all', ?)",
                    (json.dumps(bias_model, ensure_ascii=False),)
                )
                conn.commit()
        except Exception as e:
            print(f"[경고] 성향 관측 모델 상태 저장 실패: {e}")
        classified = sum(1 for r in bias_model.values() if r.get("lean"))
        print(f"성향 관측 모델: 표 축적 {len(bias_model)}개 매체, 분류 확정 {classified}개")

        briefing = build_briefing(bias_model)

        # 안전장치: 본 브리핑 이슈가 0건이면 AI 라벨링(Gemini 등)이 전량 실패한 것.
        # (헤드라인 수집·속보는 정상인데 label_clusters가 실패하면 이 상태 — 주로
        #  LLM 할당량 소진/장애.) 그대로 배포하면 정상 뉴스가 사라진 빈 사이트가
        #  나가고 게임 마이그레이션만 남아 '게임만 N건'처럼 보인다.
        # → 빈 사이트 대신 '마지막 정상 스냅샷'의 뉴스로 폴백 배포한다. 단, 이 실행분은
        #    아카이브하지 않는다(스테일 이슈가 새 타임스탬프로 중복 적재되는 것 방지).
        labeling_failed = not briefing.get("issues")
        if labeling_failed:
            prev_good = next((entry for entry in prev_snaps if entry[1].get("issues")), None)
            if not prev_good:
                raise SystemExit(
                    "[중단] 본 브리핑 이슈 0건이고 폴백할 정상 스냅샷도 없음 — 기존 사이트 유지."
                )
            good_stamp, good_briefing = prev_good
            print(
                f"[폴백] AI 라벨링 실패 — 마지막 정상 스냅샷({good_stamp})의 "
                f"이슈 {len(good_briefing['issues'])}건으로 배포(이번 실행분은 아카이브 안 함)."
            )
            briefing["issues"] = good_briefing["issues"]
            briefing["heat"] = good_briefing.get("heat", {})
            briefing["slots"] = good_briefing.get("slots", {})

        from fetch_community import fetch_community

        try:
            community = fetch_community()
        except Exception as e:
            print(f"[경고] 커뮤니티 단계 실패 — 건너뜀: {e}")
            community = []

        # 아카이브: 현재 브리핑을 저장소 archive/에 스냅샷 (워크플로우가 커밋).
        # 폴백 배포(라벨링 실패)일 땐 아카이브하지 않고 기존 스냅샷으로 렌더한다.
        kst = timezone(timedelta(hours=9))
        if labeling_failed:
            snapshots = prev_snaps[:ARCHIVE_KEEP]
            stamp = good_stamp
        else:
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

    # 커뮤니티의 게임 보드 뉴스(board_news)를 추출해 메인 브리핑의 '게임' 카테고리 이슈로 편입
    game_issues = []
    filtered_community = []
    for p in community:
        if p.get("board_news"):
            game_issues.append({
                "label": p["title"],
                "summary": "게임 커뮤니티 뉴스 게시판에서 수집한 소식입니다. 자세한 내용은 원문에서 확인하세요.",
                "category": "게임",
                "outlet_count": 1,
                "bias": {"moderate": 1},
                "headlines": [{
                    "outlet": p.get("source", "게임커뮤니티"),
                    "title": p["title"],
                    "link": p["link"],
                    "time": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H:%M"),
                    "bias": "moderate"
                }],
                "latest_ts": datetime.now(timezone.utc).isoformat()
            })
        else:
            filtered_community.append(p)
    
    community = filtered_community
    briefing["issues"].extend(game_issues)

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
