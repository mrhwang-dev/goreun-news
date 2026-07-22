"""커뮤니티 인기글 수집 — '게시글 제목 + 원문 링크'만 사용한다.

뉴스와 동일한 안전선: 본문·이미지는 수집하지 않고 제목을 원문 그대로
표시하며 반드시 원문에 아웃링크한다.

소스 선정 (2026-07-22 확인):
- 루리웹 베스트: robots.txt에서 /best 허용, HTML 구조 안정적
- 더쿠 HOT: robots.txt 미제공(제한 없음), 공지 글 필터링 필요
- 제외: 클리앙(추천 페이지 410), 오늘의유머(RSS 중단), 개드립(403 차단),
  에펨코리아(수집 차단 정책), 뽐뿌(핫게시물 페이지 파싱 불가)
"""

from __future__ import annotations

import html
import re
import time
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

POSTS_PER_SOURCE = 12

NOTICE_MARKERS = ("공지", "필독", "📢", "🚨", "이벤트 안내", "이용 규칙", "◤")


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _clean_title(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^\d+\s+", "", text)      # 목록 순번 제거
    text = re.sub(r"\s*\(\d+\)$", "", text)  # 말미 댓글 수 제거
    return text


def _parse_ruliweb(page: str) -> list[dict]:
    posts = []
    for m in re.finditer(
        r'<a class="subject_link[^"]*"\s+href="(/best/[^"]+)"[^>]*>(.*?)</a>',
        page,
        re.S,
    ):
        title = _clean_title(m.group(2))
        if len(title) < 4:
            continue
        link = "https://bbs.ruliweb.com" + html.unescape(m.group(1))
        posts.append({"title": title, "link": link})
    return posts


def _parse_theqoo(page: str) -> list[dict]:
    posts = []
    for m in re.finditer(r'<a href="(/hot/\d+)"[^>]*>(.*?)</a>', page, re.S):
        title = _clean_title(m.group(2))
        if len(title) < 4 or any(marker in title for marker in NOTICE_MARKERS):
            continue
        posts.append({"title": title, "link": "https://theqoo.net" + m.group(1)})
    return posts


SOURCES = [
    {"name": "루리웹", "url": "https://bbs.ruliweb.com/best/all/now", "parse": _parse_ruliweb},
    {"name": "더쿠", "url": "https://theqoo.net/hot", "parse": _parse_theqoo},
]


def fetch_community() -> list[dict]:
    """소스별 인기글을 모아 [{source, title, link}] 목록으로 반환한다."""
    all_posts: list[dict] = []
    for source in SOURCES:
        try:
            page = _get(source["url"])
            posts = source["parse"](page)
        except Exception as e:  # 개별 소스 장애가 전체를 막지 않도록
            print(f"[경고] {source['name']} 인기글 수집 실패: {e}")
            continue
        seen: set[str] = set()
        count = 0
        for post in posts:
            if post["link"] in seen:
                continue
            seen.add(post["link"])
            all_posts.append({"source": source["name"], **post})
            count += 1
            if count >= POSTS_PER_SOURCE:
                break
        print(f"[커뮤니티] {source['name']} 인기글 {count}건")
        time.sleep(0.3)
    return all_posts
