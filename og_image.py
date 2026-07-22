"""SNS 공유용 OG 카드(1200×630 PNG) 생성.

언론사 이미지를 쓰지 않고 빌드 시점에 자체 그래픽을 생성한다 — 저작권 안전.
브랜드 + 날짜 + 1위 이슈 라벨 + 분야별 슬롯 비율 컬러 바로 구성.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 카테고리 컬러 (build_site.py와 동일 팔레트)
CATEGORY_COLORS = {
    "정치": "#4f6df5",
    "경제": "#2e9e6b",
    "사회": "#e0862e",
    "국제": "#2596a6",
    "IT·과학": "#8b5cf6",
    "생활·문화": "#d55c8d",
    "게임": "#e5484d",
}

FONT_PATHS = [
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",  # Ubuntu (Actions)
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",  # macOS
    "/Library/Fonts/AppleGothic.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _wrap(text: str, limit: int, max_lines: int = 2) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= limit:
            cur = f"{cur} {w}".strip()
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: limit - 1] + "…"
    return lines


def build_icon(out_path: Path, size: int = 512) -> Path | None:
    """PWA/파비콘용 브랜드 마크 아이콘 PNG."""
    try:
        img = Image.new("RGB", (size, size), "#2563eb")
        d = ImageDraw.Draw(img)
        bar_w, bar_h = int(size * 0.56), int(size * 0.11)
        bx = (size - bar_w) // 2
        for i, color in enumerate(("#ffffff", "#e3e8fb", "#c9d3f5")):
            by = int(size * (0.26 + i * 0.18))
            d.rounded_rectangle([bx, by, bx + bar_w, by + bar_h], radius=bar_h // 2, fill=color)
        img.save(out_path, "PNG")
        return out_path
    except Exception as e:
        print(f"[경고] 아이콘 생성 실패: {e}")
        return None


def _num_press(briefing: dict) -> int:
    try:
        import config
        return len(config.PRESS_FEEDS)
    except Exception:
        return 60


def build_og(briefing: dict, out_path: Path, generated_at: datetime) -> Path | None:
    """카톡·SNS 공유 썸네일(1200×630). 상단 성향 스펙트럼 띠 + 브랜드 +
    오늘의 톱뉴스 + 하단 정보줄로 여백 없이 꽉 차게 구성한다."""
    try:
        W, H = 1200, 630
        L = 90  # 좌측 여백
        img = Image.new("RGB", (W, H), "#0f1012")
        d = ImageDraw.Draw(img)

        # 상단 성향 스펙트럼 띠(진보 파랑 · 중도 회색 · 보수 빨강) — 브랜드 시그니처
        seg = [("#3b6ff5", 0.46), ("#6b7280", 0.08), ("#ef4444", 0.46)]
        x = 0
        for color, frac in seg:
            w = int(W * frac)
            d.rectangle([x, 0, x + w, 12], fill=color)
            x += w
        if x < W:
            d.rectangle([x, 0, W, 12], fill="#ef4444")

        # 브랜드 마크 + 워드마크
        mx, my, ms = L, 78, 104
        d.rounded_rectangle([mx, my, mx + ms, my + ms], radius=24, fill="#2563eb")
        bar_w, bar_h = int(ms * 0.56), int(ms * 0.11)
        bx = mx + (ms - bar_w) // 2
        for i, color in enumerate(("#ffffff", "#e3e8fb", "#c9d3f5")):
            by = my + int(ms * (0.26 + i * 0.18))
            d.rounded_rectangle([bx, by, bx + bar_w, by + bar_h], radius=bar_h // 2, fill=color)
        d.text((mx + ms + 34, my + 2), "고른뉴스", font=_font(94), fill="#f2f2f4")
        d.text((mx + ms + 36, my + 112), "골라 담아, 고르게 전합니다", font=_font(34), fill="#9a9aa2")

        # 핵심 메시지 강조 — 왼쪽 파란 액센트 바로 프레이밍
        hero = [f"{_num_press(briefing)}개 언론사 교차확인", "매시간 AI 중립 뉴스 브리핑"]
        hl_y = 320
        hf = _font(70)
        line_h = 88
        d.rounded_rectangle([L, hl_y + 8, L + 8, hl_y + 8 + len(hero) * line_h - 24],
                            radius=4, fill="#2563eb")
        y = hl_y
        for i, line in enumerate(hero):
            d.text((L + 34, y), line, font=hf, fill="#f2f2f4" if i == 0 else "#c9d3f5")
            y += line_h

        # 하단 도메인
        info_y = H - 74
        d.line([L, info_y - 24, W - L, info_y - 24], fill="#26262b", width=2)
        dom = "goreunnews.cloud"
        df = _font(38)
        dw = d.textlength(dom, font=df)
        d.text((W - L - dw, info_y - 4), dom, font=df, fill="#7aa2ff")

        # 최하단: 분야별 슬롯 비율 컬러 바
        slots = briefing.get("slots", {})
        total = sum(slots.values()) or 1
        x, bar_y, bh = 0, H - 10, 10
        for cat, n in slots.items():
            w = int(W * n / total)
            d.rectangle([x, bar_y, x + w, bar_y + bh], fill=CATEGORY_COLORS.get(cat, "#4f6df5"))
            x += w
        if x < W:
            d.rectangle([x, bar_y, W, bar_y + bh], fill="#2c2c31")

        img.save(out_path, "PNG")
        return out_path
    except Exception as e:  # 폰트 부재 등 — OG 카드는 부가 요소라 빌드를 막지 않는다
        print(f"[경고] OG 이미지 생성 실패: {e}")
        return None
