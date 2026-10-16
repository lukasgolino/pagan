"""Render a palette as a labeled swatch image (all colors, then each ramp)."""

from __future__ import annotations

from functools import cache

from PIL import Image, ImageDraw, ImageFont

from pagan.palette import Color, Palette

BACKGROUND = (30, 30, 36)
TEXT = (230, 230, 230)
MUTED = (150, 150, 166)

PAD = 16
COLUMNS = 8
CELL_W = 96  # width of one color cell in the grid
SWATCH_W = 88
SWATCH_H = 44
CELL_H = SWATCH_H + 34  # swatch + name + hex
RAMP_LABEL_W = 120
RAMP_SWATCH = 44

Font = ImageFont.FreeTypeFont | ImageFont.ImageFont


@cache
def _font(size: int) -> Font:
    return ImageFont.load_default(size=size)


_GLYPH_FONTS = ("DejaVuSans.ttf", "Arial Unicode.ttf", "arialuni.ttf", "segoeui.ttf", "Arial.ttf", "arial.ttf")


def _key_font(size: int) -> Font:
    """A font with Greek and Latin-1 glyphs for palette keys (Pillow's default lacks Greek), if the system
    has one. Swatches are previews, so the fallback only affects how they look."""
    for name in _GLYPH_FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return _font(size)


def _contrast(color: Color) -> tuple[int, int, int]:
    r, g, b = color.rgb
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return (0, 0, 0) if luminance > 0.5 else (255, 255, 255)


def _fit(draw: ImageDraw.ImageDraw, text: str, font: Font, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def render_swatch(palette: Palette, title: str | None = None) -> Image.Image:
    colors = list(palette.colors.values())
    rows = -(-len(colors) // COLUMNS)
    longest_ramp = max((len(r) for r in palette.ramps.values()), default=0)

    title_h = 28
    section_h = 22
    grid_h = rows * CELL_H
    ramps_h = (section_h + len(palette.ramps) * (RAMP_SWATCH + 6)) if palette.ramps else 0
    width = PAD * 2 + max(min(len(colors), COLUMNS) * CELL_W, RAMP_LABEL_W + longest_ramp * RAMP_SWATCH)
    height = PAD * 2 + title_h + section_h + grid_h + (8 + ramps_h if ramps_h else 0)

    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    title_font, label_font, key_font = _font(18), _font(12), _key_font(16)

    name = title or palette.name or "inline palette"
    summary = f"{len(colors)} colors, {len(palette.ramps)} ramps"
    draw.text((PAD, PAD), name, font=title_font, fill=TEXT)
    draw.text((PAD + draw.textlength(name, font=title_font) + 12, PAD + 4), summary, font=label_font, fill=MUTED)

    y = PAD + title_h
    draw.text((PAD, y), "colors", font=label_font, fill=MUTED)
    y += section_h
    for i, color in enumerate(colors):
        x = PAD + (i % COLUMNS) * CELL_W
        cy = y + (i // COLUMNS) * CELL_H
        draw.rectangle((x, cy, x + SWATCH_W - 1, cy + SWATCH_H - 1), fill=color.rgb)
        draw.text((x + 5, cy + 3), color.key, font=key_font, fill=_contrast(color))
        draw.text((x, cy + SWATCH_H + 3), _fit(draw, color.name or "", label_font, SWATCH_W), font=label_font, fill=TEXT)
        draw.text((x, cy + SWATCH_H + 18), color.hex, font=label_font, fill=MUTED)
    y += grid_h

    if palette.ramps:
        y += 8
        draw.text((PAD, y), "ramps (shadow -> highlight)", font=label_font, fill=MUTED)
        y += section_h
        for ramp_name, keys in palette.ramps.items():
            label = _fit(draw, ramp_name, label_font, RAMP_LABEL_W - 8)
            draw.text((PAD, y + RAMP_SWATCH // 2 - 7), label, font=label_font, fill=TEXT)
            for j, key in enumerate(keys):
                color = palette.colors[key]
                x = PAD + RAMP_LABEL_W + j * RAMP_SWATCH
                draw.rectangle((x, y, x + RAMP_SWATCH - 1, y + RAMP_SWATCH - 1), fill=color.rgb)
                draw.text((x + 5, y + 3), key, font=key_font, fill=_contrast(color))
            y += RAMP_SWATCH + 6

    return image
