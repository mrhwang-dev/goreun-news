"""언론사 공개 RSS에서 헤드라인(제목·링크·시각)만 수집한다.

본문·요약문(description)은 수집하지 않는다 — 저작권 안전선(SOURCES.md).
"""

from __future__ import annotations

import html
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import config

import re

UA = "Mozilla/5.0 (compatible; GoreunNews/1.0; +https://goreun.news)"


def _fetch_xml(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
        encoding = "utf-8"
        content_type = resp.headers.get("Content-Type", "")
        if "charset=" in content_type.lower():
            encoding = content_type.lower().split("charset=")[-1].split(";")[0].strip()
        elif b"encoding=" in raw[:100].lower():
            m = re.search(rb'encoding=["\']([^"\']+)["\']', raw[:100], re.IGNORECASE)
            if m:
                encoding = m.group(1).decode("ascii", errors="ignore")

        try:
            text = raw.decode(encoding, errors="replace")
        except (LookupError, UnicodeDecodeError):
            text = raw.decode("utf-8", errors="replace")

        # Expat 파서가 XML 선언문 내 euc-kr/cp949 표기에 반응하여 오류를 일으키는 현상 방지
        return re.sub(r'encoding=["\'][^"\']+["\']', 'encoding="utf-8"', text, count=1, flags=re.I)


def _parse_ts(text: str | None) -> datetime | None:
    if not text:
        return None
    cleaned = text.strip()
    try:
        dt = parsedate_to_datetime(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        pass
    try:
        dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
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
            root = ET.fromstring(_fetch_xml(feed["url"]))
        except Exception as e:  # 개별 피드 장애가 전체를 막지 않도록
            print(f"[경고] {feed['outlet']} 피드 수집 실패: {e}")
            continue

        feed_count = 0
        for item in root.iter("item"):
            # 일부 피드는 엔티티를 이중 인코딩(&amp;#8593; 등)하므로 한 번 더 해제
            title = html.unescape((item.findtext("title") or "").strip())
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
            feed_count += 1
            if feed_count >= config.MAX_ITEMS_PER_FEED:
                break
        time.sleep(0.1)

    return items
