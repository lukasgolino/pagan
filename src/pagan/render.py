"""Turn resolved asset frames into native-resolution RGBA images. Deterministic by construction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from pagan.asset import Asset, Grid, TileShape
from pagan.palette import TRANSPARENT
from pagan.project import Project

RGBA = tuple[int, int, int, int]
CLEAR: RGBA = (0, 0, 0, 0)


def color_table(asset: Asset, variant: str | None = None) -> dict[str, RGBA]:
    """Key -> RGBA for the asset's palette, or for one of its variants (alpha from "#rrggbbaa" colours)."""
    if variant is None:
        return {key: c.rgba for key, c in asset.palette.colors.items()}
    v = asset.variants[variant]
    table: dict[str, RGBA] = {}
    for key in asset.palette.colors:
        target = v.keys.get(key, key)
        if target in v.palette.colors:
            table[key] = v.palette.colors[target].rgba
    return table


def grid_image(grid: Grid, table: dict[str, RGBA]) -> Image.Image:
    height, width = len(grid), len(grid[0]) if grid else 0
    image = Image.new("RGBA", (width, height), CLEAR)
    image.putdata([CLEAR if c == TRANSPARENT else table[c] for row in grid for c in row])
    return image


def frame_image(asset: Asset, frame: str, variant: str | None = None) -> Image.Image:
    return grid_image(asset.frames[frame], color_table(asset, variant))


def sheet_columns(asset: Asset) -> int:
    """Frames per row in sheets/atlases: a tileset's `columns`, a sprite's `sheet_columns`, else up to 8."""
    count = len(asset.frames)
    if asset.kind == "tileset":
        return asset.columns
    return max(1, min(count, asset.sheet_columns or 8))


def frame_rects(asset: Asset) -> dict[str, tuple[int, int, int, int]]:
    """Frame -> (x, y, w, h) in the sheet, in source order (stable when frames are appended)."""
    width, height = asset.size
    if asset.kind == "tileset":
        cells = tile_cells(asset)
        return {name: (cells[name][0] * width, cells[name][1] * height, width, height) for name in asset.frames}
    columns = sheet_columns(asset)
    return {
        name: ((i % columns) * width, (i // columns) * height, width, height)
        for i, name in enumerate(asset.frames)
    }


def tile_origin(shape: TileShape, column: int, row: int, size: tuple[int, int]) -> tuple[int, int]:
    """Top-left pixel of map cell (column, row) as Godot 4.7.2's TileMapLayer places it (map_to_local, measured),
    for square and isometric tiles. Isometric positions step by half a tile; odd sizes round down."""
    width, height = size
    if shape.shape == "square":
        return column * width, row * height
    if shape.shape != "isometric":
        raise ValueError(f"tile_shape {shape.shape} isn't supported here (square and isometric are)")
    c, r = column, row
    # In half tiles (x, y) from the map origin's tile.
    if shape.layout in ("stacked", "stacked_offset"):
        shift = r % 2 if shape.offset_axis == "horizontal" else c % 2
        if shape.layout == "stacked_offset":
            shift = 1 - shift
        x, y = (2 * c + shift, r) if shape.offset_axis == "horizontal" else (c, 2 * r + shift)
    elif shape.layout == "stairs_right":
        x, y = 2 * c + r, r
    elif shape.layout == "stairs_down":
        x, y = c, c + 2 * r
    elif shape.layout == "diamond_right":
        x, y = c + r, r - c
    else:  # diamond_down
        x, y = c - r, c + r
    return x * width // 2, y * height // 2


def layout_image(asset: Asset, rows: list[list[str]], variant: str | None = None, shape: TileShape | None = None) -> Image.Image:
    """Tiles placed on the map: rows of tile names ("." = empty), row r column c = map cell (c, r) in the
    tileset's `tile_shape` (or `shape`). Drawn top to bottom, so tiles lower on screen overlap the ones above."""
    shape = shape or asset.tile_shape
    placed = sorted(
        ((tile_origin(shape, c, r, asset.size), name) for r, row in enumerate(rows) for c, name in enumerate(row) if name != TRANSPARENT),
        key=lambda item: (item[0][1], item[0][0]),
    )
    width, height = asset.size
    if shape.shape == "square":  # the whole grid, empty cells included (as before)
        left = top = 0
        right, bottom = max((len(r) for r in rows), default=0) * width, len(rows) * height
    elif placed:
        left, top = min(x for (x, _), _ in placed), min(y for (_, y), _ in placed)
        right, bottom = max(x for (x, _), _ in placed) + width, max(y for (_, y), _ in placed) + height
    else:
        left = top = right = bottom = 0
    image = Image.new("RGBA", (right - left, bottom - top), CLEAR)
    tiles: dict[str, Image.Image] = {}
    for (x, y), name in placed:
        if name not in tiles:
            tiles[name] = frame_image(asset, name, variant)
        image.alpha_composite(tiles[name], (x - left, y - top))
    return image


def tile_cells(asset: Asset) -> dict[str, tuple[int, int]]:
    """Atlas cell (column, row) of every tile, filled row by row in source order, `columns` wide.

    An animated tile's frames sit side by side in animation order (engines step through neighbouring
    cells), starting on a new row if they wouldn't fit in the current one (or always, with `new_row`); an
    animation longer than a row wraps into a block `columns` wide. Without animations this is plain source order.
    """
    columns = asset.columns
    animation_of = {frame: anim for anim in asset.animations.values() for frame in anim.frames}
    cells: dict[str, tuple[int, int]] = {}
    col = row = 0
    for name in asset.frames:
        if name in cells:
            continue
        anim = animation_of.get(name)
        group = anim.frames if anim is not None else (name,)
        count = len(group)
        if anim is not None and anim.new_row and col:
            col, row = 0, row + 1
        if count <= columns:
            if col + count > columns:
                col, row = 0, row + 1
            for i, frame in enumerate(group):
                cells[frame] = (col + i, row)
            col += count
            if col == columns:
                col, row = 0, row + 1
        else:
            if col:
                col, row = 0, row + 1
            for i, frame in enumerate(group):
                cells[frame] = (i % columns, row + i // columns)
            row += -(-count // columns)
    return cells


def sheet_image(asset: Asset, variant: str | None = None) -> Image.Image:
    """All frames in a grid: the sprite sheet / tileset atlas."""
    rects = frame_rects(asset)
    width = max(x + w for x, _, w, _ in rects.values())
    height = max(y + h for _, y, _, h in rects.values())
    sheet = Image.new("RGBA", (width, height), CLEAR)
    table = color_table(asset, variant)
    for name, (x, y, _, _) in rects.items():
        sheet.paste(grid_image(asset.frames[name], table), (x, y))
    return sheet


TRIM_GAP = 1  # transparent pixels between trimmed cells, so filtering never bleeds a neighbour in


@dataclass(frozen=True)
class TrimmedFrame:
    """Where a trimmed frame's crop sits, in output pixels: `rect` (x, y, w, h) in the sheet, `offset` (x, y)
    of the crop's top-left corner within the full logical frame."""

    rect: tuple[int, int, int, int]
    offset: tuple[int, int]


def content_box(grid: Grid, factor: int = 1) -> tuple[int, int, int, int]:
    """(x, y, w, h) of the grid's non-transparent pixels, in output pixels (`factor` source pixels each, rounded
    outwards so a box-filtered frame is cropped exactly). A fully transparent frame keeps its top-left pixel
    (1x1 at 0, 0), so every frame has a real region in the sheet."""
    left, right, top, bottom = len(grid[0]), 0, None, 0
    for y, row in enumerate(grid):
        stripped = row.rstrip(TRANSPARENT)
        if not stripped:
            continue
        left = min(left, len(row) - len(row.lstrip(TRANSPARENT)))
        right = max(right, len(stripped))
        if top is None:
            top = y
        bottom = y + 1
    if top is None:
        return (0, 0, 1, 1)
    x0, y0 = left // factor, top // factor
    return (x0, y0, -(-right // factor) - x0, -(-bottom // factor) - y0)


def trim_layout(asset: Asset, factor: int = 1) -> dict[str, TrimmedFrame]:
    """Trimmed frames shelf-packed in source order, in output pixels: `sheet_columns` crops per row (default up to
    8, as untrimmed), each row as tall as its tallest crop, TRIM_GAP transparent pixels between cells. Never rotated.
    The layout only depends on which pixels are transparent, so every variant shares it."""
    columns = sheet_columns(asset)
    layout: dict[str, TrimmedFrame] = {}
    x = y = row_height = 0
    for i, name in enumerate(asset.frames):
        if i and i % columns == 0:
            x, y, row_height = 0, y + row_height + TRIM_GAP, 0
        ox, oy, w, h = content_box(asset.frames[name], factor)
        layout[name] = TrimmedFrame((x, y, w, h), (ox, oy))
        x += w + TRIM_GAP
        row_height = max(row_height, h)
    return layout


def trimmed_sheet(asset: Asset, layout: dict[str, TrimmedFrame], variant: str | None = None, factor: int = 1) -> Image.Image:
    """The trimmed sheet, at output size: each frame box-filtered by `factor`, cropped and pasted at its cell."""
    width = max(f.rect[0] + f.rect[2] for f in layout.values())
    height = max(f.rect[1] + f.rect[3] for f in layout.values())
    sheet = Image.new("RGBA", (width, height), CLEAR)
    for name, frame in layout.items():
        (x, y, w, h), (ox, oy) = frame.rect, frame.offset
        image = downsample(frame_image(asset, name, variant), factor)
        sheet.paste(image.crop((ox, oy, ox + w, oy + h)), (x, y))
    return sheet


def supersample_factor(asset: Asset, project: Project) -> int:
    """How many source pixels make one output pixel on each axis: the asset's `supersample`, else the project's."""
    return asset.supersample if asset.supersample is not None else project.config.supersample


def downsample(image: Image.Image, factor: int) -> Image.Image:
    """Box-filter an RGBA image by `factor` (its size must be a multiple): each output pixel averages a
    factor x factor block, colours weighted by alpha so edges against transparency don't darken.
    Integer maths only, so output is identical on every machine."""
    if factor == 1:
        return image
    data = np.asarray(image.convert("RGBA"), dtype=np.int64)
    h, w = data.shape[0] // factor, data.shape[1] // factor
    blocks = data.reshape(h, factor, w, factor, 4)
    alpha = blocks[..., 3].sum(axis=(1, 3))
    weighted = (blocks[..., :3] * blocks[..., 3:4]).sum(axis=(1, 3))
    out = np.zeros((h, w, 4), dtype=np.int64)
    covered = alpha > 0
    out[covered, :3] = (weighted[covered] * 2 + alpha[covered][:, None]) // (alpha[covered][:, None] * 2)
    n = factor * factor
    out[..., 3] = (alpha * 2 + n) // (n * 2)
    out[out[..., 3] == 0] = 0
    return Image.fromarray(out.astype(np.uint8), "RGBA")


def save_png(image: Image.Image, path: Path) -> None:
    """Save with fixed settings and no metadata, so identical images give identical bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=False, compress_level=9)
