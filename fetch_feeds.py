"""언론사 공개 RSS에서 헤드라인(제목·링크·시각)만 수집한다.

본문·요약문(description)은 수집하지 않는다 — 저작권 안전선(SOURCES.md).
"""

from __future__ import annotations

import asyncio
import httpx
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import config
from quality import is_promotional

UA = "Mozilla/5.0 (compatible; GoreunNews/1.0; +https://goreunnews.cloud)"
KST = timezone(timedelta(hours=9))


async def _fetch_xml(client: httpx.AsyncClient, url: str) -> str:
    try:
        resp = await client.get(url, timeout=15.0)
        resp.raise_for_status()
        raw = resp.content
    except Exception as e:
        print(f"[경고] RSS 수집 실패 ({url}): {e}")
        return ""

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


def _extract_date_str(item: ET.Element) -> str | None:
    """RSS item / Atom entry 요소 안에서 다양한 태그(pubDate, dc:date, published, updated)를 탐색한다."""
    for elem in item:
        tag_name = elem.tag.split("}")[-1].lower() if "}" in elem.tag else elem.tag.lower()
        if tag_name in ("pubdate", "date", "published", "updated"):
            if elem.text and elem.text.strip():
                return elem.text.strip()
    return None


def _parse_ts(text: str | None) -> datetime | None:
    """pubDate / dc:date / Atom published 날짜 파싱.
    타임존이 없는 시각은 KST(UTC+9)로 설정한다.
    """
    if not text:
        return None
    cleaned = text.strip()
    # RFC822 쉼표 띄어쓰기 보정 ("Wed,22" -> "Wed, 22")
    cleaned = re.sub(r"^([A-Za-z]{3}),(\d)", r"\1, \2", cleaned)
    # 한국어 요일 표기 제거 ("2026-07-22 (수) 16:54:12" -> "2026-07-22 16:54:12")
    cleaned = re.sub(r"\s*\([월화수목금토일]\)", "", cleaned)

    # 1. RFC 822 / 2822 파싱
    try:
        dt = parsedate_to_datetime(cleaned)
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KST)
            return dt
    except (ValueError, TypeError, OverflowError):
        pass

    # 2. ISO 8601 / fromisoformat 파싱
    try:
        iso_str = cleaned.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return dt
    except (ValueError, TypeError):
        pass

    # 3. strptime 파싱 (국내 언론사의 다양한 날짜 구분 기호)
    norm = cleaned.replace(".", "-").replace("/", "-")
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(norm, fmt)
            return dt.replace(tzinfo=KST)
        except (ValueError, TypeError):
            continue

    return None


async def _fetch_feed_items(client: httpx.AsyncClient, feed: dict, cutoff: datetime) -> tuple[list[dict], int]:
    text = await _fetch_xml(client, feed["url"])
    if not text:
        return [], 0
    try:
        root = ET.fromstring(text)
    except Exception as e:
        print(f"[경고] {feed['outlet']} XML 파싱 실패: {e}")
        return [], 0

    items: list[dict] = []
    promo_dropped = 0
    feed_count = 0
    # RSS <item> 과 Atom <entry> 모두 호환 탐색
    raw_items = list(root.iter("item")) or list(root.iter("entry")) or list(root.iter("{http://www.w3.org/2005/Atom}entry"))
    for item in raw_items:
        title = html.unescape((item.findtext("title") or "").strip())
        link = (item.findtext("link") or "").strip()
        if not link:
            # Atom link 요소 처리 (<link href="..."/>)
            link_elem = item.find("link") or item.find("{http://www.w3.org/2005/Atom}link")
            if link_elem is not None:
                link = link_elem.attrib.get("href", "").strip()
        if not title or not link:
            continue
        if is_promotional(title):
            promo_dropped += 1
            continue
        raw_date = _extract_date_str(item)
        parsed_ts = _parse_ts(raw_date)
        # 발행 시각을 못 읽으면 수집 시각으로 대체하되, 추정값임을 표시한다.
        # 속보 등 '발행 시각'을 그대로 노출하는 곳에서는 추정값을 쓰지 않는다.
        ts = parsed_ts or datetime.now(timezone.utc)
        if ts < cutoff:
            continue
        items.append({
            "title": title, "link": link, "outlet": feed["outlet"],
            "ts": ts, "ts_estimated": parsed_ts is None,
        })
        feed_count += 1
        if feed_count >= config.MAX_ITEMS_PER_FEED:
            break
    return items, promo_dropped


async def _fetch_headlines_async() -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.MAX_ITEM_AGE_HOURS)
    all_items: list[dict] = []
    seen: set[str] = set()
    total_promo_dropped = 0

    async with httpx.AsyncClient(headers={"User-Agent": UA}) as client:
        tasks = [
            _fetch_feed_items(client, feed, cutoff)
            for feed in config.PRESS_FEEDS
        ]
        results = await asyncio.gather(*tasks)

        for items, promo_dropped in results:
            total_promo_dropped += promo_dropped
            for it in items:
                if it["link"] not in seen:
                    seen.add(it["link"])
                    all_items.append(it)

    if total_promo_dropped:
        print(f"[품질 필터] 광고성 기사 {total_promo_dropped}건 제외")
    print(f"[피드 수집] 총 {len(all_items)}건 수집 완료 ({len(config.PRESS_FEEDS)}개 피드 비동기 수집)")
    return all_items


def fetch_headlines() -> list[dict]:
    """설정된 모든 언론사 피드에서 최근 기사 헤드라인을 비동기로 수집해 반환한다."""
    return asyncio.run(_fetch_headlines_async())
