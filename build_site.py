"""브리핑 데이터를 Tailwind 기반 인터랙티브 정적 페이지로 렌더링한다.

- index.html: 뉴스 대시보드 — 좌 70% 이슈 카드 그리드 / 우 30% 사이드바
  (정책 브리핑·공개 API), 모바일은 1단. 카테고리 탭(+기사 수 뱃지) 필터,
  탭 아래 속보 티커(페이드 전환, prefers-reduced-motion 존중).
- community.html: 커뮤니티 인기글 전용 페이지 (소스 탭 필터).
- 10분마다 JSON 폴링으로 새 브리핑 감지 시 자동 새로고침.
- 버그 제보: Sentry Feedback 위젯. 공개 API: /briefing.json, /community.json
"""

from __future__ import annotations

import html
import urllib.parse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import config
from og_image import CATEGORY_COLORS, build_og

# ── 공통 조각 ───────────────────────────────────────────────────────────

LOGO_MARK = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="26" height="26" aria-hidden="true" class="shrink-0 rounded-[7px]">
  <rect width="64" height="64" rx="14" fill="#2563eb"/>
  <rect x="14" y="17" width="36" height="7" rx="3.5" fill="#fff"/>
  <rect x="14" y="28.5" width="36" height="7" rx="3.5" fill="#fff" opacity="0.88"/>
  <rect x="14" y="40" width="36" height="7" rx="3.5" fill="#fff" opacity="0.76"/>
</svg>"""

FAVICON_SVG = "data:image/svg+xml," + urllib.parse.quote(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="14" fill="#2563eb"/>'
    '<rect x="14" y="17" width="36" height="7" rx="3.5" fill="#fff"/>'
    '<rect x="14" y="28.5" width="36" height="7" rx="3.5" fill="#fff" opacity="0.88"/>'
    '<rect x="14" y="40" width="36" height="7" rx="3.5" fill="#fff" opacity="0.76"/>'
    "</svg>"
)

CUSTOM_STYLE = """
.no-scrollbar::-webkit-scrollbar { display: none; }
.no-scrollbar { scrollbar-width: none; }
.tab[aria-selected="true"] { @apply bg-neutral-900 text-stone-50 border-neutral-900 dark:bg-neutral-100 dark:text-neutral-900 dark:border-neutral-100; }
.tab[aria-selected="true"] .badge { @apply bg-white/20 dark:bg-black/10; }
details[open] .tri { transform: rotate(180deg); }
.tri { transition: transform 0.15s; }
.ticker-item { transition: opacity 0.5s; }
.ticker-item.show { opacity: 1; }
@media (prefers-reduced-motion: reduce) { .ticker-item, .tri { transition: none; } }
"""

AD_SLOT = (
    '<div class="rounded-xl border border-dashed border-stone-300 dark:border-neutral-600 '
    'bg-stone-100 dark:bg-neutral-800/60 text-neutral-400 text-xs text-center px-4 py-7">'
    "광고 영역 — AdSense/카카오 AdFit 승인 후 코드 삽입</div>"
)

DISCLAIMER = (
    "고른뉴스는 언론사 기사 본문을 수집·저장·복제하지 않습니다. 이슈 카드는 각 언론사가 "
    "공개한 헤드라인(제목)과 원문 링크만을 표시하며, 요약문은 헤드라인에 담긴 정보만을 "
    "근거로 AI가 새로 작성한 문장입니다. 모든 기사의 저작권은 각 언론사에 있으며, "
    "자세한 내용은 반드시 원문 기사를 확인해 주세요."
)

KOGL_NOTICE = (
    "'정책 브리핑' 섹션은 대한민국 정책브리핑(korea.kr)의 정책뉴스 자료를 활용하였으며, "
    "해당 자료는 공공누리 제1유형에 따라 이용할 수 있습니다."
)

COMMUNITY_NOTICE = (
    "커뮤니티 인기글은 각 커뮤니티가 공개한 게시글 제목과 원문 링크만을 표시합니다. "
    "게시글의 저작권은 각 작성자와 해당 커뮤니티에 있습니다."
)

BASE_SCRIPT = """
(function () {
  // 탭 필터 (뉴스: data-cat / 커뮤니티: data-src)
  var tabs = document.querySelectorAll(".tab");
  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      tabs.forEach(function (t) { t.setAttribute("aria-selected", "false"); });
      tab.setAttribute("aria-selected", "true");
      var key = tab.dataset.filter;
      var val = tab.dataset.value;
      document.querySelectorAll("[data-" + key + "]").forEach(function (el) {
        el.hidden = val !== "전체" && el.dataset[key] !== val;
      });
    });
  });

  // 속보 티커: 5초 간격 페이드 전환 (모션 최소화 설정 시 첫 항목 고정)
  var items = document.querySelectorAll(".ticker-item");
  if (items.length) {
    var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    items[0].classList.add("show");
    if (!reduced && items.length > 1) {
      var idx = 0;
      setInterval(function () {
        items[idx].classList.remove("show");
        idx = (idx + 1) % items.length;
        items[idx].classList.add("show");
      }, 5000);
    }
  }

  // 새 데이터 감지 → 자동 새로고침 (10분 주기)
  var root = document.documentElement;
  var current = root.dataset.generatedAt;
  var feed = root.dataset.feed;
  if (feed) {
    setInterval(function () {
      fetch(feed, { cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.generated_at && d.generated_at !== current) location.reload();
        })
        .catch(function () {});
    }, 10 * 60 * 1000);
  }
})();

window.sentryOnLoad = function () {
  Sentry.init({
    integrations: [
      Sentry.feedbackIntegration({
        autoInject: false,
        colorScheme: "system",
        showBranding: false,
        formTitle: "버그 제보",
        nameLabel: "이름", namePlaceholder: "이름 (선택)",
        emailLabel: "이메일", emailPlaceholder: "이메일 (선택)",
        messageLabel: "내용", messagePlaceholder: "발견한 문제나 개선 아이디어를 알려주세요",
        submitButtonLabel: "보내기", cancelButtonLabel: "취소",
        successMessageText: "제보해 주셔서 감사합니다.",
      }),
    ],
  });
  var feedback = Sentry.getFeedback && Sentry.getFeedback();
  var btn = document.getElementById("bug-report");
  if (feedback && btn) feedback.attachTo(btn, {});
};
"""


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def _favicon(link: str) -> str:
    host = urllib.parse.urlparse(link).netloc
    if not host:
        return ""
    return (
        f'<img class="inline-block rounded-[3px] -mt-0.5 mr-1.5" '
        f'src="https://www.google.com/s2/favicons?domain={_esc(host)}&amp;sz=32" '
        'width="16" height="16" alt="" loading="lazy">'
    )


def _tab(label: str, count: int, filter_key: str, value: str, selected: bool, dot: str = "") -> str:
    sel = "true" if selected else "false"
    return (
        f'<button type="button" class="tab shrink-0 inline-flex items-center gap-1.5 rounded-full '
        f'border border-stone-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 '
        f'px-3.5 py-1.5 text-sm focus-visible:outline focus-visible:outline-2 '
        f'focus-visible:outline-blue-500" aria-selected="{sel}" '
        f'data-filter="{filter_key}" data-value="{_esc(value)}">'
        f"{dot}{_esc(label)}"
        f'<span class="badge text-[11px] tabular-nums rounded-full bg-stone-200 '
        f'dark:bg-neutral-700 px-1.5 py-0.5">{count}</span></button>'
    )


def _page(
    *, title: str, active: str, generated_at: str, feed: str,
    updated_label: str, head_extra: str, tabs_html: str, after_header: str,
    main_html: str, footer_notes: list[str], site_stamp: str,
) -> str:
    nav = "".join(
        f'<a href="{href}" class="px-2 py-1 rounded-lg text-sm '
        + (
            "font-bold text-blue-600 dark:text-blue-400"
            if active == key
            else "text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100"
        )
        + f'">{label}</a>'
        for key, label, href in (
            ("news", "뉴스", "index.html"),
            ("community", "커뮤니티", "community.html"),
        )
    )
    notes = "".join(f'<p class="mb-2 max-w-[72ch]">{_esc(n)}</p>' for n in footer_notes)
    sentry = ""
    if config.SENTRY_LOADER_KEY:
        sentry = (
            f'<script src="https://js.sentry-cdn.com/{config.SENTRY_LOADER_KEY}.min.js" '
            'crossorigin="anonymous"></script>'
        )
    return f"""<!doctype html>
<html lang="ko" data-generated-at="{_esc(generated_at)}" data-feed="{feed}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<meta name="description" content="여러 언론사의 헤드라인을 교차 확인해 매시간 정리하는 중립 뉴스 브리핑">
{head_extra}
<link rel="icon" href="{FAVICON_SVG}">
<script src="https://cdn.tailwindcss.com"></script>
<script>tailwind.config = {{ darkMode: "media" }}</script>
<style type="text/tailwindcss">{CUSTOM_STYLE}</style>
<!-- AdSense 승인 후 사이트 확인/광고 스크립트를 여기에 붙여넣으세요 -->
</head>
<body class="bg-stone-50 dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100 antialiased" style='font-family:"Pretendard Variable",Pretendard,-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR","Malgun Gothic",sans-serif'>
<header class="sticky top-0 z-20 border-b border-stone-200 dark:border-neutral-700 bg-stone-50/90 dark:bg-neutral-900/90 backdrop-blur">
  <div class="max-w-6xl mx-auto px-5">
    <div class="flex items-center gap-2.5 py-3 flex-wrap">
      {LOGO_MARK}
      <span class="text-xl font-extrabold tracking-tight">{_esc(config.SITE_TITLE)}</span>
      <span class="hidden md:inline text-xs text-neutral-500 dark:text-neutral-400">{_esc(config.SITE_TAGLINE)}</span>
      <nav class="flex gap-1 ml-2" aria-label="페이지">{nav}</nav>
      <span class="ml-auto text-xs text-neutral-500 dark:text-neutral-400 tabular-nums">{_esc(updated_label)}</span>
      <button type="button" id="bug-report" class="rounded-full border border-stone-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-1 text-xs text-neutral-500 dark:text-neutral-400 hover:text-blue-600 hover:border-blue-500 dark:hover:text-blue-400">버그 제보</button>
    </div>
    <nav class="flex gap-2 overflow-x-auto no-scrollbar pb-3" aria-label="필터">{tabs_html}</nav>
  </div>
</header>
{after_header}
<main class="max-w-6xl mx-auto px-5">{main_html}</main>
<footer class="border-t border-stone-200 dark:border-neutral-700 mt-4 py-5 pb-12 text-xs text-neutral-500 dark:text-neutral-400">
  <div class="max-w-6xl mx-auto px-5">
    {notes}
    <p>{site_stamp}</p>
  </div>
</footer>
<script>{BASE_SCRIPT}</script>
{sentry}
</body>
</html>"""


# ── 뉴스 페이지 ─────────────────────────────────────────────────────────


def _render_ticker(breaking: list[dict]) -> str:
    if not breaking:
        return ""
    items = "".join(
        f'<a class="ticker-item absolute inset-0 flex items-center gap-2 opacity-0 truncate text-sm" '
        f'href="{_esc(b["link"])}" target="_blank" rel="noopener nofollow">'
        f'<time class="text-red-600 dark:text-red-400 text-xs font-semibold tabular-nums shrink-0">{_esc(b["time"])}</time>'
        f'<span class="truncate">{_esc(b["title"])}</span>'
        f'<span class="text-xs text-neutral-400 shrink-0">{_esc(b["outlet"])}</span></a>'
        for b in breaking
    )
    return f"""<div class="border-b border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800">
  <div class="max-w-6xl mx-auto px-5 py-2 flex items-center gap-3">
    <span class="text-red-600 dark:text-red-400 font-bold text-xs tracking-[0.12em] shrink-0">속보</span>
    <div class="relative flex-1 h-6 overflow-hidden">{items}</div>
  </div>
</div>"""


def _render_issue(issue: dict) -> str:
    heads = issue.get("headlines", [])
    color = CATEGORY_COLORS.get(issue["category"], "#2563eb")
    outlet_count = issue.get("outlet_count", len({h["outlet"] for h in heads}))
    rows = "".join(
        f'<li><a class="block text-[13px] hover:text-blue-600 dark:hover:text-blue-400" '
        f'href="{_esc(h["link"])}" target="_blank" rel="noopener nofollow">'
        f'{_favicon(h["link"])}<b class="font-semibold text-neutral-400 text-xs mr-1.5">{_esc(h["outlet"])}</b>'
        f'{_esc(h["title"])}</a></li>'
        for h in heads
    )
    return f"""<article class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5 border-t-[3px]" style="border-top-color:{color}" data-cat="{_esc(issue["category"])}">
  <div class="flex items-center justify-between text-xs">
    <span class="font-semibold rounded-full px-2.5 py-0.5" style="color:{color};background:{color}1f">{_esc(issue["category"])}</span>
    <span class="text-neutral-400">{outlet_count}개 매체</span>
  </div>
  <h3 class="mt-2.5 mb-1.5 font-bold text-[15px] leading-snug [text-wrap:balance]">{_esc(issue["label"])}</h3>
  <p class="text-sm text-neutral-600 dark:text-neutral-300 mb-3.5">{_esc(issue["summary"])}</p>
  <details class="border-t border-stone-200 dark:border-neutral-700 pt-3">
    <summary class="list-none [&::-webkit-details-marker]:hidden cursor-pointer select-none inline-flex items-center gap-1.5 rounded-lg border border-stone-200 dark:border-neutral-600 px-3 py-1.5 text-xs font-medium text-blue-600 dark:text-blue-400 hover:bg-stone-100 dark:hover:bg-neutral-700">
      매체별 헤드라인 {len(heads)}건 <span class="tri">▾</span>
    </summary>
    <ul class="mt-2.5 flex flex-col gap-1.5">{rows}</ul>
  </details>
</article>"""


def _render_sidebar(policy: list[dict]) -> str:
    items = "".join(
        f"""<div class="border-t border-stone-200 dark:border-neutral-700 py-3 first:border-0 first:pt-0 last:pb-0">
  <h3 class="text-[13px] font-semibold mb-1"><a class="hover:text-blue-600 dark:hover:text-blue-400" href="{_esc(p["link"])}" target="_blank" rel="noopener">{_esc(p["title"])}</a></h3>
  <p class="text-xs text-neutral-500 dark:text-neutral-400">{_esc(p["summary"])}</p>
</div>"""
        for p in policy
    )
    return f"""<aside class="flex flex-col gap-5">
  <section class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5">
    <h2 class="text-sm font-bold mb-0.5">정책 브리핑</h2>
    <p class="text-[11px] text-neutral-400 mb-3">출처: 대한민국 정책브리핑(korea.kr) · 공공누리 제1유형</p>
    {items}
  </section>
  {AD_SLOT}
  <section class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5">
    <h2 class="text-sm font-bold mb-0.5">공개 API</h2>
    <p class="text-[11px] text-neutral-400 mb-2.5">이 페이지의 모든 데이터는 JSON으로도 제공됩니다 (매시간 갱신).</p>
    <code class="block rounded-lg bg-stone-100 dark:bg-neutral-900 px-2.5 py-2 text-[11px] overflow-x-auto">GET /briefing.json<br>GET /community.json</code>
  </section>
</aside>"""


def build(briefing: dict, community: list[dict], out_dir: Path) -> Path:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    generated_at = briefing.get("generated_at", now.isoformat())
    out_dir.mkdir(parents=True, exist_ok=True)

    punycode_domain = config.SITE_DOMAIN.encode("idna").decode()
    og_url = ""
    if build_og(briefing, out_dir / "og.png", now):
        og_url = f"http://{punycode_domain}/og.png"
    og_meta = f"""<meta property="og:type" content="website">
<meta property="og:title" content="{_esc(config.SITE_TITLE)} — {_esc(config.SITE_TAGLINE)}">
<meta property="og:description" content="여러 언론사의 헤드라인을 교차 확인해 매시간 정리하는 중립 뉴스 브리핑">
{f'<meta property="og:image" content="{_esc(og_url)}">' if og_url else ""}
<meta name="twitter:card" content="summary_large_image">"""

    issues = briefing.get("issues", [])
    heat = briefing.get("heat", {})
    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue["category"]] = counts.get(issue["category"], 0) + 1
    hottest = max(heat, key=heat.get) if heat else None

    tabs = [_tab("전체", len(issues), "cat", "전체", True)]
    for cat in config.ISSUE_CATEGORIES:
        if cat not in counts:
            continue
        color = CATEGORY_COLORS.get(cat, "#2563eb")
        dot = f'<span class="inline-block w-2 h-2 rounded-full" style="background:{color}"></span>'
        label = f"{cat} 🔥" if cat == hottest else cat
        tabs.append(_tab(label, counts[cat], "cat", cat, False, dot))

    cards = []
    for i, issue in enumerate(issues):
        cards.append(_render_issue(issue))
        if i == 5:
            cards.append(f'<div class="sm:col-span-2">{AD_SLOT}</div>')

    main_html = f"""<div class="grid grid-cols-1 lg:grid-cols-[7fr_3fr] gap-7 py-6">
  <section class="grid sm:grid-cols-2 gap-4 content-start" aria-label="주요 이슈">{"".join(cards)}</section>
  {_render_sidebar(briefing.get("policy", []))}
</div>"""

    page = _page(
        title=f"{config.SITE_TITLE} — {config.SITE_TAGLINE}",
        active="news",
        generated_at=generated_at,
        feed="briefing.json",
        updated_label=f"{now.strftime('%m월 %d일 %H:%M')} 업데이트 · 매시간 갱신",
        head_extra=og_meta,
        tabs_html="".join(tabs),
        after_header=_render_ticker(briefing.get("breaking", [])),
        main_html=main_html,
        footer_notes=[DISCLAIMER, KOGL_NOTICE],
        site_stamp=f"ⓒ {_esc(config.SITE_TITLE)} ({_esc(config.SITE_DOMAIN)}) · 생성 시각 {now.strftime('%Y-%m-%d %H:%M KST')}",
    )
    (out_dir / "index.html").write_text(page, encoding="utf-8")

    build_community_page(community, out_dir, generated_at, now)
    return out_dir / "index.html"


# ── 커뮤니티 페이지 ─────────────────────────────────────────────────────


def build_community_page(
    posts: list[dict], out_dir: Path, generated_at: str, now: datetime
) -> Path:
    counts: dict[str, int] = {}
    for post in posts:
        counts[post["source"]] = counts.get(post["source"], 0) + 1

    tabs = [_tab("전체", len(posts), "src", "전체", True)] + [
        _tab(src, n, "src", src, False) for src, n in counts.items()
    ]

    rows = "".join(
        f"""<li data-src="{_esc(p["source"])}">
  <a class="flex items-center gap-3 px-4 py-3 hover:bg-stone-50 dark:hover:bg-neutral-700/40" href="{_esc(p["link"])}" target="_blank" rel="noopener nofollow">
    <span class="w-6 text-right text-sm font-bold text-neutral-300 dark:text-neutral-600 tabular-nums shrink-0">{i + 1}</span>
    <span class="flex-1 text-sm truncate">{_esc(p["title"])}</span>
    <span class="text-[11px] rounded-full px-2 py-0.5 bg-stone-100 dark:bg-neutral-700 text-neutral-500 dark:text-neutral-400 shrink-0">{_esc(p["source"])}</span>
  </a>
</li>"""
        for i, p in enumerate(posts)
    )

    main_html = f"""<div class="max-w-3xl mx-auto py-6 flex flex-col gap-5">
  <ol class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 divide-y divide-stone-200 dark:divide-neutral-700 overflow-hidden">{rows}</ol>
  {AD_SLOT}
</div>"""

    page = _page(
        title=f"커뮤니티 인기글 — {config.SITE_TITLE}",
        active="community",
        generated_at=generated_at,
        feed="community.json",
        updated_label=f"{now.strftime('%m월 %d일 %H:%M')} 업데이트 · 매시간 갱신",
        head_extra="",
        tabs_html="".join(tabs),
        after_header="",
        main_html=main_html,
        footer_notes=[COMMUNITY_NOTICE],
        site_stamp=f"ⓒ {_esc(config.SITE_TITLE)} ({_esc(config.SITE_DOMAIN)}) · 생성 시각 {now.strftime('%Y-%m-%d %H:%M KST')}",
    )
    out_path = out_dir / "community.html"
    out_path.write_text(page, encoding="utf-8")
    return out_path
