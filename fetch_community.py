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
import json
import re
import time
import urllib.request
from pathlib import Path

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

POSTS_PER_SOURCE = 20  # 소스별 수집 상한 (노출은 참여도 점수로 통합 선별)
TOTAL_POSTS = 36       # 최종 노출 수

NOTICE_MARKERS = ("공지", "필독", "📢", "🚨", "이벤트 안내", "이용 규칙", "◤")

# 🔥 HOT 판정: 키워드 포함 또는 최근 1시간 내 처음 목격된 '초신성' 게시물
HOT_KEYWORDS = ("단독", "후기", "레전드", "속보", "충격", "최초")

# 📰 뉴스성 게시물 감지 — 정밀 신호만 사용.
# 국가명('미국','일본')·범용 동사('발표','출시','사고')는 유머글 오분류율이 높아
# 제외 (라이브 실측: 광범위 마커의 75%가 유머글에 뱃지를 붙였음)
NEWS_MARKERS = (
    "외신", "속보", "단독", "BBC", "CNN", "NYT", "로이터", "가디언", "블룸버그",
    "닛케이", "네이처", "AFP", "AP통신", "연합뉴스", "기자회견", "판결", "리콜",
)
SEEN_PATH = Path(__file__).resolve().parent / "data" / "community_seen.json"
SEEN_TTL_SECONDS = 48 * 3600
NEW_POST_WINDOW_SECONDS = 3600


def _get(url: str, _depth: int = 0) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        # py3.9 urllib는 308을 추적하지 않으므로 수동 추적
        if e.code in (301, 302, 307, 308) and _depth < 3:
            location = e.headers.get("Location")
            if location:
                import urllib.parse as _up

                return _get(_up.urljoin(url, location), _depth + 1)
        raise


def _clean_title(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^\d+\s+", "", text)      # 목록 순번 제거
    text = re.sub(r"\s*\(\d+\)$", "", text)  # 말미 댓글 수 제거
    return text


def _num_in(segment: str, css_class: str) -> int | None:
    """행 조각 안에서 해당 클래스 셀의 숫자를 추출한다 (자식 태그 허용)."""
    m = re.search(rf'class="{css_class}"[^>]*>\s*(?:<[^>]+>\s*)*([0-9,]+)', segment)
    return int(m.group(1).replace(",", "")) if m else None


def _parse_ruliweb(page: str) -> list[dict]:
    # 행(tr) 단위로 제목·추천·조회를 짝지어 수집한다 — 행 경계를 넘는
    # 정규식 매칭이 다음 행의 지표를 오귀속시키던 문제를 원천 차단.
    posts = []
    for row in re.finditer(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        seg = row.group(1)
        a = re.search(
            r'<a class="subject_link[^"]*"\s+href="(/best/[^"]+)"[^>]*>(.*?)</a>', seg, re.S
        )
        if not a:
            continue
        title = _clean_title(a.group(2))
        if len(title) < 4:
            continue
        posts.append({
            "title": title,
            "link": "https://bbs.ruliweb.com" + html.unescape(a.group(1)),
            "recommends": _num_in(seg, "recomd"),
            "views": _num_in(seg, "hit"),
        })
    return posts


def _parse_theqoo(page: str) -> list[dict]:
    # 행(tr) 단위로 제목 앵커와 조회수(td.m_no)를 짝지어 수집한다
    posts = []
    for row in re.finditer(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        seg = row.group(1)
        a = re.search(r'<a href="(/hot/\d+)"[^>]*>(.*?)</a>', seg, re.S)
        if not a:
            continue
        title = _clean_title(a.group(2))
        if len(title) < 4 or any(marker in title for marker in NOTICE_MARKERS):
            continue
        views_m = re.search(r'class="m_no">\s*([0-9,]+)', seg)
        views = int(views_m.group(1).replace(",", "")) if views_m else None
        posts.append({"title": title, "link": "https://theqoo.net" + a.group(1), "views": views})
    return posts


def _parse_etoland(page: str) -> list[dict]:
    posts = []
    for m in re.finditer(
        r'<a([^>]+href="(/b/etohumor07/view/[^"]+)"[^>]*)>(.*?)</a>', page, re.S
    ):
        title_m = re.search(r'title="([^"]{4,})"', m.group(1))
        if not title_m:
            continue
        title = _clean_title(title_m.group(1))
        if len(title) < 4 or any(marker in title for marker in NOTICE_MARKERS):
            continue
        comments_m = re.search(r"comment-s[^>]*>\((?:<!-- -->)?(\d+)", m.group(3))
        posts.append({
            "title": title,
            "link": "https://www.etoland.co.kr" + html.unescape(m.group(2)),
            "comments": int(comments_m.group(1)) if comments_m else None,
        })
    return posts


def _parse_ruliweb_news(page: str) -> list[dict]:
    """루리웹 게임뉴스 보드 — 게시판 자체가 뉴스라 news 태그를 기본 부여한다."""
    posts = []
    for m in re.finditer(
        r'<a class="deco"[^>]*href="(https://bbs\.ruliweb\.com/news/(?:board/\d+/)?read/\d+)"[^>]*>(.*?)</a>',
        page,
        re.S,
    ):
        title = _clean_title(m.group(2))
        if len(title) < 4 or any(marker in title for marker in NOTICE_MARKERS):
            continue
        posts.append({"title": title, "link": m.group(1)})
    return posts


SOURCES = [
    {"name": "루리웹", "url": "https://bbs.ruliweb.com/best/all/now", "parse": _parse_ruliweb},
    # 게임 커뮤니티 특화: 게임 뉴스 보드 (커뮤니티발 뉴스 커버리지)
    {"name": "루리웹", "url": "https://bbs.ruliweb.com/news", "parse": _parse_ruliweb_news, "force_news": True},
    # 더쿠는 데이터센터 IP(GitHub Actions)에서 403이 잦다 — 실패해도 다른 소스는 유지됨
    {"name": "더쿠", "url": "https://theqoo.net/hot", "parse": _parse_theqoo},
    {"name": "이토랜드", "url": "https://etoland.co.kr/b/etohumor07/list", "parse": _parse_etoland},
]


THUMB_FETCH_BUDGET = 20  # 실행당 og:image 조회 상한 (신규 글만, 캐시 재사용)


def _load_seen() -> dict[str, dict]:
    try:
        raw = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    # 구버전(link → float) 레코드 마이그레이션
    return {
        k: (v if isinstance(v, dict) else {"t": v, "thumb": None, "checked": False})
        for k, v in raw.items()
    }


def _fetch_thumb(link: str) -> str | None:
    """게시글 페이지의 og:image URL(대표 썸네일)을 가져온다. 본문은 저장하지 않는다."""
    try:
        page = _get(link)
    except Exception:
        return None
    m = re.search(r'property="og:image"[^>]*content="([^"]+)"', page) or re.search(
        r'content="([^"]+)"[^>]*property="og:image"', page
    )
    if not m:
        return None
    url = html.unescape(m.group(1)).strip()
    return url if url.startswith("http") else None


def fetch_community() -> list[dict]:
    """소스별 인기글 [{source, title, link, hot, thumb}] 목록을 반환한다."""
    now = time.time()
    prev_seen = _load_seen()
    first_run = not prev_seen  # 최초 실행에는 '초신성' 판정을 하지 않는다
    seen_out = {k: v for k, v in prev_seen.items() if now - v.get("t", 0) < SEEN_TTL_SECONDS}

    per_source: list[list[dict]] = []
    for source in SOURCES:
        try:
            page = _get(source["url"])
            posts = source["parse"](page)
        except Exception as e:  # 개별 소스 장애가 전체를 막지 않도록
            print(f"[경고] {source['name']} 인기글 수집 실패: {e}")
            continue
        dedupe: set[str] = set()
        bucket: list[dict] = []
        for post in posts:
            if post["link"] in dedupe:
                continue
            dedupe.add(post["link"])
            rec = seen_out.setdefault(post["link"], {"t": now, "thumb": None, "checked": False})
            is_supernova = (not first_run) and (now - rec["t"] < NEW_POST_WINDOW_SECONDS)
            hot = is_supernova or any(k in post["title"] for k in HOT_KEYWORDS)
            news = bool(source.get("force_news")) or any(
                k in post["title"] for k in NEWS_MARKERS
            )
            bucket.append({"source": source["name"], "hot": hot, "news": news, **post})
            if len(bucket) >= POSTS_PER_SOURCE:
                break
        print(f"[커뮤니티] {source['name']} 인기글 {len(bucket)}건")
        per_source.append(bucket)
        time.sleep(0.3)

    # 참여도 랭킹 v2 — 공정한 교차 정렬:
    # 1) 기본 점수 = 소스 내 순위 백분위(1 - idx/n). 모든 소스에 공통 축이라
    #    지표 없는 소스가 지표 소스를 체계적으로 앞지르는 역전이 없다.
    # 2) 참여 보정 = 지표 '종류별'로 소스 내 최대값 정규화(0~1)의 절반.
    #    views는 views끼리, recommends는 recommends끼리만 비교 — 스케일 혼합 금지.
    # 결과: 지표 있는 인기글이 같은 순위의 무지표 글보다 앞서되(최대 +0.5),
    # 무지표 소스도 순위 비례로 공정하게 섞인다.
    METRIC_KEYS = ("views", "recommends", "comments")

    scored: list[dict] = []
    for bucket in per_source:
        max_by_key = {
            key: max((p.get(key) or 0 for p in bucket), default=0) for key in METRIC_KEYS
        }
        n = max(len(bucket), 1)
        for idx, post in enumerate(bucket):
            base = 1.0 - idx / n
            boost = 0.0
            for key in METRIC_KEYS:
                value = post.get(key)
                if value and max_by_key[key]:
                    boost = max(boost, 0.5 * value / max_by_key[key])
            scored.append({**post, "_score": base + boost})

    scored.sort(key=lambda p: p["_score"], reverse=True)
    all_posts = [{k: v for k, v in p.items() if k != "_score"} for p in scored[:TOTAL_POSTS]]

    # 썸네일: 신규 글만 og:image 1회 조회 (핫링크 표시용 URL만 저장, 이미지 미복제)
    budget = THUMB_FETCH_BUDGET
    for post in all_posts:
        rec = seen_out[post["link"]]
        if not rec.get("checked") and budget > 0:
            rec["thumb"] = _fetch_thumb(post["link"])
            rec["checked"] = True
            budget -= 1
            time.sleep(0.2)
        post["thumb"] = rec.get("thumb")

    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(seen_out), encoding="utf-8")
    return all_posts
