"""Turn resolved asset frames into native-resolution RGBA images. Deterministic by construction."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from pagan.asset import Asset, Grid
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
    """Frames per row in sheets/atlases: a tileset's `columns`, else up to 8."""
    count = len(asset.frames)
    return asset.columns if asset.kind == "tileset" else max(1, min(count, 8))


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
