"""브리핑 데이터를 인터랙티브 정적 페이지로 렌더링한다.

- 멀티 컬럼: 데스크톱은 이슈 피드(카드 그리드) + 우측 레일(정책 브리핑·API 안내),
  모바일(≤980px)은 단일 컬럼으로 자연스럽게 재배치된다.
- 인터랙션: 분야 필터 칩, 매체별 헤드라인 펼치기(details), 10분마다
  /briefing.json 폴링으로 새 브리핑 감지 시 자동 새로고침.
- 버그 제보: Sentry Feedback 위젯 (로더 스크립트 + attachTo 커스텀 버튼).
- 공개 API: 같은 데이터가 /briefing.json 으로 그대로 제공된다.
"""

import html
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import config

STYLE = """
:root {
  --bg: #faf9f7; --card: #ffffff; --text: #1c1c1e; --muted: #6e6e73;
  --accent: #2563eb; --border: #e6e2da; --badge-bg: #e8f0fe; --badge-text: #1d4ed8;
  --ad-bg: #f3f1ec; --breaking: #c2352b; --chip-on: #1c1c1e; --chip-on-text: #faf9f7;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #141416; --card: #1e1e21; --text: #ececee; --muted: #98989f;
    --accent: #7aa2ff; --border: #2c2c31; --badge-bg: #1d2a45; --badge-text: #9db9ff;
    --ad-bg: #1a1a1d; --breaking: #ff7a6e; --chip-on: #ececee; --chip-on-text: #141416;
  }
}
:root[data-theme="dark"] {
  --bg: #141416; --card: #1e1e21; --text: #ececee; --muted: #98989f;
  --accent: #7aa2ff; --border: #2c2c31; --badge-bg: #1d2a45; --badge-text: #9db9ff;
  --ad-bg: #1a1a1d; --breaking: #ff7a6e; --chip-on: #ececee; --chip-on-text: #141416;
}
:root[data-theme="light"] {
  --bg: #faf9f7; --card: #ffffff; --text: #1c1c1e; --muted: #6e6e73;
  --accent: #2563eb; --border: #e6e2da; --badge-bg: #e8f0fe; --badge-text: #1d4ed8;
  --ad-bg: #f3f1ec; --breaking: #c2352b; --chip-on: #1c1c1e; --chip-on-text: #faf9f7;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: "Pretendard Variable", Pretendard, -apple-system, BlinkMacSystemFont,
    "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", sans-serif;
  line-height: 1.6; -webkit-font-smoothing: antialiased;
}
a { color: inherit; }
.wrap { max-width: 1120px; margin: 0 auto; padding: 0 20px; }

/* ── 헤더 ── */
header.site {
  position: sticky; top: 0; z-index: 20;
  background: color-mix(in srgb, var(--bg) 88%, transparent);
  backdrop-filter: blur(10px); border-bottom: 1px solid var(--border);
}
.masthead { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; padding: 14px 0 8px; }
.masthead h1 { font-size: 1.35rem; margin: 0; letter-spacing: -0.02em; }
.masthead .tagline { color: var(--muted); font-size: 0.82rem; }
.masthead .updated {
  margin-left: auto; color: var(--muted); font-size: 0.78rem;
  font-variant-numeric: tabular-nums;
}
.btn-bug {
  border: 1px solid var(--border); background: var(--card); color: var(--muted);
  border-radius: 999px; padding: 4px 12px; font-size: 0.76rem; cursor: pointer;
}
.btn-bug:hover, .btn-bug:focus-visible { color: var(--accent); border-color: var(--accent); outline: none; }
.chips { display: flex; gap: 8px; overflow-x: auto; padding: 6px 0 12px; scrollbar-width: none; }
.chips::-webkit-scrollbar { display: none; }
.chip {
  flex: 0 0 auto; border: 1px solid var(--border); background: var(--card);
  color: var(--text); border-radius: 999px; padding: 5px 14px; font-size: 0.82rem;
  cursor: pointer; white-space: nowrap;
}
.chip .n { color: var(--muted); font-size: 0.74rem; margin-left: 3px; font-variant-numeric: tabular-nums; }
.chip.on { background: var(--chip-on); color: var(--chip-on-text); border-color: var(--chip-on); }
.chip.on .n { color: inherit; opacity: 0.7; }
.chip:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }

/* ── 속보 티커 ── */
.ticker { border-bottom: 1px solid var(--border); background: var(--card); }
.ticker-inner { display: flex; align-items: center; gap: 14px; overflow-x: auto; padding: 8px 20px; }
.ticker-tag {
  flex: 0 0 auto; color: var(--breaking); font-weight: 700; font-size: 0.8rem;
  letter-spacing: 0.06em;
}
.ticker a {
  flex: 0 0 auto; text-decoration: none; font-size: 0.84rem; white-space: nowrap;
}
.ticker a time { color: var(--breaking); font-variant-numeric: tabular-nums; margin-right: 6px; font-size: 0.78rem; }
.ticker a .o { color: var(--muted); font-size: 0.76rem; margin-left: 6px; }
.ticker a:hover { color: var(--accent); }

/* ── 본문 레이아웃 ── */
.layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 28px; padding: 24px 0 56px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; align-items: start; }
.issue {
  background: var(--card); border: 1px solid var(--border); border-radius: 12px;
  padding: 16px 18px;
}
.issue .meta { display: flex; align-items: center; gap: 8px; font-size: 0.74rem; color: var(--muted); }
.issue .cat { color: var(--badge-text); background: var(--badge-bg); border-radius: 999px; padding: 1px 9px; font-weight: 600; }
.issue h3 { margin: 8px 0 6px; font-size: 1rem; letter-spacing: -0.01em; text-wrap: balance; }
.issue p { margin: 0 0 10px; font-size: 0.89rem; }
.issue details { border-top: 1px solid var(--border); padding-top: 8px; }
.issue summary {
  cursor: pointer; color: var(--muted); font-size: 0.79rem; list-style: none;
  display: flex; align-items: center; gap: 6px;
}
.issue summary::before { content: "▸"; transition: transform 0.15s; }
@media (prefers-reduced-motion: reduce) { .issue summary::before { transition: none; } }
.issue details[open] summary::before { transform: rotate(90deg); }
.issue summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.issue ul { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.issue ul a { text-decoration: none; font-size: 0.82rem; display: block; }
.issue ul a b { font-weight: 600; color: var(--muted); font-size: 0.76rem; margin-right: 6px; }
.issue ul a:hover { color: var(--accent); }

/* ── 우측 레일 ── */
.rail { display: flex; flex-direction: column; gap: 18px; }
.panel { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; }
.panel h2 { margin: 0 0 4px; font-size: 0.95rem; }
.panel .src { color: var(--muted); font-size: 0.72rem; margin: 0 0 12px; }
.policy-item { border-top: 1px solid var(--border); padding: 10px 0; }
.policy-item:last-child { padding-bottom: 0; }
.policy-item h3 { margin: 0 0 4px; font-size: 0.87rem; }
.policy-item h3 a { text-decoration: none; }
.policy-item h3 a:hover { color: var(--accent); }
.policy-item p { margin: 0; font-size: 0.8rem; color: var(--muted); }
.api-box code {
  display: block; background: var(--ad-bg); border-radius: 8px; padding: 8px 10px;
  font-size: 0.76rem; overflow-x: auto; margin-top: 8px;
}
.ad-slot {
  padding: 26px 16px; text-align: center; border: 1px dashed var(--border);
  border-radius: 12px; background: var(--ad-bg); color: var(--muted); font-size: 0.78rem;
}
.feed .ad-slot { grid-column: 1 / -1; }

/* ── 푸터 ── */
footer.site { border-top: 1px solid var(--border); padding: 20px 0 48px; color: var(--muted); font-size: 0.76rem; }
footer.site p { margin: 0 0 8px; max-width: 72ch; }

/* ── 모바일 ── */
@media (max-width: 980px) {
  .layout { grid-template-columns: 1fr; gap: 20px; padding-top: 16px; }
  .masthead .tagline { display: none; }
}
"""

SCRIPT = """
(function () {
  // 분야 필터
  var chips = document.querySelectorAll(".chip[data-cat]");
  chips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      chips.forEach(function (c) { c.classList.remove("on"); });
      chip.classList.add("on");
      var cat = chip.dataset.cat;
      document.querySelectorAll(".issue[data-cat]").forEach(function (card) {
        card.hidden = cat !== "전체" && card.dataset.cat !== cat;
      });
    });
  });

  // 새 브리핑 감지 → 자동 새로고침 (10분 주기)
  var current = document.documentElement.dataset.generatedAt;
  setInterval(function () {
    fetch("briefing.json", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.generated_at && d.generated_at !== current) location.reload();
      })
      .catch(function () {});
  }, 10 * 60 * 1000);
})();

// Sentry 버그 제보 위젯 (로더가 SDK를 지연 로드한 뒤 호출됨)
window.sentryOnLoad = function () {
  Sentry.init({
    integrations: [
      Sentry.feedbackIntegration({
        autoInject: false,
        colorScheme: "system",
        showBranding: false,
        formTitle: "버그 제보",
        nameLabel: "이름",
        namePlaceholder: "이름 (선택)",
        emailLabel: "이메일",
        emailPlaceholder: "이메일 (선택)",
        messageLabel: "내용",
        messagePlaceholder: "발견한 문제나 개선 아이디어를 알려주세요",
        submitButtonLabel: "보내기",
        cancelButtonLabel: "취소",
        successMessageText: "제보해 주셔서 감사합니다.",
      }),
    ],
  });
  var feedback = Sentry.getFeedback && Sentry.getFeedback();
  var btn = document.getElementById("bug-report");
  if (feedback && btn) feedback.attachTo(btn, {});
};
"""

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


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def _render_breaking(breaking: list[dict]) -> str:
    if not breaking:
        return ""
    links = "".join(
        f'<a href="{_esc(b["link"])}" target="_blank" rel="noopener nofollow">'
        f'<time>{_esc(b["time"])}</time>{_esc(b["title"])}'
        f'<span class="o">{_esc(b["outlet"])}</span></a>'
        for b in breaking
    )
    return (
        '<div class="ticker"><div class="wrap ticker-inner">'
        '<span class="ticker-tag">속보</span>' + links + "</div></div>"
    )


def _render_chips(briefing: dict) -> str:
    issues = briefing.get("issues", [])
    heat = briefing.get("heat", {})
    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue["category"]] = counts.get(issue["category"], 0) + 1
    hottest = max(heat, key=heat.get) if heat else None

    chips = [
        f'<button class="chip on" data-cat="전체">전체<span class="n">{len(issues)}</span></button>'
    ]
    for cat in config.ISSUE_CATEGORIES:
        if cat not in counts:
            continue
        fire = " 🔥" if cat == hottest else ""
        chips.append(
            f'<button class="chip" data-cat="{_esc(cat)}">{_esc(cat)}{fire}'
            f'<span class="n">{counts[cat]}</span></button>'
        )
    return '<nav class="chips" aria-label="분야 필터">' + "".join(chips) + "</nav>"


def _render_issue(issue: dict) -> str:
    heads = issue.get("headlines", [])
    outlet_count = issue.get("outlet_count", len({h["outlet"] for h in heads}))
    badge = (
        f'<span class="cat">{_esc(issue["category"])}</span>'
        f"<span>{outlet_count}개 매체</span>"
    )
    items = "".join(
        f'<li><a href="{_esc(h["link"])}" target="_blank" rel="noopener nofollow">'
        f'<b>{_esc(h["outlet"])}</b>{_esc(h["title"])}</a></li>'
        for h in heads
    )
    return f"""<article class="issue" data-cat="{_esc(issue["category"])}">
  <div class="meta">{badge}</div>
  <h3>{_esc(issue["label"])}</h3>
  <p>{_esc(issue["summary"])}</p>
  <details>
    <summary>매체별 헤드라인 {len(heads)}건</summary>
    <ul>{items}</ul>
  </details>
</article>"""


def _render_policy(policy: list[dict]) -> str:
    items = "".join(
        f"""<div class="policy-item">
  <h3><a href="{_esc(p["link"])}" target="_blank" rel="noopener">{_esc(p["title"])}</a></h3>
  <p>{_esc(p["summary"])}</p>
</div>"""
        for p in policy
    )
    return f"""<section class="panel">
  <h2>정책 브리핑</h2>
  <p class="src">출처: 대한민국 정책브리핑(korea.kr) · 공공누리 제1유형</p>
  {items}
</section>"""


AD_SLOT = '<div class="ad-slot">광고 영역 — AdSense/카카오 AdFit 승인 후 코드 삽입</div>'


def build(briefing: dict, out_dir: Path) -> Path:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    generated_at = briefing.get("generated_at", now.isoformat())

    issue_cards = []
    for i, issue in enumerate(briefing.get("issues", [])):
        issue_cards.append(_render_issue(issue))
        if i == 5:
            issue_cards.append(AD_SLOT)

    sentry_loader = ""
    if config.SENTRY_LOADER_KEY:
        sentry_loader = (
            f'<script src="https://js.sentry-cdn.com/{config.SENTRY_LOADER_KEY}.min.js" '
            'crossorigin="anonymous"></script>'
        )

    page = f"""<!doctype html>
<html lang="ko" data-generated-at="{_esc(generated_at)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(config.SITE_TITLE)} — {_esc(config.SITE_TAGLINE)}</title>
<meta name="description" content="여러 언론사의 헤드라인을 교차 확인해 매시간 정리하는 중립 뉴스 브리핑">
<style>{STYLE}</style>
<!-- AdSense 승인 후 사이트 확인/광고 스크립트를 여기에 붙여넣으세요 -->
</head>
<body>
<header class="site">
  <div class="wrap">
    <div class="masthead">
      <h1>{_esc(config.SITE_TITLE)}</h1>
      <span class="tagline">{_esc(config.SITE_TAGLINE)}</span>
      <span class="updated">{now.strftime('%m월 %d일 %H:%M')} 업데이트 · 매시간 갱신</span>
      <button type="button" class="btn-bug" id="bug-report">버그 제보</button>
    </div>
    {_render_chips(briefing)}
  </div>
</header>
{_render_breaking(briefing.get("breaking", []))}
<main class="wrap">
  <div class="layout">
    <section class="feed cards" aria-label="주요 이슈">
      {"".join(issue_cards)}
    </section>
    <aside class="rail">
      {_render_policy(briefing.get("policy", []))}
      {AD_SLOT}
      <section class="panel api-box">
        <h2>공개 API</h2>
        <p class="src">이 페이지의 모든 데이터는 JSON으로도 제공됩니다 (매시간 갱신).</p>
        <code>GET /briefing.json</code>
      </section>
    </aside>
  </div>
</main>
<footer class="site">
  <div class="wrap">
    <p>{_esc(DISCLAIMER)}</p>
    <p>{_esc(KOGL_NOTICE)}</p>
    <p>ⓒ {_esc(config.SITE_TITLE)} ({_esc(config.SITE_DOMAIN)}) · 생성 시각 {now.strftime('%Y-%m-%d %H:%M KST')}</p>
  </div>
</footer>
<script>{SCRIPT}</script>
{sentry_loader}
</body>
</html>"""

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(page, encoding="utf-8")
    return out_path
