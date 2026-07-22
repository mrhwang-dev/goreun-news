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

CUSTOM_STYLE = """
.no-scrollbar::-webkit-scrollbar { display: none; }
.no-scrollbar { scrollbar-width: none; }
.tab[aria-selected="true"] { @apply bg-neutral-900 text-stone-50 border-neutral-900 dark:bg-neutral-100 dark:text-neutral-900 dark:border-neutral-100; }
.tab[aria-selected="true"] .badge { @apply bg-white/20 dark:bg-black/10; }
details[open] .tri { transform: rotate(180deg); }
.tri { transition: transform 0.15s; }
/* 티커: 숨은 항목이 클릭을 가로채지 않도록 pointer-events/visibility 제어 */
.ticker-item { opacity: 0; visibility: hidden; pointer-events: none; transition: opacity 0.5s, visibility 0.5s; }
.ticker-item.show { opacity: 1; visibility: visible; pointer-events: auto; }
/* 글자 크기 단계 (가/가+) — 기본은 1단계 */
:root[data-fs="0"] .fs-t { font-size: 14px; }
:root[data-fs="0"] .fs-p { font-size: 12.5px; }
:root[data-fs="2"] .fs-t { font-size: 17px; }
:root[data-fs="2"] .fs-p { font-size: 15.5px; }
#site-header { transition: transform 0.3s; }
/* AI 요약 3줄 클램프 + 하단 페이드, 클릭 시 펼침 */
.summary-wrap p { @apply line-clamp-3; }
.summary-wrap.open p { -webkit-line-clamp: unset; }
.summary-wrap .fade { @apply absolute bottom-0 inset-x-0 h-5 bg-gradient-to-t from-white dark:from-neutral-800 to-transparent pointer-events-none transition-opacity; }
.summary-wrap.open .fade, .summary-wrap.no-clamp .fade { opacity: 0; }
.summary-wrap.no-clamp { cursor: default; }
/* 무한 스크롤: 아직 공개되지 않은 카드 */
.not-revealed { display: none; }
/* 히어로 카드: 현재 보기(전체/분야)의 1위 이슈를 크게 — JS가 .is-hero 부여 */
.is-hero { grid-column: 1 / -1; border-top-width: 4px; border-radius: 1rem; padding: 1.75rem; }
.is-hero h3 { font-size: 1.7rem; line-height: 1.25; font-weight: 800; letter-spacing: -0.02em; }
@media (min-width: 1024px) { .is-hero h3 { font-size: 2rem; } }
.is-hero .summary-wrap { cursor: default; }
.is-hero .summary-wrap p { -webkit-line-clamp: unset; font-size: 0.95rem; line-height: 1.7; max-width: 62ch; }
.is-hero .summary-wrap .fade { opacity: 0; }
.is-hero .bias-inline { display: block; max-width: 26rem; }
.is-hero .hero-badge { display: inline-flex; }
/* 티커 → 카드 도착 하이라이트 (2초간 은은한 블루 링) */
.flash-ring { animation: flashRing 1s ease-in-out 2; }
@keyframes flashRing {
  0%, 100% { box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.5); }
  50% { box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.15); }
}
@media (prefers-reduced-motion: reduce) {
  .ticker-item, .tri, #site-header, .summary-wrap .fade { transition: none; }
  .flash-ring { animation: none; box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.5); }
}
"""

def ad_slot(unit_id: str) -> str:
    """광고 슬롯 모듈 — CLS 방지를 위해 min-h 고정 + 로드 전 스켈레톤 배경.

    승인 후 이 div 내부에 AdSense/AdFit 코드를 삽입한다 (unit_id로 슬롯 구분).
    """
    return f"""<div class="ad-unit relative overflow-hidden rounded-xl border border-stone-200 dark:border-neutral-700 min-h-[250px] flex items-center justify-center" data-ad-unit="{unit_id}">
  <div class="absolute inset-0 animate-pulse bg-gradient-to-br from-stone-100 to-stone-200 dark:from-neutral-800 dark:to-neutral-700" aria-hidden="true"></div>
  <span class="relative text-neutral-400 text-xs">광고 영역 ({unit_id}) — AdSense/카카오 AdFit 코드 삽입</span>
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

BASE_SCRIPT = """
// ── 탭 필터 (뉴스: data-cat / 커뮤니티: data-src) ──
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

// ── 속보 티커: 5초 간격 페이드 전환 (모션 최소화 설정 시 첫 항목 고정) ──
var tickerItems = document.querySelectorAll(".ticker-item");
if (tickerItems.length) {
  var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  tickerItems[0].classList.add("show");
  if (!reducedMotion && tickerItems.length > 1) {
    var tickerIdx = 0;
    setInterval(function () {
      tickerItems[tickerIdx].classList.remove("show");
      tickerIdx = (tickerIdx + 1) % tickerItems.length;
      tickerItems[tickerIdx].classList.add("show");
    }, 5000);
  }
}

// ── 오프라인 페일세이프: 서비스워커 캐시 + 경고 배너 ──
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(function () {});
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

// ── 속보 티커 클릭 → 해당 이슈 카드로 스크롤 + 2초 링 하이라이트 ──
document.querySelectorAll(".ticker-jump").forEach(function (a) {
  a.addEventListener("click", function (e) {
    e.preventDefault();
    var card = document.getElementById(a.dataset.target);
    if (!card) return;
    if (card.hidden) {
      var allTab = document.querySelector('.tab[data-value="전체"]');
      if (allTab) allTab.click();
    }
    var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    card.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
    card.classList.remove("flash-ring");
    void card.offsetWidth; // 애니메이션 재시작
    card.classList.add("flash-ring");
    setTimeout(function () { card.classList.remove("flash-ring"); }, 2100);
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
document.querySelectorAll(".scrap-btn").forEach(function (btn) {
  paintStar(btn, isScrapped(JSON.parse(btn.dataset.scrap).id));
  btn.addEventListener("click", function (e) {
    e.preventDefault();
    var on = toggleScrap(JSON.parse(btn.dataset.scrap));
    paintStar(btn, on);
    toast(on ? "스크랩북에 저장했습니다 ★" : "스크랩을 해제했습니다");
  });
});

// ── 공유 (모바일: OS 공유 시트 / 데스크톱: 클립보드 복사 + 토스트) ──
document.querySelectorAll(".share-btn").forEach(function (btn) {
  btn.addEventListener("click", function () {
    var url = location.origin + location.pathname +
      (btn.dataset.anchor ? "#" + btn.dataset.anchor : "");
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

// ── 글자 크기 조절 (가/가+, localStorage 유지) ──
var FS_KEY = "goreun_fs";
function applyFs(level) {
  level = Math.max(0, Math.min(2, level));
  document.documentElement.dataset.fs = String(level);
  localStorage.setItem(FS_KEY, String(level));
  return level;
}
var fsLevel = applyFs(parseInt(localStorage.getItem(FS_KEY) || "1", 10));
var fsDown = document.getElementById("fs-down");
var fsUp = document.getElementById("fs-up");
if (fsDown) fsDown.addEventListener("click", function () { fsLevel = applyFs(fsLevel - 1); });
if (fsUp) fsUp.addEventListener("click", function () { fsLevel = applyFs(fsLevel + 1); });

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
    var s = document.createElement("script");
    s.src = H2C_URL;
    s.onload = resolve;
    s.onerror = reject;
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
  bt2.textContent = "고른뉴스.메인.한국 · AI 중립 뉴스 브리핑";
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

SCRAPBOOK_SCRIPT = """
(function () {
  var listEl = document.getElementById("scrap-news");
  var postsEl = document.getElementById("scrap-posts");
  var OUTLET_BIAS = __OUTLET_BIAS__;
  var BIAS_META = [
    ["progressive", "진보", "#3b82f6"],
    ["moderate", "중도", "#9ca3af"],
    ["conservative", "보수", "#ef4444"],
  ];

  // 스크랩한 뉴스의 매체 성향 비율 미니 대시보드 (conic-gradient 도넛)
  function renderBiasDash(scraps) {
    var sec = document.getElementById("bias-dash");
    if (!sec) return;
    var counts = { progressive: 0, moderate: 0, conservative: 0 };
    scraps.filter(function (s) { return s.type === "issue"; }).forEach(function (s) {
      (s.headlines || []).forEach(function (h) {
        counts[OUTLET_BIAS[h.outlet] || "moderate"]++;
      });
    });
    var total = counts.progressive + counts.moderate + counts.conservative;
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

  function render() {
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

  render();
})();
"""

SERVICE_WORKER = """
var CACHE = "goreun-v1";
self.addEventListener("install", function (e) { self.skipWaiting(); });
self.addEventListener("activate", function (e) { e.waitUntil(clients.claim()); });
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
    main_html: str, footer_notes: list[str], site_stamp: str, extra_script: str = "",
    banner_html: str = "",
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
    return f"""<!doctype html>
<html lang="ko" data-generated-at="{_esc(generated_at)}" data-feed="{feed}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<meta name="description" content="여러 언론사의 헤드라인을 교차 확인해 매시간 정리하는 중립 뉴스 브리핑">
{head_extra}
<link rel="icon" href="{FAVICON_SVG}">
<link rel="manifest" href="site.webmanifest">
<link rel="apple-touch-icon" href="icon-512.png">
<meta name="theme-color" content="#2563eb">
<script src="https://cdn.tailwindcss.com"></script>
<script>tailwind.config = {{ darkMode: "media" }}</script>
<style type="text/tailwindcss">{CUSTOM_STYLE}</style>
<!-- AdSense 승인 후 사이트 확인/광고 스크립트를 여기에 붙여넣으세요 -->
</head>
<body class="bg-stone-50 dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100 antialiased" style='font-family:"Pretendard Variable",Pretendard,-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR","Malgun Gothic",sans-serif'>
<div id="offline-banner" hidden class="bg-amber-100 dark:bg-amber-500/15 text-amber-800 dark:text-amber-300 text-xs text-center px-4 py-2">오프라인 상태이거나 최신 뉴스를 불러오지 못했습니다. 이전 뉴스를 보여줍니다.</div>
<header id="site-header" class="sticky top-0 z-20 border-b border-stone-200 dark:border-neutral-700 bg-stone-50/90 dark:bg-neutral-900/90 backdrop-blur">
  <div class="max-w-6xl mx-auto px-5">
    <div class="flex items-center gap-2.5 py-3 flex-wrap">
      <a href="index.html" class="flex items-center gap-2.5 shrink-0" aria-label="고른뉴스 홈">
        {LOGO_MARK}
        <span class="text-xl font-extrabold tracking-tight">{_esc(config.SITE_TITLE)}</span>
      </a>
      <span class="hidden md:inline text-xs text-neutral-500 dark:text-neutral-400">{_esc(config.SITE_TAGLINE)}</span>
      <nav class="flex gap-1 ml-2" aria-label="페이지">{nav}</nav>
      <span class="ml-auto flex items-center gap-1.5 text-xs text-neutral-500 dark:text-neutral-400">
        <span class="relative flex h-2 w-2" aria-hidden="true">
          <span class="animate-pulse absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
          <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
        </span>
        <span id="updated-label" class="tabular-nums">{_esc(updated_label)}</span>
      </span>
      <span class="flex gap-1">
        <button type="button" id="fs-down" title="글자 작게" class="rounded-full border border-stone-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-2.5 py-1 text-xs text-neutral-500 dark:text-neutral-400 hover:text-blue-600 hover:border-blue-500">가</button>
        <button type="button" id="fs-up" title="글자 크게" class="rounded-full border border-stone-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-2.5 py-1 text-sm text-neutral-500 dark:text-neutral-400 hover:text-blue-600 hover:border-blue-500">가+</button>
        <button type="button" id="bug-report" class="rounded-full border border-stone-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-1 text-xs text-neutral-500 dark:text-neutral-400 hover:text-blue-600 hover:border-blue-500 dark:hover:text-blue-400">버그 제보</button>
      </span>
    </div>
    {tabs_nav}
  </div>
</header>
{after_header}
<main class="max-w-6xl mx-auto px-5">{main_html}</main>
<footer class="border-t border-stone-200 dark:border-neutral-700 mt-4 py-5 pb-12 text-xs text-neutral-500 dark:text-neutral-400">
  <div class="max-w-6xl mx-auto px-5">
    {notes}
    <p class="flex flex-wrap gap-x-3 gap-y-1"><span>{site_stamp}</span><span id="visit-count" class="tabular-nums"></span></p>
  </div>
</footer>
<button type="button" id="to-top" hidden aria-label="맨 위로" class="fixed bottom-6 right-5 z-40 w-11 h-11 rounded-full bg-neutral-900 text-stone-50 dark:bg-neutral-100 dark:text-neutral-900 shadow-lg text-lg">↑</button>
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
    parts = []
    for b in breaking:
        idx = b.get("issue_index")
        if idx is not None:
            # 대응하는 이슈 카드가 있으면 카드로 스크롤 (JS에서 부드러운 이동 + 하이라이트)
            attrs = f'href="#issue-{idx}" data-target="issue-{idx}" class="ticker-item ticker-jump absolute inset-0 flex items-center gap-2 truncate text-sm"'
        else:
            attrs = f'href="{_esc(b["link"])}" target="_blank" rel="noopener nofollow" class="ticker-item absolute inset-0 flex items-center gap-2 truncate text-sm"'
        parts.append(
            f"<a {attrs}>"
            f'<time class="text-red-600 dark:text-red-400 text-xs font-semibold tabular-nums shrink-0">{_esc(b["time"])}</time>'
            f'<span class="truncate">{_esc(b["title"])}</span>'
            f'<span class="text-xs text-neutral-400 shrink-0">{_esc(b["outlet"])}</span></a>'
        )
    items = "".join(parts)
    return f"""<div class="border-b border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800">
  <div class="max-w-6xl mx-auto px-5 py-2 flex items-center gap-3">
    <span class="text-red-600 dark:text-red-400 font-bold text-xs tracking-[0.12em] shrink-0">속보</span>
    <div class="relative flex-1 h-6 overflow-hidden">{items}</div>
  </div>
</div>"""


def _render_bias_bar(bias: dict | None) -> str:
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
            segments.append(
                f'<span class="{BIAS_BAR_CLASSES[key]}" style="width:{n / total * 100:.0f}%"></span>'
            )
        labels.append(
            f'<span class="inline-flex items-center gap-1">'
            f'<span class="w-1.5 h-1.5 rounded-full" style="background:{dot_colors[key]}"></span>'
            f"{label} {n}</span>"
        )
    return f"""<div class="mb-2.5" aria-label="보도 매체 성향 분포">
  <div class="flex h-1.5 rounded-full overflow-hidden bg-stone-200 dark:bg-neutral-700">{"".join(segments)}</div>
  <div class="flex gap-3 text-[10px] text-neutral-400 mt-1.5">{"".join(labels)}</div>
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
    # 수직 타임라인: 송고 시간순(1보 → 최신)으로 사건의 흐름을 보여준다
    rows = "".join(
        f'<li class="relative">'
        f'<span class="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full bg-white dark:bg-neutral-800 border-2" style="border-color:{color}" aria-hidden="true"></span>'
        + f'<a class="flex items-start gap-2 text-[13px] hover:text-blue-600 dark:hover:text-blue-400" '
        f'href="{_esc(h["link"])}" target="_blank" rel="noopener nofollow">'
        + (
            f'<time class="w-9 shrink-0 pt-px text-[11px] text-neutral-400 tabular-nums">{_esc(h["time"])}</time>'
            if h.get("time")
            else ""
        )
        + f'{_favicon(h["link"])}'
        f'<span class="min-w-0"><b class="font-semibold text-neutral-400 text-xs mr-1.5">{_esc(h["outlet"])}</b>'
        f'{_esc(h["title"])}</span></a></li>'
        for h in heads
    )
    bias_attr = _esc(json.dumps(issue.get("bias") or {}, ensure_ascii=False))
    return f"""<article id="{anchor}" class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5 border-t-[3px]" style="border-top-color:{color}" data-cat="{_esc(issue["category"])}" data-bias="{bias_attr}">
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
  <h3 class="fs-t mt-2.5 mb-1.5 font-bold text-[15px] leading-snug [text-wrap:balance]">{_esc(issue["label"])}</h3>
  <div class="summary-wrap relative cursor-pointer mb-3.5" title="클릭하면 전체 요약을 봅니다">
    <p class="fs-p text-sm text-neutral-600 dark:text-neutral-300">{_esc(issue["summary"])}</p>
    <span class="fade"></span>
  </div>
  <div class="bias-inline hidden mb-3.5">{_render_bias_bar(issue.get("bias"))}</div>
  <div class="flex items-center gap-2 border-t border-stone-200 dark:border-neutral-700 pt-3">
    <details class="flex-1">
      <summary class="list-none [&::-webkit-details-marker]:hidden cursor-pointer select-none inline-flex items-center gap-1.5 rounded-lg border border-stone-200 dark:border-neutral-600 px-3 py-1.5 text-xs font-medium text-blue-600 dark:text-blue-400 hover:bg-stone-100 dark:hover:bg-neutral-700">
        매체별 헤드라인 {len(heads)}건 <span class="tri">▾</span>
      </summary>
      <div class="mt-3">{_render_bias_bar(issue.get("bias"))}</div>
      <ul class="relative ml-1.5 pl-4 border-l-2 border-stone-200 dark:border-neutral-700 flex flex-col gap-3">{rows}</ul>
    </details>
    <button type="button" class="share-btn shrink-0 self-start rounded-lg border border-stone-200 dark:border-neutral-600 px-3 py-1.5 text-xs text-neutral-500 dark:text-neutral-400 hover:text-blue-600 hover:border-blue-500" data-anchor="{anchor}" data-title="{_esc(issue["label"])}" data-text="{_esc(issue["summary"])}">공유</button>
    <button type="button" class="imgsave-btn shrink-0 self-start rounded-lg border border-stone-200 dark:border-neutral-600 px-3 py-1.5 text-xs text-neutral-500 dark:text-neutral-400 hover:text-blue-600 hover:border-blue-500" title="인스타그램용 정사각 이미지로 저장">이미지 저장</button>
  </div>
</article>"""


def _render_sidebar(policy: list[dict]) -> str:
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
    return f"""<aside class="flex flex-col gap-5 self-start lg:sticky lg:top-20">
  <section class="rounded-xl border border-stone-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-5">
    <h2 class="text-sm font-bold mb-0.5">정책 브리핑</h2>
    <p class="text-[11px] text-neutral-400 mb-3">출처: 대한민국 정책브리핑(korea.kr) · 공공누리 제1유형</p>
    {items}
  </section>
  {ad_slot("sidebar-1")}
  {newsletter_form}
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
        og_url = f"https://{punycode_domain}/og.png"
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
        card = _render_issue(issue, i)
        if i >= config.INITIAL_CARDS:
            # 무한 스크롤: 최초 12개 이후는 숨겨 두고 스크롤 시 12개씩 공개
            card = card.replace('<article id=', '<article data-lazy="1" id=', 1).replace(
                'class="rounded-xl', 'class="not-revealed rounded-xl', 1
            )
        cards.append(card)
        if i == 3:  # 4번째와 5번째 카드 사이 광고
            cards.append(f'<div class="sm:col-span-2">{ad_slot("feed-1")}</div>')
    cards.append('<div id="feed-sentinel" class="sm:col-span-2 h-1" aria-hidden="true"></div>')

    main_html = f"""<div class="grid grid-cols-1 lg:grid-cols-[7fr_3fr] gap-7 py-6">
  <section class="grid sm:grid-cols-2 gap-4 content-start" aria-label="주요 이슈">{"".join(cards)}</section>
  {_render_sidebar(briefing.get("policy", []))}
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

    page = _page(
        title=f"{config.SITE_TITLE} — {config.SITE_TAGLINE}",
        active="news",
        banner_html=nl_banner,
        generated_at=generated_at,
        feed="briefing.json",
        updated_label=updated,
        head_extra=og_meta,
        tabs_html="".join(tabs),
        after_header=_render_ticker(briefing.get("breaking", [])),
        main_html=main_html,
        footer_notes=[DISCLAIMER, KOGL_NOTICE],
        site_stamp=stamp,
    )
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    (out_dir / "sw.js").write_text(SERVICE_WORKER, encoding="utf-8")

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

    build_community_page(community, out_dir, generated_at, now, updated, stamp)
    build_scrapbook_page(out_dir, generated_at, now, updated, stamp)
    build_seo_files(briefing, out_dir, punycode_domain, now)
    return out_dir / "index.html"


# ── SEO: sitemap.xml / rss.xml / robots.txt 자동 생성 ───────────────────


def build_seo_files(
    briefing: dict, out_dir: Path, domain: str, now: datetime
) -> None:
    from email.utils import format_datetime

    base = f"https://{domain}"
    lastmod = now.strftime("%Y-%m-%dT%H:%M:%S%z")
    lastmod = lastmod[:-2] + ":" + lastmod[-2:]  # +0900 → +09:00

    pages = [
        ("", "1.0", "hourly"),
        ("community.html", "0.8", "hourly"),
        ("scrapbook.html", "0.3", "monthly"),
    ]
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
        items.append(
            "<item>"
            f"<title>{html.escape(issue['label'])}</title>"
            f"<link>{base}/#issue-{i}</link>"
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
    "오늘", "진짜", "근데", "이거", "그냥", "사람", "요즘", "하는", "보는", "있는",
    "없는", "이제", "다시", "때문", "정도", "레전드", "후기", "단독", "속보",
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


def _trend_keywords(posts: list[dict], top_n: int = 8) -> list[str]:
    """게시글 제목에서 빈출 키워드를 추출한다 (간단 토큰 빈도)."""
    import re as _re
    from collections import Counter

    counter: Counter[str] = Counter()
    for post in posts:
        for token in _re.findall(r"[가-힣]{2,}", post["title"]):
            if token not in _TREND_STOPWORDS and token not in SOURCE_BADGE:
                counter[token] += 1
    return [w for w, n in counter.most_common(top_n) if n >= 2]


def build_community_page(
    posts: list[dict], out_dir: Path, generated_at: str,
    now: datetime, updated: str, stamp: str,
) -> Path:
    counts: dict[str, int] = {}
    for post in posts:
        counts[post["source"]] = counts.get(post["source"], 0) + 1

    tabs = [_tab("전체", len(posts), "src", "전체", True)] + [
        _tab(src, n, "src", src, False) for src, n in counts.items()
    ]

    cards = []
    for i, p in enumerate(posts):
        hot = p.get("hot")
        badge_cls = SOURCE_BADGE.get(p["source"], "bg-stone-500 text-white")
        hot_badge = (
            '<span class="text-[10px] font-bold text-red-500 shrink-0">🔥 HOT</span>'
            if hot
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
    <span class="ml-auto text-xs font-bold text-neutral-300 dark:text-neutral-600 tabular-nums">#{i + 1}</span>
    <button type="button" class="scrap-btn text-base leading-none text-neutral-300 dark:text-neutral-600 hover:text-amber-500 shrink-0" aria-label="스크랩" data-scrap="{scrap_payload}">☆</button>
  </div>
  <a class="flex items-start gap-3 hover:text-blue-600 dark:hover:text-blue-400" href="{_esc(p["link"])}" target="_blank" rel="noopener nofollow">
    <span class="flex-1 min-w-0 text-sm leading-snug line-clamp-2">{_esc(p["title"])}</span>
    {thumb_html}
  </a>
</article>""")

    trend_chips = "".join(
        f'<span class="text-xs rounded-full border border-stone-200 dark:border-neutral-600 px-2.5 py-1 text-neutral-600 dark:text-neutral-300">#{_esc(w)}</span>'
        for w in _trend_keywords(posts)
    ) or '<span class="text-xs text-neutral-400">키워드 집계 중</span>'

    sidebar = f"""<aside class="flex flex-col gap-5 self-start lg:sticky lg:top-20">
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

    # 베스트 오브 베스트: 각 커뮤니티 1위 글 + HOT 글을 상단에 크로스 커뮤니티로
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
    {best_section}
    <section class="grid grid-cols-1 lg:grid-cols-2 gap-4 content-start" aria-label="커뮤니티 인기글">{"".join(cards)}</section>
  </div>
  {sidebar}
</div>"""

    page = _page(
        title=f"커뮤니티 인기글 — {config.SITE_TITLE}",
        active="community",
        generated_at=generated_at,
        feed="community.json",
        updated_label=updated,
        head_extra="",
        tabs_html="".join(tabs),
        after_header="",
        main_html=main_html,
        footer_notes=[COMMUNITY_NOTICE],
        site_stamp=stamp,
        extra_script=COMMUNITY_SIDEBAR_SCRIPT,
    )
    out_path = out_dir / "community.html"
    out_path.write_text(page, encoding="utf-8")
    return out_path


# ── 스크랩북 페이지 (클라이언트 렌더링) ─────────────────────────────────


def build_scrapbook_page(
    out_dir: Path, generated_at: str, now: datetime, updated: str, stamp: str
) -> Path:
    main_html = """<div class="max-w-3xl mx-auto py-6 flex flex-col gap-6">
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
    )
    out_path = out_dir / "scrapbook.html"
    out_path.write_text(page, encoding="utf-8")
    return out_path
