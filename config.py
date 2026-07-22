"""고른뉴스 (goreun.news) — 설정."""

import os

# ── 소스 구성 (저작권 검토 결과: SOURCES.md) ─────────────────────────────
# 언론사 RSS: '제목 + 원문 링크' 큐레이션만 사용. 본문 수집·요약 금지.
#   - 제목은 저작물성 부정(판례), 링크는 침해 아님(대법원 2009다4343)
#   - 제외: SBS(비상업 한정 명시), 한겨레(피드에 AI 활용 금지 명시),
#           매일경제(봇 차단), 중앙일보(RSS 중단), 연합뉴스(미제공)
PRESS_FEEDS = [
    {"outlet": "조선일보", "url": "https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml"},
    {"outlet": "경향신문", "url": "https://www.khan.co.kr/rss/rssdata/total_news.xml"},
    {"outlet": "동아일보", "url": "https://rss.donga.com/total.xml"},
    {"outlet": "한국경제", "url": "https://www.hankyung.com/feed/all-news"},
    {"outlet": "세계일보", "url": "https://www.segye.com/Articles/RSSList/segye_recent.xml"},
]

# 정책 브리핑: 대한민국 정책브리핑(korea.kr) 정책뉴스.
# 공공누리 제1유형 — 출처표시 조건으로 상업적 이용·변형(AI 요약) 허용.
POLICY_LIST_URL = "https://www.korea.kr/news/policyNewsList.do"
POLICY_VIEW_URL = "https://www.korea.kr/news/policyNewsView.do?newsId={news_id}"
POLICY_COUNT = 6  # 요약할 정책뉴스 수

# ── 클러스터링·배분 파라미터 (알고리즘: cluster.py) ─────────────────────
MAX_ITEM_AGE_HOURS = 24    # 이 시간 이내 기사만 사용
JACCARD_THRESHOLD = 0.30   # 문자 2-그램 자카드 유사도 임계값
OVERLAP_THRESHOLD = 0.40   # 겹침 계수 임계값 (제목 길이 차이 보완)
CANDIDATE_ISSUES = 30      # AI 라벨링 대상 상위 클러스터 수
TOP_ISSUES = 12            # 사이트에 노출할 최종 이슈 수
MAX_ISSUES_PER_CATEGORY = 5  # 핫 분야라도 이 이상은 배분하지 않음
HEAT_DECAY_HOURS = 6.0     # 열기 계산의 최신성 감쇠 상수(시간)
MAX_HEADLINES_PER_ISSUE = 6

# 이슈 분류 카테고리 (AI가 이 중 하나를 지정)
ISSUE_CATEGORIES = ["정치", "경제", "사회", "국제", "IT·과학", "생활·문화"]

# ── 모델/사이트 ─────────────────────────────────────────────────────────
# 비용을 줄이려면 BRIEFING_MODEL=claude-haiku-4-5 로 변경.
MODEL = os.environ.get("BRIEFING_MODEL", "claude-opus-4-8")

SITE_TITLE = "고른뉴스"
SITE_TAGLINE = "골라 담아, 고르게 전합니다"
# 현재 연결 도메인 (내도메인.한국 무료 도메인). goreun.news 구매 시 교체.
SITE_DOMAIN = "고른뉴스.메인.한국"

# Sentry 버그 제보 위젯 — 로더 스크립트 공개 키 (cwworks/goreun-news 프로젝트).
# 브라우저용 공개 DSN 키라 저장소에 포함해도 안전하다. 비우면 위젯 미노출.
SENTRY_LOADER_KEY = os.environ.get("SENTRY_LOADER_KEY", "d80edcd8a1167eecfe0d7ef5bdb37f7c")
