"""브리핑 데이터를 Tailwind 기반 인터랙티브 정적 페이지로 렌더링한다.

- index.html: 뉴스 대시보드 — 좌 70% 이슈 카드 그리드 / 우 30% 사이드바
  (정책 브리핑·광고·뉴스레터·공개 API), 모바일 1단. 카테고리 탭(+뱃지) 필터,
  속보 티커(페이드 전환), 성향 스펙트럼 바, 스크랩·공유 버튼.
- community.html: 커뮤니티 인기글 전용 페이지 (소스 탭, 🔥 HOT 하이라이트).
- scrapbook.html: localStorage 기반 스크랩북 (클라이언트 렌더링).
- 공통: 글자 크기 조절(가/가+), 모바일 스크롤 헤더 숨김 + Top FAB,
  서비스워커 오프라인 페일세이프 + 경고 배너, 10분 주기 갱신 감지,
  Sentry 버그 제보. 공개 API: /briefing.json, /community.json
"""

from __future__ import annotations

import html
import json
import urllib.parse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import config
from og_image import CATEGORY_COLORS, build_icon, build_og

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


def ad_slot(unit_id: str) -> str:
    """광고 슬롯 모듈 — CLS 방지를 위해 min-h 고정 + 로드 전 스켈레톤 배경.

    ADSENSE_CLIENT_ID 설정 시 구글 애드센스 코드를 자동 게재합니다.
    """
    if config.ADSENSE_CLIENT_ID:
        return f"""<div class="ad-unit relative overflow-hidden rounded-xl border border-stone-200 dark:border-neutral-700 min-h-[250px] flex items-center justify-center bg-stone-50 dark:bg-neutral-900" data-ad-unit="{unit_id}">
  <ins class="adsbygoogle"
       style="display:block;width:100%;height:100%"
       data-ad-client="{_esc(config.ADSENSE_CLIENT_ID)}"
       data-ad-format="auto"
       data-full-width-responsive="true"></ins>
  <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
</div>"""
    return f"""<div class="ad-unit relative overflow-hidden rounded-xl border border-stone-200 dark:border-neutral-700 min-h-[250px] flex items-center justify-center" data-ad-unit="{unit_id}">
  <div class="absolute inset-0 animate-pulse bg-gradient-to-br from-stone-100 to-stone-200 dark:from-neutral-800 dark:to-neutral-700" aria-hidden="true"></div>
  <span class="relative text-neutral-400 text-xs">광고 영역 ({unit_id}) — ADSENSE_CLIENT_ID 설정 시 자동 게재</span>
</div>"""

DISCLAIMER = (
    "고른뉴스는 언론사 기사 본문을 수집·저장·복제하지 않습니다. 이슈 카드는 각 언론사가 "
    "공개한 헤드라인(제목)과 원문 링크만을 표시하며, 요약문은 헤드라인에 담긴 정보만을 "
    "근거로 AI가 새로 작성한 문장입니다. 매체 성향 분류는 참고용 일반 분류입니다. "
    "모든 기사의 저작권은 각 언론사에 있으며, 자세한 내용은 반드시 원문 기사를 확인해 주세요."
)

KOGL_NOTICE = (
    "'정책 브리핑' 섹션은 대한민국 정책브리핑(korea.kr)의 정책뉴스 자료를 활용하였으며, "
    "해당 자료는 공공누리 제1유형에 따라 이용할 수 있습니다."
)

COMMUNITY_NOTICE = (
    "커뮤니티 인기글은 각 커뮤니티가 공개한 게시글 제목과 원문 링크만을 표시합니다. "
    "게시글의 저작권은 각 작성자와 해당 커뮤니티에 있습니다."
)

BIAS_LABELS = [("progressive", "진보"), ("moderate", "중도"), ("conservative", "보수")]
BIAS_BAR_CLASSES = {
    "progressive": "bg-blue-500",
    "moderate": "bg-neutral-400",
    "conservative": "bg-red-500",
}

# 공유·RSS 영구 링크의 기준 URL (아카이브 스냅샷). run.py가 설정.
_SHARE_BASE: str | None = None


def set_share_base(url: str | None) -> None:
    global _SHARE_BASE
    _SHARE_BASE = url

BASE_SCRIPT = """
// ── 다크/라이트/시스템 테마 전환 ──
var themeBtn = document.getElementById("theme-toggle");
var themeIcon = document.getElementById("theme-icon");
function getTheme() { return localStorage.getItem("goreun_theme") || "system"; }
function setTheme(t) {
  localStorage.setItem("goreun_theme", t);
  applyTheme();
}
function applyTheme() {
  var t = getTheme();
  var isDark = t === "dark" || (t === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", isDark);
  if (themeIcon) {
    if (t === "dark") themeIcon.textContent = "🌙 다크";
    else if (t === "light") themeIcon.textContent = "☀️ 라이트";
    else themeIcon.textContent = "💻 시스템";
  }
}
if (themeBtn) {
  themeBtn.addEventListener("click", function() {
    var cur = getTheme();
    var next = cur === "system" ? "dark" : (cur === "dark" ? "light" : "system");
    setTheme(next);
    toast(next === "dark" ? "다크 모드" : (next === "light" ? "라이트 모드" : "시스템 설정 모드"));
  });
}
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function() {
  if (getTheme() === "system") applyTheme();
});
applyTheme();

// ── 탭 필터 (뉴스: data-cat / 커뮤니티: data-src) ──
var tabs = document.querySelectorAll(".tab");
tabs.forEach(function (tab) {
  tab.addEventListener("click", function () {
    tabs.forEach(function (t) { t.setAttribute("aria-selected", "false"); });
    tab.setAttribute("aria-selected", "true");
    var key = tab.dataset.filter;
    var val = tab.dataset.value;
    document.querySelectorAll("[data-" + key + "]").forEach(function (el) {
      if (val === "전체") {
        // 전체 탭: 3개 이하 매체 보도(minor)는 분야 탭 전용
        el.hidden = key === "cat" && el.dataset.minor === "1";
      } else {
        el.hidden = el.dataset[key] !== val;
      }
    });
  });
});

// ── 속보 티커: 단일 요소 내용 교체(페이드) — 항목 겹침 원천 차단 ──
var tickerLink = document.getElementById("ticker-link");
var tickerDataEl = document.getElementById("ticker-data");
if (tickerLink && tickerDataEl) {
  var tickerData = [];
  try { tickerData = JSON.parse(tickerDataEl.textContent); } catch (e) {}
  var tickerReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var tickerIdx = 0;
  function applyTicker(it) {
    if (!it) return;
    tickerLink.querySelector("time").textContent = it.time;
    tickerLink.querySelector(".t-title").textContent = it.title;
    tickerLink.querySelector(".t-outlet").textContent = it.outlet;
    tickerLink.href = it.link;
    tickerLink.target = "_blank";
    tickerLink.rel = "noopener nofollow";
  }
  if (!tickerReduced && tickerData.length > 1) {
    tickerLink.style.transition = "opacity 0.3s";
    setInterval(function () {
      tickerLink.style.opacity = "0";
      setTimeout(function () {
        tickerIdx = (tickerIdx + 1) % tickerData.length;
        applyTicker(tickerData[tickerIdx]);
        tickerLink.style.opacity = "1";
      }, 300);
    }, 5000);
  }
}

// ── 오프라인 페일세이프: 서비스워커 캐시 + 경고 배너 ──
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(function () {});
}
function showOfflineBanner() {
  var banner = document.getElementById("offline-banner");
  if (banner) banner.hidden = false;
}
function hideOfflineBanner() {
  var banner = document.getElementById("offline-banner");
  if (banner) banner.hidden = true;
}
window.addEventListener("offline", showOfflineBanner);
window.addEventListener("online", hideOfflineBanner);
if (!navigator.onLine) showOfflineBanner();

// ── 새 데이터 감지 → 자동 새로고침 (10분 주기, 실패 시 배너) ──
var pageFeed = document.documentElement.dataset.feed;
var pageGeneratedAt = document.documentElement.dataset.generatedAt;
if (pageFeed) {
  setInterval(function () {
    fetch(pageFeed, { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        hideOfflineBanner();
        if (d.generated_at && d.generated_at !== pageGeneratedAt) location.reload();
      })
      .catch(showOfflineBanner);
  }, 10 * 60 * 1000);
}

// ── 무한 스크롤 (Intersection Observer, 12개씩 지연 공개) ──
var lazyCards = Array.prototype.slice.call(document.querySelectorAll(".not-revealed"));
var feedSentinel = document.getElementById("feed-sentinel");
function revealBatch(n) {
  for (var i = 0; i < n && lazyCards.length; i++) {
    lazyCards.shift().classList.remove("not-revealed");
  }
  if (!lazyCards.length && feedSentinel) {
    feedSentinel.remove();
    feedSentinel = null;
  }
}
if (feedSentinel && lazyCards.length && "IntersectionObserver" in window) {
  var feedObserver = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) revealBatch(12);
    });
  }, { rootMargin: "600px 0px" });
  feedObserver.observe(feedSentinel);
} else {
  revealBatch(Infinity);
}
// 현재 보기(전체/분야)의 첫 카드를 히어로로 승격
function updateHero() {
  var hero = null;
  document.querySelectorAll("article[data-cat]").forEach(function (card) {
    card.classList.remove("is-hero");
    if (!hero && !card.hidden && !card.classList.contains("not-revealed")) hero = card;
  });
  if (hero) hero.classList.add("is-hero");
}
updateHero();

// 분야 필터 사용 시 전부 공개 후 해당 분야 1위를 히어로로
tabs.forEach(function (tab) {
  tab.addEventListener("click", function () {
    revealBatch(Infinity);
    updateHero();
  });
});

// ── 헤드라인 펼침: 토글은 버튼 행에, 본문은 카드 전체 폭으로 ──
// 펼칠 때 조회 집계(abacus)도 1회 기록 → '많이 본 이슈' 랭킹의 재료
function djb2(s) {
  var h = 5381;
  for (var i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return h.toString(36);
}
var ABACUS = "https://abacus.jasoncameron.dev/";
document.querySelectorAll("details.headlines-toggle").forEach(function (d) {
  d.addEventListener("toggle", function () {
    var foot = d.closest(".card-foot");
    var body = foot && foot.querySelector(".headlines-body");
    if (body) body.hidden = !d.open;
    if (d.open && !d._viewed) {
      d._viewed = true;
      var card = d.closest("article");
      var label = card && card.querySelector("h3");
      if (label) fetch(ABACUS + "hit/goreun-news/iv-" + djb2(label.textContent)).catch(function () {});
    }
  });
});

// ── 많이 본 이슈 TOP 5 (상위 18개 카드의 조회수 조회) ──
var tvPanel = document.getElementById("top-viewed-panel");
if (tvPanel) {
  var tvCards = Array.prototype.slice.call(document.querySelectorAll("article[data-cat]")).slice(0, 12);
  Promise.all(tvCards.map(function (card) {
    var label = (card.querySelector("h3") || {}).textContent || "";
    return fetch(ABACUS + "get/goreun-news/iv-" + djb2(label))
      .then(function (r) { return r.json(); })
      .then(function (d) { return { card: card, label: label, n: d.value || 0 }; })
      .catch(function () { return { card: card, label: label, n: 0 }; });
  })).then(function (res) {
    var top = res.filter(function (x) { return x.n > 0; })
      .sort(function (a, b) { return b.n - a.n; }).slice(0, 5);
    if (!top.length) return;
    tvPanel.hidden = false;
    var ol = document.getElementById("top-viewed");
    top.forEach(function (x, i) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.className = "flex items-start gap-2 py-1.5 text-[13px] border-t border-stone-100 dark:border-neutral-700/60 first:border-0 hover:text-blue-600 dark:hover:text-blue-400";
      a.href = "#" + x.card.id;
      var rank = document.createElement("span");
      rank.className = "font-bold text-neutral-300 dark:text-neutral-600 tabular-nums shrink-0";
      rank.textContent = String(i + 1);
      var t = document.createElement("span");
      t.className = "flex-1 min-w-0 line-clamp-2";
      t.textContent = x.label;
      a.appendChild(rank); a.appendChild(t);
      li.appendChild(a);
      ol.appendChild(li);
    });
  });
}

// ── 성향순/시간순 정렬 토글 (좌/우 프레이밍 비교) ──
var BIAS_ORDER = { progressive: 0, moderate: 1, unknown: 2, conservative: 3 };
document.querySelectorAll(".sort-toggle").forEach(function (btn) {
  btn.addEventListener("click", function () {
    var ul = btn.closest(".headlines-body").querySelector("ul");
    var lis = Array.prototype.slice.call(ul.children);
    var toBias = btn.dataset.mode !== "bias";
    lis.sort(function (a, b) {
      if (toBias) return (BIAS_ORDER[a.dataset.b] || 0) - (BIAS_ORDER[b.dataset.b] || 0);
      return a.dataset.t < b.dataset.t ? -1 : 1;
    });
    lis.forEach(function (li) { ul.appendChild(li); });
    btn.dataset.mode = toBias ? "bias" : "time";
    btn.textContent = toBias ? "시간순 보기" : "성향순 보기";
  });
});

// ── 키워드 팔로우: 등록 키워드 포함 이슈 상단 고정 + 강조 ──
var KW_KEY = "goreun_keywords";
function loadKws() {
  try { return JSON.parse(localStorage.getItem(KW_KEY)) || []; } catch (e) { return []; }
}
function saveKws(list) { localStorage.setItem(KW_KEY, JSON.stringify(list)); }
function renderKws() {
  var box = document.getElementById("kw-list");
  if (!box) return;
  box.textContent = "";
  loadKws().forEach(function (kw) {
    var chip = document.createElement("button");
    chip.type = "button";
    chip.className = "inline-flex items-center gap-1 rounded-full bg-amber-100 dark:bg-amber-500/20 text-amber-800 dark:text-amber-300 text-xs px-2.5 py-1";
    chip.textContent = "🔔 " + kw + " ✕";
    chip.title = "키워드 삭제";
    chip.addEventListener("click", function () {
      saveKws(loadKws().filter(function (k) { return k !== kw; }));
      document.querySelectorAll(".kw-hit").forEach(function (c) { c.classList.remove("kw-hit"); });
      renderKws();
      applyKws();
    });
    box.appendChild(chip);
  });
}
function applyKws() {
  var kws = loadKws();
  if (!kws.length) { updateHero(); return; }
  var feed = document.querySelector('section[aria-label="주요 이슈"]');
  if (!feed) return;
  var matched = [];
  feed.querySelectorAll("article[data-cat]").forEach(function (card) {
    var txt = ((card.querySelector("h3") || {}).textContent || "") + " " +
      ((card.querySelector(".summary-wrap p") || {}).textContent || "");
    if (kws.some(function (k) { return txt.indexOf(k) >= 0; })) matched.push(card);
  });
  matched.reverse().forEach(function (card) {
    card.classList.add("kw-hit");
    card.classList.remove("not-revealed");
    feed.insertBefore(card, feed.firstChild);
  });
  updateHero();
}
var kwForm = document.getElementById("kw-form");
if (kwForm) {
  kwForm.addEventListener("submit", function (e) {
    e.preventDefault();
    var input = document.getElementById("kw-input");
    var kw = input.value.trim();
    if (!kw) return;
    var list = loadKws();
    if (list.indexOf(kw) < 0 && list.length < 10) { list.push(kw); saveKws(list); }
    input.value = "";
    renderKws();
    applyKws();
    toast("'" + kw + "' 키워드를 팔로우합니다");
  });
  renderKws();
  applyKws();
}

// ── AI 요약 3줄 클램프: 클릭 시 부드럽게 펼침 ──
document.querySelectorAll(".summary-wrap").forEach(function (wrap) {
  var p = wrap.querySelector("p");
  if (p.scrollHeight <= p.clientHeight + 2) {
    wrap.classList.add("no-clamp");
    return;
  }
  wrap.addEventListener("click", function () {
    if (wrap.classList.contains("open")) {
      wrap.classList.remove("open");
      return;
    }
    var start = p.clientHeight;
    wrap.classList.add("open");
    var end = p.scrollHeight;
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      p.style.maxHeight = start + "px";
      p.style.overflow = "hidden";
      requestAnimationFrame(function () {
        p.style.transition = "max-height 0.3s ease";
        p.style.maxHeight = end + "px";
        setTimeout(function () {
          p.style.maxHeight = "";
          p.style.transition = "";
          p.style.overflow = "";
        }, 320);
      });
    }
  });
});

// ── 갱신 시각 상대 표시 ("방금 전/N분 전 갱신됨") ──
var updatedLabel = document.getElementById("updated-label");
if (updatedLabel && pageGeneratedAt) {
  var renderUpdated = function () {
    var diff = (Date.now() - new Date(pageGeneratedAt).getTime()) / 1000;
    if (isNaN(diff) || diff < 0) return;
    var text;
    if (diff < 60) text = "방금 전 갱신됨";
    else if (diff < 3600) text = Math.floor(diff / 60) + "분 전 갱신됨";
    else if (diff < 86400) text = Math.floor(diff / 3600) + "시간 전 갱신됨";
    else text = Math.floor(diff / 86400) + "일 전 갱신됨";
    updatedLabel.textContent = text;
  };
  renderUpdated();
  setInterval(renderUpdated, 30 * 1000);
}

// ── 토스트 ──
var toastEl;
function toast(msg) {
  if (!toastEl) {
    toastEl = document.createElement("div");
    toastEl.className = "fixed bottom-6 left-1/2 -translate-x-1/2 z-50 rounded-full " +
      "bg-neutral-900 text-stone-50 dark:bg-neutral-100 dark:text-neutral-900 " +
      "text-sm px-4 py-2 shadow-lg opacity-0 transition-opacity pointer-events-none";
    document.body.appendChild(toastEl);
  }
  toastEl.textContent = msg;
  toastEl.style.opacity = "1";
  clearTimeout(toastEl._t);
  toastEl._t = setTimeout(function () { toastEl.style.opacity = "0"; }, 1800);
}

// ── 스크랩 (localStorage) ──
var SCRAP_KEY = "goreun_scraps";
function loadScraps() {
  try { return JSON.parse(localStorage.getItem(SCRAP_KEY)) || []; }
  catch (e) { return []; }
}
function saveScraps(list) { localStorage.setItem(SCRAP_KEY, JSON.stringify(list)); }
function isScrapped(id) {
  return loadScraps().some(function (s) { return s.id === id; });
}
function toggleScrap(item) {
  var list = loadScraps();
  var i = list.findIndex(function (s) { return s.id === item.id; });
  if (i >= 0) { list.splice(i, 1); }
  else { item.saved_at = new Date().toISOString(); list.push(item); }
  saveScraps(list);
  return i < 0;
}
function paintStar(btn, on) {
  btn.textContent = on ? "★" : "☆";
  btn.classList.toggle("text-amber-500", on);
  btn.setAttribute("aria-pressed", on ? "true" : "false");
}
// ── 로그인/회원가입 (아이디·닉네임·비밀번호 — 기기 저장, 비밀번호는 해시) ──
var AUTH_KEY = "goreun_user";
var ACCOUNTS_KEY = "goreun_accounts";
function authUser() {
  try { return JSON.parse(localStorage.getItem(AUTH_KEY)); } catch (e) { return null; }
}
function loadAccounts() {
  try { return JSON.parse(localStorage.getItem(ACCOUNTS_KEY)) || {}; } catch (e) { return {}; }
}
function sha256(text) {
  return crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)).then(function (buf) {
    return Array.from(new Uint8Array(buf)).map(function (b) { return b.toString(16).padStart(2, "0"); }).join("");
  });
}
var loginCallback = null;
var authMode = "login";
function setAuthMode(mode) {
  authMode = mode;
  var isSignup = mode === "signup";
  document.getElementById("login-nick").hidden = !isSignup;
  document.getElementById("login-nick").required = isSignup;
  document.getElementById("login-submit").textContent = isSignup ? "가입하고 시작" : "로그인";
  document.getElementById("auth-tab-login").setAttribute("aria-selected", String(!isSignup));
  document.getElementById("auth-tab-signup").setAttribute("aria-selected", String(isSignup));
  var err = document.getElementById("login-error");
  if (err) err.hidden = true;
}
function openLogin(cb) {
  loginCallback = cb || null;
  var m = document.getElementById("login-modal");
  if (!m) return;
  // 계정이 하나도 없으면 회원가입 탭을 기본으로
  setAuthMode(Object.keys(loadAccounts()).length ? "login" : "signup");
  m.hidden = false;
  var i = document.getElementById("login-id");
  if (i) i.focus();
}
function closeLogin() {
  var m = document.getElementById("login-modal");
  if (m) m.hidden = true;
}
function renderAuth() {
  var area = document.getElementById("auth-area");
  if (!area) return;
  area.textContent = "";
  var user = authUser();
  if (user) {
    var name = document.createElement("span");
    name.className = "text-xs text-neutral-500 dark:text-neutral-400 px-1";
    name.textContent = (user.name || user.id) + " 님";
    var out = document.createElement("button");
    out.type = "button";
    out.className = "rounded-full border border-stone-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-1 text-xs text-neutral-500 dark:text-neutral-400 hover:text-blue-600 hover:border-blue-500";
    out.textContent = "로그아웃";
    out.addEventListener("click", function () {
      localStorage.removeItem(AUTH_KEY);
      renderAuth();
      if (typeof renderScrapGate === "function") renderScrapGate();
      toast("로그아웃했습니다");
    });
    area.appendChild(name); area.appendChild(out);
  } else {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "rounded-full border border-stone-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-1 text-xs text-neutral-500 dark:text-neutral-400 hover:text-blue-600 hover:border-blue-500";
    btn.textContent = "로그인";
    btn.addEventListener("click", function () { openLogin(); });
    area.appendChild(btn);
  }
}
var loginForm = document.getElementById("login-form");
if (loginForm) {
  document.getElementById("auth-tab-login").addEventListener("click", function () { setAuthMode("login"); });
  document.getElementById("auth-tab-signup").addEventListener("click", function () { setAuthMode("signup"); });
  loginForm.addEventListener("submit", function (e) {
    e.preventDefault();
    var id = document.getElementById("login-id").value.trim();
    var pw = document.getElementById("login-pw").value;
    var err = document.getElementById("login-error");
    function fail(msg) { err.textContent = msg; err.hidden = false; }
    if (!id || !pw) return;
    sha256("goreun_salt_v1:" + id + ":" + pw).then(function (hash) {
      var accounts = loadAccounts();
      if (authMode === "signup") {
        if (accounts[id]) { fail("이미 존재하는 아이디입니다. 로그인 탭을 이용하세요."); return; }
        var nick = document.getElementById("login-nick").value.trim() || id;
        accounts[id] = { nick: nick, hash: hash };
        localStorage.setItem(ACCOUNTS_KEY, JSON.stringify(accounts));
        localStorage.setItem(AUTH_KEY, JSON.stringify({ id: id, name: nick }));
      } else {
        var account = accounts[id];
        if (!account || account.hash !== hash) { fail("아이디 또는 비밀번호가 일치하지 않습니다."); return; }
        localStorage.setItem(AUTH_KEY, JSON.stringify({ id: id, name: account.nick }));
      }
      closeLogin();
      renderAuth();
      if (typeof renderScrapGate === "function") renderScrapGate();
      toast((authUser().name) + " 님, 환영합니다");
      if (loginCallback) { var cb = loginCallback; loginCallback = null; cb(); }
    });
  });
  document.getElementById("login-close").addEventListener("click", closeLogin);
}
renderAuth();

// ── 첫 방문 온보딩 가이드 (다단계 기능 소개) ──
var obModal = document.getElementById("onboard-modal");
if (obModal && !localStorage.getItem("goreun_onboarded")) {
  var OB_STEPS = [
    { e: "⚖️", t: "고른뉴스에 오신 것을 환영합니다", d: "__FEED_COUNT__개 언론사의 헤드라인을 교차 확인해, 감정적 표현을 걷어낸 중립 브리핑을 매시간 자동으로 만듭니다." },
    { e: "🎨", t: "성향 스펙트럼", d: "각 이슈를 어떤 성향의 매체들이 보도했는지 진보-중도-보수 분포 바로 보여줍니다. 카드를 펼치면 매체별 원문 제목을 시간순 타임라인으로 비교할 수 있어요." },
    { e: "🕳️", t: "블라인드스팟", d: "한쪽 성향 매체만 보도한 이슈를 따로 모아 보여줍니다. 내 피드에서 놓치기 쉬운 관점을 확인하세요." },
    { e: "🔍", t: "프레임 체크", d: "같은 사건을 두고 매체들이 제목에서 어떤 단어를 골랐는지 AI가 해부합니다. 분포가 아니라 언어에서 프레임을 직접 목격하세요." },
    { e: "⭐", t: "나만의 뉴스룸", d: "회원가입하면 스크랩북을 쓸 수 있고, 키워드 알림으로 관심 이슈를 상단에 고정할 수 있습니다. 모든 정보는 내 기기에만 저장됩니다." },
  ];
  var obIdx = 0;
  var dots = document.getElementById("ob-dots");
  OB_STEPS.forEach(function (_, i) {
    var d = document.createElement("span");
    d.className = "w-2 h-2 rounded-full bg-stone-300 dark:bg-neutral-600";
    dots.appendChild(d);
  });
  function obRender() {
    var s = OB_STEPS[obIdx];
    document.getElementById("ob-emoji").textContent = s.e;
    document.getElementById("ob-title").textContent = s.t;
    document.getElementById("ob-desc").textContent = s.d;
    document.getElementById("ob-prev").hidden = obIdx === 0;
    document.getElementById("ob-next").textContent = obIdx === OB_STEPS.length - 1 ? "시작하기" : "다음";
    Array.prototype.forEach.call(dots.children, function (d, i) {
      d.className = "w-2 h-2 rounded-full " + (i === obIdx ? "bg-blue-600" : "bg-stone-300 dark:bg-neutral-600");
    });
  }
  function obClose() {
    localStorage.setItem("goreun_onboarded", "1");
    obModal.hidden = true;
  }
  document.getElementById("ob-next").addEventListener("click", function () {
    if (obIdx === OB_STEPS.length - 1) { obClose(); return; }
    obIdx++; obRender();
  });
  document.getElementById("ob-prev").addEventListener("click", function () {
    if (obIdx > 0) { obIdx--; obRender(); }
  });
  document.getElementById("ob-skip").addEventListener("click", obClose);
  obRender();
  obModal.hidden = false;
}

// ── 스크랩: 로그인해야 사용 가능 ──
document.querySelectorAll(".scrap-btn").forEach(function (btn) {
  paintStar(btn, isScrapped(JSON.parse(btn.dataset.scrap).id));
  btn.addEventListener("click", function (e) {
    e.preventDefault();
    if (!authUser()) {
      openLogin(function () {
        var on = toggleScrap(JSON.parse(btn.dataset.scrap));
        paintStar(btn, on);
      });
      toast("스크랩은 로그인 후 이용할 수 있습니다");
      return;
    }
    var on = toggleScrap(JSON.parse(btn.dataset.scrap));
    paintStar(btn, on);
    toast(on ? "스크랩북에 저장했습니다 ★" : "스크랩을 해제했습니다");
  });
});

// ── 공유 (모바일: OS 공유 시트 / 데스크톱: 클립보드 복사 + 토스트) ──
document.querySelectorAll(".share-btn").forEach(function (btn) {
  btn.addEventListener("click", function () {
    var url = btn.dataset.url || (location.origin + location.pathname +
      (btn.dataset.anchor ? "#" + btn.dataset.anchor : ""));
    if (navigator.share) {
      navigator.share({ title: btn.dataset.title, text: btn.dataset.text, url: url })
        .catch(function () {});
    } else if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(
        function () { toast("링크가 복사되었습니다"); },
        function () { toast("복사에 실패했습니다"); }
      );
    }
  });
});



// ── 키보드 숏컷 & 모달 접근성 ──
document.addEventListener("keydown", function(e) {
  if (e.key === "Escape") {
    closeLogin();
    var obM = document.getElementById("onboard-modal");
    if (obM && !obM.hidden) {
      localStorage.setItem("goreun_onboarded", "1");
      obM.hidden = true;
    }
  } else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    location.href = "search.html";
  }
});
var loginModal = document.getElementById("login-modal");
if (loginModal) {
  loginModal.addEventListener("click", function(e) {
    if (e.target === loginModal) closeLogin();
  });
}

// ── 정책 브리핑 예상 읽기 시간 (약 500자/분) ──
document.querySelectorAll(".policy-item").forEach(function (item) {
  var text = item.querySelector(".policy-text");
  var meta = item.querySelector(".read-time");
  if (text && meta) {
    meta.textContent = "약 " + Math.max(1, Math.ceil(text.textContent.length / 500)) + "분";
  }
});

// ── 뉴스레터 구독 (구글 폼 AJAX 제출, 사이드바/배너 공용) ──
function wireNewsletterForm(form, doneEl) {
  if (!form) return;
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var action = form.dataset.action;
    var entry = form.dataset.entry;
    var email = form.querySelector("input[type=email]").value;
    if (!action || !entry) { toast("구독 폼이 아직 연결되지 않았습니다"); return; }
    var body = new FormData();
    body.append(entry, email);
    body.append("_subject", "고른뉴스 뉴스레터 구독 신청");
    body.append("_captcha", "false");
    body.append("_template", "table");
    fetch(action, { method: "POST", mode: "no-cors", body: body }).finally(function () {
      form.hidden = true;
      if (doneEl) doneEl.hidden = false;
      localStorage.setItem("goreun_nl_subscribed", "1");
    });
  });
}
wireNewsletterForm(
  document.getElementById("newsletter"),
  document.getElementById("newsletter-done")
);

// ── 행동 기반 슬라이드업 구독 배너 (스크롤 50% 또는 카드 3회 펼침) ──
var nlBanner = document.getElementById("nl-banner");
if (nlBanner) {
  if (
    localStorage.getItem("goreun_nl_dismissed") ||
    localStorage.getItem("goreun_nl_subscribed")
  ) {
    nlBanner.remove();
    nlBanner = null;
  } else {
    wireNewsletterForm(
      document.getElementById("nl-banner-form"),
      document.getElementById("nl-banner-done")
    );
    var bannerShown = false;
    var detailsOpened = 0;
    var showNlBanner = function () {
      if (bannerShown || !nlBanner) return;
      bannerShown = true;
      nlBanner.style.transform = "translateY(0)";
    };
    document.getElementById("nl-banner-close").addEventListener("click", function () {
      nlBanner.style.transform = "";
      localStorage.setItem("goreun_nl_dismissed", "1");
      setTimeout(function () { nlBanner && nlBanner.remove(); nlBanner = null; }, 500);
    });
    document.querySelectorAll("article details").forEach(function (d) {
      d.addEventListener("toggle", function () {
        if (d.open && ++detailsOpened >= 3) showNlBanner();
      });
    });
    window.addEventListener("scroll", function () {
      var max = document.documentElement.scrollHeight - window.innerHeight;
      if (max > 0 && window.scrollY / max >= 0.5) showNlBanner();
    }, { passive: true });
  }
}

// ── '이미지로 저장' (html2canvas 동적 로드, 1:1 인스타 카드) ──
var H2C_URL = "https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js";
function loadHtml2Canvas() {
  if (window.html2canvas) return Promise.resolve();
  return new Promise(function (resolve, reject) {
    var timer = setTimeout(function () { reject(new Error("html2canvas load timeout")); }, 8000);
    var s = document.createElement("script");
    s.src = H2C_URL;
    s.onload = function () { clearTimeout(timer); resolve(); };
    s.onerror = function (e) { clearTimeout(timer); reject(e); };
    document.head.appendChild(s);
  });
}
var BIAS_META = [
  ["progressive", "진보", "#3b82f6"],
  ["moderate", "중도", "#9ca3af"],
  ["conservative", "보수", "#ef4444"],
];
function buildShareCard(card) {
  var label = (card.querySelector("h2, h3") || {}).textContent || "";
  var summaryEl = card.querySelector(".summary-wrap p") || card.querySelector("p");
  var summary = summaryEl ? summaryEl.textContent : "";
  var catColor = card.style.borderTopColor || "#2563eb";
  var catEl = card.querySelector('span[class*="font-semibold"]');
  var cat = catEl ? catEl.textContent : "";
  var bias = {};
  try { bias = JSON.parse(card.dataset.bias || "{}"); } catch (e) {}
  var total = 0;
  BIAS_META.forEach(function (b) { total += bias[b[0]] || 0; });

  var d = document.createElement("div");
  d.setAttribute("style",
    "position:fixed;left:-10990px;top:0;width:1080px;height:1080px;box-sizing:border-box;" +
    "background:#faf9f7;color:#1c1c1e;padding:100px;display:flex;flex-direction:column;" +
    "justify-content:space-between;font-family:'Apple SD Gothic Neo','Noto Sans KR','Malgun Gothic',sans-serif;");

  var top = document.createElement("div");
  var chip = document.createElement("span");
  chip.setAttribute("style", "display:inline-block;font-size:26px;font-weight:700;color:" + catColor +
    ";background:" + catColor + "1f;border-radius:999px;padding:8px 26px;margin-bottom:44px;");
  chip.textContent = cat;
  var h = document.createElement("div");
  h.setAttribute("style", "font-size:58px;font-weight:800;line-height:1.35;letter-spacing:-0.5px;margin-bottom:40px;word-break:keep-all;");
  h.textContent = label;
  var p = document.createElement("div");
  p.setAttribute("style", "font-size:31px;line-height:1.75;color:#4b4b50;word-break:keep-all;");
  p.textContent = summary;
  top.appendChild(chip); top.appendChild(h); top.appendChild(p);

  var bottom = document.createElement("div");
  if (total > 0) {
    var bar = document.createElement("div");
    bar.setAttribute("style", "display:flex;height:14px;border-radius:999px;overflow:hidden;background:#e6e2da;margin-bottom:16px;");
    var legend = document.createElement("div");
    legend.setAttribute("style", "display:flex;justify-content:space-between;font-size:22px;color:#8a8a90;margin-bottom:52px;");
    BIAS_META.forEach(function (b) {
      var n = bias[b[0]] || 0;
      if (n > 0) {
        var seg = document.createElement("span");
        seg.setAttribute("style", "width:" + (n / total * 100) + "%;background:" + b[2] + ";");
        bar.appendChild(seg);
      }
      var lg = document.createElement("span");
      lg.textContent = b[1] + " " + n;
      legend.appendChild(lg);
    });
    bottom.appendChild(bar); bottom.appendChild(legend);
  }
  var brand = document.createElement("div");
  brand.setAttribute("style", "display:flex;align-items:center;gap:20px;border-top:2px solid #e6e2da;padding-top:44px;");
  var mark = document.createElement("div");
  mark.setAttribute("style", "width:64px;height:64px;border-radius:15px;background:#2563eb;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:7px;");
  for (var bi = 0; bi < 3; bi++) {
    var barEl = document.createElement("div");
    barEl.setAttribute("style", "width:36px;height:7px;border-radius:4px;background:rgba(255,255,255," + (1 - bi * 0.12) + ");");
    mark.appendChild(barEl);
  }
  var brandText = document.createElement("div");
  brandText.innerHTML = "";
  var bt1 = document.createElement("div");
  bt1.setAttribute("style", "font-size:30px;font-weight:800;");
  bt1.textContent = "고른뉴스";
  var bt2 = document.createElement("div");
  bt2.setAttribute("style", "font-size:22px;color:#8a8a90;");
  bt2.textContent = "goreunnews.cloud · AI 중립 뉴스 브리핑";
  brandText.appendChild(bt1); brandText.appendChild(bt2);
  brand.appendChild(mark); brand.appendChild(brandText);
  bottom.appendChild(brand);

  d.appendChild(top); d.appendChild(bottom);
  return d;
}
document.querySelectorAll(".imgsave-btn").forEach(function (btn) {
  btn.addEventListener("click", function () {
    var card = btn.closest("article");
    if (!card) return;
    toast("이미지 생성 중…");
    loadHtml2Canvas().then(function () {
      var node = buildShareCard(card);
      document.body.appendChild(node);
      return window.html2canvas(node, { width: 1080, height: 1080, scale: 1, backgroundColor: "#faf9f7" })
        .then(function (canvas) {
          node.remove();
          var a = document.createElement("a");
          a.download = "goreun-news.png";
          a.href = canvas.toDataURL("image/png");
          a.click();
          toast("이미지가 저장되었습니다");
        });
    }).catch(function () { toast("이미지 생성에 실패했습니다"); });
  });
});

// ── 모바일: 스크롤 다운 시 헤더 숨김 / 업 시 표시 + Top FAB ──
var siteHeader = document.getElementById("site-header");
var toTop = document.getElementById("to-top");
var lastY = window.scrollY;
var mobileMq = window.matchMedia("(max-width: 1023px)");
window.addEventListener("scroll", function () {
  var y = window.scrollY;
  if (siteHeader && mobileMq.matches) {
    if (y > lastY && y > 120) siteHeader.style.transform = "translateY(-100%)";
    else siteHeader.style.transform = "";
  } else if (siteHeader) {
    siteHeader.style.transform = "";
  }
  lastY = y;
  if (toTop) toTop.hidden = y < 600;
}, { passive: true });
if (toTop) {
  toTop.addEventListener("click", function () {
    var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: 0, behavior: reduced ? "auto" : "smooth" });
  });
}

// ── 방문자 수 (abacus.jasoncameron.dev — CORS 지원, 세션당 1회 집계) ──
var visitEl = document.getElementById("visit-count");
if (visitEl) {
  var kstDay = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10).replace(/-/g, "");
  var counted = sessionStorage.getItem("goreun_counted") === kstDay;
  var abacus = "https://abacus.jasoncameron.dev/" + (counted ? "get" : "hit") + "/goreun-news/";
  function counterValue(key) {
    return fetch(abacus + key)
      .then(function (r) { return r.json(); })
      .then(function (d) { return d.value || 0; })
      .catch(function () { return 0; });
  }
  Promise.all([counterValue("total"), counterValue("day-" + kstDay)]).then(function (res) {
    if (!counted) sessionStorage.setItem("goreun_counted", kstDay);
    if (res[0] > 0) {
      visitEl.textContent = "오늘 " + res[1].toLocaleString() + " · 누적 " +
        res[0].toLocaleString() + "명 방문";
    }
  });
}

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
        isRequiredLabel: "(필수)",
        addScreenshotButtonLabel: "스크린샷 첨부",
        removeScreenshotButtonLabel: "스크린샷 제거",
        submitButtonLabel: "보내기", cancelButtonLabel: "취소",
        confirmButtonLabel: "확인",
        successMessageText: "제보해 주셔서 감사합니다.",
      }),
    ],
  });
  var feedback = Sentry.getFeedback && Sentry.getFeedback();
  var btn = document.getElementById("bug-report");
  if (feedback && btn) feedback.attachTo(btn, {});
};
"""
BASE_SCRIPT = BASE_SCRIPT.replace("__FEED_COUNT__", str(len(config.PRESS_FEEDS)))

SCRAPBOOK_SCRIPT = """
(function () {
  var listEl = document.getElementById("scrap-news");
  var postsEl = document.getElementById("scrap-posts");
  var OUTLET_BIAS = __OUTLET_BIAS__;
  var BIAS_META = [
    ["progressive", "진보", "#3b82f6"],
    ["moderate", "중도", "#9ca3af"],
    ["conservative", "보수", "#ef4444"],
    ["unknown", "분류 없음", "#d6d3d1"],
  ];

  // 스크랩한 뉴스의 매체 성향 비율 미니 대시보드 (conic-gradient 도넛)
  function renderBiasDash(scraps) {
    var sec = document.getElementById("bias-dash");
    if (!sec) return;
    var counts = { progressive: 0, moderate: 0, conservative: 0, unknown: 0 };
    scraps.filter(function (s) { return s.type === "issue"; }).forEach(function (s) {
      (s.headlines || []).forEach(function (h) {
        counts[OUTLET_BIAS[h.outlet] || "unknown"]++;
      });
    });
    var total = counts.progressive + counts.moderate + counts.conservative + counts.unknown;
    sec.hidden = total === 0;
    if (!total) return;
    var stops = [];
    var acc = 0;
    var legend = document.getElementById("bias-legend");
    legend.textContent = "";
    BIAS_META.forEach(function (b) {
      var n = counts[b[0]];
      var pct = (n / total) * 100;
      if (n > 0) {
        stops.push(b[2] + " " + acc + "% " + (acc + pct) + "%");
        acc += pct;
      }
      var li = document.createElement("li");
      li.className = "flex items-center gap-2";
      var dot = document.createElement("span");
      dot.className = "w-2.5 h-2.5 rounded-full shrink-0";
      dot.style.background = b[2];
      var lab = document.createElement("span");
      lab.className = "flex-1";
      lab.textContent = b[1];
      var val = document.createElement("span");
      val.className = "tabular-nums text-neutral-500 dark:text-neutral-400";
      val.textContent = n + "건 (" + Math.round(pct) + "%)";
      li.appendChild(dot); li.appendChild(lab); li.appendChild(val);
      legend.appendChild(li);
    });
    document.getElementById("bias-donut").style.background =
      "conic-gradient(" + stops.join(",") + ")";
    document.getElementById("bias-total").textContent = total;
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  function renderScrapGate() {
    var gate = document.getElementById("scrap-login-gate");
    var logged = !!authUser();
    if (gate) gate.hidden = logged;
    ["bias-dash", "scrap-empty", "scrap-news-sec", "scrap-posts-sec"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el && !logged) el.hidden = true;
    });
    if (logged) render();
  }
  window.renderScrapGate = renderScrapGate;
  var gateBtn = document.getElementById("scrap-gate-login");
  if (gateBtn) gateBtn.addEventListener("click", function () { openLogin(renderScrapGate); });

  function render() {
    if (!authUser()) return;
    var scraps = loadScraps().sort(function (a, b) {
      return (b.saved_at || "").localeCompare(a.saved_at || "");
    });
    var news = scraps.filter(function (s) { return s.type === "issue"; });
    var posts = scraps.filter(function (s) { return s.type === "post"; });

    document.getElementById("scrap-empty").hidden = scraps.length > 0;
    document.getElementById("scrap-news-sec").hidden = news.length === 0;
    document.getElementById("scrap-posts-sec").hidden = posts.length === 0;
    renderBiasDash(scraps);
    listEl.textContent = "";
    postsEl.textContent = "";

    news.forEach(function (s) {
      var card = el("article", "rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5");
      var top = el("div", "flex items-center justify-between text-xs");
      top.appendChild(el("span", "font-semibold text-neutral-400", s.category || "뉴스"));
      var rm = el("button", "text-amber-500 text-base", "★");
      rm.title = "스크랩 해제";
      rm.addEventListener("click", function () { toggleScrap(s); render(); });
      top.appendChild(rm);
      card.appendChild(top);
      card.appendChild(el("h3", "fs-t mt-2 mb-1.5 font-bold text-[15px] leading-snug", s.label));
      card.appendChild(el("p", "fs-p text-sm text-neutral-600 dark:text-neutral-300 mb-2", s.summary));
      var ul = el("ul", "flex flex-col gap-1 border-t border-stone-200 dark:border-neutral-700 pt-2");
      (s.headlines || []).forEach(function (h) {
        var li = el("li");
        var a = el("a", "block text-[13px] hover:text-blue-600", "");
        a.href = h.link; a.target = "_blank"; a.rel = "noopener nofollow";
        a.appendChild(el("b", "font-semibold text-neutral-400 text-xs mr-1.5", h.outlet));
        a.appendChild(document.createTextNode(h.title));
        li.appendChild(a);
        ul.appendChild(li);
      });
      card.appendChild(ul);
      listEl.appendChild(card);
    });

    posts.forEach(function (s) {
      var li = el("li");
      var row = el("div", "flex items-center gap-3 px-4 py-3");
      var rm = el("button", "text-amber-500 shrink-0", "★");
      rm.title = "스크랩 해제";
      rm.addEventListener("click", function () { toggleScrap(s); render(); });
      row.appendChild(rm);
      var a = el("a", "flex-1 text-sm truncate hover:text-blue-600", s.title);
      a.href = s.link; a.target = "_blank"; a.rel = "noopener nofollow";
      row.appendChild(a);
      row.appendChild(el("span", "text-[11px] rounded-full px-2 py-0.5 bg-stone-100 dark:bg-neutral-700 text-neutral-500 shrink-0", s.source));
      li.appendChild(row);
      postsEl.appendChild(li);
    });
  }

  renderScrapGate();
})();
"""

SERVICE_WORKER = """
var CACHE = "goreun-v1";
self.addEventListener("install", function (e) { self.skipWaiting(); });
self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return clients.claim(); }));
});
self.addEventListener("fetch", function (e) {
  if (e.request.method !== "GET") return;
  var url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  // 네트워크 우선, 실패 시 마지막 성공 캐시 제공 (오프라인 페일세이프)
  e.respondWith(
    fetch(e.request)
      .then(function (resp) {
        var copy = resp.clone();
        caches.open(CACHE).then(function (c) { c.put(e.request, copy); });
        return resp;
      })
      .catch(function () { return caches.match(e.request); })
  );
});
"""


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def _favicon(link: str) -> str:
    host = urllib.parse.urlparse(link).netloc
    if not host:
        return '<span class="w-4 h-4 shrink-0"></span>'
    return (
        f'<img class="w-4 h-4 rounded-[3px] mt-0.5 shrink-0" '
        f'src="https://www.google.com/s2/favicons?domain={_esc(host)}&amp;sz=32" '
        'width="16" height="16" alt="" loading="lazy">'
    )


FRAME_COLORS = {"progressive": "#3b82f6", "conservative": "#ef4444", "moderate": "#9ca3af", "common": "#b45309"}


def _highlight_title(title: str, frame_words: list[dict]) -> str:
    """제목 속 프레임 단어를 성향 색으로 하이라이트.

    2단계 치환: 긴 단어부터 플레이스홀더로 치환한 뒤 마크업으로 복원 —
    "규제"와 "규제 실패"가 함께 있을 때 mark 태그가 중첩되는 것을 방지.
    """
    out = _esc(title)
    placeholders: dict[str, str] = {}
    ordered = sorted(frame_words, key=lambda w: -len(w.get("word", "")))
    for idx, w in enumerate(ordered):
        token = _esc(w.get("word", ""))
        if not token or token not in out:
            continue
        color = FRAME_COLORS.get(w.get("side"), "#b45309")
        placeholder = f"\x00F{idx}\x00"
        placeholders[placeholder] = (
            f'<mark style="background:transparent;color:{color};font-weight:700">{token}</mark>'
        )
        out = out.replace(token, placeholder)
    for placeholder, markup in placeholders.items():
        out = out.replace(placeholder, markup)
    return out


def _headline_anchor(h: dict, title_html: str) -> str:
    """매체 파비콘 + 매체명 + 제목 링크 — 카드·블라인드스팟·프레임 탭 공용."""
    return (
        f'<a class="flex items-start gap-2 text-[13px] hover:text-blue-600 dark:hover:text-blue-400" '
        f'href="{_esc(h["link"])}" target="_blank" rel="noopener nofollow">'
        f'{_favicon(h["link"])}'
        f'<span class="min-w-0"><b class="font-semibold text-neutral-400 text-xs mr-1.5">{_esc(h["outlet"])}</b>'
        f'{title_html}</span></a>'
    )


def _frame_chips(words: list[dict]) -> str:
    return " · ".join(
        f'<span style="color:{FRAME_COLORS.get(w.get("side"), "#b45309")}" class="font-semibold">{_esc(w.get("word", ""))}</span>'
        for w in words
        if w.get("word")
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


def _seo_meta(
    *, title: str, description: str, canonical: str,
    og_type: str = "website", og_image: str = "",
    jsonld_type: str = "WebPage", jsonld_extra: str = "",
    jsonld_breadcrumb: bool = True,
) -> str:
    """공통 SEO 메타 블록(Open Graph + Twitter Card + JSON-LD) 생성.

    모든 페이지에서 공통으로 쓰이는 메타를 _page() 안에서 자동 주입하기 위한 헬퍼.
    - og_image 미지정 시 사이트 기본 OG 이미지(/og.png) 사용.
    - jsonld_extra는 index 페이지의 WebSite/NewsMediaOrganization 등 추가 그래프를 싣는 슬롯.
    """
    base = f"https://{config.SITE_DOMAIN}"
    path = "" if canonical == "/" else canonical
    url = f"{base}/{path}" if path else f"{base}/"
    desc = description or config.SITE_DESCRIPTION
    img = og_image or f"{base}/og.png"
    site_name = config.SITE_TITLE

    og = [
        f'<meta property="og:type" content="{_esc(og_type)}">',
        f'<meta property="og:title" content="{_esc(title)}">',
        f'<meta property="og:description" content="{_esc(desc)}">',
        f'<meta property="og:url" content="{_esc(url)}">',
        f'<meta property="og:site_name" content="{_esc(site_name)}">',
        '<meta property="og:locale" content="ko_KR">',
        f'<meta property="og:image" content="{_esc(img)}">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        f'<meta property="og:image:alt" content="{_esc(site_name)} {_esc(config.SITE_TAGLINE)}">',
    ]
    tw = [
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{_esc(title)}">',
        f'<meta name="twitter:description" content="{_esc(desc)}">',
        f'<meta name="twitter:image" content="{_esc(img)}">',
    ]

    # JSON-LD 구조화 데이터: 페이지 본체 + (선택) BreadcrumbList + (선택) 추가 그래프
    graph: list[str] = []
    page_node = {
        "@type": jsonld_type,
        "@id": url,
        "name": title,
        "url": url,
        "description": desc,
        "inLanguage": "ko-KR",
        "isPartOf": {"@type": "WebSite", "@id": f"{base}/"},
    }
    graph.append(json.dumps(page_node, ensure_ascii=False))
    if jsonld_breadcrumb and canonical:
        crumb = {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": site_name,
                 "item": f"{base}/"},
                {"@type": "ListItem", "position": 2, "name": title.split(" — ")[0],
                 "item": url},
            ],
        }
        graph.append(json.dumps(crumb, ensure_ascii=False))
    if jsonld_extra:
        graph.append(jsonld_extra)
    ld = (
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@graph":[' + ",".join(graph) + "]}</script>"
    )
    return "\n".join([*og, *tw, ld])


def _page(
    *, title: str, active: str, generated_at: str, feed: str,
    updated_label: str, head_extra: str, tabs_html: str, after_header: str,
    main_html: str, footer_notes: list[str], site_stamp: str, extra_script: str = "",
    banner_html: str = "", asset_prefix: str = "",
    description: str = "", canonical: str = "",
    og_type: str = "website", og_image: str = "",
    jsonld_type: str = "WebPage", jsonld_extra: str = "",
    jsonld_breadcrumb: bool = True, noindex: bool = False,
) -> str:
    nav = "".join(
        f'<a href="{asset_prefix}{href}" class="px-2 py-1 rounded-lg text-sm '
        + (
            "font-bold text-blue-600 dark:text-blue-400"
            if active == key
            else "text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100"
        )
        + f'">{label}</a>'
        for key, label, href in (
            ("news", "뉴스", "index.html"),
            ("blindspot", "블라인드스팟", "blindspot.html"),
            ("frame", "프레임 체크", "frame.html"),
            ("community", "커뮤니티", "community.html"),
            ("scrapbook", "스크랩북", "scrapbook.html"),
        )
    )
    tabs_nav = (
        f'<nav class="flex gap-2 overflow-x-auto no-scrollbar pb-3" aria-label="필터">{tabs_html}</nav>'
        if tabs_html
        else ""
    )
    notes = "".join(f'<p class="mb-2 max-w-[72ch]">{_esc(n)}</p>' for n in footer_notes)
    sentry = ""
    if config.SENTRY_LOADER_KEY:
        sentry = (
            f'<script src="https://js.sentry-cdn.com/{config.SENTRY_LOADER_KEY}.min.js" '
            'crossorigin="anonymous"></script>'
        )
    # canonical: 루트는 "/", 그 외는 파일명. 미지정 시 태그 생략
    canonical_tag = ""
    if canonical:
        path = "" if canonical == "/" else canonical
        canonical_tag = f'<link rel="canonical" href="https://{config.SITE_DOMAIN}/{path}">\n'
    robots_tag = '<meta name="robots" content="noindex, follow">\n' if noindex else ""
    gsc_tag = ""
    if config.GOOGLE_SITE_VERIFICATION:
        gsc_tag = f'<meta name="google-site-verification" content="{_esc(config.GOOGLE_SITE_VERIFICATION)}">\n'
    adsense_script = ""
    if config.ADSENSE_CLIENT_ID:
        adsense_script = (
            f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={_esc(config.ADSENSE_CLIENT_ID)}" '
            'crossorigin="anonymous"></script>'
        )
    seo_meta = "" if noindex else _seo_meta(
        title=title, description=description, canonical=canonical,
        og_type=og_type, og_image=og_image,
        jsonld_type=jsonld_type, jsonld_extra=jsonld_extra,
        jsonld_breadcrumb=jsonld_breadcrumb,
    )
    return f"""<!doctype html>
<html lang="ko" data-generated-at="{_esc(generated_at)}" data-feed="{feed}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(description or config.SITE_DESCRIPTION)}">
{canonical_tag}{robots_tag}{gsc_tag}
<link rel="alternate" type="application/rss+xml" title="{_esc(config.SITE_TITLE)} RSS" href="https://{config.SITE_DOMAIN}/rss.xml">
{adsense_script}
{seo_meta}
{head_extra}
<link rel="icon" href="{FAVICON_SVG}">
<link rel="manifest" href="{asset_prefix}site.webmanifest">
<link rel="apple-touch-icon" href="{asset_prefix}icon-512.png">
<meta name="theme-color" content="#2563eb">
<link rel="stylesheet" href="{asset_prefix}tailwind.css">
<script>
(function() {{
  var t = localStorage.getItem("goreun_theme") || "system";
  if (t === "dark" || (t === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches)) {{
    document.documentElement.classList.add("dark");
  }} else {{
    document.documentElement.classList.remove("dark");
  }}
}})();
</script>
<!-- AdSense 승인 후 사이트 확인/광고 스크립트를 여기에 붙여넣으세요 -->
</head>
<body class="bg-stone-50 dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100 antialiased" style='font-family:"Pretendard Variable",Pretendard,-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR","Malgun Gothic",sans-serif'>
<div id="offline-banner" hidden class="bg-amber-100 dark:bg-amber-500/15 text-amber-800 dark:text-amber-300 text-xs text-center px-4 py-2">오프라인 상태이거나 최신 뉴스를 불러오지 못했습니다. 이전 뉴스를 보여줍니다.</div>
<header id="site-header" class="sticky top-0 z-20 border-b border-stone-200/80 dark:border-neutral-800 bg-stone-50/90 dark:bg-neutral-900/90 backdrop-blur-md">
  <div class="max-w-[1440px] mx-auto px-4 sm:px-6">
    <div class="flex items-center justify-between py-2.5 gap-3 border-b border-stone-200/60 dark:border-neutral-800/60">
      <div class="flex items-center gap-3 shrink-0">
        <a href="index.html" class="flex items-center gap-2.5 hover:opacity-90 transition-opacity" aria-label="고른뉴스 홈">
          {LOGO_MARK}
          <span class="text-xl font-extrabold tracking-tight bg-gradient-to-r from-blue-600 to-indigo-600 dark:from-blue-400 dark:to-indigo-400 bg-clip-text text-transparent">{_esc(config.SITE_TITLE)}</span>
        </a>
        <span class="hidden md:inline-block text-xs text-neutral-500 dark:text-neutral-400 font-medium pl-2 border-l border-stone-300 dark:border-neutral-700">{_esc(config.SITE_TAGLINE)}</span>
      </div>
      
      <div class="flex items-center gap-2">
        <span class="hidden sm:flex items-center gap-1.5 text-xs text-neutral-500 dark:text-neutral-400 mr-1">
          <span class="relative flex h-2 w-2" aria-hidden="true">
            <span class="animate-pulse absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
          <span id="updated-label" class="tabular-nums">{_esc(updated_label)}</span>
        </span>

        <span id="auth-area" class="flex items-center gap-1"></span>

        <button type="button" id="theme-toggle" title="테마 변경 (라이트/다크/시스템)" class="rounded-full border border-stone-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-2.5 py-1 text-xs text-neutral-600 dark:text-neutral-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors flex items-center gap-1">
          <span id="theme-icon">💻</span>
        </button>

        <button type="button" id="bug-report" class="hidden sm:inline-flex rounded-full border border-stone-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-1 text-xs text-neutral-500 dark:text-neutral-400 hover:text-blue-600 dark:hover:text-blue-400 transition-colors">버그 제보</button>
      </div>
    </div>

    <div class="flex items-center justify-between py-2 overflow-x-auto no-scrollbar">
      <nav class="flex items-center gap-1 overflow-x-auto no-scrollbar [&>a]:shrink-0" aria-label="페이지">{nav}</nav>
      <a href="search.html" class="hidden sm:flex items-center gap-1.5 text-xs text-neutral-400 dark:text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300 px-2 py-1 rounded-lg transition-colors shrink-0">
        <span>🔍 검색</span>
        <kbd class="hidden md:inline-block font-mono text-[10px] bg-stone-200/70 dark:bg-neutral-800 px-1.5 py-0.5 rounded border border-stone-300/50 dark:border-neutral-700">⌘K</kbd>
      </a>
    </div>
    {tabs_nav}
  </div>
</header>
{after_header}
<main class="max-w-[1440px] mx-auto px-5">{main_html}</main>
<footer class="border-t border-stone-200 dark:border-neutral-700 mt-4 py-5 pb-12 text-xs text-neutral-500 dark:text-neutral-400">
  <div class="max-w-[1440px] mx-auto px-5">
    {notes}
    <p class="flex flex-wrap gap-x-3 gap-y-1 mb-2">
      <a class="hover:text-blue-600 dark:hover:text-blue-400" href="{asset_prefix}about.html">고른뉴스란?</a>
      <a class="hover:text-blue-600 dark:hover:text-blue-400" href="{asset_prefix}terms.html">이용약관</a>
      <a class="hover:text-blue-600 dark:hover:text-blue-400" href="{asset_prefix}privacy.html">개인정보처리방침</a>
      <a class="hover:text-blue-600 dark:hover:text-blue-400" href="{asset_prefix}newsletter.html">뉴스레터 미리보기</a>
    </p>
    <p class="flex flex-wrap gap-x-3 gap-y-1"><span>{site_stamp}</span><span id="visit-count" class="tabular-nums"></span></p>
  </div>
</footer>
<div id="login-modal" hidden role="dialog" aria-modal="true" aria-label="로그인 및 회원가입 모달" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
  <div class="w-[22rem] rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5 shadow-2xl">
    <div class="flex gap-1 mb-3">
      <button type="button" id="auth-tab-login" class="auth-tab flex-1 rounded-lg py-1.5 text-sm font-medium transition-colors" aria-selected="true">로그인</button>
      <button type="button" id="auth-tab-signup" class="auth-tab flex-1 rounded-lg py-1.5 text-sm font-medium transition-colors" aria-selected="false">회원가입</button>
    </div>
    <p class="text-xs text-neutral-400 mb-3 leading-relaxed">계정 정보는 이 기기(브라우저)에만 저장되며 서버로 전송되지 않습니다. 비밀번호는 해시로만 보관됩니다.</p>
    <form id="login-form" class="flex flex-col gap-2">
      <input id="login-id" type="text" required maxlength="20" autocomplete="username" placeholder="아이디" class="rounded-lg border border-stone-300 dark:border-neutral-600 bg-stone-50 dark:bg-neutral-900 px-3 py-2 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-blue-500">
      <input id="login-nick" type="text" maxlength="16" placeholder="닉네임" hidden class="rounded-lg border border-stone-300 dark:border-neutral-600 bg-stone-50 dark:bg-neutral-900 px-3 py-2 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-blue-500">
      <input id="login-pw" type="password" required maxlength="32" autocomplete="current-password" placeholder="비밀번호" class="rounded-lg border border-stone-300 dark:border-neutral-600 bg-stone-50 dark:bg-neutral-900 px-3 py-2 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-blue-500">
      <p id="login-error" hidden class="text-xs text-red-500"></p>
      <button type="submit" id="login-submit" class="rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium py-2 transition-colors">로그인</button>
    </form>
    <button type="button" id="login-close" class="mt-2.5 w-full text-center text-xs text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-200">닫기</button>
  </div>
</div>
<button type="button" id="to-top" hidden aria-label="맨 위로" class="fixed bottom-6 right-5 z-40 w-11 h-11 rounded-full bg-neutral-900 text-stone-50 dark:bg-neutral-100 dark:text-neutral-900 shadow-xl text-lg hover:scale-105 active:scale-95 transition-transform flex items-center justify-center">↑</button>
{banner_html}
<script>{BASE_SCRIPT}</script>
{f"<script>{extra_script}</script>" if extra_script else ""}
{sentry}
</body>
</html>"""


# ── 뉴스 페이지 ─────────────────────────────────────────────────────────


def _render_ticker(breaking: list[dict]) -> str:
    if not breaking:
        return ""
    items = [
        {
            "time": b["time"],
            "title": b["title"],
            "outlet": b["outlet"],
            "link": b["link"],
        }
        for b in breaking
    ]
    payload = json.dumps(items, ensure_ascii=False).replace("</", "<\\/")
    first = items[0]
    return f"""<div class="border-b border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800">
  <div class="max-w-[1440px] mx-auto px-5 py-2 flex items-center gap-3">
    <span class="text-red-600 dark:text-red-400 font-bold text-xs tracking-[0.12em] shrink-0">속보</span>
    <a id="ticker-link" class="flex items-center gap-2 min-w-0 flex-1 text-sm" href="{_esc(first["link"])}" target="_blank" rel="noopener nofollow">
      <time class="text-red-600 dark:text-red-400 text-xs font-semibold tabular-nums shrink-0">{_esc(first["time"])}</time>
      <span class="t-title truncate">{_esc(first["title"])}</span>
      <span class="t-outlet text-xs text-neutral-400 shrink-0">{_esc(first["outlet"])}</span>
    </a>
    <script type="application/json" id="ticker-data">{payload}</script>
  </div>
</div>"""


def _render_bias_bar(bias: dict | None) -> str:
    """성향 분포 바. 전체 매체 대비 각 성향 비중 및 분류 없음 비중을 정직하게 연출."""
    if not bias:
        return ""
    total = sum(bias.values())
    if total == 0:
        return ""
    dot_colors = {"progressive": "#3b82f6", "moderate": "#9ca3af", "conservative": "#ef4444"}
    segments, labels = [], []
    for key, label in BIAS_LABELS:
        n = bias.get(key, 0)
        if n:
            pct = (n / total) * 100
            segments.append(
                f'<span class="{BIAS_BAR_CLASSES[key]}" style="width:{pct:.1f}%" title="{label} {n}곳 ({pct:.1f}%)"></span>'
            )
        labels.append(
            f'<span class="inline-flex items-center gap-1">'
            f'<span class="w-1.5 h-1.5 rounded-full" style="background:{dot_colors[key]}"></span>'
            f"{label} {n}</span>"
        )
    unknown = bias.get("unknown", 0)
    if unknown:
        pct = (unknown / total) * 100
        segments.append(
            f'<span class="bg-stone-300 dark:bg-neutral-600 opacity-60" style="width:{pct:.1f}%" title="분류 없음 {unknown}곳 ({pct:.1f}%)"></span>'
        )
        labels.append(
            f'<span class="inline-flex items-center gap-1">'
            f'<span class="w-1.5 h-1.5 rounded-full bg-stone-300 dark:bg-neutral-600"></span>'
            f"분류 없음 {unknown}</span>"
        )
    bar = f'<div class="flex h-1.5 rounded-full overflow-hidden bg-stone-200 dark:bg-neutral-700">{"".join(segments)}</div>'
    return f"""<div class="mb-2.5" aria-label="보도 매체 성향 분포">
  {bar}
  <div class="flex flex-wrap gap-3 text-[10px] text-neutral-400 mt-1.5">{"".join(labels)}</div>
</div>"""


def _render_issue(issue: dict, index: int) -> str:
    heads = issue.get("headlines", [])
    color = CATEGORY_COLORS.get(issue["category"], "#2563eb")
    outlet_count = issue.get("outlet_count", len({h["outlet"] for h in heads}))
    anchor = f"issue-{index}"
    scrap_payload = _esc(json.dumps(
        {
            "id": f"issue:{issue['label']}",
            "type": "issue",
            "label": issue["label"],
            "summary": issue["summary"],
            "category": issue["category"],
            "headlines": heads,
        },
        ensure_ascii=False,
    ))
    bias_dots = {"progressive": "#3b82f6", "moderate": "#9ca3af", "conservative": "#ef4444", "unknown": "#d6d3d1"}
    framing = issue.get("framing") or {}
    frame_words = framing.get("words") or []

    side_frame_words = [w for w in frame_words if w.get("side") != "common"]

    def _hl(title: str) -> str:
        # 공통어까지 색칠하면 노이즈 — 진영 전용어만 하이라이트
        return _highlight_title(title, side_frame_words)

    framing_html = ""
    if framing.get("note"):
        chips = _frame_chips(frame_words)
        framing_html = f"""<div class="rounded-lg border border-stone-200 dark:border-neutral-700 bg-stone-50 dark:bg-neutral-900/60 p-3 mb-3">
  <p class="text-[11px] font-bold mb-1">🔍 프레임 체크 — 같은 사건, 다른 단어 <span class="font-normal text-neutral-400">(참고용 AI 분석)</span></p>
  <p class="text-xs text-neutral-600 dark:text-neutral-300">{_esc(framing["note"])}</p>
  {f'<p class="mt-1.5 text-xs text-neutral-500 dark:text-neutral-400">프레임 단어: {chips}</p>' if chips else ""}
</div>"""

    # 수직 타임라인: 송고 시간순(1보 → 최신)으로 사건의 흐름을 보여준다
    rows = "".join(
        f'<li class="relative" data-b="{_esc(h.get("bias", "unknown"))}" data-t="{_esc(h.get("time", ""))}">'
        f'<span class="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full bg-white dark:bg-neutral-800 border-2" style="border-color:{color}" aria-hidden="true"></span>'
        + f'<a class="flex items-start gap-2 text-[13px] hover:text-blue-600 dark:hover:text-blue-400" '
        f'href="{_esc(h["link"])}" target="_blank" rel="noopener nofollow">'
        + (
            f'<time class="min-w-[2.25rem] shrink-0 pt-px text-[11px] text-neutral-400 tabular-nums whitespace-nowrap">{_esc(h["time"])}</time>'
            if h.get("time")
            else ""
        )
        + f'{_favicon(h["link"])}'
        f'<span class="min-w-0"><b class="font-semibold text-xs mr-1.5" style="color:{bias_dots.get(h.get("bias", "unknown"), "#9ca3af")}">{_esc(h["outlet"])}</b>'
        f'{_hl(h["title"])}</span></a></li>'
        for h in heads
    )
    bias_attr = _esc(json.dumps(issue.get("bias") or {}, ensure_ascii=False))
    if outlet_count >= 7:
        tier_cls, span_cls = "card-lg ", " sm:col-span-2"
    elif outlet_count >= 4:
        tier_cls, span_cls = "", ""
    else:
        tier_cls, span_cls = "card-sm ", ""
    minor_attr = ' data-minor="1" hidden' if outlet_count <= 3 else ""  # 전체 탭에선 숨김
    return f"""<article id="{anchor}" class="{tier_cls}rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5 border-t-[3px]{span_cls}" style="border-top-color:{color}" data-cat="{_esc(issue["category"])}" data-oc="{outlet_count}" data-bias="{bias_attr}"{minor_attr}>
  <div class="flex items-center justify-between text-xs">
    <span class="flex items-center gap-2 flex-wrap">
      <span class="font-semibold rounded-full px-2.5 py-0.5" style="color:{color};background:{color}1f">{_esc(issue["category"])}</span>
      <span class="hero-badge hidden items-center font-bold rounded-full px-2.5 py-0.5 bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400">📢 {outlet_count}개 매체 집중 보도</span>
    </span>
    <span class="flex items-center gap-2">
      <span class="text-neutral-400">{outlet_count}개 매체</span>
      <button type="button" class="scrap-btn text-base leading-none text-neutral-300 dark:text-neutral-600 hover:text-amber-500" aria-label="스크랩" data-scrap="{scrap_payload}">☆</button>
    </span>
  </div>
  <h3 class="fs-t mt-2.5 mb-1.5 font-bold text-[15px] leading-snug break-keep [text-wrap:balance]">{_esc(issue["label"])}</h3>
  <div class="summary-wrap relative cursor-pointer mb-3.5" title="클릭하면 전체 요약을 봅니다">
    <p class="fs-p text-sm text-neutral-600 dark:text-neutral-300 break-keep">{_esc(issue["summary"])}</p>
    <span class="fade"></span>
  </div>
  <div class="bias-inline hidden mb-3.5">{_render_bias_bar(issue.get("bias"))}</div>
  <div class="card-foot border-t border-stone-200 dark:border-neutral-700 pt-3">
    <div class="flex items-center gap-2">
      <details class="headlines-toggle">
        <summary class="list-none [&::-webkit-details-marker]:hidden cursor-pointer select-none inline-flex items-center gap-1.5 rounded-lg border border-stone-200 dark:border-neutral-600 px-3 py-1.5 text-xs font-medium text-blue-600 dark:text-blue-400 hover:bg-stone-100 dark:hover:bg-neutral-700">
          매체별 헤드라인 {len(heads)}건 <span class="tri">▾</span>
        </summary>
      </details>
      <span class="flex-1"></span>
      <button type="button" class="share-btn shrink-0 rounded-lg border border-stone-200 dark:border-neutral-600 px-3 py-1.5 text-xs text-neutral-500 dark:text-neutral-400 hover:text-blue-600 hover:border-blue-500" data-anchor="{anchor}"{f' data-url="{_esc(_SHARE_BASE)}#{anchor}"' if _SHARE_BASE else ""} data-title="{_esc(issue["label"])}" data-text="{_esc(issue["summary"])}">공유</button>
      <button type="button" class="imgsave-btn shrink-0 rounded-lg border border-stone-200 dark:border-neutral-600 px-3 py-1.5 text-xs text-neutral-500 dark:text-neutral-400 hover:text-blue-600 hover:border-blue-500" title="인스타그램용 정사각 이미지로 저장">이미지 저장</button>
    </div>
    <div class="headlines-body mt-3" hidden>
      {framing_html}
      <div class="flex justify-end -mb-1"><button type="button" class="sort-toggle text-[10px] text-neutral-400 hover:text-blue-600 dark:hover:text-blue-400" data-mode="time">성향순 보기</button></div>
      {_render_bias_bar(issue.get("bias"))}
      <ul class="relative ml-1.5 mt-3 pl-4 border-l-2 border-stone-200 dark:border-neutral-700 flex flex-col gap-3">{rows}</ul>
    </div>
  </div>
</article>"""


def _render_blindspot(blindspot: dict | None) -> str:
    """블라인드스팟 — 한쪽 성향 매체만 보도한 이슈 (Ground News 방식)."""
    if not blindspot:
        return ""
    groups = [
        ("progressive_missing", "보수 매체만 보도", FRAME_COLORS["conservative"], "진보 매체가 다루지 않은 이슈"),
        ("conservative_missing", "진보 매체만 보도", FRAME_COLORS["progressive"], "보수 매체가 다루지 않은 이슈"),
    ]
    def _bs_row(it: dict, color: str) -> str:
        if it.get("issue_index") is not None:
            href = f"#issue-{it['issue_index']}"
            target = ""
        else:
            href = _esc(it["link"])
            target = ' target="_blank" rel="noopener nofollow"'
        return (
            f'<li><a class="flex items-start gap-2 py-1.5 text-[13px] hover:text-blue-600 dark:hover:text-blue-400" '
            f'href="{href}"{target}>'
            f'<span class="mt-1.5 w-1.5 h-1.5 rounded-full shrink-0" style="background:{color}"></span>'
            f'<span class="flex-1 min-w-0 line-clamp-2">{_esc(it["label"])}</span>'
            f'<span class="text-[10px] text-neutral-400 shrink-0">{it["outlet_count"]}곳</span></a></li>'
        )

    parts = []
    for key, title, color, hint in groups:
        items = (blindspot.get(key) or [])[:4]  # 사이드바는 맛보기 4건
        if not items:
            continue
        rows = "".join(_bs_row(it, color) for it in items)
        parts.append(
            f'<div class="mt-2 first:mt-0"><h3 class="text-xs font-bold" style="color:{color}" title="{_esc(hint)}">{title}</h3>'
            f'<ul class="divide-y divide-stone-100 dark:divide-neutral-700/60">{rows}</ul></div>'
        )
    if not parts:
        return ""
    return f"""<section class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5">
  <h2 class="text-sm font-bold mb-0.5">블라인드스팟</h2>
  <p class="text-[11px] text-neutral-400 mb-2">한쪽 성향 매체만 보도한 이슈 — 놓치기 쉬운 관점입니다</p>
  {"".join(parts)}
  <a href="blindspot.html" class="block mt-2.5 text-xs text-blue-600 dark:text-blue-400 hover:underline">블라인드스팟 전체 보기 →</a>
</section>"""


def _render_sidebar(policy: list[dict], blindspot: dict | None = None) -> str:
    items = "".join(
        f"""<div class="policy-item border-t border-stone-200 dark:border-neutral-700 py-3 first:border-0 first:pt-0 last:pb-0">
  <div class="flex items-center justify-between gap-2 mb-1">
    <h3 class="fs-t text-[13px] font-semibold"><a class="hover:text-blue-600 dark:hover:text-blue-400" href="{_esc(p["link"])}" target="_blank" rel="noopener">{_esc(p["title"])}</a></h3>
    <span class="read-time text-[10px] text-neutral-400 shrink-0"></span>
  </div>
  <p class="policy-text fs-p text-xs text-neutral-500 dark:text-neutral-400 line-clamp-2">{_esc(p["summary"])}</p>
</div>"""
        for p in policy
    )
    newsletter_form = f"""<section class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5">
    <h2 class="text-sm font-bold mb-0.5">뉴스레터</h2>
    <p class="text-[11px] text-neutral-400 mb-3">매일 아침 7시, 요약된 뉴스를 메일로 받아보세요</p>
    <form id="newsletter" class="flex gap-2" data-action="{_esc(config.NEWSLETTER_FORM_ACTION)}" data-entry="{_esc(config.NEWSLETTER_FORM_ENTRY)}">
      <input type="email" required placeholder="you@example.com" class="min-w-0 flex-1 rounded-lg border border-stone-300 dark:border-neutral-600 bg-stone-50 dark:bg-neutral-900 px-3 py-1.5 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-blue-500">
      <button type="submit" class="shrink-0 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-3.5 py-1.5">구독</button>
    </form>
    <p id="newsletter-done" hidden class="text-sm font-medium text-emerald-600 dark:text-emerald-400">구독이 완료되었습니다!</p>
  </section>"""
    top_viewed = """<section id="top-viewed-panel" hidden class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5">
    <h2 class="text-sm font-bold mb-0.5">많이 본 이슈</h2>
    <p class="text-[11px] text-neutral-400 mb-2">독자들이 많이 펼쳐본 이슈 TOP 5</p>
    <ol id="top-viewed" class="flex flex-col"></ol>
  </section>"""
    keyword_panel = """<section class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5">
    <h2 class="text-sm font-bold mb-0.5">키워드 알림</h2>
    <p class="text-[11px] text-neutral-400 mb-2.5">등록한 키워드가 포함된 이슈를 상단 고정·강조합니다 (이 브라우저에만 저장)</p>
    <form id="kw-form" class="flex gap-2">
      <input id="kw-input" type="text" maxlength="20" placeholder="예: 반도체" class="min-w-0 flex-1 rounded-lg border border-stone-300 dark:border-neutral-600 bg-stone-50 dark:bg-neutral-900 px-3 py-1.5 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-blue-500">
      <button type="submit" class="shrink-0 rounded-lg border border-stone-300 dark:border-neutral-600 px-3 py-1.5 text-sm text-neutral-600 dark:text-neutral-300 hover:border-blue-500 hover:text-blue-600">추가</button>
    </form>
    <div id="kw-list" class="flex flex-wrap gap-1.5 mt-2.5"></div>
  </section>"""
    policy_panel = (
        f"""<section class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5">
    <h2 class="text-sm font-bold mb-0.5">정책 브리핑</h2>
    <p class="text-[11px] text-neutral-400 mb-3">출처: 대한민국 정책브리핑(korea.kr) · 공공누리 제1유형</p>
    {items}
  </section>"""
        if policy
        else ""
    )
    return f"""<aside class="flex flex-col gap-5 self-start lg:sticky lg:top-20">
  {_render_blindspot(blindspot)}
  {policy_panel}
  {top_viewed}
  {ad_slot("sidebar-1")}
  {newsletter_form}
  {keyword_panel}
  <section class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5">
    <h2 class="text-sm font-bold mb-0.5">공개 API</h2>
    <p class="text-[11px] text-neutral-400 mb-2.5">이 페이지의 모든 데이터는 JSON으로도 제공됩니다 (매시간 갱신).</p>
    <code class="block rounded-lg bg-stone-100 dark:bg-neutral-900 px-2.5 py-2 text-[11px] overflow-x-auto">GET /briefing.json<br>GET /community.json<br>GET /bias-model.json</code>
  </section>
</aside>"""


def build(
    briefing: dict, community: list[dict], out_dir: Path,
    archive_stamps: list[str] | None = None,
    snapshots: list[tuple[str, dict]] | None = None,
) -> Path:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    generated_at = briefing.get("generated_at", now.isoformat())
    out_dir.mkdir(parents=True, exist_ok=True)

    punycode_domain = config.SITE_DOMAIN.encode("idna").decode()
    og_url = f"https://{punycode_domain}/og.png" if build_og(briefing, out_dir / "og.png", now) else ""
    # index 전용 추가 JSON-LD 그래프: WebSite(사이트 검색액션) + NewsMediaOrganization
    index_website = {
        "@type": "WebSite",
        "@id": f"https://{config.SITE_DOMAIN}/#website",
        "name": config.SITE_TITLE,
        "url": f"https://{config.SITE_DOMAIN}/",
        "publisher": {"@id": f"https://{config.SITE_DOMAIN}/#org"},
        "potentialAction": {
            "@type": "SearchAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": f"https://{config.SITE_DOMAIN}/search.html?q={{search_term_string}}",
            },
            "query-input": "required name=search_term_string",
        },
    }
    index_org = {
        "@type": "NewsMediaOrganization",
        "@id": f"https://{config.SITE_DOMAIN}/#org",
        "name": config.SITE_TITLE,
        "url": f"https://{config.SITE_DOMAIN}/",
        "logo": f"https://{config.SITE_DOMAIN}/icon-512.png",
        "slogan": config.SITE_TAGLINE,
        "sameAs": [],
    }
    index_jsonld = (
        json.dumps(index_website, ensure_ascii=False)
        + ","
        + json.dumps(index_org, ensure_ascii=False)
    )

    issues = briefing.get("issues", [])
    heat = briefing.get("heat", {})
    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue["category"]] = counts.get(issue["category"], 0) + 1
    hottest = max(heat, key=heat.get) if heat else None

    major_count = sum(1 for i in issues if i.get("outlet_count", 0) > 3)
    tabs = [_tab("전체", major_count, "cat", "전체", True)]
    for cat in config.ISSUE_CATEGORIES:
        if cat not in counts:
            continue
        color = CATEGORY_COLORS.get(cat, "#2563eb")
        dot = f'<span class="inline-block w-2 h-2 rounded-full" style="background:{color}"></span>'
        label = f"{cat} 🔥" if cat == hottest else cat
        tabs.append(_tab(label, counts[cat], "cat", cat, False, dot))

    cards = []
    for i, issue in enumerate(issues):
        card = _render_issue(issue, i)
        if i >= config.INITIAL_CARDS:
            # 무한 스크롤: 최초 12개 이후는 숨겨 두고 스크롤 시 12개씩 공개
            card = card.replace('<article id=', '<article data-lazy="1" id=', 1).replace(
                'class="rounded-xl', 'class="not-revealed rounded-xl', 1
            )
        cards.append(card)
        if i == 3:  # 4번째와 5번째 카드 사이 광고
            cards.append(f'<div class="col-span-full">{ad_slot("feed-1")}</div>')
    cards.append('<div id="feed-sentinel" class="col-span-full h-1" aria-hidden="true"></div>')
    # 뉴스는 오늘만 표시 — 이전일은 하단 날짜 스트립으로 해당일 스냅샷 이동
    today = now.strftime("%Y-%m-%d")
    dates = _dates_of(snapshots or [])
    cards.append(f'<div class="col-span-full">{_date_strip(dates, today, "archive")}</div>')

    main_html = f"""<div class="grid grid-cols-1 lg:grid-cols-[7fr_3fr] gap-7 py-6">
  <h1 class="sr-only">{_esc(config.SITE_TITLE)} — {_esc(config.SITE_TAGLINE)}</h1>
  <section class="grid sm:grid-cols-2 gap-4 content-start" aria-label="주요 이슈">{"".join(cards)}</section>
  {_render_sidebar(briefing.get("policy", []), briefing.get("blindspot"))}
</div>"""

    stamp = (
        f"ⓒ {_esc(config.SITE_TITLE)} ({_esc(config.SITE_DOMAIN)}) · "
        f"생성 시각 {now.strftime('%Y-%m-%d %H:%M KST')}"
    )
    updated = f"{now.strftime('%m월 %d일 %H:%M')} 업데이트 · 매시간 갱신"

    nl_banner = f"""<div id="nl-banner" style="transform:translateY(150%)" class="fixed bottom-5 left-5 z-40 w-80 max-w-[calc(100vw-2.5rem)] rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 shadow-xl p-4 transition-transform duration-500">
  <button type="button" id="nl-banner-close" class="absolute top-2 right-3 text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-200" aria-label="닫기">✕</button>
  <p class="text-sm font-semibold mb-0.5">내일 아침 핵심 뉴스도 요약해 드릴까요?</p>
  <p class="text-xs text-neutral-400 mb-2.5">매일 아침 7시, 메일로 보내드려요.</p>
  <form id="nl-banner-form" class="flex gap-2" data-action="{_esc(config.NEWSLETTER_FORM_ACTION)}" data-entry="{_esc(config.NEWSLETTER_FORM_ENTRY)}">
    <input type="email" required placeholder="you@example.com" class="min-w-0 flex-1 rounded-lg border border-stone-300 dark:border-neutral-600 bg-stone-50 dark:bg-neutral-900 px-3 py-1.5 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-blue-500">
    <button type="submit" class="shrink-0 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-3.5 py-1.5">구독</button>
  </form>
  <p id="nl-banner-done" hidden class="text-sm font-medium text-emerald-600 dark:text-emerald-400">구독이 완료되었습니다!</p>
</div>"""

    onboarding = """<div id="onboard-modal" hidden class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
  <div class="w-[24rem] max-w-full rounded-2xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-6 shadow-2xl text-center">
    <div id="ob-emoji" class="text-5xl mb-3">⚖️</div>
    <h3 id="ob-title" class="text-lg font-extrabold mb-1.5"></h3>
    <p id="ob-desc" class="text-sm text-neutral-500 dark:text-neutral-400 leading-relaxed min-h-[4.5rem]"></p>
    <div id="ob-dots" class="flex justify-center gap-1.5 my-4"></div>
    <div class="flex gap-2">
      <button type="button" id="ob-prev" class="flex-1 rounded-lg border border-stone-300 dark:border-neutral-600 py-2 text-sm text-neutral-500 dark:text-neutral-400">이전</button>
      <button type="button" id="ob-next" class="flex-[2] rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium py-2">다음</button>
    </div>
    <button type="button" id="ob-skip" class="mt-3 text-xs text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-200">건너뛰기</button>
  </div>
</div>"""

    page = _page(
        title=f"{config.SITE_TITLE} — {config.SITE_TAGLINE}",
        canonical="/",
        description=f"{len(config.PRESS_FEEDS)}개 언론사 헤드라인을 교차 확인한 매시간 중립 뉴스 브리핑 — 성향 스펙트럼·블라인드스팟·프레임 체크로 한 사건을 여러 시각에서.",
        active="news",
        banner_html=nl_banner + onboarding,
        generated_at=generated_at,
        feed="briefing.json",
        updated_label=updated,
        head_extra="",
        tabs_html="".join(tabs),
        after_header=_render_ticker(briefing.get("breaking", [])),
        main_html=main_html,
        footer_notes=[DISCLAIMER, KOGL_NOTICE],
        site_stamp=stamp,
        og_type="website",
        og_image=og_url,
        jsonld_type="WebSite",
        jsonld_extra=index_jsonld,
        jsonld_breadcrumb=False,
    )
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    (out_dir / "sw.js").write_text(
        SERVICE_WORKER.replace("goreun-v1", f"goreun-{now.strftime('%Y%m%d%H')}"),
        encoding="utf-8",
    )

    # PWA: 홈 화면 설치용 매니페스트 + 아이콘
    build_icon(out_dir / "icon-512.png")
    (out_dir / "site.webmanifest").write_text(
        json.dumps(
            {
                "name": config.SITE_TITLE,
                "short_name": config.SITE_TITLE,
                "description": config.SITE_TAGLINE,
                "start_url": "./",
                "display": "standalone",
                "background_color": "#faf9f7",
                "theme_color": "#2563eb",
                "icons": [
                    {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # AdSense ads.txt — 광고 게재 필수 파일 (소유권 확인 보조 수단이기도 함)
    if config.ADSENSE_CLIENT_ID:
        pub_id = config.ADSENSE_CLIENT_ID.replace("ca-", "", 1)
        (out_dir / "ads.txt").write_text(
            f"google.com, {pub_id}, DIRECT, f08c47fec0942fa0\n", encoding="utf-8"
        )

    build_community_page(community, out_dir, generated_at, now, updated, stamp)
    build_scrapbook_page(out_dir, generated_at, now, updated, stamp)
    build_docs(out_dir, generated_at, updated, stamp)
    build_newsletter_page(briefing, out_dir, now)
    build_blindspot_page(briefing, out_dir, generated_at, updated, stamp, snapshots or [], now)
    build_frame_page(briefing, out_dir, generated_at, updated, stamp, snapshots or [], now)
    build_seo_files(briefing, out_dir, punycode_domain, now, archive_stamps or [])
    return out_dir / "index.html"


# ── 날짜 유틸: 스트립(사진 참조 스타일)·날짜별 스냅샷 ───────────────────

_WEEKDAYS = "월화수목금토일"


def _date_label(date_str: str) -> str:
    from datetime import datetime as _dt

    d = _dt.strptime(date_str, "%Y-%m-%d")
    return f"{d.month:02d}월 {d.day:02d}일({_WEEKDAYS[d.weekday()]})"


def _dates_of(snapshots: list[tuple[str, dict]]) -> list[tuple[str, str]]:
    """스냅샷들에서 (날짜, 그 날짜의 최신 스탬프) 목록을 최신순으로 만든다."""
    seen: dict[str, str] = {}
    for stamp, _ in snapshots:  # snapshots는 최신순
        date = stamp[:10]
        if date not in seen:
            seen[date] = stamp
    return list(seen.items())


def _date_strip(
    dates: list[tuple[str, str]], active_date: str, mode: str, asset_prefix: str = ""
) -> str:
    """섹션 하단 날짜 선택 스트립. mode: 'archive'(스냅샷 링크) | 'anchor'(#d-날짜)."""
    if len(dates) < 2:
        return ""  # 선택지가 없으면 표시하지 않는다
    parts = []
    for date, stamp in dates[:7]:
        label = _esc(_date_label(date))
        if date == active_date:
            parts.append(f'<span class="font-bold text-blue-600 dark:text-blue-400">{label}</span>')
        elif mode == "anchor":
            parts.append(f'<a class="hover:text-blue-600 dark:hover:text-blue-400" href="#d-{date}">{label}</a>')
        else:
            parts.append(f'<a class="hover:text-blue-600 dark:hover:text-blue-400" href="{asset_prefix}archive/{_esc(stamp)}/">{label}</a>')
    return (
        '<div class="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-sm text-neutral-500 dark:text-neutral-400 py-5">'
        + '<span class="text-neutral-300 dark:text-neutral-600 select-none"> · </span>'.join(parts)
        + "</div>"
    )


# ── 블라인드스팟 탭: 좌우 대비 전체 뷰 ──────────────────────────────────


def build_blindspot_page(
    briefing: dict, out_dir: Path, generated_at: str, updated: str, stamp: str,
    snapshots: list[tuple[str, dict]], now: datetime,
) -> None:
    """블라인드스팟 — 날짜별 누적 뷰. 시간이 지나도 사라지지 않고 모인다."""

    def _column(items: list[dict], title: str, color: str) -> str:
        if not items:
            return '<p class="text-sm text-neutral-400 py-6 text-center">해당 이슈 없음</p>'
        card_list = []
        for it in items:
            heads = "".join(
                f"<li>{_headline_anchor(h, _esc(h['title']))}</li>"
                for h in it.get("headlines", [])
            )
            anchor = (
                f'index.html#issue-{it["issue_index"]}'
                if it.get("issue_index") is not None
                else _esc(it.get("link", "#"))
            )
            card_list.append(f"""<article class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5 border-t-[3px]" style="border-top-color:{color}">
  <div class="flex items-center justify-between text-xs mb-1.5">
    <span class="font-semibold" style="color:{color}">{title}</span>
    <span class="text-neutral-400">{it["outlet_count"]}개 매체</span>
  </div>
  <h3 class="font-bold text-[15px] leading-snug mb-1.5"><a class="hover:text-blue-600 dark:hover:text-blue-400" href="{anchor}">{_esc(it["label"])}</a></h3>
  {f'<p class="text-sm text-neutral-600 dark:text-neutral-300 mb-2.5 line-clamp-3">{_esc(it["summary"])}</p>' if it.get("summary") else ""}
  {_render_bias_bar(it.get("bias"))}
  <ul class="flex flex-col gap-1.5 border-t border-stone-200 dark:border-neutral-700 pt-2.5">{heads}</ul>
</article>""")
        return f'<div class="flex flex-col gap-4">{"".join(card_list)}</div>'

    # 날짜별 블라인드스팟 수집: 오늘=현재 브리핑, 이전일=그 날짜 최신 스냅샷.
    # 같은 이슈(라벨)는 처음 등장한(최신) 날짜에만 남긴다.
    today = now.strftime("%Y-%m-%d")
    dates = _dates_of(snapshots)
    per_date: list[tuple[str, dict]] = []
    seen_labels: set[str] = set()
    snap_map = dict(snapshots)
    for date, latest_stamp in (dates or [(today, "")]):
        source = briefing if date == today else snap_map.get(latest_stamp, {})
        bs = source.get("blindspot") or {}
        day = {}
        for key in ("progressive_missing", "conservative_missing"):
            fresh = [it for it in (bs.get(key) or []) if it["label"] not in seen_labels]
            for it in fresh:
                seen_labels.add(it["label"])
            # 과거 날짜 항목의 index 앵커는 현재 index와 무관하므로 원문 링크로
            if date != today:
                fresh = [{**it, "issue_index": None} for it in fresh]
            day[key] = fresh
        if day.get("progressive_missing") or day.get("conservative_missing"):
            per_date.append((date, day))
    if not per_date:
        per_date = [(today, briefing.get("blindspot") or {})]

    sections = []
    for date, day in per_date:
        sections.append(f"""<section id="d-{date}">
  <h2 class="text-base font-bold mb-3 tabular-nums">{_esc(_date_label(date))}</h2>
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
    <div>
      <h3 class="text-sm font-bold mb-3" style="color:{FRAME_COLORS['progressive']}">🔵 진보 매체만 보도한 이슈</h3>
      {_column(day.get("conservative_missing") or [], "진보 매체만 보도", FRAME_COLORS["progressive"])}
    </div>
    <div>
      <h3 class="text-sm font-bold mb-3" style="color:{FRAME_COLORS['conservative']}">🔴 보수 매체만 보도한 이슈</h3>
      {_column(day.get("progressive_missing") or [], "보수 매체만 보도", FRAME_COLORS["conservative"])}
    </div>
  </div>
</section>""")

    main_html = f"""<div class="py-6 flex flex-col gap-6">
  <div>
    <h1 class="text-xl font-extrabold tracking-tight mb-1">블라인드스팟 — 특정 성향 매체만 보도한 이슈</h1>
    <p class="text-xs text-neutral-400 max-w-[80ch]">블라인드스팟은 한쪽 성향 매체만 보도한 이슈입니다. 지난 항목도 날짜별로 계속 쌓입니다. 성향 분류는 참고용 일반 분류입니다.</p>
  </div>
  {"".join(sections)}
  {_date_strip(dates, "", "anchor")}
</div>"""

    page = _page(
        title=f"블라인드스팟 — {config.SITE_TITLE}",
        canonical="blindspot.html",
        description="한쪽 성향 매체만 보도한 이슈 모음 — 놓치기 쉬운 관점을 날짜별로 보존합니다.",
        active="blindspot",
        generated_at=generated_at,
        feed="briefing.json",
        updated_label=updated,
        head_extra="",
        tabs_html="",
        after_header="",
        main_html=main_html,
        footer_notes=[DISCLAIMER],
        site_stamp=stamp,
        og_type="article",
    )
    (out_dir / "blindspot.html").write_text(page, encoding="utf-8")


# ── 프레임 체크 탭: 오늘의 프레임 갤러리 ────────────────────────────────


def build_frame_page(
    briefing: dict, out_dir: Path, generated_at: str, updated: str, stamp: str,
    snapshots: list[tuple[str, dict]], now: datetime,
) -> None:
    """프레임 체크 — 날짜별 갤러리 + 각 헤드라인의 최초 보도 일시 표기."""
    # 최초 보도 일시: 아카이브 전체에서 링크가 처음 목격된 (날짜, 송고시각)
    first_seen: dict[str, tuple[str, str]] = {}
    for snap_stamp, brief in sorted(snapshots, key=lambda s: s[0]):
        date = snap_stamp[:10]
        for issue in brief.get("issues", []):
            for h in issue.get("headlines", []):
                link = h.get("link")
                if link and link not in first_seen:
                    first_seen[link] = (date, h.get("time", ""))
    today = now.strftime("%Y-%m-%d")
    for issue in briefing.get("issues", []):
        for h in issue.get("headlines", []):
            link = h.get("link")
            if link and link not in first_seen:
                first_seen[link] = (today, h.get("time", ""))

    def _first_seen_label(h: dict) -> str:
        date, tm = first_seen.get(h.get("link", ""), (today, h.get("time", "")))
        return f"{date[5:7]}.{date[8:10]} {tm}".strip()

    def _framed_cards(issues: list[dict], link_to_index: bool) -> list[str]:
        cards = []
        for i, issue in issues:
            framing = issue.get("framing") or {}
            if not framing.get("note"):
                continue
            words = framing.get("words") or []
            chips = _frame_chips(words)
            # 표시 기준(최초 목격 일시)과 정렬 기준을 일치시킨다
            ordered_heads = sorted(
                issue.get("headlines", []),
                key=lambda h: first_seen.get(h.get("link", ""), (today, h.get("time", ""))),
            )[:8]
            side_words = [w for w in words if w.get("side") != "common"]  # 공통어는 칩에만
            heads = "".join(
                f'<li class="flex items-start gap-2">'
                f'<time class="w-[5.5rem] shrink-0 pt-px text-[10px] text-neutral-400 tabular-nums" title="최초 보도 일시">{_esc(_first_seen_label(h))}</time>'
                f'<div class="min-w-0 flex-1">{_headline_anchor(h, _highlight_title(h["title"], side_words))}</div></li>'
                for h in ordered_heads
            )
            color = CATEGORY_COLORS.get(issue["category"], "#2563eb")
            title_html = (
                f'<a class="hover:text-blue-600 dark:hover:text-blue-400" href="index.html#issue-{i}">{_esc(issue["label"])}</a>'
                if link_to_index
                else _esc(issue["label"])
            )
            cards.append(f"""<article class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5 border-t-[3px]" style="border-top-color:{color}">
  <div class="flex items-center justify-between text-xs mb-1.5">
    <span class="font-semibold rounded-full px-2.5 py-0.5" style="color:{color};background:{color}1f">{_esc(issue["category"])}</span>
    <span class="text-neutral-400">{issue.get("outlet_count", 0)}개 매체</span>
  </div>
  <h3 class="font-bold text-[15px] leading-snug mb-2">{title_html}</h3>
  <div class="rounded-lg border border-stone-200 dark:border-neutral-700 bg-stone-50 dark:bg-neutral-900/60 p-3 mb-3">
    <p class="text-xs text-neutral-600 dark:text-neutral-300">{_esc(framing["note"])}</p>
    {f'<p class="mt-1.5 text-xs text-neutral-500 dark:text-neutral-400">프레임 단어: {chips}</p>' if chips else ""}
  </div>
  <ul class="flex flex-col gap-1.5">{heads}</ul>
</article>""")
        return cards

    dates = _dates_of(snapshots)
    snap_map = dict(snapshots)
    sections = []
    seen_labels: set[str] = set()
    for date, latest_stamp in (dates or [(today, "")]):
        source = briefing if date == today else snap_map.get(latest_stamp, {})
        pool = []
        for i, issue in enumerate(source.get("issues", [])):
            if issue.get("framing", {}).get("note") and issue["label"] not in seen_labels:
                seen_labels.add(issue["label"])
                pool.append((i, issue))
        cards = _framed_cards(pool, link_to_index=(date == today))
        if not cards:
            continue
        sections.append(f"""<section id="d-{date}">
  <h2 class="text-base font-bold mb-3 tabular-nums">{_esc(_date_label(date))}</h2>
  <div class="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4 content-start">{"".join(cards)}</div>
</section>""")

    body = "".join(sections) or '<p class="text-sm text-neutral-400 py-16 text-center">프레임 분석 대상 이슈가 아직 없습니다.</p>'
    main_html = f"""<div class="py-6 flex flex-col gap-6">
  <div>
    <h1 class="text-xl font-extrabold tracking-tight mb-1">프레임 체크 — 매체별 어조·시각차 비교</h1>
    <p class="text-xs text-neutral-400 max-w-[80ch]">🔍 프레임 체크 — 같은 사건을 다룬 매체들이 제목에서 어떤 단어를 골랐는지 해부합니다. 각 헤드라인 앞의 일시는 아카이브에서 처음 목격된 최초 보도 시점입니다. 참고용 AI 분석.</p>
  </div>
  {body}
  {_date_strip(dates, "", "anchor")}
</div>"""

    page = _page(
        title=f"프레임 체크 — {config.SITE_TITLE}",
        canonical="frame.html",
        description="같은 사건, 다른 단어 — 매체별 제목의 단어 선택 차이를 알고리즘과 AI로 해부합니다.",
        active="frame",
        generated_at=generated_at,
        feed="briefing.json",
        updated_label=updated,
        head_extra="",
        tabs_html="",
        after_header="",
        main_html=main_html,
        footer_notes=[DISCLAIMER],
        site_stamp=stamp,
        og_type="article",
    )
    (out_dir / "frame.html").write_text(page, encoding="utf-8")


# ── 검색: 아카이브 전체 이슈 인덱스 + 클라이언트 검색 페이지 ────────────

SEARCH_SCRIPT = """
(function () {
  var box = document.getElementById("search-results");
  var input = document.getElementById("search-q");
  var dateSel = document.getElementById("search-date");
  var stat = document.getElementById("search-stat");
  var items = [];

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text) n.textContent = text;
    return n;
  }

  function render() {
    var q = (input.value || "").trim().toLowerCase();
    var d = dateSel.value;
    var toks = q ? q.split(/\s+/) : [];
    var res = items.filter(function (it) {
      if (d && it.d !== d) return false;
      if (!toks.length) return true;
      var hay = (it.t + " " + it.s).toLowerCase();
      return toks.every(function (t) { return hay.indexOf(t) >= 0; });
    }).slice(0, 100);
    stat.textContent = (toks.length || d) ? res.length + "건" : "검색어를 입력하거나 날짜를 선택하세요 (전체 " + items.length + "건 수록)";
    box.textContent = "";
    res.forEach(function (it) {
      var card = el("a", "block rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-4 hover:border-blue-400");
      card.href = it.u;
      var meta = el("div", "flex items-center gap-2 text-[11px] text-neutral-400 mb-1");
      meta.appendChild(el("span", "tabular-nums", it.d));
      if (it.c) meta.appendChild(el("span", "rounded-full bg-stone-100 dark:bg-neutral-700 px-2 py-0.5", it.c));
      meta.appendChild(el("span", "", it.n + "개 매체"));
      card.appendChild(meta);
      card.appendChild(el("div", "font-bold text-sm mb-1", it.t));
      if (it.s) card.appendChild(el("p", "text-xs text-neutral-500 dark:text-neutral-400 line-clamp-2", it.s));
      box.appendChild(card);
    });
    var qs = new URLSearchParams();
    if (input.value.trim()) qs.set("q", input.value.trim());
    if (d) qs.set("d", d);
    history.replaceState(null, "", qs.toString() ? "?" + qs.toString() : "search.html");
    updateTrend(toks, d);
    updateRelated(toks, res);
  }

  /* 날짜별 보도 추이 — 검색어 매칭 건수를 날짜별로 집계한 미니 막대 차트 */
  var trendBox = document.getElementById("search-trend");
  var trendBars = document.getElementById("trend-bars");
  function updateTrend(toks, activeDate) {
    if (!toks.length) { trendBox.classList.add("hidden"); return; }
    var byDate = {};
    items.forEach(function (it) {
      var hay = (it.t + " " + it.s).toLowerCase();
      if (toks.every(function (t) { return hay.indexOf(t) >= 0; })) byDate[it.d] = (byDate[it.d] || 0) + 1;
    });
    var dates = Object.keys(byDate).sort();
    if (dates.length < 2) { trendBox.classList.add("hidden"); return; }
    trendBox.classList.remove("hidden");
    var max = 0;
    dates.forEach(function (dt) { if (byDate[dt] > max) max = byDate[dt]; });
    trendBars.textContent = "";
    dates.forEach(function (dt) {
      var col = el("button", "flex-1 min-w-0 flex flex-col items-center gap-0.5 group");
      col.type = "button";
      col.title = dt + " · " + byDate[dt] + "건";
      var bar = el("div", "w-full max-w-[26px] rounded-t " + (dt === activeDate ? "bg-blue-600" : "bg-blue-300 dark:bg-blue-800 group-hover:bg-blue-500"));
      bar.style.height = Math.max(4, Math.round(byDate[dt] / max * 48)) + "px";
      col.appendChild(bar);
      col.appendChild(el("span", "text-[9px] text-neutral-400 tabular-nums", dt.slice(5)));
      col.addEventListener("click", function () { dateSel.value = (dateSel.value === dt ? "" : dt); render(); });
      trendBars.appendChild(col);
    });
  }

  /* 연관어 — 매칭 결과 제목에서 조사 어미를 걷어낸 뒤 빈도순 상위 8개 */
  var relBox = document.getElementById("search-rel");
  var REL_STOP = ["있다","했다","한다","위해","대한","관련","이번","오늘","기자","단독","속보","종합","논란","발표","진행","확인","이후","최근","때문","통해","그리고","하지만","전체","모든"];
  function stem(w) {
    var sfx = ["에서","으로","이라","라고","까지","부터","에게","은","는","이","가","을","를","에","의","로","와","과","도","만","들","등"];
    for (var i = 0; i < sfx.length; i++) {
      if (w.length > sfx[i].length + 1 && w.slice(-sfx[i].length) === sfx[i]) return w.slice(0, -sfx[i].length);
    }
    return w;
  }
  function updateRelated(toks, res) {
    while (relBox.children.length > 1) relBox.removeChild(relBox.lastChild);
    if (!toks.length || res.length < 2) { relBox.classList.add("hidden"); return; }
    var freq = {};
    res.forEach(function (it) {
      it.t.split(/[^0-9A-Za-z\uAC00-\uD7A3]+/).forEach(function (w) {
        w = stem(w);
        if (w.length < 2 || REL_STOP.indexOf(w) >= 0) return;
        var lw = w.toLowerCase();
        if (toks.some(function (t) { return lw.indexOf(t) >= 0 || t.indexOf(lw) >= 0; })) return;
        freq[w] = (freq[w] || 0) + 1;
      });
    });
    var top = Object.keys(freq).filter(function (w) { return freq[w] >= 2; })
      .sort(function (a, b) { return freq[b] - freq[a]; }).slice(0, 8);
    if (!top.length) { relBox.classList.add("hidden"); return; }
    relBox.classList.remove("hidden");
    relBox.classList.add("flex");
    top.forEach(function (w) {
      var chip = el("button", "rounded-full border border-stone-300 dark:border-neutral-600 px-2.5 py-1 hover:border-blue-500 hover:text-blue-600 dark:hover:text-blue-400", w + " " + freq[w]);
      chip.type = "button";
      chip.addEventListener("click", function () { input.value = input.value.trim() + " " + w; render(); });
      relBox.appendChild(chip);
    });
  }

  var debounceTimer;
  function debounced() { clearTimeout(debounceTimer); debounceTimer = setTimeout(render, 200); }

  fetch("search-index.json").then(function (r) { return r.json(); }).then(function (d) {
    items = d.items || [];
    var dates = [];
    items.forEach(function (it) { if (dates.indexOf(it.d) < 0) dates.push(it.d); });
    dates.sort().reverse().forEach(function (dt) {
      var opt = document.createElement("option");
      opt.value = dt; opt.textContent = dt;
      dateSel.appendChild(opt);
    });
    var p = new URLSearchParams(location.search);
    if (p.get("q")) input.value = p.get("q");
    if (p.get("d")) dateSel.value = p.get("d");
    render();
  }).catch(function () { stat.textContent = "검색 인덱스를 불러오지 못했습니다"; });

  input.addEventListener("input", debounced);
  dateSel.addEventListener("change", render);
})();
"""


def build_search_assets(
    snapshots: list[tuple[str, dict]], out_dir: Path, now: datetime
) -> None:
    """아카이브 전체 이슈를 검색 인덱스로 통합하고 검색 페이지를 렌더링한다.

    키 = (라벨, 날짜): 같은 라벨이라도 날짜가 다르면 별도 항목으로 유지해
    날짜 필터 검색에서 과거 사건이 소실되지 않는다. 같은 날짜 안에서만
    최신 스냅샷이 덮어쓴다.
    """
    entries: dict[tuple[str, str], dict] = {}
    for stamp, brief in sorted(snapshots, key=lambda s: s[0]):
        try:
            dt_utc = datetime.strptime(stamp, "%Y-%m-%d-%H%M").replace(tzinfo=timezone.utc)
            date = dt_utc.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        except Exception:
            date = stamp[:10]
        for i, issue in enumerate(brief.get("issues", [])):
            label = issue.get("label")
            if not label:
                continue
            entries[(label, date)] = {
                "d": date,
                "t": label,
                "s": (issue.get("summary") or "")[:120],
                "c": issue.get("category", ""),
                "n": issue.get("outlet_count", 0),
                "u": f"archive/{stamp}/#issue-{i}",
            }
    index = sorted(entries.values(), key=lambda e: e["d"], reverse=True)[:2000]
    (out_dir / "search-index.json").write_text(
        json.dumps({"generated_at": now.isoformat(), "items": index}, ensure_ascii=False),
        encoding="utf-8",
    )

    main_html = """<div class="max-w-3xl mx-auto py-6 flex flex-col gap-4">
  <h1 class="text-xl font-extrabold tracking-tight">뉴스 및 아카이브 검색</h1>
  <div class="flex gap-2">
    <input id="search-q" type="search" placeholder="단어로 검색 (제목·요약)" class="min-w-0 flex-1 rounded-xl border border-stone-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-4 py-2.5 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-blue-500">
    <select id="search-date" class="shrink-0 rounded-xl border border-stone-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-2.5 text-sm">
      <option value="">전체 날짜</option>
    </select>
  </div>
  <p id="search-stat" class="text-xs text-neutral-400"></p>
  <div id="search-trend" class="hidden rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-4">
    <p class="text-[11px] font-bold text-neutral-400 mb-2">날짜별 보도 추이 <span class="font-normal">— 막대를 누르면 해당 날짜로 필터</span></p>
    <div id="trend-bars" class="flex items-end gap-1 h-16"></div>
  </div>
  <div id="search-rel" class="hidden flex-wrap items-center gap-1.5 text-xs">
    <span class="text-neutral-400 mr-1">연관어</span>
  </div>
  <div id="search-results" class="flex flex-col gap-3"></div>
</div>"""

    stamp_footer = (
        f"ⓒ {_esc(config.SITE_TITLE)} ({_esc(config.SITE_DOMAIN)}) · "
        f"생성 시각 {now.strftime('%Y-%m-%d %H:%M KST')}"
    )
    page = _page(
        title=f"검색 — {config.SITE_TITLE}",
        canonical="search.html",
        description="시간별 아카이브에 쌓인 이슈를 단어·날짜로 검색하고 보도 추이와 연관어를 확인하세요.",
        active="search",
        generated_at=now.isoformat(),
        feed="",
        updated_label="아카이브 검색",
        head_extra="",
        tabs_html="",
        after_header="",
        main_html=main_html,
        footer_notes=["검색은 시간별 아카이브에 수록된 이슈(제목·AI 요약)를 대상으로 하며, 결과는 해당 시각의 브리핑 스냅샷으로 연결됩니다."],
        site_stamp=stamp_footer,
        extra_script=SEARCH_SCRIPT,
        og_type="website",
    )
    (out_dir / "search.html").write_text(page, encoding="utf-8")


# ── 정적 문서: 소개·약관·개인정보 + 뉴스레터 미리보기 ──────────────────


def _build_doc(out_dir: Path, filename: str, title: str, body: str,
               generated_at: str, updated: str, stamp: str,
               jsonld_type: str = "WebPage") -> None:
    main_html = f"""<div class="max-w-2xl mx-auto py-8 prose-doc">
  <h1 class="text-xl font-extrabold mb-6">{_esc(title)}</h1>
  {body}
</div>"""
    page = _page(
        title=f"{title} — {config.SITE_TITLE}", active="", generated_at=generated_at,
        canonical=filename, description=f"{title} — 고른뉴스 공식 문서",
        feed="", updated_label=updated, head_extra="", tabs_html="", after_header="",
        main_html=main_html, footer_notes=[], site_stamp=stamp,
        og_type="article", jsonld_type=jsonld_type,
    )
    (out_dir / filename).write_text(page, encoding="utf-8")


ABOUT_BODY = f"""
<p>고른뉴스는 <b>"골라 담아, 고르게 전합니다"</b>를 원칙으로 하는 AI 중립 뉴스 브리핑입니다. {len(config.PRESS_FEEDS)}개 언론사(일간지·주간지·월간지·지역지·인터넷 언론·외신 한국어판)의 공개 헤드라인을 매시간 수집해, 같은 사건을 다룬 기사들을 알고리즘으로 묶고 AI가 감정적·평가적 표현을 걷어낸 요약을 새로 씁니다.</p>
<h2>무엇이 다른가요</h2>
<ul>
<li><b>성향 스펙트럼</b> — 이슈별로 진보·중도·보수 매체의 보도 분포를 보여줍니다. 분류 근거가 약한 매체는 '중도'로 뭉개지 않고 '분류 없음'으로 정직하게 표기하며, 관측 데이터가 쌓이면 알고리즘이 추정합니다.</li>
<li><b>블라인드스팟</b> — 한쪽 성향 매체만 보도한 이슈를 따로 모읍니다.</li>
<li><b>프레임 체크</b> — 같은 사건의 제목들에서 매체별 단어 선택 차이를 알고리즘+AI로 해부합니다.</li>
<li><b>아카이브·검색</b> — 매시간 브리핑이 영구 보존되고, 단어·날짜로 검색할 수 있습니다.</li>
</ul>
<h2>저작권 원칙</h2>
<p>기사 본문을 수집·저장·복제하지 않습니다. 각 언론사가 공개한 헤드라인(제목)과 원문 링크만 표시하고, 요약문은 헤드라인 정보만으로 AI가 새로 작성합니다. 정책 브리핑은 공공누리 제1유형(korea.kr) 자료를 출처 표시와 함께 활용합니다.</p>
<h2>운영</h2>
<p>1인 운영 프로젝트이며 전 과정이 오픈소스로 공개되어 있습니다. 문의·제보는 상단의 '버그 제보' 버튼을 이용해 주세요.</p>
"""

TERMS_BODY = """
<p>본 약관은 고른뉴스(goreunnews.cloud, 이하 "서비스") 이용에 관한 조건을 규정합니다. 서비스를 이용하면 본 약관에 동의한 것으로 봅니다.</p>
<h2>1. 서비스의 성격</h2>
<p>서비스는 언론사가 공개한 헤드라인과 원문 링크를 큐레이션하고 AI가 작성한 요약·분석(성향 분포, 프레임 체크 등)을 제공하는 무료 서비스입니다. AI 분석은 참고용이며 정확성을 보증하지 않습니다. 기사의 저작권은 각 언론사에 있으며, 상세 내용은 반드시 원문에서 확인해야 합니다.</p>
<h2>2. 계정</h2>
<p>회원 기능(스크랩북 등)의 계정 정보는 이용자의 기기(브라우저 저장소)에만 저장되며 서버로 전송되지 않습니다. 기기·브라우저를 변경하면 계정과 스크랩이 이전되지 않습니다.</p>
<h2>3. 금지 행위</h2>
<p>서비스에 대한 자동화된 대량 요청, 서비스 저해 행위, 콘텐츠의 상업적 무단 재배포를 금지합니다. 공개 API(briefing.json 등)는 출처 표기를 조건으로 비상업적 이용을 허용합니다.</p>
<h2>4. 면책</h2>
<p>서비스는 "있는 그대로" 제공되며, 요약·분류의 오류, 외부 링크 콘텐츠, 서비스 중단으로 인한 손해에 대해 책임지지 않습니다.</p>
<h2>5. 약관의 변경</h2>
<p>약관이 변경되면 본 페이지에 게시하며, 게시 시점부터 효력이 발생합니다.</p>
<p class="text-neutral-400">시행일: 2026년 7월 22일</p>
"""

PRIVACY_BODY = """
<p>고른뉴스는 개인정보 최소 수집을 설계 원칙으로 합니다.</p>
<h2>1. 서버로 수집하는 개인정보: 없음</h2>
<p>회원가입(아이디·닉네임·비밀번호), 스크랩북, 키워드 알림, 글자 크기 설정은 모두 <b>이용자 기기의 브라우저 저장소(localStorage)에만 저장</b>되며 운영자 서버로 전송되지 않습니다. 비밀번호는 기기 안에서도 해시로만 보관됩니다.</p>
<h2>2. 뉴스레터 구독</h2>
<p>구독 신청 시 입력한 이메일 주소는 폼 전송 대행(FormSubmit)을 거쳐 운영자 이메일로 전달되며, 뉴스레터 발송 목적에만 사용됩니다. 수신 거부를 원하면 '버그 제보'로 요청하면 즉시 삭제합니다.</p>
<h2>3. 자동 수집 항목</h2>
<ul>
<li><b>방문 통계</b> — 익명 카운터(abacus)로 방문 횟수만 집계하며 개인을 식별하지 않습니다.</li>
<li><b>오류 수집</b> — '버그 제보'와 오류 모니터링(Sentry)은 제보 내용과 브라우저 환경 정보를 수집할 수 있습니다.</li>
<li><b>광고</b> — Google AdSense가 광고 제공을 위해 쿠키를 사용할 수 있습니다. <a class="text-blue-500" href="https://policies.google.com/technologies/ads?hl=ko" target="_blank" rel="noopener">Google 광고 정책</a>을 참고하세요.</li>
</ul>
<h2>4. 문의</h2>
<p>개인정보 관련 문의는 상단 '버그 제보' 버튼으로 접수해 주세요.</p>
<p class="text-neutral-400">시행일: 2026년 7월 22일</p>
"""


def build_docs(out_dir: Path, generated_at: str, updated: str, stamp: str) -> None:
    _build_doc(out_dir, "about.html", "고른뉴스란?", ABOUT_BODY, generated_at, updated, stamp, jsonld_type="AboutPage")
    _build_doc(out_dir, "terms.html", "이용약관", TERMS_BODY, generated_at, updated, stamp)
    _build_doc(out_dir, "privacy.html", "개인정보처리방침", PRIVACY_BODY, generated_at, updated, stamp, jsonld_type="WebPage")


def build_newsletter_page(briefing: dict, out_dir: Path, now: datetime) -> None:
    """뉴스레터 미리보기 — 이메일 호환 인라인 스타일 단일 컬럼 (발송 템플릿 겸용)."""
    issues = briefing.get("issues", [])
    top3 = issues[:3]
    bs = briefing.get("blindspot") or {}
    bs_pick = (bs.get("progressive_missing") or bs.get("conservative_missing") or [None])[0]
    frame_pick = next((i for i in issues if i.get("framing", {}).get("note")), None)
    policy = (briefing.get("policy") or [None])[0]

    def _sec(title, inner):
        return (f'<tr><td style="padding:18px 24px 6px;font-size:13px;font-weight:700;'
                f'color:#2563eb;letter-spacing:1px;">{title}</td></tr>{inner}')

    rows = ""
    for i, issue in enumerate(top3):
        rows += (f'<tr><td style="padding:8px 24px;">'
                 f'<div style="font-size:16px;font-weight:700;line-height:1.4;color:#1c1c1e;">{i+1}. {_esc(issue["label"])}</div>'
                 f'<div style="font-size:13px;line-height:1.7;color:#55555a;margin-top:4px;">{_esc(issue["summary"])}</div>'
                 f'<div style="font-size:12px;color:#8a8a90;margin-top:3px;">{issue.get("outlet_count",0)}개 매체 보도 · '
                 f'<a href="https://{config.SITE_DOMAIN}/#issue-{i}" style="color:#2563eb;">자세히 보기</a></div>'
                 f'</td></tr>')
    body_sections = _sec("오늘의 세 가지", rows)
    if bs_pick:
        body_sections += _sec("🕳️ 블라인드스팟", f'<tr><td style="padding:8px 24px;font-size:13px;color:#55555a;line-height:1.6;"><b style="color:#1c1c1e;">{_esc(bs_pick["label"])}</b> — 한쪽 성향 매체만 보도한 이슈입니다. <a href="https://{config.SITE_DOMAIN}/blindspot.html" style="color:#2563eb;">전체 보기</a></td></tr>')
    if frame_pick:
        body_sections += _sec("🔍 프레임 체크", f'<tr><td style="padding:8px 24px;font-size:13px;color:#55555a;line-height:1.6;">{_esc(frame_pick["framing"]["note"])} <a href="https://{config.SITE_DOMAIN}/frame.html" style="color:#2563eb;">더 보기</a></td></tr>')
    if policy:
        body_sections += _sec("🏛️ 오늘의 정책", f'<tr><td style="padding:8px 24px;font-size:13px;color:#55555a;line-height:1.6;"><b style="color:#1c1c1e;">{_esc(policy["title"])}</b> — {_esc(policy["summary"])}</td></tr>')

    html_doc = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>고른뉴스 레터</title></head>
<body style="margin:0;background:#f4f2ee;font-family:'Apple SD Gothic Neo','Noto Sans KR','Malgun Gothic',sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e6e2da;">
  <tr><td style="background:#2563eb;padding:22px 24px;">
    <div style="color:#fff;font-size:20px;font-weight:800;">고른뉴스</div>
    <div style="color:#cfe0ff;font-size:12px;margin-top:2px;">{now.strftime('%Y년 %m월 %d일')} 아침 브리핑 · 골라 담아, 고르게 전합니다</div>
  </td></tr>
  {body_sections}
  <tr><td style="padding:20px 24px;border-top:1px solid #eee;">
    <div style="font-size:11px;color:#9a9aa0;line-height:1.6;">이 메일은 goreunnews.cloud 뉴스레터 구독 신청자에게 발송됩니다. 요약은 헤드라인 정보만으로 AI가 작성했으며, 기사 저작권은 각 언론사에 있습니다.<br>
    <a href="https://{config.SITE_DOMAIN}/" style="color:#2563eb;">사이트에서 보기</a> · <a href="https://{config.SITE_DOMAIN}/privacy.html" style="color:#9a9aa0;">개인정보처리방침</a></div>
  </td></tr>
</table></td></tr></table></body></html>"""
    (out_dir / "newsletter.html").write_text(html_doc, encoding="utf-8")


# ── 아카이브: 시간별 스냅샷 영구 페이지 ─────────────────────────────────


def build_archive_pages(
    snapshots: list[tuple[str, dict]], out_dir: Path, now: datetime
) -> None:
    """/archive/<stamp>/ 정적 스냅샷 페이지 + 아카이브 목록 페이지.

    매시간 index를 덮어써도 과거 브리핑과 공유 링크(#issue-N)가 살아남는다.
    """
    prev_share = _SHARE_BASE
    set_share_base(None)  # 아카이브 페이지 자체가 영구 링크
    stamp_footer = (
        f"ⓒ {_esc(config.SITE_TITLE)} ({_esc(config.SITE_DOMAIN)}) · "
        f"생성 시각 {now.strftime('%Y-%m-%d %H:%M KST')}"
    )
    for stamp, briefing in snapshots:
        cards = "".join(
            _render_issue(issue, i) for i, issue in enumerate(briefing.get("issues", []))
        )
        main_html = f"""<div class="py-6">
  <h1 class="text-xl font-extrabold tracking-tight mb-2">{_esc(stamp)} 브리핑 스냅샷</h1>
  <p class="text-xs text-neutral-400 mb-4">{_esc(stamp)} (KST) 시점의 브리핑 스냅샷입니다.
    <a class="text-blue-600 dark:text-blue-400 hover:underline" href="../../">최신 브리핑 보기 →</a>
    <a class="ml-2 text-blue-600 dark:text-blue-400 hover:underline" href="../">전체 아카이브 →</a></p>
  <section class="grid sm:grid-cols-2 gap-4 content-start">{cards}</section>
</div>"""
        page = _page(
            title=f"{stamp} 브리핑 아카이브 — {config.SITE_TITLE}",
            canonical=f"archive/{stamp}/",
            description=f"{stamp} (KST) 시점의 브리핑 스냅샷 — 매시간 저장된 뉴스 이슈 영구 보존본.",
            active="news",
            generated_at=briefing.get("generated_at", ""),
            feed="",
            updated_label=f"{stamp} 스냅샷",
            head_extra="",
            tabs_html="",
            after_header="",
            main_html=main_html,
            footer_notes=[DISCLAIMER],
            site_stamp=stamp_footer,
            asset_prefix="../../",
            og_type="article",
        )
        page_dir = out_dir / "archive" / stamp
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "index.html").write_text(page, encoding="utf-8")

    # 날짜별 그룹으로 탐색성 개선
    by_date: dict[str, list[str]] = {}
    for s, _ in snapshots:
        by_date.setdefault(s[:10], []).append(s)
    sections = []
    for date in sorted(by_date, reverse=True):
        chips = "".join(
            f'<a class="rounded-lg border border-stone-200 dark:border-neutral-600 px-3 py-1.5 text-sm tabular-nums hover:border-blue-500 hover:text-blue-600 dark:hover:text-blue-400" href="{_esc(s)}/">{_esc(s[11:])}시</a>'
            for s in sorted(by_date[date], reverse=True)
        )
        sections.append(
            f'<section><h3 class="text-sm font-bold mb-2 tabular-nums">{_esc(date)}</h3>'
            f'<div class="flex flex-wrap gap-2">{chips}</div></section>'
        )
    index_html = f"""<div class="max-w-2xl mx-auto py-6 flex flex-col gap-6">
  <div class="flex items-center justify-between">
    <h1 class="text-lg font-extrabold">시간별 브리핑 아카이브</h1>
    <a href="../search.html" class="text-xs text-blue-600 dark:text-blue-400 hover:underline">단어로 검색 →</a>
  </div>
  {"".join(sections)}
</div>"""
    page = _page(
        title=f"브리핑 아카이브 — {config.SITE_TITLE}",
        canonical="archive/",
        description="매시간 저장된 브리핑 스냅샷 아카이브 — 지난 뉴스를 시각 단위로 다시 봅니다.",
        active="news",
        generated_at="",
        feed="",
        updated_label="아카이브",
        head_extra="",
        tabs_html="",
        after_header="",
        main_html=index_html,
        footer_notes=[],
        site_stamp=stamp_footer,
        asset_prefix="../",
    )
    (out_dir / "archive").mkdir(parents=True, exist_ok=True)
    (out_dir / "archive" / "index.html").write_text(page, encoding="utf-8")
    set_share_base(prev_share)


# ── SEO: sitemap.xml / rss.xml / robots.txt 자동 생성 ───────────────────


def build_seo_files(
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
        '<?xml version="1.0" encoding="UTF-8"?>\n'
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
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        f"<title>{html.escape(config.SITE_TITLE)}</title>"
        f"<link>{base}/</link>"
        f"<description>{html.escape(config.SITE_TAGLINE)} — 여러 언론사의 헤드라인을 교차 확인한 중립 뉴스 브리핑</description>"
        "<language>ko</language>"
        f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>"
        f"{''.join(items)}</channel></rss>",
        encoding="utf-8",
    )

    (out_dir / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n", encoding="utf-8"
    )


# ── 커뮤니티 페이지 ─────────────────────────────────────────────────────

# 커뮤니티 브랜드 컬러 뱃지
SOURCE_BADGE = {
    "루리웹": "bg-blue-600 text-white",
    "더쿠": "bg-gray-700 text-white",
    "이토랜드": "bg-orange-500 text-white",
}

_TREND_STOPWORDS = {
    # 기능어·시간·정도
    "오늘", "어제", "내일", "요즘", "이번", "지난", "최근", "현재", "결국", "그냥",
    "진짜", "정도", "때문", "가장", "제일", "모든", "이제", "다시", "하는", "있는",
    "없는", "있고", "있다", "된다", "한다", "논란", "이유", "상황", "결과", "수준",
    # 커뮤니티 상투어
    "근황", "주년", "레전드", "후기", "단독", "속보", "충격", "화제", "반응", "정리",
    "모음", "공개", "등장", "사람", "사람들", "대박", "실화", "여자", "남자", "국내",
    "관련", "발표", "기념", "네티즌", "누리꾼", "시작", "예정", "진행", "확인", "완료", "가능", "무슨", "어떤", "얼마",
}

COMMUNITY_SIDEBAR_SCRIPT = """
(function () {
  var box = document.getElementById("comm-scraps");
  if (!box) return;
  var posts = loadScraps().filter(function (s) { return s.type === "post"; }).slice(0, 5);
  if (!posts.length) {
    box.innerHTML = '<p class="text-xs text-neutral-400">게시글의 ☆를 눌러 저장해 보세요.</p>';
    return;
  }
  posts.forEach(function (s) {
    var a = document.createElement("a");
    a.className = "block text-[13px] py-1.5 border-t border-stone-200 dark:border-neutral-700 first:border-0 hover:text-blue-600 dark:hover:text-blue-400 truncate";
    a.href = s.link; a.target = "_blank"; a.rel = "noopener nofollow";
    a.textContent = s.title;
    box.appendChild(a);
  });
})();
"""


def _fmt_count(v: int) -> str:
    return f"{v / 10000:.1f}만" if v >= 10000 else f"{v:,}"


def _metric_line(p: dict) -> str:
    """조회·추천·댓글 지표 라인 (있는 것만)."""
    parts = []
    if p.get("views"):
        parts.append(f"👁 {_fmt_count(p['views'])}")
    if p.get("recommends"):
        parts.append(f"👍 {_fmt_count(p['recommends'])}")
    if p.get("comments"):
        parts.append(f"💬 {_fmt_count(p['comments'])}")
    if not parts:
        return ""
    return f'<div class="mt-1.5 text-[11px] text-neutral-400 tabular-nums">{" · ".join(parts)}</div>'


def _trend_keywords(posts: list[dict], top_n: int = 8) -> list[str]:
    """트렌드 키워드 산출 알고리즘.

    1) 토큰화 + 어근 정규화(cluster.stem_token) — '있고'→'있', 조사 제거
    2) 불용어 사전 — 기능어·감탄사·커뮤니티 상투어('이유','근황','주년' 등) 배제,
       한 글자 어근·숫자 배제
    3) 교차 소스 검증 — 서로 다른 커뮤니티 2곳 이상에서 등장하면 가중(+2/소스)
    4) 점수 = 빈도 + 교차 소스 보너스, 빈도 2 미만은 탈락
    """
    import re as _re
    from collections import Counter, defaultdict

    from cluster import stem_token

    stop = _TREND_STOPWORDS
    freq: Counter[str] = Counter()
    sources: defaultdict[str, set] = defaultdict(set)
    for post in posts:
        seen_in_title: set[str] = set()
        for raw in _re.findall(r"[가-힣]{2,}", post["title"]):
            token = stem_token(raw)
            if len(token) < 2 or token in stop or token in SOURCE_BADGE:
                continue
            if token in seen_in_title:
                continue
            seen_in_title.add(token)
            freq[token] += 1
            sources[token].add(post.get("source", ""))
    scored = [
        (freq[tk] + 2 * (len(sources[tk]) - 1), tk)
        for tk in freq
        if freq[tk] >= 2
    ]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [tk for _, tk in scored[:top_n]]


def build_community_page(
    posts: list[dict], out_dir: Path, generated_at: str,
    now: datetime, updated: str, stamp: str,
) -> Path:
    # 베스트 오브 베스트: 각 커뮤니티 1위 글 + HOT 글 (목록보다 먼저 계산)
    seen_links: set[str] = set()
    best_posts: list[dict] = []
    first_of_source: set[str] = set()
    for p in posts:
        is_first = p["source"] not in first_of_source
        if is_first:
            first_of_source.add(p["source"])
        if (is_first or p.get("hot")) and p["link"] not in seen_links:
            seen_links.add(p["link"])
            best_posts.append(p)
    best_links = {p["link"] for p in best_posts[:6]}

    cards = []
    listed = [p for p in posts if p["link"] not in best_links]
    for i, p in enumerate(listed):
        hot = p.get("hot")
        badge_cls = SOURCE_BADGE.get(p["source"], "bg-stone-500 text-white")
        hot_badge = (
            '<span class="text-[10px] font-bold text-red-500 shrink-0">🔥 HOT</span>'
            if hot
            else ""
        )
        news_badge = (
            '<span class="text-[10px] font-bold text-sky-600 dark:text-sky-400 shrink-0">📰 뉴스</span>'
            if p.get("news")
            else ""
        )
        # HOT 초신성: 연한 붉은 배경 + 붉은 링으로 확실히 대비
        card_extra = (
            " bg-red-50 dark:bg-red-500/10 ring-1 ring-red-200 dark:ring-red-500/30"
            if hot
            else " bg-white dark:bg-neutral-800"
        )
        scrap_payload = _esc(json.dumps(
            {
                "id": f"post:{p['link']}",
                "type": "post",
                "title": p["title"],
                "source": p["source"],
                "link": p["link"],
            },
            ensure_ascii=False,
        ))
        thumb_html = ""
        if p.get("thumb"):
            # 원본 서버 핫링크 소형 썸네일 — 로드 실패 시 자동 숨김
            thumb_html = (
                f'<img src="{_esc(p["thumb"])}" alt="" loading="lazy" referrerpolicy="no-referrer" '
                'class="w-16 h-16 object-cover rounded-lg shrink-0 bg-stone-100 dark:bg-neutral-700" '
                "onerror=\"this.style.display='none'\">"
            )
        cards.append(f"""<article data-src="{_esc(p["source"])}" class="rounded-lg border border-stone-200 dark:border-neutral-700 p-4 transition-all duration-200 hover:-translate-y-1 hover:shadow-md{card_extra}">
  <div class="flex items-center gap-2 mb-1.5">
    <span class="text-[11px] rounded-full px-2 py-0.5 font-medium {badge_cls} shrink-0">{_esc(p["source"])}</span>
    {hot_badge}
    {news_badge}
    <span class="ml-auto text-xs font-bold text-neutral-300 dark:text-neutral-600 tabular-nums">#{i + 1}</span>
    <button type="button" class="scrap-btn text-base leading-none text-neutral-300 dark:text-neutral-600 hover:text-amber-500 shrink-0" aria-label="스크랩" data-scrap="{scrap_payload}">☆</button>
  </div>
  <a class="flex items-start gap-3 hover:text-blue-600 dark:hover:text-blue-400" href="{_esc(p["link"])}" target="_blank" rel="noopener nofollow">
    <span class="flex-1 min-w-0 text-sm leading-snug line-clamp-2">{_esc(p["title"])}</span>
    {thumb_html}
  </a>
  {_metric_line(p)}
</article>""")

    trend_chips = "".join(
        f'<span class="text-xs rounded-full border border-stone-200 dark:border-neutral-600 px-2.5 py-1 text-neutral-600 dark:text-neutral-300">#{_esc(w)}</span>'
        for w in _trend_keywords(posts)
    ) or '<span class="text-xs text-neutral-400">키워드 집계 중</span>'

    marker_news = [p for p in posts if p.get("news") and not p.get("board_news")]
    board_news = [p for p in posts if p.get("news") and p.get("board_news")]
    news_posts = (marker_news + board_news)[:5]
    news_rows = "".join(
        f'<a class="block text-[13px] py-1.5 border-t border-stone-200 dark:border-neutral-700 first:border-0 hover:text-blue-600 dark:hover:text-blue-400 truncate" '
        f'href="{_esc(p["link"])}" target="_blank" rel="noopener nofollow">{_esc(p["title"])}</a>'
        for p in news_posts
    )
    news_panel = (
        f"""<section class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5">
    <h2 class="text-sm font-bold mb-0.5">📰 커뮤니티가 주목한 뉴스</h2>
    <p class="text-[11px] text-neutral-400 mb-2">해외토픽·게임·시사성 게시물</p>
    {news_rows}
  </section>"""
        if news_posts
        else ""
    )
    sidebar = f"""<aside class="flex flex-col gap-5 self-start lg:sticky lg:top-20">
  {news_panel}
  <section class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5">
    <h2 class="text-sm font-bold mb-2">트렌드 키워드</h2>
    <div class="flex flex-wrap gap-1.5">{trend_chips}</div>
  </section>
  <section class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5">
    <h2 class="text-sm font-bold mb-2">스크랩한 커뮤니티 글</h2>
    <div id="comm-scraps"></div>
    <a href="scrapbook.html" class="block mt-2.5 text-xs text-blue-600 dark:text-blue-400 hover:underline">스크랩북 전체 보기 →</a>
  </section>
  {ad_slot("community-1")}
</aside>"""


    def _best_card(p: dict) -> str:
        thumb_html = ""
        if p.get("thumb"):
            thumb_html = (
                f'<img src="{_esc(p["thumb"])}" alt="" loading="lazy" referrerpolicy="no-referrer" '
                'class="w-12 h-12 object-cover rounded-lg shrink-0 bg-stone-100 dark:bg-neutral-700" '
                "onerror=\"this.style.display='none'\">"
            )
        return f"""<a href="{_esc(p["link"])}" target="_blank" rel="noopener nofollow" class="block rounded-lg border border-amber-200 dark:border-amber-500/30 bg-amber-50/70 dark:bg-amber-500/10 p-3.5 transition-all duration-200 hover:-translate-y-1 hover:shadow-md">
  <div class="flex items-center gap-1.5 mb-1">
    <span class="text-[10px] font-bold text-amber-600 dark:text-amber-400">👑 BEST</span>
    <span class="text-[10px] rounded-full px-1.5 py-0.5 {SOURCE_BADGE.get(p["source"], "bg-stone-500 text-white")}">{_esc(p["source"])}</span>
  </div>
  <span class="flex items-start gap-2.5">
    <span class="flex-1 min-w-0 text-[13px] leading-snug line-clamp-2">{_esc(p["title"])}</span>
    {thumb_html}
  </span>
</a>"""

    best_cards = "".join(_best_card(p) for p in best_posts[:6])
    best_section = (
        f'<section class="mb-1" aria-label="베스트 오브 베스트">'
        f'<h2 class="text-sm font-bold mb-2.5">오늘의 베스트</h2>'
        f'<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">{best_cards}</div></section>'
        if best_posts
        else ""
    )

    main_html = f"""<div class="grid grid-cols-1 lg:grid-cols-[7fr_3fr] gap-7 py-6">
  <div class="flex flex-col gap-5">
    <h1 class="text-xl font-extrabold tracking-tight">커뮤니티 트렌드 — 실시간 핫게시물</h1>
    {best_section}
    <section class="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4 content-start" aria-label="커뮤니티 인기글">{"".join(cards)}</section>
  </div>
  {sidebar}
</div>"""

    page = _page(
        title=f"커뮤니티 인기글 — {config.SITE_TITLE}",
        canonical="community.html",
        description="주요 커뮤니티에서 화제가 된 글과 뉴스를 참여도 기준으로 모아 보여줍니다.",
        active="community",
        generated_at=generated_at,
        feed="community.json",
        updated_label=updated,
        head_extra="",
        tabs_html="",
        after_header="",
        main_html=main_html,
        footer_notes=[COMMUNITY_NOTICE],
        site_stamp=stamp,
        extra_script=COMMUNITY_SIDEBAR_SCRIPT,
        og_type="website",
    )
    out_path = out_dir / "community.html"
    out_path.write_text(page, encoding="utf-8")
    return out_path


# ── 스크랩북 페이지 (클라이언트 렌더링) ─────────────────────────────────


def build_scrapbook_page(
    out_dir: Path, generated_at: str, now: datetime, updated: str, stamp: str
) -> Path:
    main_html = """<div class="max-w-3xl mx-auto py-6 flex flex-col gap-6">
  <h1 class="text-xl font-extrabold tracking-tight">스크랩북</h1>
  <div id="scrap-login-gate" hidden class="text-center py-16">
    <p class="text-sm text-neutral-500 dark:text-neutral-400 mb-4">스크랩북은 로그인 후 이용할 수 있습니다.<br><span class="text-xs text-neutral-400">닉네임만 입력하면 되고, 정보는 이 기기에만 저장됩니다.</span></p>
    <button type="button" id="scrap-gate-login" class="rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-5 py-2">로그인</button>
  </div>
  <section id="bias-dash" hidden class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5">
    <h2 class="text-sm font-bold mb-1">내가 주로 읽는 뉴스의 성향 비율</h2>
    <p class="text-[11px] text-neutral-400 mb-4">스크랩한 뉴스에 참여한 매체들의 성향 분포입니다 (참고용 일반 분류)</p>
    <div class="flex items-center gap-7">
      <div id="bias-donut" class="w-28 h-28 rounded-full shrink-0 flex items-center justify-center">
        <div class="w-[4.5rem] h-[4.5rem] rounded-full bg-white dark:bg-neutral-800 flex flex-col items-center justify-center">
          <span id="bias-total" class="text-lg font-bold tabular-nums">0</span>
          <span class="text-[10px] text-neutral-400">매체 집계</span>
        </div>
      </div>
      <ul id="bias-legend" class="flex-1 flex flex-col gap-2 text-sm"></ul>
    </div>
  </section>
  <div id="scrap-empty" hidden class="text-center text-sm text-neutral-400 py-16">아직 스크랩한 글이 없습니다.<br>뉴스 카드나 커뮤니티 글의 ☆를 눌러 저장해 보세요.</div>
  <section id="scrap-news-sec" hidden>
    <h2 class="text-sm font-bold mb-3">뉴스</h2>
    <div id="scrap-news" class="grid sm:grid-cols-2 gap-4"></div>
  </section>
  <section id="scrap-posts-sec" hidden>
    <h2 class="text-sm font-bold mb-3">커뮤니티</h2>
    <ol id="scrap-posts" class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 divide-y divide-stone-200 dark:divide-neutral-700 overflow-hidden"></ol>
  </section>
</div>"""

    page = _page(
        title=f"스크랩북 — {config.SITE_TITLE}",
        canonical="scrapbook.html",
        description="저장한 뉴스·커뮤니티 글을 모아 보는 개인 스크랩북.",
        active="scrapbook",
        generated_at=generated_at,
        feed="",
        updated_label=updated,
        head_extra="",
        tabs_html="",
        after_header="",
        main_html=main_html,
        footer_notes=["스크랩한 글은 이 브라우저의 로컬 저장소(localStorage)에만 저장됩니다."],
        site_stamp=stamp,
        extra_script=SCRAPBOOK_SCRIPT.replace(
            "__OUTLET_BIAS__", json.dumps(config.OUTLET_BIAS, ensure_ascii=False)
        ),
        og_type="website",
        noindex=True,  # 개인화 페이지 — 검색 색인에서 제외
    )
    out_path = out_dir / "scrapbook.html"
    out_path.write_text(page, encoding="utf-8")
    return out_path
