"""브리핑 데이터를 정적 HTML로 렌더링한다."""

import html
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import config

STYLE = """
:root {
  --bg: #faf9f7; --card: #ffffff; --text: #1c1c1e; --muted: #6e6e73;
  --accent: #2563eb; --border: #e6e2da; --badge-bg: #e8f0fe; --badge-text: #1d4ed8;
  --ad-bg: #f3f1ec;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #141416; --card: #1e1e21; --text: #ececee; --muted: #98989f;
    --accent: #7aa2ff; --border: #2c2c31; --badge-bg: #1d2a45; --badge-text: #9db9ff;
    --ad-bg: #1a1a1d;
  }
}
:root[data-theme="dark"] {
  --bg: #141416; --card: #1e1e21; --text: #ececee; --muted: #98989f;
  --accent: #7aa2ff; --border: #2c2c31; --badge-bg: #1d2a45; --badge-text: #9db9ff;
  --ad-bg: #1a1a1d;
}
:root[data-theme="light"] {
  --bg: #faf9f7; --card: #ffffff; --text: #1c1c1e; --muted: #6e6e73;
  --accent: #2563eb; --border: #e6e2da; --badge-bg: #e8f0fe; --badge-text: #1d4ed8;
  --ad-bg: #f3f1ec;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: "Pretendard Variable", Pretendard, -apple-system, BlinkMacSystemFont,
    "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", sans-serif;
  line-height: 1.65; -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 680px; margin: 0 auto; padding: 0 20px 64px; }
header.site { padding: 44px 0 8px; }
.site h1 { font-size: 1.7rem; margin: 0 0 4px; letter-spacing: -0.02em; }
.site .tagline { color: var(--muted); font-size: 0.95rem; margin: 0; }
.site .date { color: var(--accent); font-weight: 600; font-size: 0.9rem; margin: 14px 0 0; }
.notice {
  background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 12px 16px; font-size: 0.85rem; color: var(--muted); margin: 20px 0 0;
}
section.category { margin-top: 40px; }
section.category > h2 {
  font-size: 1.15rem; margin: 0 0 14px; padding-bottom: 8px;
  border-bottom: 2px solid var(--accent); display: inline-block; letter-spacing: -0.01em;
}
.issue {
  background: var(--card); border: 1px solid var(--border); border-radius: 12px;
  padding: 18px 20px; margin-bottom: 14px;
}
.issue h3 { margin: 0 0 8px; font-size: 1.02rem; letter-spacing: -0.01em; }
.issue p.summary { margin: 0 0 12px; font-size: 0.94rem; }
.badge {
  display: inline-block; font-size: 0.72rem; font-weight: 600;
  background: var(--badge-bg); color: var(--badge-text);
  border-radius: 999px; padding: 2px 10px; margin-left: 8px; vertical-align: 2px;
}
.sources { display: flex; flex-wrap: wrap; gap: 6px; }
.sources a {
  font-size: 0.78rem; color: var(--muted); text-decoration: none;
  border: 1px solid var(--border); border-radius: 999px; padding: 3px 11px;
  max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.sources a:hover { color: var(--accent); border-color: var(--accent); }
.sources a b { font-weight: 600; color: var(--text); }
.ad-slot {
  margin: 32px 0 0; padding: 28px 16px; text-align: center;
  border: 1px dashed var(--border); border-radius: 12px;
  background: var(--ad-bg); color: var(--muted); font-size: 0.8rem;
}
footer.site {
  margin-top: 56px; padding-top: 20px; border-top: 1px solid var(--border);
  color: var(--muted); font-size: 0.78rem;
}
footer.site p { margin: 0 0 8px; }
"""

# 광고 코드 발급 후 이 자리에 AdSense/AdFit 스크립트를 붙여넣으세요.
AD_SLOT = '<div class="ad-slot">광고 영역 — AdSense/카카오 AdFit 승인 후 코드 삽입</div>'

DISCLAIMER = (
    "본 사이트는 기사 본문을 저장·복제하지 않습니다. 네이버 뉴스 검색 API가 제공하는 "
    "제목·요약 정보를 바탕으로 AI가 작성한 브리핑과 원문 링크만을 제공하며, "
    "모든 기사의 저작권은 각 언론사에 있습니다. 자세한 내용은 원문 기사를 확인해 주세요."
)


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def render_body(briefing: dict, generated_at: datetime) -> str:
    """<style> + 본문 마크업. (문서 래퍼 없이 재사용 가능하도록 분리)"""
    parts = [f"<style>{STYLE}</style>", '<div class="wrap">']
    parts.append(
        f"""<header class="site">
  <h1>{_esc(config.SITE_TITLE)}</h1>
  <p class="tagline">{_esc(config.SITE_TAGLINE)}</p>
  <p class="date">{generated_at.strftime('%Y년 %m월 %d일')} 아침 브리핑</p>
  <div class="notice">AI가 여러 언론사의 보도를 교차 확인해 사실 중심으로 정리한 요약입니다.
  2개 이상 매체가 함께 보도한 이슈에는 <span class="badge">교차 확인</span> 표시가 붙습니다.</div>
</header>"""
    )
    parts.append(AD_SLOT)

    categories = briefing.get("categories", [])
    for idx, cat in enumerate(categories):
        parts.append(f'<section class="category"><h2>{_esc(cat["name"])}</h2>')
        for issue in cat.get("issues", []):
            badge = '<span class="badge">교차 확인</span>' if issue.get("cross_verified") else ""
            chips = "".join(
                f'<a href="{_esc(s["link"])}" target="_blank" rel="noopener nofollow">'
                f'<b>{_esc(s["outlet"])}</b> · {_esc(s["title"])}</a>'
                for s in issue.get("sources", [])
            )
            parts.append(
                f"""<article class="issue">
  <h3>{_esc(issue["title"])}{badge}</h3>
  <p class="summary">{_esc(issue["summary"])}</p>
  <div class="sources">{chips}</div>
</article>"""
            )
        parts.append("</section>")
        # 카테고리 중간에 광고 1회
        if idx == len(categories) // 2 - 1:
            parts.append(AD_SLOT)

    parts.append(
        f"""<footer class="site">
  <p>{_esc(DISCLAIMER)}</p>
  <p>매일 아침 7시(KST) 자동 업데이트 · 생성 시각 {generated_at.strftime('%Y-%m-%d %H:%M KST')}</p>
</footer></div>"""
    )
    return "\n".join(parts)


def build(briefing: dict, out_dir: Path) -> Path:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    body = render_body(briefing, now)
    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(config.SITE_TITLE)} — {now.strftime('%Y.%m.%d')}</title>
<meta name="description" content="{html.escape(config.SITE_TAGLINE)}">
<!-- AdSense 승인 후 사이트 소유 확인/광고 스크립트를 여기에 붙여넣으세요 -->
</head>
<body>
{body}
</body>
</html>"""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(page, encoding="utf-8")
    return out_path
