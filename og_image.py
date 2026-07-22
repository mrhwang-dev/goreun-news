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


def build_og(briefing: dict, out_path: Path, generated_at: datetime) -> Path | None:
    try:
        W, H = 1200, 630
        img = Image.new("RGB", (W, H), "#141416")
        d = ImageDraw.Draw(img)

        # 브랜드 마크 (고르게 정렬된 세 줄)
        mx, my, ms = 80, 84, 92
        d.rounded_rectangle([mx, my, mx + ms, my + ms], radius=20, fill="#2563eb")
        bar_w, bar_h = int(ms * 0.56), int(ms * 0.11)
        bx = mx + (ms - bar_w) // 2
        for i, color in enumerate(("#ffffff", "#e3e8fb", "#c9d3f5")):
            by = my + int(ms * (0.26 + i * 0.18))
            d.rounded_rectangle(
                [bx, by, bx + bar_w, by + bar_h], radius=bar_h // 2, fill=color
            )

        d.text((mx + ms + 32, 88), "고른뉴스", font=_font(84), fill="#ececee")
        d.text((80, 222), "골라 담아, 고르게 전합니다", font=_font(34), fill="#98989f")
        d.text(
            (80, 268),
            generated_at.strftime("%Y년 %m월 %d일 %H시 브리핑"),
            font=_font(30),
            fill="#7aa2ff",
        )

        issues = briefing.get("issues", [])
        if issues:
            label_font = _font(46)
            y = 372
            for line in _wrap(issues[0]["label"], 24):
                d.text((80, y), line, font=label_font, fill="#ececee")
                y += 62

        # 하단: 분야별 슬롯 비율 컬러 바
        slots = briefing.get("slots", {})
        total = sum(slots.values()) or 1
        x, bar_y, bar_h = 0, H - 18, 18
        for cat, n in slots.items():
            w = int(W * n / total)
            d.rectangle(
                [x, bar_y, x + w, bar_y + bar_h],
                fill=CATEGORY_COLORS.get(cat, "#4f6df5"),
            )
            x += w
        if x < W:
            d.rectangle([x, bar_y, W, bar_y + bar_h], fill="#2c2c31")

        img.save(out_path, "PNG")
        return out_path
    except Exception as e:  # 폰트 부재 등 — OG 카드는 부가 요소라 빌드를 막지 않는다
        print(f"[경고] OG 이미지 생성 실패: {e}")
        return None
