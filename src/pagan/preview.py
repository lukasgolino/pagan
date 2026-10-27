"""Upscaled previews for looking at art: frames, contact sheets, animated GIFs, tiling checks, gallery.

Previews are for humans and agents to *look at*; they are not build output and need not be byte-stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from PIL import Image, ImageDraw

from pagan.asset import Asset, Grid, axis_combinations
from pagan.palette import TRANSPARENT
from pagan.render import downsample, frame_image, layout_image, save_png, sheet_image
from pagan.swatch import Font, _font
from pagan.views import View, closeup_views, orbit_views, thumbnail
from pagan.voxel import Camera

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


def preview_variants(asset: Asset, every_combination: bool = False) -> Asset:
    """The asset with the variants previews show. With `variant_axes`: its plain variants plus each axis option
    on its own (named "<axis>.<option>", as in the manifest; options that leave the axis as it is are the base),
    not every combination, which grows as the product of the axes. `every_combination`: every combination
    instead of the options (as `variant_sheets = true` builds them)."""
    if not asset.variant_axes:
        return asset
    plain = {name: v for name, v in asset.variants.items() if "+" not in name}  # "+" can't occur in a variant name
    if every_combination:
        combos = {name: v for name, v in asset.variants.items() if "+" in name}
        return replace(asset, variants={**plain, **(combos or axis_combinations(asset.variant_axes, asset.palette))})
    options = {
        f"{axis}.{name}": replace(v, name=f"{axis}.{name}")
        for axis, choices in asset.variant_axes.items()
        for name, v in choices.items()
        if any(target != key for key, target in v.keys.items())
    }
    return replace(asset, variants={**plain, **options})


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


Cell = tuple[str, Image.Image]
Row = tuple[str, list[Cell]]
Unit = tuple[str, str, list[Cell]]  # a line of cells: (its row's heading, the heading drawn above it or "", cells)


def _cell_width(measure: ImageDraw.ImageDraw, font: Font, label: str, img: Image.Image) -> int:
    return max(img.width, int(measure.textlength(label, font=font))) + PAD


def _units(rows: list[Row], measure: ImageDraw.ImageDraw, font: Font, max_width: int | None) -> list[Unit]:
    """Rows wrapped into lines of at most MAX_PER_ROW cells (and `max_width` px, when given; a cell wider
    than that gets a line of its own)."""
    units: list[Unit] = []
    for heading, cells in rows:
        chunks: list[list[Cell]]
        if max_width is None:
            chunks = [cells[i : i + MAX_PER_ROW] for i in range(0, len(cells), MAX_PER_ROW)] or [[]]
        else:
            chunks, width = [], PAD * 2
            current: list[Cell] = []
            for label, img in cells:
                w = _cell_width(measure, font, label, img)
                if current and (len(current) == MAX_PER_ROW or width + w > max_width):
                    chunks.append(current)
                    current, width = [], PAD * 2
                current.append((label, img))
                width += w
            chunks.append(current)
        for i, chunk in enumerate(chunks):
            units.append((heading, heading if i == 0 else "", chunk))
    return units


def _unit_height(unit: Unit) -> int:
    _, shown, chunk = unit
    return (LABEL_H if shown else 0) + max((img.height for _, img in chunk), default=0) + LABEL_H + PAD


def _header_height(subtitle: str) -> int:
    return PAD + 24 + (LABEL_H if subtitle else 0)


def _draw_grid(title: str, subtitle: str, units: list[Unit]) -> Image.Image:
    font, title_font = _font(12), _font(16)
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    width = max(PAD * 2 + int(measure.textlength(title, font=title_font)), PAD * 2 + int(measure.textlength(subtitle, font=font)))
    height = _header_height(subtitle)
    for unit in units:
        chunk = unit[2]
        width = max(width, PAD * 2 + sum(_cell_width(measure, font, label, img) for label, img in chunk))
        height += _unit_height(unit)

    sheet = Image.new("RGBA", (width, height), (*BG_DARK, 255))
    draw = ImageDraw.Draw(sheet)
    draw.text((PAD, PAD), title, font=title_font, fill=TEXT)
    y = PAD + 24
    if subtitle:
        draw.text((PAD, y - 4), subtitle, font=font, fill=MUTED)
        y += LABEL_H
    for _, shown, chunk in units:
        if shown:
            draw.text((PAD, y), shown, font=font, fill=MUTED)
            y += LABEL_H
        x = PAD
        row_h = max((img.height for _, img in chunk), default=0)
        for label, img in chunk:
            sheet.alpha_composite(img, (x, y))
            draw.text((x, y + img.height + 2), label, font=font, fill=TEXT)
            x += max(img.width, int(draw.textlength(label, font=font))) + PAD
        y += row_h + LABEL_H + PAD
    return sheet


def _labelled_grid(title: str, subtitle: str, rows: list[Row]) -> Image.Image:
    """Rows of labelled cells under section headings. All cells in a row share a size."""
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    return _draw_grid(title, subtitle, _units(rows, measure, _font(12), None))


def _grid_size(title: str, subtitle: str, rows: list[Row]) -> tuple[int, int]:
    """The size _labelled_grid would draw, without drawing it."""
    font, title_font = _font(12), _font(16)
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    units = _units(rows, measure, font, None)
    width = max(PAD * 2 + int(measure.textlength(title, font=title_font)), PAD * 2 + int(measure.textlength(subtitle, font=font)))
    width = max([width, *(PAD * 2 + sum(_cell_width(measure, font, label, img) for label, img in u[2]) for u in units)])
    return width, _header_height(subtitle) + sum(_unit_height(u) for u in units)


def _paged_grid(title: str, subtitle: str, rows: list[Row], cap: int) -> list[Image.Image]:
    """The labelled grid wrapped to at most `cap` px wide and split into pages at most `cap` px tall (a single
    cell bigger than that still gets a page of its own). A row carried over to the next page repeats its heading."""
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    units = _units(rows, measure, _font(12), cap)
    page_subtitle = f"{subtitle} · page 1/9999" if subtitle else "page 1/9999"  # room for the page number
    pages: list[list[Unit]] = [[]]
    height = _header_height(page_subtitle)
    for heading, shown, chunk in units:
        unit = (heading, shown, chunk)
        if pages[-1] and height + _unit_height(unit) > cap:
            pages.append([])
            height = _header_height(page_subtitle)
            if not shown and heading:
                unit = (heading, f"{heading} (continued)", chunk)
        pages[-1].append(unit)
        height += _unit_height(unit)
    if len(pages) == 1:
        return [_draw_grid(title, subtitle, pages[0])]
    return [_draw_grid(title, f"{subtitle} · page {i}/{len(pages)}" if subtitle else f"page {i}/{len(pages)}", page) for i, page in enumerate(pages, 1)]


SHEET_CAP = 4096  # px: a contact sheet bigger than this on either side is split into pages


@dataclass
class _SheetParts:
    """A contact sheet's rows, whole and split into an overview and one page per animation."""

    title: str
    subtitle: str
    whole: list[Row]
    overview: list[Row]
    pages: dict[str, list[Row]]  # animation (models: pose, across headings) -> its rows


def _sheet_parts(asset: Asset, options: PreviewOptions, supersample: int) -> _SheetParts:
    scale = options.scale or auto_scale(asset.size)
    images: dict[tuple[str, str | None], Image.Image] = {}

    def cell(name: str, variant: str | None = None) -> Cell:
        if (name, variant) not in images:
            images[(name, variant)] = upscale(frame_image(asset, name, variant), scale, options)
        return name, images[(name, variant)]

    changes: dict[str, Row] = {}
    for anim in asset.animations.values():
        if len(anim.frames) < 2:
            continue
        cells = []
        for i, name in enumerate(anim.frames):
            previous = anim.frames[i - 1]  # frame 0 compares with the last (the loop seam)
            cells.append((f"{previous}->{name}", upscale(change_image(asset, previous, name), scale, options)))
        changes[anim.name] = (f"{anim.name}: changes (magenta = changed/new pixel, cyan = pixel removed)", cells)

    rows: list[Row] = []
    overview: list[Row] = []
    pages: dict[str, list[Row]] = {}
    if asset.kind == "model":
        # One row per heading: the static frame, then that heading's animation frames.
        headings = [a.name for a in asset.animations.values() if a.frames == (a.name,)]
        animated = len(asset.animations) > len(headings)
        if not animated:  # static model: all headings together, wrapping in rows
            rows.append(("headings", [cell(h) for h in headings]))
        for heading in headings if animated else []:
            names = [heading] + [f for a in asset.animations.values() if a.name.endswith(f"_{heading}") for f in a.frames]
            rows.append((f"heading {heading}", [cell(n) for n in names]))
        variant_rows: list[Row] = [(v, [cell(h, v) for h in headings]) for v in asset.variants]
        rows += variant_rows
        overview += [("headings", [cell(h) for h in headings]), *variant_rows]
        for anim in asset.animations.values():
            if anim.name in headings:
                continue
            # "<pose>_<heading>" (one heading: just "<pose>"); a pose's page has its heading rows, then their changes
            match = next((h for h in headings if len(headings) > 1 and anim.name.endswith(f"_{h}")), None)
            facing, pose = (match, anim.name[: -len(match) - 1]) if match else (headings[0], anim.name)
            page = pages.setdefault(pose, [])
            at = sum(1 for heading, _ in page if heading.startswith("heading "))
            page.insert(at, (f"heading {facing}", [cell(f) for f in anim.frames]))
            if anim.name in changes:
                page.append(changes[anim.name])
    else:
        animated_frames = {f for a in asset.animations.values() for f in a.frames}
        for variant in (None, *asset.variants):
            label = "" if variant is None and not asset.variants else (variant or base_label(asset))
            rows.append((label, [cell(name, variant) for name in asset.frames]))
            loose = [cell(name, variant) for name in asset.frames if name not in animated_frames]
            if loose:
                overview.append((label, loose))
        for anim in asset.animations.values():
            frames = list(dict.fromkeys(anim.frames))
            for variant in (None, *asset.variants):
                label = "" if variant is None and not asset.variants else (variant or base_label(asset))
                pages.setdefault(anim.name, []).append((label, [cell(name, variant) for name in frames]))
            if anim.name in changes:
                pages[anim.name].append(changes[anim.name])
    extra: list[Row] = []
    if supersample > 1:
        # What the game gets: each frame box-filtered down, shown at the same on-screen size as the source.
        names = [a.name for a in asset.animations.values() if a.frames == (a.name,)] if asset.kind == "model" else list(asset.frames)
        cells = [(n, upscale(downsample(frame_image(asset, n), supersample), scale * supersample, options)) for n in names]
        extra.append((f"as built: 1/{supersample} size, box-filtered (shown x{scale * supersample}; 1x: built_1x.png)", cells))
    if asset.kind == "tileset":
        extra.append(("tiled 3x3 (check seams)", [(name, upscale(tiled(asset, name, 3), max(1, scale // 2), options)) for name in asset.frames]))
    if asset.textures is not None and asset.textures.groups:
        from pagan.api import compose  # local import: api builds on most modules

        cells = []
        for name, group in asset.textures.groups.items():
            layout = [" ".join(row) for row in group] * 2
            image = compose(asset, [f"{row} {row}" for row in layout])
            cells.append((name, upscale(image, max(1, scale // 2), options)))
        extra.append(("texture groups tiled 2x2 (check seams)", cells))
    summary: list[Row] = []
    if asset.animations and asset.kind != "model":
        text = ", ".join(
            f"{a.name} ({len(a.frames)}f @ {a.fps:g}fps{'' if a.loop else ', once'}{'' if a.loop_from is None else f', loops from {a.loop_from}'})"
            for a in asset.animations.values()
        )
        summary.append((f"animations: {text}", []))
    rows += extra + list(changes.values()) + summary
    width, height = asset.size
    palette = asset.palette.name or "inline palette"
    subtitle = f"{asset.kind} · {palette} · {asset.status} · style v{asset.style_version}"
    if asset.description:
        subtitle += f" · {asset.description[:90]}{'…' if len(asset.description) > 90 else ''}"
    return _SheetParts(f"{asset.name}  {width}x{height}  x{scale}", subtitle, rows, overview + extra, pages)


def contact_sheet(asset: Asset, options: PreviewOptions, supersample: int = 1) -> Image.Image:
    """Every frame, heading, variant and animation "changes" row on one labelled sheet (any size)."""
    parts = _sheet_parts(asset, options, supersample)
    return _labelled_grid(parts.title, parts.subtitle, parts.whole)


def _page_names(stem: str, count: int) -> list[str]:
    return [f"{stem}.png" if i == 1 else f"{stem}.{i}.png" for i in range(1, count + 1)]


def contact_pages(asset: Asset, options: PreviewOptions, supersample: int = 1, cap: int | None = None) -> list[tuple[str, Image.Image]]:
    """The contact sheet as (file name, image) pages. A sheet within `cap` px (default SHEET_CAP) on both sides is one page,
    sheet.png (the whole contact sheet). A bigger one is split: sheet.png = an overview (headings or frames
    outside animations, variants, as-built/tiling rows) with an index of the other pages, and one page per
    animation, sheet.<animation>.png (models: one per pose, every heading on it). A page still bigger than
    `cap` continues on sheet.<animation>.2.png, .3, ... (the overview on sheet.2.png, ...); rows wrap to fit
    `cap` px wide."""
    cap = cap or SHEET_CAP
    parts = _sheet_parts(asset, options, supersample)
    width, height = _grid_size(parts.title, parts.subtitle, parts.whole)
    if width <= cap and height <= cap:
        return [("sheet.png", _labelled_grid(parts.title, parts.subtitle, parts.whole))]
    out: list[tuple[str, Image.Image]] = []
    index: list[Row] = []
    for anim, rows in parts.pages.items():
        images = _paged_grid(f"{parts.title}  animation {anim}", parts.subtitle, rows, cap)
        names = _page_names(f"sheet.{anim}", len(images))
        out += zip(names, images, strict=True)
        index.append((f"animation {anim}: {', '.join(names)}", []))
    overview = _paged_grid(parts.title, parts.subtitle, [*parts.overview, *index], cap)
    return [*zip(_page_names("sheet", len(overview)), overview, strict=True), *out]


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
    if asset.tile_shape.shape == "isometric":  # neighbours as the map places them
        return layout_image(asset, [[tile] * repeat for _ in range(repeat)])
    single = frame_image(asset, tile)
    out = Image.new("RGBA", (single.width * repeat, single.height * repeat), (0, 0, 0, 0))
    for ty in range(repeat):
        for tx in range(repeat):
            out.paste(single, (tx * single.width, ty * single.height))
    return out


LOOP_FROM_REPEATS = 3  # preview GIFs of a `loop_from` animation show its looping part this many times per replay


def animation_gif(asset: Asset, animation: str, options: PreviewOptions, path: Path, variant: str | None = None) -> None:
    anim = asset.animations[animation]
    scale = options.scale or auto_scale(asset.size)
    # GIFs only have 1-bit alpha, so always composite onto an opaque background.
    opaque = PreviewOptions(scale=scale, grid=options.grid, background="checker" if options.background == "none" else options.background)
    frames = [upscale(frame_image(asset, f, variant), scale, opaque).convert("RGB") for f in anim.frames]
    steps = anim.durations or (1.0,) * len(frames)
    durations = [max(20, round(100 * step / anim.fps) * 10) for step in steps]  # GIF timing has 10ms resolution
    if anim.loop_from is not None:  # a GIF can only replay everything: the intro once, then the loop LOOP_FROM_REPEATS times
        n = anim.loop_from
        frames += frames[n:] * (LOOP_FROM_REPEATS - 1)
        durations += durations[n:] * (LOOP_FROM_REPEATS - 1)
    frame_ms = durations[-1]
    if not anim.loop:
        durations[-1] = max(frame_ms, 1000)  # one-shot: hold the last frame, then replay for viewing
    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations, loop=0, disposal=1)


@dataclass
class PreviewResult:
    asset: str
    sheet: Path
    montage: Path
    frames: list[Path]
    gifs: list[Path]
    scale: int
    variants: Path | None = None  # base + every variant side by side (only when the asset has variants)
    variants_1x: Path | None = None
    built_1x: Path | None = None  # supersampled assets: the frames as built, 1x
    native: list[Path] = field(default_factory=list)  # 1x frames and sheets (native/), as `pagan render` writes
    sheet_pages: list[Path] = field(default_factory=list)  # a sheet over SHEET_CAP px: the pages after sheet.png


def base_label(asset: Asset) -> str:
    """What the base colours are called next to the variants: the asset's base_variant, or "base"."""
    return asset.base_variant or "base"


def built_strip(asset: Asset, supersample: int, gap: int = 1) -> Image.Image:
    """Every main frame as the build writes it (box-filtered by `supersample`), at 1x on transparent."""
    names = [a.name for a in asset.animations.values() if a.frames == (a.name,)] if asset.kind == "model" else list(asset.frames)
    width, height = asset.size[0] // supersample, asset.size[1] // supersample
    strip = Image.new("RGBA", (len(names) * (width + gap) - gap, height), (0, 0, 0, 0))
    for i, name in enumerate(names):
        strip.alpha_composite(downsample(frame_image(asset, name), supersample), (i * (width + gap), 0))
    return strip


def representative_frame(asset: Asset) -> str:
    """The frame that stands for the asset: the first one with any pixels (a model's first heading; not a
    tileset's deliberately empty first tile), else the first frame."""
    drawn = (name for name, grid in asset.frames.items() if any(c != TRANSPARENT for row in grid for c in row))
    return next(drawn, next(iter(asset.frames)))


def variants_image(asset: Asset, options: PreviewOptions, frame: str | None = None) -> Image.Image:
    """The same frame in the base colours and every variant, labelled, at the preview scale."""
    scale = options.scale or auto_scale(asset.size)
    frame = frame or representative_frame(asset)
    cells = [(name or base_label(asset), upscale(frame_image(asset, frame, name), scale, options)) for name in (None, *asset.variants)]
    return _labelled_grid(f"{asset.name} variants  x{scale}", f"frame {frame} (pick another: --frame NAME)", [("", cells)])


def variants_strip(asset: Asset, gap: int = 1, frame: str | None = None) -> Image.Image:
    """The same comparison at 1x on a transparent background (how they'll look in game)."""
    frame = frame or representative_frame(asset)
    names = (None, *asset.variants)
    width, height = asset.size
    strip = Image.new("RGBA", (len(names) * (width + gap) - gap, height), (0, 0, 0, 0))
    for i, name in enumerate(names):
        strip.alpha_composite(frame_image(asset, frame, name), (i * (width + gap), 0))
    return strip


def variants_grid(asset: Asset, images: dict[str | None, Image.Image], options: PreviewOptions, subtitle: str) -> Image.Image:
    """Already-drawn images (e.g. a tile scene) per variant (None = base), labelled side by side."""
    first = next(iter(images.values()))
    scale = options.scale or max(1, auto_scale((first.width, first.height)))
    cells = [(name or base_label(asset), upscale(image, scale, options)) for name, image in images.items()]
    return _labelled_grid(f"{asset.name} variants  x{scale}", subtitle, [("", cells)])


def write_native(asset: Asset, out_dir: Path) -> list[Path]:
    """1x PNGs of every frame and the sheet (base and each variant) in <out_dir>/<asset>/native/."""
    base = out_dir / asset.name / "native"
    written: list[Path] = []
    for variant in (None, *asset.variants):
        folder = base if variant is None else base / variant
        for frame in asset.frames:
            path = folder / "frames" / f"{frame}.png"
            save_png(frame_image(asset, frame, variant), path)
            written.append(path)
        sheet = folder / "sheet.png"
        save_png(sheet_image(asset, variant), sheet)
        written.append(sheet)
    return written


def montage(asset: Asset, options: PreviewOptions, per_row: int = 8) -> Image.Image:
    """The main frames packed tightly on the background, no labels: how they'll look side by side in game.

    Models: one frame per heading; sprites and tilesets: every frame.
    """
    scale = options.scale or auto_scale(asset.size)
    if asset.kind == "model":
        names = [a.name for a in asset.animations.values() if a.frames == (a.name,)]
    else:
        names = list(asset.frames)
    width, height = asset.size[0] * scale, asset.size[1] * scale
    columns = max(1, min(per_row, len(names)))
    rows = -(-len(names) // columns)
    out = _background((columns * width, rows * height), options.background, max(4, scale))
    for i, name in enumerate(names):
        frame = upscale(frame_image(asset, name), scale, PreviewOptions(scale=scale, grid=options.grid, background="none"))
        out.alpha_composite(frame, ((i % columns) * width, (i // columns) * height))
    return out


def views_sheet(
    asset: Asset, rows: list[tuple[str, list[View]]], options: PreviewOptions, title: str, engine: bool = False
) -> Image.Image:
    """Labelled rows of 3D views (orbit, closeup, engine) at one scale."""
    biggest = max((max(v.image.size) for _, views in rows for v in views), default=1)
    scale = options.scale or max(1, min(8, 128 // biggest))
    cells = [(heading, [(v.label, upscale(v.image, scale, options)) for v in views]) for heading, views in rows]
    how = "Godot's renderer: PAGAN ramp shader, one sun, shadows" if engine else "PAGAN's renderer with the project light (no engine needed)"
    subtitle = f"headings: the way the model's front faces (e = right); {how}"
    return _labelled_grid(f"{asset.name}  {title}  x{scale}", subtitle, cells)


def write_orbit(asset: Asset, out_dir: Path, options: PreviewOptions, camera_scale: float) -> Path:
    """orbit.png: every heading at elevations from below (-30) to straight down (90)."""
    path = out_dir / asset.name / "orbit.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    views_sheet(asset, orbit_views(asset, camera_scale), options, "orbit").save(path)
    return path


def write_closeup(asset: Asset, part_id: str, out_dir: Path, options: PreviewOptions) -> Path:
    """closeup_<part>.png: one part filling the view (KeyError if the model has no such part)."""
    path = out_dir / asset.name / f"closeup_{part_id}.png"
    rows = closeup_views(asset, part_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    views_sheet(asset, rows, options, f"closeup {part_id}").save(path)
    return path


def write_previews(
    asset: Asset, out_dir: Path, options: PreviewOptions, supersample: int = 1, frame: str | None = None, camera: Camera | None = None
) -> PreviewResult:
    """Every preview of one asset, plus its 1x frames (as `pagan render` writes them) for scripted montages.
    `frame`: the frame variants.png compares (default: the first one with pixels). A mesh-only model (no
    frames) gets its orbit sheet as `sheet` and a 3/4 view as `montage`."""
    folder = out_dir / asset.name
    if asset.mesh_only:
        camera = camera or Camera()
        sheet = write_orbit(asset, out_dir, options, camera.scale)
        montage_path = folder / "montage.png"
        view = thumbnail(asset, camera, 256)
        upscale(view, options.scale or auto_scale(view.size), options).save(montage_path)
        return PreviewResult(asset=asset.name, sheet=sheet, montage=montage_path, frames=[], gifs=[], scale=options.scale or 1)
    scale = options.scale or auto_scale(asset.size)
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
    for stale in folder.glob("sheet.*.png"):  # pages of an earlier, bigger sheet
        stale.unlink()
    sheet_pages: list[Path] = []
    for name, image in contact_pages(asset, options, supersample):
        image.save(folder / name)
        sheet_pages.append(folder / name)
    montage_path = folder / "montage.png"
    montage(asset, options).save(montage_path)
    result = PreviewResult(asset=asset.name, sheet=sheet_pages[0], montage=montage_path, frames=frames, gifs=gifs, scale=scale)
    result.sheet_pages = sheet_pages[1:]
    result.native = write_native(asset, out_dir)
    if asset.variants:
        result.variants = folder / "variants.png"
        variants_image(asset, options, frame).save(result.variants)
        result.variants_1x = folder / "variants_1x.png"
        variants_strip(asset, frame=frame).save(result.variants_1x)
    if supersample > 1:
        result.built_1x = folder / "built_1x.png"
        built_strip(asset, supersample).save(result.built_1x)
    return result


def gallery(assets: list[Asset], options: PreviewOptions, title: str, camera: Camera | None = None) -> Image.Image:
    """Every asset's first frame side by side at a common scale: checks the set looks cohesive."""
    if not assets:
        return _labelled_grid(title, "no assets", [])
    biggest = max((max(a.size) for a in assets if not a.mesh_only), default=64)
    scale = options.scale or max(2, min(8, 192 // biggest))  # common scale, so relative sizes stay true
    rows: list[tuple[str, list[tuple[str, Image.Image]]]] = []
    meshes = sorted((a for a in assets if a.mesh_only), key=lambda a: a.name)
    if meshes:  # no sprite frames: a 3/4 view at the project camera's elevation, fitted to the biggest frame
        camera = camera or Camera()
        cells = [(f"{a.name}{'' if a.status == 'approved' else ' (draft)'}", upscale(thumbnail(a, camera, biggest), scale, options)) for a in meshes]
        rows.append(("3D meshes (mesh only)", cells))
    for kind, heading in (("model", "3D models"), ("sprite", "sprites"), ("tileset", "tilesets")):
        cells = []
        for asset in sorted((a for a in assets if a.kind == kind and not a.mesh_only), key=lambda a: a.name):
            first = next(iter(asset.frames))
            marker = "" if asset.status == "approved" else " (draft)"
            cells.append((f"{asset.name}{marker}", upscale(frame_image(asset, first), scale, options)))
            for variant in asset.variants:
                cells.append((f"{asset.name}@{variant}", upscale(frame_image(asset, first, variant), scale, options)))
        if cells:
            rows.append((heading, cells))
    return _labelled_grid(title, f"{len(assets)} assets, x{scale}", rows)
