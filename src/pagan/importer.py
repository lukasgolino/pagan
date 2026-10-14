"""`pagan import`: bring an existing PNG under PAGAN's constraints.

Undo nearest-neighbour upscaling, threshold alpha, then either snap every pixel to the nearest palette
color (perceptual OKLab distance) or, in open mode, extract the image's own colors into an inline palette.
"""

from __future__ import annotations

import math
import string
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from pagan.color import RGB, distance, rgb_to_hex, rgb_to_oklab
from pagan.palette import Palette

KEYS = string.digits + string.ascii_lowercase + string.ascii_uppercase


@dataclass
class ImportReport:
    source_size: tuple[int, int]
    scale: int
    size: tuple[int, int]
    opaque_pixels: int
    source_colors: int
    changed_pixels: int = 0  # pixels whose color changed when snapping
    max_distance: float = 0.0  # worst OKLab distance of a snapped color
    mapping: dict[str, tuple[str, float]] = field(default_factory=dict)  # source hex -> (key, distance)
    reduced_from: int | None = None  # open mode: colors before reducing to the key limit


def detect_scale(image: Image.Image) -> int:
    """Largest s such that the image is made of uniform s x s blocks (1 if it isn't upscaled)."""
    width, height = image.size
    data = image.tobytes()
    bpp = len(image.getbands())

    def px(x: int, y: int) -> bytes:
        i = (y * width + x) * bpp
        return data[i : i + bpp]

    g = math.gcd(width, height)
    # Run lengths along rows and columns bound the scale; their gcd is the only candidate worth checking.
    for y in range(height):
        run = 1
        for x in range(1, width + 1):
            if x < width and px(x, y) == px(x - 1, y):
                run += 1
            else:
                g = math.gcd(g, run)
                run = 1
        if g == 1:
            return 1
    for x in range(width):
        run = 1
        for y in range(1, height + 1):
            if y < height and px(x, y) == px(x, y - 1):
                run += 1
            else:
                g = math.gcd(g, run)
                run = 1
        if g == 1:
            return 1
    return g


def _downscale(image: Image.Image, scale: int) -> Image.Image:
    if scale == 1:
        return image
    return image.resize((image.width // scale, image.height // scale), Image.Resampling.NEAREST, reducing_gap=None)


def _pixels(image: Image.Image, alpha_threshold: int) -> list[list[RGB | None]]:
    rgba = image.convert("RGBA")
    data = rgba.tobytes()
    rows: list[list[RGB | None]] = []
    for y in range(rgba.height):
        row: list[RGB | None] = []
        for x in range(rgba.width):
            i = (y * rgba.width + x) * 4
            r, g, b, a = data[i : i + 4]
            row.append((r, g, b) if a >= alpha_threshold else None)
        rows.append(row)
    return rows


def _to_rgba(image: Image.Image, alpha_threshold: int) -> Image.Image:
    """8-bit RGBA with fully transparent pixels normalised (their RGB can be junk that breaks scale detection)."""
    if image.mode in ("I", "I;16", "I;16B", "I;16L", "I;16N"):
        image = image.point(lambda v: v / 257).convert("L")  # 16-bit grey -> 8-bit, keeping the levels
    rgba = image.convert("RGBA")
    data = bytearray(rgba.tobytes())
    for i in range(0, len(data), 4):
        if data[i + 3] < alpha_threshold:
            data[i : i + 4] = b"\0\0\0\0"
    return Image.frombytes("RGBA", rgba.size, bytes(data))


def import_png(
    image: Image.Image,
    *,
    palette: Palette | None,
    scale: int | None = None,
    alpha_threshold: int = 128,
    max_colors: int = 32,
) -> tuple[list[str], dict[str, str] | None, ImportReport]:
    """Returns (grid rows, inline palette key->hex or None when snapping to `palette`, report)."""
    if max_colors < 1:
        raise ValueError("max_colors must be at least 1")
    source_size = image.size
    rgba = _to_rgba(image, alpha_threshold)
    scale = scale or detect_scale(rgba)
    small = _downscale(rgba, scale)
    pixels = _pixels(small, alpha_threshold)
    colors = sorted({p for row in pixels for p in row if p is not None})
    report = ImportReport(
        source_size=source_size,
        scale=scale,
        size=small.size,
        opaque_pixels=sum(p is not None for row in pixels for p in row),
        source_colors=len(colors),
    )

    if palette is not None:
        targets = [(key, rgb_to_oklab(c.rgb), c.rgb) for key, c in palette.colors.items()]
        lookup: dict[RGB, str] = {}
        for color in colors:
            lab = rgb_to_oklab(color)
            key, d, rgb = min(((k, distance(lab, t), rgb) for k, t, rgb in targets), key=lambda item: (item[1], item[0]))
            lookup[color] = key
            report.mapping[rgb_to_hex(color)] = (key, round(d, 4))
            report.max_distance = max(report.max_distance, d)
            if rgb != color:
                report.changed_pixels += sum(p == color for row in pixels for p in row)
        rows = ["".join("." if p is None else lookup[p] for p in row) for row in pixels]
        return rows, None, report

    # Open mode: the image's own colors become an inline palette (reduced if there are too many).
    limit = min(max_colors, len(KEYS))
    if len(colors) > limit:
        report.reduced_from = len(colors)
        opaque = Image.new("RGB", small.size)
        opaque.putdata([p or (0, 0, 0) for row in pixels for p in row])
        quantized = opaque.quantize(colors=limit, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        flat_palette = quantized.getpalette() or []
        indexes = quantized.tobytes()
        width = small.width
        reduced: list[list[RGB | None]] = []
        for y, row in enumerate(pixels):
            new_row: list[RGB | None] = []
            for x, p in enumerate(row):
                if p is None:
                    new_row.append(None)
                else:
                    i = indexes[y * width + x] * 3
                    new_row.append((flat_palette[i], flat_palette[i + 1], flat_palette[i + 2]))
            reduced.append(new_row)
        report.changed_pixels = sum(a != b for ra, rb in zip(pixels, reduced, strict=True) for a, b in zip(ra, rb, strict=True))
        pixels = reduced
        colors = sorted({p for row in pixels for p in row if p is not None})
    # Darkest first, so "0" is the natural outline color.
    ordered = sorted(colors, key=lambda c: (rgb_to_oklab(c)[0], c))
    keys = {color: KEYS[i] for i, color in enumerate(ordered)}
    inline = {keys[c]: rgb_to_hex(c) for c in ordered}
    rows = ["".join("." if p is None else keys[p] for p in row) for row in pixels]
    return rows, inline, report


def sprite_yaml(name: str, rows: list[str], palette_name: str | None, inline: dict[str, str] | None, source: Path) -> str:
    width, height = (len(rows[0]) if rows else 0), len(rows)
    lines = [
        f"name: {name}",
        f'description: "Imported from {source.name}. TODO: describe what this is."',
    ]
    if inline is not None:
        lines.append("palette:")
        lines.append("  colors:")
        lines.extend(f'    "{key}": "{hex_value}"' for key, hex_value in inline.items())
    elif palette_name is not None:
        lines.append(f"palette: {palette_name}")
    lines += [
        f"size: [{width}, {height}]",
        f"pivot: [{width // 2}, {height}]",
        "status: draft",
        "tags: [imported]",
        "frames:",
        "  main: |",
        *(f"    {row}" for row in rows),
    ]
    return "\n".join(lines) + "\n"
