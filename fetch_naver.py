"""네이버 뉴스 검색 API(NAVER API HUB)로 헤드라인을 보강 수집한다.

RSS와 동일한 저작권 안전선(SOURCES.md): '제목 + 원문 링크'만 사용하고 본문·
요약문(description)은 수집하지 않으며, 반드시 원문(originallink)으로 아웃링크한다.
콘텐츠 이용이 제한된 매체(한겨레·SBS 등)는 도메인 기준으로 제외해 기존 방침을 지킨다.
출처 매체는 원문 도메인으로 판별하며, 판별 불가한 도메인은 교차확인 집계 오염을
막기 위해 제외한다(정확도 우선).
"""

from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import config

ENDPOINT = "https://naverapihub.apigw.ntruss.com/search/v1/news"  # NAVER API HUB 게이트웨이
DISPLAY = 100          # 질의당 최대 (네이버 상한 100)
SLEEP_BETWEEN = 0.1    # 질의 간 간격

# 분야별 최신 기사 보강 질의. 특수문자(·) 없는 검색어로 정리.
QUERIES = ["정치", "경제", "사회", "국제", "과학", "문화"]

# 원문 도메인 → 매체명. 기존 RSS 매체와 이름을 맞춰야 클러스터 교차확인 집계가 합쳐진다.
DOMAIN_TO_OUTLET: dict[str, str] = {
    "chosun.com": "조선일보", "khan.co.kr": "경향신문", "donga.com": "동아일보",
    "segye.com": "세계일보", "seoul.co.kr": "서울신문", "mbn.co.kr": "MBN",
    "hankyung.com": "한국경제", "mt.co.kr": "머니투데이", "edaily.co.kr": "이데일리",
    "mk.co.kr": "매일경제", "etnews.com": "전자신문", "bloter.net": "블로터",
    "ohmynews.com": "오마이뉴스", "mediatoday.co.kr": "미디어오늘",
    "sisain.co.kr": "시사인", "kmib.co.kr": "국민일보", "nocutnews.co.kr": "노컷뉴스",
    "jtbc.co.kr": "JTBC", "kbs.co.kr": "KBS", "imbc.com": "MBC",
    "news1.kr": "뉴스1", "newsis.com": "뉴시스", "hankookilbo.com": "한국일보",
    "yna.co.kr": "연합뉴스", "hani.co.kr": "한겨레", "sbs.co.kr": "SBS",
    "joongang.co.kr": "중앙일보", "joins.com": "중앙일보", "munhwa.com": "문화일보",
    "hankyung.io": "한국경제",
}


def _domain(url: str) -> str:
    try:
        host = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def _base_domain(host: str) -> str:
    """a.b.chosun.com → chosun.com (co.kr/or.kr 등 2단계 TLD 고려)."""
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "or", "go", "ne", "re"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _clean_title(title: str) -> str:
    title = re.sub(r"</?b>", "", title)          # 검색어 강조 태그 제거
    return html.unescape(title).strip()


def _parse_pubdate(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return parsedate_to_datetime(text.strip())
    except (ValueError, TypeError, OverflowError):
        return None


def fetch_naver_news() -> list[dict]:
    """네이버 뉴스 검색 결과를 헤드라인 형식 [{title, link, outlet, ts, ts_estimated}]로 반환.

    자격증명(NAVER_CLIENT_ID/SECRET) 미설정이면 빈 목록을 반환한다.
    """
    cid = os.environ.get("NAVER_CLIENT_ID")
    csec = os.environ.get("NAVER_CLIENT_SECRET")
    if not (cid and csec):
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.MAX_ITEM_AGE_HOURS)
    exclude = config.NAVER_EXCLUDE_DOMAINS
    seen: set[str] = set()
    out: list[dict] = []
    dropped_excluded = 0

    for query in QUERIES:
        url = ENDPOINT + "?" + urllib.parse.urlencode(
            {"query": query, "display": DISPLAY, "start": 1, "sort": "date", "format": "json"}
        )
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "X-NCP-APIGW-API-KEY-ID": cid,      # Client ID
                    "X-NCP-APIGW-API-KEY": csec,        # Client Secret
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"[경고] 네이버 검색 실패 (query={query}): {e}")
            continue

        for item in data.get("items", []):
            link = (item.get("originallink") or item.get("link") or "").strip()
            if not link or link in seen:
                continue
            dom = _base_domain(_domain(link))
            if dom in exclude:
                dropped_excluded += 1
                continue
            outlet = DOMAIN_TO_OUTLET.get(dom)
            if not outlet:            # 미매핑 도메인은 출처 정확도를 위해 제외
                continue
            title = _clean_title(item.get("title", ""))
            if len(title) < 6:
                continue
            ts = _parse_pubdate(item.get("pubDate"))
            if ts is None or ts < cutoff:
                continue
            seen.add(link)
            out.append({
                "title": title, "link": link, "outlet": outlet,
                "ts": ts, "ts_estimated": False,
            })
        time.sleep(SLEEP_BETWEEN)

    note = f" (제외매체 {dropped_excluded}건 필터)" if dropped_excluded else ""
    print(f"[네이버 검색] {len(out)}건 보강 수집 ({len(QUERIES)}개 질의){note}")
    return out
