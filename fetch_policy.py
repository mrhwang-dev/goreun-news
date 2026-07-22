"""대한민국 정책브리핑(korea.kr) 정책뉴스 수집.

korea.kr 정책뉴스는 공공누리 제1유형 — 출처표시 조건으로 상업적 이용과
변형(AI 요약)이 허용된다. robots.txt도 전체 수집을 허용한다(Allow: /).
텍스트만 사용하고 사진·이미지는 수집하지 않는다(제3자 저작물).
"""

from __future__ import annotations

import html
import re
import time
import urllib.request

import config

UA = "Mozilla/5.0 (compatible; GoreunNews/1.0; +https://goreun.news)"


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _strip_tags(fragment: str) -> str:
    fragment = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", fragment, flags=re.S | re.I)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(fragment)).strip()


def fetch_policy_news(count: int | None = None) -> list[dict]:
    """정책뉴스 목록에서 최신 기사 본문 텍스트를 수집한다."""
    count = count or config.POLICY_COUNT
    try:
        listing = _get(config.POLICY_LIST_URL)
    except Exception as e:  # korea.kr 간헐 타임아웃 — 전체 파이프라인을 막지 않는다
        print(f"[경고] 정책뉴스 목록 수집 실패: {e}")
        return []
    news_ids = []
    for m in re.finditer(r"policyNewsView\.do\?newsId=(\d+)", listing):
        if m.group(1) not in news_ids:
            news_ids.append(m.group(1))
    news_ids = news_ids[:count]

    articles: list[dict] = []
    for news_id in news_ids:
        url = config.POLICY_VIEW_URL.format(news_id=news_id)
        try:
            page = _get(url)
        except Exception as e:
            print(f"[경고] 정책뉴스 {news_id} 수집 실패: {e}")
            continue

        title_m = (
            re.search(r'(?:property|name)="og:title"\s+content="([^"]+)"', page)
            or re.search(r'content="([^"]+)"\s+(?:property|name)="og:title"', page)
        )
        title = html.unescape(title_m.group(1)) if title_m else ""
        title = re.sub(r"\s*[-|]\s*정책뉴스.*$", "", title).strip()

        body_m = re.search(
            r'<div[^>]+class="[^"]*article_body[^"]*"[^>]*>(.*?)</div>\s*<', page, re.S
        )
        if body_m:
            body = _strip_tags(body_m.group(1))
        else:
            desc_m = (
                re.search(r'(?:property|name)="og:description"\s+content="([^"]*)"', page)
                or re.search(r'content="([^"]*)"\s+(?:property|name)="og:description"', page)
            )
            body = html.unescape(desc_m.group(1)) if desc_m else ""

        if not title or len(body) < 80:
            continue
        articles.append({"id": news_id, "title": title, "link": url, "body": body[:3000]})
        time.sleep(0.3)

    return articles
