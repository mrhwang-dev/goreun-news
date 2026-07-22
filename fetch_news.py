"""네이버 뉴스 검색 API로 기사 메타데이터(제목·요약문·링크)를 수집한다.

저작권 안전선: 본문 크롤링은 하지 않는다. API가 제공하는
title / description / link 필드만 사용하고, 모든 이슈에 원문 링크를 표기한다.
"""

import html
import json
import os
import re
import time
import urllib.parse
import urllib.request

NAVER_URL = "https://openapi.naver.com/v1/search/news.json"

# originallink 도메인 → 언론사 표기명 (대표적인 곳만; 없으면 도메인 그대로 표시)
OUTLET_NAMES = {
    "yna.co.kr": "연합뉴스",
    "newsis.com": "뉴시스",
    "news1.kr": "뉴스1",
    "chosun.com": "조선일보",
    "joongang.co.kr": "중앙일보",
    "donga.com": "동아일보",
    "hani.co.kr": "한겨레",
    "khan.co.kr": "경향신문",
    "hankookilbo.com": "한국일보",
    "kbs.co.kr": "KBS",
    "imnews.imbc.com": "MBC",
    "sbs.co.kr": "SBS",
    "jtbc.co.kr": "JTBC",
    "ytn.co.kr": "YTN",
    "mk.co.kr": "매일경제",
    "hankyung.com": "한국경제",
    "sedaily.com": "서울경제",
    "edaily.co.kr": "이데일리",
    "mt.co.kr": "머니투데이",
    "etnews.com": "전자신문",
    "zdnet.co.kr": "지디넷코리아",
    "ohmynews.com": "오마이뉴스",
    "pressian.com": "프레시안",
    "segye.com": "세계일보",
    "kmib.co.kr": "국민일보",
    "seoul.co.kr": "서울신문",
    "munhwa.com": "문화일보",
}


def _clean(text: str) -> str:
    """네이버 API 응답의 <b> 강조 태그와 HTML 엔티티를 제거한다."""
    text = re.sub(r"</?b>", "", text or "")
    return html.unescape(text).strip()


def _outlet(url: str) -> str:
    m = re.match(r"https?://(?:www\.|news\.|n\.)?([^/:]+)", url or "")
    if not m:
        return "출처"
    domain = m.group(1)
    for key, name in OUTLET_NAMES.items():
        if domain.endswith(key):
            return name
    return domain


def fetch_category(queries: list[str], per_query: int = 30) -> list[dict]:
    """카테고리에 속한 키워드들로 검색해 중복을 제거한 기사 목록을 반환한다."""
    client_id = os.environ["NAVER_CLIENT_ID"]
    client_secret = os.environ["NAVER_CLIENT_SECRET"]

    items: list[dict] = []
    seen_links: set[str] = set()
    seen_titles: set[str] = set()

    for query in queries:
        params = urllib.parse.urlencode(
            {"query": query, "display": per_query, "sort": "date"}
        )
        req = urllib.request.Request(
            f"{NAVER_URL}?{params}",
            headers={
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)

        for it in data.get("items", []):
            link = it.get("originallink") or it.get("link")
            title = _clean(it.get("title", ""))
            if not link or not title:
                continue
            if link in seen_links or title in seen_titles:
                continue
            seen_links.add(link)
            seen_titles.add(title)
            items.append(
                {
                    "title": title,
                    "description": _clean(it.get("description", "")),
                    "link": link,
                    "outlet": _outlet(link),
                    "pub_date": it.get("pubDate", ""),
                }
            )
        time.sleep(0.2)  # 네이버 API 초당 호출 제한 여유

    return items
