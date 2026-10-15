"""Upscaled previews for looking at art: frames, contact sheets, animated GIFs, tiling checks, gallery.

Previews are for humans and agents to *look at*; they are not build output and need not be byte-stable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from pagan.asset import Asset, Grid
from pagan.palette import TRANSPARENT
from pagan.render import frame_image
from pagan.swatch import _font

BG_DARK = (30, 30, 36)
TEXT = (230, 230, 230)
MUTED = (150, 150, 166)
CHECKER = ((92, 92, 104), (120, 120, 134))
GRID_COLOR = (0, 0, 0, 70)
PAD = 12
LABEL_H = 18
MAX_PER_ROW = 8

Background = str  # "checker", "none", or "#rrggbb"


@dataclass(frozen=True)
class PreviewOptions:
    scale: int | None = None  # None = automatic
    grid: bool = False
    background: Background = "checker"


def auto_scale(size: tuple[int, int]) -> int:
    """Aim for frames around 256px on their long side."""
    return max(1, min(16, 256 // max(size)))


def _background(size: tuple[int, int], background: Background, cell: int) -> Image.Image:
    width, height = size
    if background == "none":
        return Image.new("RGBA", size, (0, 0, 0, 0))
    if background.startswith("#") and len(background) == 7:
        rgb = tuple(int(background[i : i + 2], 16) for i in (1, 3, 5))
        return Image.new("RGBA", size, (*rgb, 255))
    image = Image.new("RGBA", size, (*CHECKER[0], 255))
    draw = ImageDraw.Draw(image)
    for y in range(0, height, cell):
        for x in range(0, width, cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=(*CHECKER[1], 255))
    return image


def upscale(image: Image.Image, scale: int, options: PreviewOptions) -> Image.Image:
    big = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
    out = _background(big.size, options.background, max(4, scale))
    out.alpha_composite(big)
    if options.grid and scale >= 4:
        overlay = Image.new("RGBA", out.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for x in range(0, out.width, scale):
            draw.line((x, 0, x, out.height), fill=GRID_COLOR)
        for y in range(0, out.height, scale):
            draw.line((0, y, out.width, y), fill=GRID_COLOR)
        out.alpha_composite(overlay)
    return out


def _labelled_grid(title: str, subtitle: str, rows: list[tuple[str, list[tuple[str, Image.Image]]]]) -> Image.Image:
    """Rows of labelled cells under section headings. All cells in a row share a size."""
    font, title_font = _font(12), _font(16)
    cell_rows: list[tuple[str, list[list[tuple[str, Image.Image]]]]] = []
    for heading, cells in rows:
        chunks = [cells[i : i + MAX_PER_ROW] for i in range(0, len(cells), MAX_PER_ROW)] or [[]]
        cell_rows.append((heading, chunks))

    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    width = max(PAD * 2 + int(measure.textlength(title, font=title_font)), PAD * 2 + int(measure.textlength(subtitle, font=font)))
    height = PAD + 24 + (LABEL_H if subtitle else 0)
    for heading, chunks in cell_rows:
        height += LABEL_H if heading else 0
        for chunk in chunks:
            row_w = PAD + sum(max(img.width, int(measure.textlength(label, font=font))) + PAD for label, img in chunk)
            width = max(width, row_w + PAD)
            height += max((img.height for _, img in chunk), default=0) + LABEL_H + PAD

    sheet = Image.new("RGBA", (width, height), (*BG_DARK, 255))
    draw = ImageDraw.Draw(sheet)
    draw.text((PAD, PAD), title, font=title_font, fill=TEXT)
    y = PAD + 24
    if subtitle:
        draw.text((PAD, y - 4), subtitle, font=font, fill=MUTED)
        y += LABEL_H
    for heading, chunks in cell_rows:
        if heading:
            draw.text((PAD, y), heading, font=font, fill=MUTED)
            y += LABEL_H
        for chunk in chunks:
            x = PAD
            row_h = max((img.height for _, img in chunk), default=0)
            for label, img in chunk:
                sheet.alpha_composite(img, (x, y))
                draw.text((x, y + img.height + 2), label, font=font, fill=TEXT)
                x += max(img.width, int(draw.textlength(label, font=font))) + PAD
            y += row_h + LABEL_H + PAD
    return sheet


def contact_sheet(asset: Asset, options: PreviewOptions) -> Image.Image:
    scale = options.scale or auto_scale(asset.size)
    rows: list[tuple[str, list[tuple[str, Image.Image]]]] = []
    if asset.kind == "model":
        # One row per heading: the static frame, then that heading's animation frames.
        headings = [a.name for a in asset.animations.values() if a.frames == (a.name,)]
        animated = len(asset.animations) > len(headings)
        if not animated:  # static model: all headings together, wrapping in rows
            rows.append(("headings", [(h, upscale(frame_image(asset, h), scale, options)) for h in headings]))
        for heading in headings if animated else []:
            names = [heading] + [f for a in asset.animations.values() if a.name.endswith(f"_{heading}") for f in a.frames]
            rows.append((f"heading {heading}", [(n, upscale(frame_image(asset, n), scale, options)) for n in names]))
        for variant_name in asset.variants:
            rows.append((variant_name, [(h, upscale(frame_image(asset, h, variant_name), scale, options)) for h in headings]))
    else:
        for variant in (None, *asset.variants):
            cells = [(name, upscale(frame_image(asset, name, variant), scale, options)) for name in asset.frames]
            rows.append(("" if variant is None and not asset.variants else (variant or "base"), cells))
    if asset.kind == "tileset":
        rows.append(("tiled 3x3 (check seams)", [(name, upscale(tiled(asset, name, 3), max(1, scale // 2), options)) for name in asset.frames]))
    for anim in asset.animations.values():
        if len(anim.frames) < 2:
            continue
        cells = []
        for i, name in enumerate(anim.frames):
            previous = anim.frames[i - 1]  # frame 0 compares with the last (the loop seam)
            cells.append((f"{previous}->{name}", upscale(change_image(asset, previous, name), scale, options)))
        rows.append((f"{anim.name}: changes (magenta = changed/new pixel, cyan = pixel removed)", cells))
    if asset.animations and asset.kind != "model":
        summary = ", ".join(f"{a.name} ({len(a.frames)}f @ {a.fps:g}fps{'' if a.loop else ', once'})" for a in asset.animations.values())
        rows.append((f"animations: {summary}", []))
    width, height = asset.size
    palette = asset.palette.name or "inline palette"
    title = f"{asset.name}  {width}x{height}  x{scale}"
    subtitle = f"{asset.kind} · {palette} · {asset.status} · style v{asset.style_version}"
    if asset.description:
        subtitle += f" · {asset.description[:90]}{'…' if len(asset.description) > 90 else ''}"
    return _labelled_grid(title, subtitle, rows)


CHANGED = (255, 40, 200, 255)
REMOVED = (40, 220, 255, 255)


def change_image(asset: Asset, before: str, after: str) -> Image.Image:
    """`after` dimmed, with pixels that differ from `before` highlighted. Jumps stand out at a glance."""
    a: Grid = asset.frames[before]
    b: Grid = asset.frames[after]
    image = frame_image(asset, after)
    dim = Image.new("RGBA", image.size, (0, 0, 0, 0))
    dim.alpha_composite(image)
    dim = Image.blend(Image.new("RGBA", image.size, (0, 0, 0, 0)), dim, 0.35)
    pixels = dim.load()
    assert pixels is not None
    for y, (row_a, row_b) in enumerate(zip(a, b, strict=True)):
        for x, (pa, pb) in enumerate(zip(row_a, row_b, strict=True)):
            if pa != pb:
                pixels[x, y] = REMOVED if pb == TRANSPARENT else CHANGED
    return dim


def tiled(asset: Asset, tile: str, repeat: int) -> Image.Image:
    single = frame_image(asset, tile)
    out = Image.new("RGBA", (single.width * repeat, single.height * repeat), (0, 0, 0, 0))
    for ty in range(repeat):
        for tx in range(repeat):
            out.paste(single, (tx * single.width, ty * single.height))
    return out


def animation_gif(asset: Asset, animation: str, options: PreviewOptions, path: Path, variant: str | None = None) -> None:
    anim = asset.animations[animation]
    scale = options.scale or auto_scale(asset.size)
    # GIFs only have 1-bit alpha, so always composite onto an opaque background.
    opaque = PreviewOptions(scale=scale, grid=options.grid, background="checker" if options.background == "none" else options.background)
    frames = [upscale(frame_image(asset, f, variant), scale, opaque).convert("RGB") for f in anim.frames]
    frame_ms = max(20, round(100 / anim.fps) * 10)  # GIF timing has 10ms resolution
    durations = [frame_ms] * len(frames)
    if not anim.loop:
        durations[-1] = max(frame_ms, 1000)  # one-shot: hold the last frame, then replay for viewing
    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations, loop=0, disposal=1)


@dataclass
class PreviewResult:
    asset: str
    sheet: Path
    frames: list[Path]
    gifs: list[Path]


def write_previews(asset: Asset, out_dir: Path, options: PreviewOptions) -> PreviewResult:
    scale = options.scale or auto_scale(asset.size)
    folder = out_dir / asset.name
    frames: list[Path] = []
    for variant in (None, *asset.variants):
        for name in asset.frames:
            path = folder / "frames" / (f"{name}.png" if variant is None else f"{name}@{variant}.png")
            path.parent.mkdir(parents=True, exist_ok=True)
            upscale(frame_image(asset, name, variant), scale, options).save(path)
            frames.append(path)
    gifs: list[Path] = []
    for name in asset.animations:
        path = folder / f"{name}.gif"
        animation_gif(asset, name, options, path)
        gifs.append(path)
    sheet = folder / "sheet.png"
    contact_sheet(asset, options).save(sheet)
    return PreviewResult(asset=asset.name, sheet=sheet, frames=frames, gifs=gifs)


def gallery(assets: list[Asset], options: PreviewOptions, title: str) -> Image.Image:
    """Every asset's first frame side by side at a common scale: checks the set looks cohesive."""
    if not assets:
        return _labelled_grid(title, "no assets", [])
    biggest = max(max(a.size) for a in assets)
    scale = options.scale or max(2, min(8, 192 // biggest))  # common scale, so relative sizes stay true
    rows: list[tuple[str, list[tuple[str, Image.Image]]]] = []
    for kind, heading in (("model", "3D models"), ("sprite", "sprites"), ("tileset", "tilesets")):
        cells = []
        for asset in sorted((a for a in assets if a.kind == kind), key=lambda a: a.name):
            first = next(iter(asset.frames))
            marker = "" if asset.status == "approved" else " (draft)"
            cells.append((f"{asset.name}{marker}", upscale(frame_image(asset, first), scale, options)))
            for variant in asset.variants:
                cells.append((f"{asset.name}@{variant}", upscale(frame_image(asset, first, variant), scale, options)))
        if cells:
            rows.append((heading, cells))
    return _labelled_grid(title, f"{len(assets)} assets, x{scale}", rows)
