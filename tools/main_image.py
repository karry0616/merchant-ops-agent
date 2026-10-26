"""商品主图生成 — 用 Pillow 合成 800×800 电商主图

三套模板：
- clean  白底简约（适合数码、家居）
- promo  红橙促销（适合活动、清仓）
- fresh  浅绿清新（适合食品、母婴、日用）
"""

from __future__ import annotations

import os
import re

from PIL import Image, ImageDraw, ImageFont

SIZE = 800
OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", "main_images"
)

_FONT_FILES = [
    (r"C:\Windows\Fonts\msyhbd.ttc", 0),
    (r"C:\Windows\Fonts\msyh.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
    ("/System/Library/Fonts/PingFang.ttc", 0),
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path, index in _FONT_FILES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size, index=index)
            except OSError:
                continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """按实际像素宽度换行，兼容中英文混排"""
    lines, current = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(current)
            current = ""
            continue
        trial = current + ch
        if draw.textlength(trial, font=font) > max_width and current:
            lines.append(current)
            current = ch
        else:
            current = trial
    if current:
        lines.append(current)
    return lines[:4]


def _gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    base = Image.new("RGB", (1, size), top)
    draw = ImageDraw.Draw(base)
    for y in range(size):
        ratio = y / max(size - 1, 1)
        draw.point(
            (0, y),
            fill=(
                round(top[0] + (bottom[0] - top[0]) * ratio),
                round(top[1] + (bottom[1] - top[1]) * ratio),
                round(top[2] + (bottom[2] - top[2]) * ratio),
            ),
        )
    return base.resize((size, size))


def _price_text(value) -> str:
    """把价格格式化成 ¥129 或 ¥129.9"""
    try:
        num = float(str(value).replace("¥", "").replace("元", "").strip())
    except (TypeError, ValueError):
        return ""
    if num <= 0:
        return ""
    return f"¥{num:.0f}" if abs(num - round(num)) < 0.05 else f"¥{num:.1f}"


def _split_points(features) -> list[str]:
    if not features:
        return []
    parts = re.split(r"[,，、;；/|\n]+", str(features))
    return [p.strip() for p in parts if p.strip()][:3]


def _draw_points(draw, points, x, y, font, color, gap=58, dot=None):
    for item in points:
        if dot:
            draw.ellipse(dot, fill=color)
        draw.text((x, y), item, font=font, fill=color)
        y += gap
    return y


PALETTES = {
    "clean": {
        "mode": "solid",
        "bg": "#FFFFFF",
        "panel": "#F3F8FF",
        "title": "#0F172A",
        "muted": "#64748B",
        "accent": "#2563EB",
        "on_accent": "#FFFFFF",
        "chip_bg": "#E8F1FD",
        "chip_fg": "#2563EB",
    },
    "promo": {
        "mode": "gradient",
        "from": "#FF5A44",
        "to": "#FF9142",
        "bg": "#FF6A3D",
        "panel": "#FFFFFF",
        "title": "#FFFFFF",
        "muted": "#FFF1E6",
        "accent": "#FFE58F",
        "on_accent": "#8A2B0B",
        "chip_bg": "#FFFFFF",
        "chip_fg": "#D93A1E",
    },
    "fresh": {
        "mode": "gradient",
        "from": "#EAF8F0",
        "to": "#CFEEDD",
        "bg": "#E4F6EC",
        "panel": "#FFFFFF",
        "title": "#10402B",
        "muted": "#4B7C65",
        "accent": "#15A05B",
        "on_accent": "#FFFFFF",
        "chip_bg": "#FFFFFF",
        "chip_fg": "#0F8C50",
    },
}


def generate_main_image(name: str, features, price, template: str = "clean", shop: str = "店铺自营") -> str:
    """生成商品主图，返回图片绝对路径"""
    palette = PALETTES.get(template, PALETTES["clean"])
    if palette["mode"] == "gradient":
        img = _gradient(SIZE, _hex(palette["from"]), _hex(palette["to"]))
    else:
        img = Image.new("RGB", (SIZE, SIZE), _hex(palette["bg"]))

    draw = ImageDraw.Draw(img)
    accent = _hex(palette["accent"])

    # 背景装饰：右上与左下两个半透明圆
    overlay = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.ellipse((520, -170, 980, 290), fill=(255, 255, 255, 42))
    od.ellipse((-190, 560, 250, 1000), fill=(255, 255, 255, 34))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # 顶部品牌角标
    chip_font = _font(26)
    chip_text = shop or "店铺自营"
    chip_w = int(draw.textlength(chip_text, font=chip_font)) + 44
    draw.rounded_rectangle((56, 52, 56 + chip_w, 106), radius=27, fill=_hex(palette["chip_bg"]))
    draw.text((56 + 22, 66), chip_text, font=chip_font, fill=_hex(palette["chip_fg"]))

    # 商品名称
    title_font = _font(64)
    title = (name or "商品名称").strip()
    lines = _wrap(draw, title, title_font, 688)
    y = 150
    for line in lines:
        draw.text((56, y), line, font=title_font, fill=_hex(palette["title"]))
        y += 82

    # 卖点
    points = _split_points(features)
    if points:
        point_font = _font(31)
        py = max(y + 18, 392)
        for item in points:
            draw.ellipse((58, py + 13, 70, py + 25), fill=accent)
            draw.text((88, py), item, font=point_font, fill=_hex(palette["muted"]))
            py += 56
        y = py

    # 价格卡
    price_label = _price_text(price)
    card_top = 606
    draw.rounded_rectangle((56, card_top, 744, 742), radius=26, fill=_hex(palette["panel"]))

    if price_label:
        label_font = _font(24)
        value_font = _font(72)
        draw.text((88, card_top + 22), "到手价", font=label_font, fill=_hex(palette["muted"]))
        draw.text((88, card_top + 56), price_label, font=value_font, fill=accent)
    else:
        tagline = _font(44)
        draw.text((88, card_top + 40), "新品上架", font=tagline, fill=_hex(palette["title"]))

    # 右下角促销贴片
    badge_font = _font(27)
    badge_text = "限时特惠" if template == "promo" else "7天无理由"
    bw = int(draw.textlength(badge_text, font=badge_font)) + 52
    draw.rounded_rectangle(
        (744 - bw, card_top + 44, 744 - 22, card_top + 100), radius=28, fill=accent
    )
    draw.text((744 - bw + 26, card_top + 58), badge_text, font=badge_font, fill=_hex(palette["on_accent"]))

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe = re.sub(r"[^\w\u4e00-\u9fa5]+", "_", (name or "商品")).strip("_")[:24] or "商品"
    path = os.path.join(OUTPUT_DIR, f"主图_{safe}_{template}.png")
    img.save(path, "PNG")
    return path


def _hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))
