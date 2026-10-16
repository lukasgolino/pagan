"""Turn resolved asset frames into native-resolution RGBA images. Deterministic by construction."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from pagan.asset import Asset, Grid
from pagan.palette import TRANSPARENT

RGBA = tuple[int, int, int, int]
CLEAR: RGBA = (0, 0, 0, 0)


def color_table(asset: Asset, variant: str | None = None) -> dict[str, RGBA]:
    """Key -> RGBA for the asset's palette, or for one of its variants."""
    if variant is None:
        return {key: (*c.rgb, 255) for key, c in asset.palette.colors.items()}
    v = asset.variants[variant]
    table: dict[str, RGBA] = {}
    for key in asset.palette.colors:
        target = v.keys.get(key, key)
        if target in v.palette.colors:
            table[key] = (*v.palette.colors[target].rgb, 255)
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
    cells), starting on a new row if they wouldn't fit in the current one; an animation longer than a
    row wraps into a block `columns` wide. Without animations this is plain source order.
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


def save_png(image: Image.Image, path: Path) -> None:
    """Save with fixed settings and no metadata, so identical images give identical bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=False, compress_level=9)
