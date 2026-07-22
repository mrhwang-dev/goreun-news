"""파이프라인 실행: 수집 → AI 중립 요약 → 정적 사이트 빌드.

사용법:
  python run.py          # 실제 파이프라인 (NAVER_*, ANTHROPIC_API_KEY 필요)
  python run.py --mock   # API 호출 없이 예시 데이터로 사이트만 생성
"""

import argparse
import json
from pathlib import Path

import config
from build_site import build

ROOT = Path(__file__).resolve().parent


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


def main() -> None:
    parser = argparse.ArgumentParser(description="오늘의 중립 브리핑 생성")
    parser.add_argument(
        "--mock", action="store_true", help="API 호출 없이 예시 데이터로 사이트 생성"
    )
    args = parser.parse_args()

    if args.mock:
        briefing = json.loads(
            (ROOT / "data" / "mock_briefing.json").read_text(encoding="utf-8")
        )
        print("예시 데이터로 사이트를 생성합니다 (API 호출 없음).")
    else:
        load_env_file()
        from fetch_news import fetch_category
        from summarize import summarize_category

        categories = []
        for cat in config.CATEGORIES:
            items = fetch_category(cat["queries"], per_query=config.ITEMS_PER_QUERY)
            print(f"[{cat['name']}] 기사 {len(items)}건 수집")
            issues = summarize_category(cat["name"], items, config.ISSUES_PER_CATEGORY)
            print(f"[{cat['name']}] 이슈 {len(issues)}건 브리핑 생성")
            categories.append({"id": cat["id"], "name": cat["name"], "issues": issues})
        briefing = {"categories": categories}

    out_path = build(briefing, ROOT / "site")
    (ROOT / "site" / "briefing.json").write_text(
        json.dumps(briefing, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"생성 완료: {out_path}")


if __name__ == "__main__":
    main()
