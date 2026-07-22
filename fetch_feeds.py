"""언론사 공개 RSS에서 헤드라인(제목·링크·시각)만 수집한다.

본문·요약문(description)은 수집하지 않는다 — 저작권 안전선(SOURCES.md).
"""

from __future__ import annotations

import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import config

UA = "Mozilla/5.0 (compatible; GoreunNews/1.0; +https://goreun.news)"


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def _parse_ts(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def fetch_headlines() -> list[dict]:
    """설정된 모든 언론사 피드에서 최근 기사 헤드라인을 모아 반환한다."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.MAX_ITEM_AGE_HOURS)
    items: list[dict] = []
    seen: set[str] = set()

    for feed in config.PRESS_FEEDS:
        try:
            root = ET.fromstring(_fetch(feed["url"]))
        except Exception as e:  # 개별 피드 장애가 전체를 막지 않도록
            print(f"[경고] {feed['outlet']} 피드 수집 실패: {e}")
            continue

        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not title or not link or link in seen:
                continue
            ts = _parse_ts(item.findtext("pubDate")) or datetime.now(timezone.utc)
            if ts < cutoff:
                continue
            seen.add(link)
            items.append(
                {"title": title, "link": link, "outlet": feed["outlet"], "ts": ts}
            )
        time.sleep(0.2)

    return items
