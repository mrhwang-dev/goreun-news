"""오늘의 중립 브리핑 — 설정."""

import os

# 카테고리별 네이버 뉴스 검색 쿼리.
# 네이버 뉴스 검색 API는 카테고리 조회가 아니라 키워드 검색이므로,
# 카테고리당 여러 키워드로 검색해 결과를 합친다.
CATEGORIES = [
    {"id": "politics", "name": "정치", "queries": ["정치", "국회", "여야"]},
    {"id": "economy", "name": "경제", "queries": ["경제", "금리", "증시"]},
    {"id": "society", "name": "사회", "queries": ["사회", "노동", "교육"]},
    {"id": "tech", "name": "IT/과학", "queries": ["인공지능", "IT 산업", "과학기술"]},
]

# 쿼리당 수집 기사 수 (네이버 API display 파라미터, 최대 100)
ITEMS_PER_QUERY = 30

# 카테고리당 브리핑 이슈 수
ISSUES_PER_CATEGORY = 5

# 요약에 투입할 카테고리당 최대 기사 수 (토큰 상한 관리)
MAX_ITEMS_FOR_SUMMARY = 60

# Claude 모델. 비용을 줄이려면 BRIEFING_MODEL=claude-haiku-4-5 로 변경.
MODEL = os.environ.get("BRIEFING_MODEL", "claude-opus-4-8")

SITE_TITLE = "고른뉴스"
SITE_TAGLINE = "골라 담아, 고르게 전합니다 — 여러 언론사의 보도를 AI가 교차 확인한 중립 브리핑"
SITE_DOMAIN = "goreun.news"
