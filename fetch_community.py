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

# 📰 뉴스성 게시물 감지: 해외 매체·외신·시사 사건 키워드 (커뮤니티발 뉴스 커버리지)
NEWS_MARKERS = (
    "외신", "속보", "BBC", "CNN", "NYT", "로이터", "가디언", "블룸버그", "닛케이",
    "네이처", "AFP", "AP통신", "발표", "출시", "판결", "사고", "화재", "지진",
    "미국", "일본", "중국", "러시아", "우크라", "이스라엘", "트럼프", "유럽",
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


def _parse_ruliweb(page: str) -> list[dict]:
    # 목록이 노출하는 추천(recomd)·조회(hit) 지표를 함께 수집한다
    metrics: dict[str, tuple[int, int]] = {}
    for m in re.finditer(
        r'subject_link[^>]*href="(/best/[^"]+)".*?class="recomd">\s*([0-9,]+)?.*?class="hit">\s*([0-9,]+)?',
        page,
        re.S,
    ):
        rec = int((m.group(2) or "0").replace(",", ""))
        hit = int((m.group(3) or "0").replace(",", ""))
        metrics[html.unescape(m.group(1))] = (rec, hit)

    posts = []
    for m in re.finditer(
        r'<a class="subject_link[^"]*"\s+href="(/best/[^"]+)"[^>]*>(.*?)</a>',
        page,
        re.S,
    ):
        title = _clean_title(m.group(2))
        if len(title) < 4:
            continue
        path = html.unescape(m.group(1))
        rec, hit = metrics.get(path, (0, 0))
        posts.append({
            "title": title,
            "link": "https://bbs.ruliweb.com" + path,
            "recommends": rec or None,
            "views": hit or None,
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

    # 참여도 기반 통합 랭킹: 소스마다 지표 스케일이 달라(더쿠 조회수 ≫ 이토랜드 댓글)
    # 소스 내 최대값으로 정규화(0~1)한 점수로 전체를 정렬한다.
    # 지표가 없는 소스는 사이트 자체 랭킹 순서를 점수로 환산해 공정하게 섞는다.
    def _engagement(post: dict) -> int | None:
        for key in ("views", "recommends", "comments"):
            if post.get(key):
                return post[key]
        return None

    scored: list[dict] = []
    for bucket in per_source:
        metrics = [_engagement(p) for p in bucket]
        max_metric = max((m for m in metrics if m), default=0)
        for idx, post in enumerate(bucket):
            metric = metrics[idx]
            if metric and max_metric:
                score = metric / max_metric
            else:
                score = 1.0 - idx / max(len(bucket), 1)
            post["src_rank"] = idx + 1
            scored.append({**post, "_score": score})

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
