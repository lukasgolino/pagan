"""3D views of a model for review (MESH_PLAN M6): any heading and elevation, from below, and close up on one part.

A free 3D camera sees what the sprite camera never shows: undersides, steep angles, a face filling the screen.
These views are rendered by PAGAN's own voxel renderer (no engine needed), with the model's light, so they
show the palette-locked shading a mesh gets from a sun in the same direction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image

from pagan.asset import Asset, _outline
from pagan.model import ROOT_ID, MeshSource, part_cells
from pagan.render import color_table, grid_image
from pagan.voxel import Camera, Cell, VoxelModel, heading_angles, render_heading

ORBIT_ELEVATIONS = (-30.0, 0.0, 30.0, 60.0, 90.0)  # below the horizon, level, 3/4, steep, straight down
CLOSEUP_ELEVATIONS = (-30.0, 15.0, 50.0)
ORBIT_HEADINGS = 8
MAX_CELL = 160  # pixels: big models render at a smaller scale so a sheet stays readable


@dataclass
class View:
    label: str
    image: Image.Image


def rest_model(source: MeshSource) -> VoxelModel:
    """The model as it rests: hidden parts hidden."""
    return source.model.posed({}, set(source.hidden))


def _reach(cells: list[Cell] | set[Cell], centre: tuple[float, float, float]) -> float:
    xs, ys, zs = ([c[i] for c in cells] for i in range(3))
    corners = [(x, y, z) for x in (min(xs), max(xs) + 1) for y in (min(ys), max(ys) + 1) for z in (min(zs), max(zs) + 1)]
    return max(math.dist(c, centre) for c in corners)


def render_view(
    asset: Asset, model: VoxelModel, centre: tuple[float, float, float], heading: float, elevation: float, scale: float, size: int
) -> Image.Image:
    """One view of `model` at 1x: `centre` (model space) lands in the middle of a size x size image."""
    source: MeshSource = asset.mesh
    grid = render_heading(
        model, source.materials, heading=heading, size=(size, size), origin=centre, pivot=(size // 2, size // 2),
        camera=Camera(elevation, scale), light=source.light,
    )  # fmt: skip
    if asset.outline and asset.outline_color is not None:
        grid = _outline(grid, asset.outline_color)
    return grid_image(grid, color_table(asset))


def _fit(reach: float, wanted_scale: float, limit: int) -> tuple[float, int]:
    """(pixels per voxel, image size) so a sphere of `reach` voxels fits: the wanted scale, smaller if needed."""
    scale = min(wanted_scale, (limit - 6) / (2 * reach)) if reach > 0 else wanted_scale
    return scale, 2 * math.ceil(reach * scale) + 6


def orbit_views(asset: Asset, camera_scale: float, elevations: tuple[float, ...] = ORBIT_ELEVATIONS) -> list[tuple[str, list[View]]]:
    """Rows of views: one row per elevation, one view per heading (e, ne, n, ... seen from that side)."""
    source: MeshSource = asset.mesh
    model = rest_model(source)
    cells = list(model.voxels)
    if not cells:
        return []
    xs, ys, zs = ([c[i] for c in cells] for i in range(3))
    centre = ((min(xs) + max(xs) + 1) / 2, (min(ys) + max(ys) + 1) / 2, (min(zs) + max(zs) + 1) / 2)
    scale, size = _fit(_reach(cells, centre), camera_scale, MAX_CELL)
    rows = []
    for elevation in elevations:
        where = "below" if elevation < 0 else ("level" if elevation == 0 else ("from above" if elevation == 90 else "above"))
        views = [View(name, render_view(asset, model, centre, angle, elevation, scale, size)) for name, angle in heading_angles(ORBIT_HEADINGS)]
        rows.append((f"elevation {elevation:+g}° ({where})", views))
    return rows


def closeup_views(asset: Asset, part_id: str, size: int = 96) -> list[tuple[str, list[View]]]:
    """One part filling the view, in place (other parts may cover it, as in game) and on its own."""
    source: MeshSource = asset.mesh
    cells = sorted(part_cells(source.model).get(part_id, set()))
    if not cells:
        raise KeyError(part_id)
    xs, ys, zs = ([c[i] for c in cells] for i in range(3))
    centre = ((min(xs) + max(xs) + 1) / 2, (min(ys) + max(ys) + 1) / 2, (min(zs) + max(zs) + 1) / 2)
    reach = max(_reach(cells, centre), 1.0)
    scale = max(1.0, min(16.0, (size - 12) / (2 * reach)))
    shown = source.model.posed({}, set(source.hidden) - {part_id})  # a hidden part is shown for its closeup
    alone = _only(shown, part_id)
    rows = []
    context = max(1.0, scale / 1.6)  # in place, the part fills ~60% of the view: its surroundings show too
    for elevation in CLOSEUP_ELEVATIONS:
        views = [View(name, render_view(asset, shown, centre, angle, elevation, context, size)) for name, angle in heading_angles(ORBIT_HEADINGS)]
        rows.append((f"{part_id} in place, elevation {elevation:+g}°", views))
    views = [View(name, render_view(asset, alone, centre, angle, 30.0, scale, size)) for name, angle in heading_angles(ORBIT_HEADINGS)]
    rows.append((f"{part_id} on its own, elevation +30°", views))
    return rows


def _only(model: VoxelModel, part_id: str) -> VoxelModel:
    """Just one part's voxels (voxels without an id are ROOT_ID's)."""
    out = VoxelModel()
    for cell in model.voxels:
        if model.groups.get(cell, ROOT_ID) == part_id:
            out._put(cell, model._data(cell))
    return out


def thumbnail(asset: Asset, camera: Camera, limit: int) -> Image.Image:
    """A mesh-only model for the gallery: the project camera's elevation, a 3/4 heading, fitted to `limit` px."""
    source: MeshSource = asset.mesh
    model = rest_model(source)
    cells = list(model.voxels)
    if not cells:
        return Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    xs, ys, zs = ([c[i] for c in cells] for i in range(3))
    centre = ((min(xs) + max(xs) + 1) / 2, (min(ys) + max(ys) + 1) / 2, (min(zs) + max(zs) + 1) / 2)
    scale, size = _fit(_reach(cells, centre), camera.scale, limit)
    return render_view(asset, model, centre, 315.0, camera.elevation, scale, size)
