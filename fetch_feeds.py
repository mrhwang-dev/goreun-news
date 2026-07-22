"""언론사 공개 RSS에서 헤드라인(제목·링크·시각)만 수집한다.

본문·요약문(description)은 수집하지 않는다 — 저작권 안전선(SOURCES.md).
"""

from __future__ import annotations

import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import config
from quality import is_promotional

UA = "Mozilla/5.0 (compatible; GoreunNews/1.0; +https://goreunnews.cloud)"


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
        text = re.sub(r'encoding=["\'][^"\']+["\']', 'encoding="utf-8"', text, count=1, flags=re.I)
        # XML 파싱 에러를 유발하는 좁은 범위 제어 문자(Control characters) 제거
        return re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', text)


KST = timezone(timedelta(hours=9))


def _parse_ts(text: str | None) -> datetime | None:
    """pubDate 파싱. 타임존이 없는 시각은 KST로 가정한다."""
    if not text:
        return None
    cleaned = text.strip()
    try:
        dt = parsedate_to_datetime(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return dt
    except (ValueError, TypeError):
        pass
    try:
        dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return dt
    except (ValueError, TypeError):
        return None


def _fetch_feed_items(feed: dict, cutoff: datetime) -> tuple[list[dict], int]:
    """단일 피드 수집 워커 함수 (ThreadPoolExecutor에서 비동기 병렬 실행)."""
    items: list[dict] = []
    promo_dropped = 0
    try:
        xml_data = _fetch_xml(feed["url"])
        root = ET.fromstring(xml_data)
    except Exception as e:
        print(f"[경고] {feed['outlet']} 피드 수집 실패: {e}")
        return [], 0

    feed_count = 0
    for item in root.iter("item"):
        title = html.unescape((item.findtext("title") or "").strip())
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        if is_promotional(title):
            promo_dropped += 1
            continue
        ts = _parse_ts(item.findtext("pubDate")) or datetime.now(timezone.utc)
        if ts < cutoff:
            continue
        items.append({"title": title, "link": link, "outlet": feed["outlet"], "ts": ts})
        feed_count += 1
        if feed_count >= config.MAX_ITEMS_PER_FEED:
            break
    return items, promo_dropped


def fetch_headlines() -> list[dict]:
    """설정된 모든 언론사 피드에서 최근 기사 헤드라인을 병렬 수집해 반환한다."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.MAX_ITEM_AGE_HOURS)
    all_items: list[dict] = []
    seen: set[str] = set()
    total_promo_dropped = 0

    # ThreadPoolExecutor로 60+ 피드를 병렬(max_workers=12) 수집하여 딜레이 90% 감소
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [
            executor.submit(_fetch_feed_items, feed, cutoff)
            for feed in config.PRESS_FEEDS
        ]
        for future in as_completed(futures):
            items, promo_dropped = future.result()
            total_promo_dropped += promo_dropped
            for it in items:
                if it["link"] not in seen:
                    seen.add(it["link"])
                    all_items.append(it)

    if total_promo_dropped:
        print(f"[품질 필터] 광고성 기사 {total_promo_dropped}건 제외")
    print(f"[피드 수집] 총 {len(all_items)}건 수집 완료 ({len(config.PRESS_FEEDS)}개 피드 병렬 수집)")
    return all_items
