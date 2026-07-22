import re
from pathlib import Path

content = Path("build_site.py").read_text(encoding="utf-8")

# Task 1: build_archive_pages skip
content = content.replace(
    '''    for stamp, briefing in snapshots:
        cards = "".join(
            _render_issue(issue, i) for i, issue in enumerate(briefing.get("issues", []))
        )''',
    '''    for stamp, briefing in snapshots:
        if (out_dir / "archive" / stamp / "index.html").exists():
            print(f"아카이브 {stamp} 이미 존재 — 건너뜀")
            continue
        cards = "".join(
            _render_issue(issue, i) for i, issue in enumerate(briefing.get("issues", []))
        )'''
)

# Task 2 & 3: SEO sitemap lastmod and RSS guid
# Also Task 6 category RSS
seo_old = '''def build_seo_files(
    briefing: dict, out_dir: Path, domain: str, now: datetime,
    archive_stamps: list[str] | None = None,
) -> None:
    from email.utils import format_datetime

    base = f"https://{domain}"
    if now.tzinfo is None:
        from datetime import timezone as _tz
        now = now.replace(tzinfo=_tz.utc)
    lastmod = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    pages = [
        ("", "1.0", "hourly"),
        ("blindspot.html", "0.8", "hourly"),
        ("frame.html", "0.8", "hourly"),
        ("community.html", "0.8", "hourly"),
        ("search.html", "0.6", "daily"),
        ("about.html", "0.5", "monthly"),
        ("terms.html", "0.2", "yearly"),
        ("privacy.html", "0.2", "yearly"),
        ("archive/", "0.5", "hourly"),
    ] + [(f"archive/{s}/", "0.6", "monthly") for s in (archive_stamps or [])]
    # scrapbook.html은 개인화 페이지(noindex)이므로 사이트맵에서 제외
    urls = "".join(
        f"<url><loc>{base}/{path}</loc><lastmod>{lastmod}</lastmod>"
        f"<changefreq>{freq}</changefreq><priority>{prio}</priority></url>"
        for path, prio, freq in pages
    )
    (out_dir / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>",
        encoding="utf-8",
    )

    # RSS: 이슈를 중요도 순(briefing["issues"] 순서 = 점수 순)으로 제공
    items = []
    for i, issue in enumerate(briefing.get("issues", [])):
        try:
            pub = format_datetime(datetime.fromisoformat(issue["latest_ts"]))
        except (KeyError, ValueError):
            pub = format_datetime(now)
        permalink = f"{_SHARE_BASE}#issue-{i}" if _SHARE_BASE else f"{base}/#issue-{i}"
        items.append(
            "<item>"
            f"<title>{html.escape(issue['label'])}</title>"
            f"<link>{html.escape(permalink)}</link>"
            f"<description>{html.escape(issue['summary'])}</description>"
            f"<category>{html.escape(issue['category'])}</category>"
            f"<pubDate>{pub}</pubDate>"
            f'<guid isPermaLink="false">goreun-issue-{html.escape(issue["label"])}</guid>'
            "</item>"
        )
    (out_dir / "rss.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\\n'
        '<rss version="2.0"><channel>'
        f"<title>{html.escape(config.SITE_TITLE)}</title>"
        f"<link>{base}/</link>"
        f"<description>{html.escape(config.SITE_TAGLINE)} — 여러 언론사의 헤드라인을 교차 확인한 중립 뉴스 브리핑</description>"
        "<language>ko</language>"
        f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>"
        f"{''.join(items)}</channel></rss>",
        encoding="utf-8",
    )'''

seo_new = '''def build_seo_files(
    briefing: dict, out_dir: Path, domain: str, now: datetime,
    archive_stamps: list[str] | None = None,
) -> None:
    from email.utils import format_datetime
    import hashlib

    base = f"https://{domain}"
    if now.tzinfo is None:
        from datetime import timezone as _tz
        now = now.replace(tzinfo=_tz.utc)
    lastmod = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    static_lastmod = "2026-07-01T00:00:00Z"

    pages = [
        ("", "1.0", "hourly", lastmod),
        ("blindspot.html", "0.8", "hourly", lastmod),
        ("frame.html", "0.8", "hourly", lastmod),
        ("community.html", "0.8", "hourly", lastmod),
        ("search.html", "0.6", "daily", static_lastmod),
        ("about.html", "0.5", "monthly", static_lastmod),
        ("terms.html", "0.2", "yearly", static_lastmod),
        ("privacy.html", "0.2", "yearly", static_lastmod),
        ("scrapbook.html", "0.2", "monthly", static_lastmod),
        ("archive/", "0.5", "hourly", lastmod),
    ] + [(f"archive/{s}/", "0.6", "monthly", f"{s[:10]}T{s[11:13]}:00:00Z" if len(s)==13 else f"{s}T00:00:00Z" if len(s)==10 else lastmod) for s in (archive_stamps or [])]
    
    # Task 6: category RSS feeds
    items_by_cat = {}
    items = []
    for i, issue in enumerate(briefing.get("issues", [])):
        cat = issue.get("category", "기타")
        try:
            pub = format_datetime(datetime.fromisoformat(issue["latest_ts"]))
        except (KeyError, ValueError):
            pub = format_datetime(now)
        permalink = f"{_SHARE_BASE}#issue-{i}" if _SHARE_BASE else f"{base}/#issue-{i}"
        links = [h.get("url", "") for h in issue.get("headlines", [])]
        hash_guid = hashlib.md5(("|".join(sorted(links))).encode()).hexdigest()
        
        item_xml = (
            "<item>"
            f"<title>{html.escape(issue['label'])}</title>"
            f"<link>{html.escape(permalink)}</link>"
            f"<description>{html.escape(issue['summary'])}</description>"
            f"<category>{html.escape(issue['category'])}</category>"
            f"<pubDate>{pub}</pubDate>"
            f'<guid isPermaLink="false">{hash_guid}</guid>'
            "</item>"
        )
        items.append(item_xml)
        items_by_cat.setdefault(cat, []).append(item_xml)
        
    for cat in items_by_cat:
        pages.append((f"rss-{cat}.xml", "0.5", "hourly", lastmod))

    urls = "".join(
        f"<url><loc>{base}/{path}</loc><lastmod>{lmod}</lastmod>"
        f"<changefreq>{freq}</changefreq><priority>{prio}</priority></url>"
        for path, prio, freq, lmod in pages if path != "scrapbook.html"
    )
    (out_dir / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>",
        encoding="utf-8",
    )

    (out_dir / "rss.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\\n'
        '<rss version="2.0"><channel>'
        f"<title>{html.escape(config.SITE_TITLE)}</title>"
        f"<link>{base}/</link>"
        f"<description>{html.escape(config.SITE_TAGLINE)} — 여러 언론사의 헤드라인을 교차 확인한 중립 뉴스 브리핑</description>"
        "<language>ko</language>"
        f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>"
        f"{''.join(items)}</channel></rss>",
        encoding="utf-8",
    )

    for cat, c_items in items_by_cat.items():
        (out_dir / f"rss-{cat}.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\\n'
            '<rss version="2.0"><channel>'
            f"<title>{html.escape(config.SITE_TITLE)} - {html.escape(cat)}</title>"
            f"<link>{base}/</link>"
            f"<description>{html.escape(config.SITE_TAGLINE)} — {html.escape(cat)} 분야 뉴스 브리핑</description>"
            "<language>ko</language>"
            f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>"
            f"{''.join(c_items)}</channel></rss>",
            encoding="utf-8",
        )'''
content = content.replace(seo_old, seo_new)

# Task 4 & 6: ARIA roles, rss links in head
content = content.replace(
    'f\'<nav class="flex gap-2 overflow-x-auto no-scrollbar pb-3" aria-label="필터">{tabs_html}</nav>\'',
    'f\'<nav role="tablist" class="flex gap-2 overflow-x-auto no-scrollbar pb-3" aria-label="필터">{tabs_html}</nav>\''
)

content = content.replace(
    'f\'<button type="button" class="tab shrink-0 inline-flex items-center gap-1.5 rounded-full \'',
    'f\'<button type="button" role="tab" tabindex="0" class="tab shrink-0 inline-flex items-center gap-1.5 rounded-full \''
)

content = content.replace(
    '<link rel="alternate" type="application/rss+xml" title="{_esc(config.SITE_TITLE)} RSS" href="https://{config.SITE_DOMAIN}/rss.xml">',
    '''<link rel="alternate" type="application/rss+xml" title="{_esc(config.SITE_TITLE)} RSS" href="https://{config.SITE_DOMAIN}/rss.xml">
''' + "".join([f'<link rel="alternate" type="application/rss+xml" title="{{_esc(config.SITE_TITLE)}} {c} RSS" href="https://{{config.SITE_DOMAIN}}/rss-{c}.xml">\\n' for c in ["정치", "경제", "사회", "국제", "IT·과학", "생활·문화"]])
)

# Task 5, 4, 9: NewsArticle JSON-LD, ARIA in summary-wrap, TTS
issue_old = '''  <div class="summary-wrap relative cursor-pointer mb-3.5" title="클릭하면 전체 요약을 봅니다">
    <p class="fs-p text-sm text-neutral-600 dark:text-neutral-300 break-keep">{_esc(issue["summary"])}</p>
    <span class="fade"></span>
  </div>'''
issue_new = '''  <div class="summary-wrap relative cursor-pointer mb-3.5" role="button" tabindex="0" aria-expanded="false" title="클릭하면 전체 요약을 봅니다">
    <p class="fs-p text-sm text-neutral-600 dark:text-neutral-300 break-keep">{_esc(issue["summary"])}</p>
    <span class="fade"></span>
  </div>'''
content = content.replace(issue_old, issue_new)

issue_share_old = '''      <span class="text-neutral-400">{outlet_count}개 매체</span>
      <button type="button" class="scrap-btn text-base leading-none text-neutral-300 dark:text-neutral-600 hover:text-amber-500" aria-label="스크랩" data-scrap="{scrap_payload}">☆</button>
    </span>'''
issue_share_new = '''      <span class="text-neutral-400">{outlet_count}개 매체</span>
      <button type="button" class="tts-btn text-base leading-none text-neutral-300 dark:text-neutral-600 hover:text-blue-500" aria-label="요약 듣기" title="요약 듣기">🔊</button>
      <button type="button" class="scrap-btn text-base leading-none text-neutral-300 dark:text-neutral-600 hover:text-amber-500" aria-label="스크랩" data-scrap="{scrap_payload}">☆</button>
    </span>'''
content = content.replace(issue_share_old, issue_share_new)

issue_end_old = '''      <ul class="relative ml-1.5 mt-3 pl-4 border-l-2 border-stone-200 dark:border-neutral-700 flex flex-col gap-3">{rows}</ul>
    </div>
  </div>
</article>"""'''
issue_end_new = '''      <ul class="relative ml-1.5 mt-3 pl-4 border-l-2 border-stone-200 dark:border-neutral-700 flex flex-col gap-3">{rows}</ul>
    </div>
  </div>
{ld_script}
</article>"""'''

# We need to compute ld_script at the beginning of _render_issue
render_issue_def = 'def _render_issue(issue: dict, index: int) -> str:'
render_issue_new = '''def _render_issue(issue: dict, index: int) -> str:
    ld_json = json.dumps({
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": issue.get("label", ""),
        "description": issue.get("summary", ""),
        "articleSection": issue.get("category", ""),
        "datePublished": issue.get("latest_ts", ""),
        "publisher": { "@type": "Organization", "name": "고른뉴스" }
    }, ensure_ascii=False)
    ld_script = f"""<script type="application/ld+json">{ld_json}</script>"""'''
content = content.replace(render_issue_def, render_issue_new)
content = content.replace(issue_end_old, issue_end_new)

# Task 7 & 9: URL State Sync & TTS logic in BASE_SCRIPT
base_script_tab = '''    tabs.forEach(function (t) { t.setAttribute("aria-selected", "false"); });
    tab.setAttribute("aria-selected", "true");
    var key = tab.dataset.filter;
    var val = tab.dataset.value;'''
base_script_tab_new = '''    tabs.forEach(function (t) { t.setAttribute("aria-selected", "false"); });
    tab.setAttribute("aria-selected", "true");
    var key = tab.dataset.filter;
    var val = tab.dataset.value;
    if (key === "cat") {
      history.replaceState(null, "", val === "전체" ? (window.location.pathname + window.location.search) : "#cat=" + encodeURIComponent(val));
    }'''
content = content.replace(base_script_tab, base_script_tab_new)

base_script_onload = '''// ── 초기 렌더링 후 이벤트 바인딩 ──
renderKws();
applyKws();'''
base_script_onload_new = '''// ── 초기 렌더링 후 이벤트 바인딩 ──
renderKws();
applyKws();

if (window.location.hash.startsWith("#cat=")) {
  var _c = decodeURIComponent(window.location.hash.substring(5));
  var _t = document.querySelector(".tab[data-value='" + _c + "']");
  if (_t) { setTimeout(function() { _t.click(); }, 0); }
}

document.addEventListener("click", function(e) {
  var b = e.target.closest(".tts-btn");
  if (b) {
    if (window.speechSynthesis.speaking) {
      window.speechSynthesis.cancel();
      if (b.dataset.playing === "1") {
        b.dataset.playing = "0"; b.textContent = "🔊";
        return;
      }
    }
    document.querySelectorAll(".tts-btn").forEach(function(btn) { btn.dataset.playing = "0"; btn.textContent = "🔊"; });
    var p = b.closest("article").querySelector(".summary-wrap p");
    if (!p) return;
    var ut = new SpeechSynthesisUtterance(p.textContent);
    ut.lang = "ko-KR";
    ut.onend = function() { b.dataset.playing = "0"; b.textContent = "🔊"; };
    b.dataset.playing = "1"; b.textContent = "⏸️";
    window.speechSynthesis.speak(ut);
  }
});
'''
content = content.replace(base_script_onload, base_script_onload_new)

# Task 8: Scrapbook Export/Import
scrapbook_ui_old = '''<div class="max-w-3xl mx-auto py-6 flex flex-col gap-6">
  <h1 class="text-xl font-extrabold tracking-tight">스크랩북</h1>
  <div id="scrap-login-gate" hidden class="text-center py-16">'''
scrapbook_ui_new = '''<div class="max-w-3xl mx-auto py-6 flex flex-col gap-6">
  <div class="flex items-center justify-between mb-2">
    <h1 class="text-xl font-extrabold tracking-tight">스크랩북</h1>
    <div class="flex gap-2">
      <button type="button" id="scrap-export" class="text-xs px-2.5 py-1 rounded border border-stone-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 hover:bg-stone-50 dark:hover:bg-neutral-700">내보내기</button>
      <label class="text-xs px-2.5 py-1 rounded border border-stone-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 hover:bg-stone-50 dark:hover:bg-neutral-700 cursor-pointer">가져오기<input type="file" id="scrap-import" accept=".json" class="hidden"></label>
    </div>
  </div>
  <div id="scrap-login-gate" hidden class="text-center py-16">'''
content = content.replace(scrapbook_ui_old, scrapbook_ui_new)

scrapbook_script_end = '''  window.addEventListener("storage", function (e) {
    if (e.key === "goreun-scrapbook") renderAll();
  });
})();
"""'''
scrapbook_script_end_new = '''  window.addEventListener("storage", function (e) {
    if (e.key === "goreun-scrapbook") renderAll();
  });
  
  document.getElementById("scrap-export").addEventListener("click", function() {
    var data = localStorage.getItem("goreun-scrapbook") || "{}";
    var blob = new Blob([data], {type: "application/json"});
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url; a.download = "scrapbook.json";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  });
  
  document.getElementById("scrap-import").addEventListener("change", function(e) {
    var f = e.target.files[0];
    if (!f) return;
    var r = new FileReader();
    r.onload = function(ev) {
      try {
        var d = JSON.parse(ev.target.result);
        if (typeof d !== "object") throw new Error();
        var cur = JSON.parse(localStorage.getItem("goreun-scrapbook") || "{}");
        for (var k in d) cur[k] = d[k];
        localStorage.setItem("goreun-scrapbook", JSON.stringify(cur));
        renderAll();
        alert("가져오기 완료!");
      } catch (err) {
        alert("잘못된 파일입니다.");
      }
    };
    r.readAsText(f);
  });
})();
"""'''
content = content.replace(scrapbook_script_end, scrapbook_script_end_new)

# Task 10: Community Image CLS
thumb_16 = '''<img src="{_esc(p["thumb"])}" alt="" loading="lazy" referrerpolicy="no-referrer" '
                'class="w-16 h-16 object-cover rounded-lg shrink-0 bg-stone-100 dark:bg-neutral-700" '
                "onerror=\\"this.style.display='none'\\">"'''
thumb_16_new = '''<img src="{_esc(p["thumb"])}" alt="" loading="lazy" referrerpolicy="no-referrer" '
                'width="64" height="64" '
                'class="w-16 h-16 object-cover rounded-lg shrink-0 bg-stone-100 dark:bg-neutral-700" '
                "onerror=\\"this.style.display='none'\\">"'''
content = content.replace(thumb_16, thumb_16_new)

thumb_12 = '''<img src="{_esc(p["thumb"])}" alt="" loading="lazy" referrerpolicy="no-referrer" '
                'class="w-12 h-12 object-cover rounded-lg shrink-0 bg-stone-100 dark:bg-neutral-700" '
                "onerror=\\"this.style.display='none'\\">"'''
thumb_12_new = '''<img src="{_esc(p["thumb"])}" alt="" loading="lazy" referrerpolicy="no-referrer" '
                'width="48" height="48" '
                'class="w-12 h-12 object-cover rounded-lg shrink-0 bg-stone-100 dark:bg-neutral-700" '
                "onerror=\\"this.style.display='none'\\">"'''
content = content.replace(thumb_12, thumb_12_new)

# Top imports
if "import hashlib" not in content:
    content = content.replace("import html", "import html\\nimport hashlib")

Path("build_site.py").write_text(content, encoding="utf-8")
print("build_site.py edits done.")
