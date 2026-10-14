"""3D voxel models: text-described shapes rendered by PAGAN into consistent, palette-shaded frames.

A model is built from primitive parts (box, hull, cylinder, ellipsoid, line, sail) and/or literal layer
grids, each with a material (a ramp of palette keys, dark -> light). PAGAN renders it from N headings with
the project's fixed camera and light, so every 3D asset in a project is projected and lit identically.

Coordinates: x forward (the model's front faces +x), y to the model's left, z up; units are voxels.
Heading 0 shows the front pointing right ("e"); headings go counter-clockwise like a compass seen from above.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from pagan.palette import TRANSPARENT

Cell = tuple[int, int, int]
Vec = tuple[float, float, float]

DIRECTION_NAMES = {
    1: ["main"],
    4: ["e", "n", "w", "s"],
    8: ["e", "ne", "n", "nw", "w", "sw", "s", "se"],
    16: ["e", "ene", "ne", "nne", "n", "nnw", "nw", "wnw", "w", "wsw", "sw", "ssw", "s", "sse", "se", "ese"],
}


@dataclass(frozen=True)
class Material:
    name: str
    keys: tuple[str, ...]  # dark -> light; one key = flat color
    two_sided: bool = False  # thin surfaces (cloth, leaves): lit from either side


@dataclass(frozen=True)
class Camera:
    elevation: float = 42.0  # degrees above the horizon (90 = straight down)
    scale: float = 1.0  # pixels per voxel


@dataclass(frozen=True)
class Light:
    direction: Vec = (-0.5, 0.45, 0.75)  # world space, towards the light: from the top-left of the screen
    ambient: float = 0.2  # brightness of fully unlit surfaces, 0..1
    shadows: bool = True
    wrap: float = 0.3  # light wraps this far around curves (softer, more readable pixel-art shading)
    shadow_strength: float = 0.65  # how much a cast shadow removes of the direct light


@dataclass
class VoxelModel:
    voxels: dict[Cell, str] = field(default_factory=dict)  # cell -> material name
    groups: dict[Cell, str] = field(default_factory=dict)  # cell -> part id (for poses)
    normals: dict[Cell, Vec] = field(default_factory=dict)  # exact normals from shapes that know them (sails)
    parts: dict[Cell, int] = field(default_factory=dict)  # cell -> index of the part that made it (no self-shadowing)
    hidden_by_default: set[str] = field(default_factory=set)  # part ids only shown by poses that `show` them

    def bounds(self) -> tuple[Cell, Cell]:
        xs = [c[0] for c in self.voxels]
        ys = [c[1] for c in self.voxels]
        zs = [c[2] for c in self.voxels]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    def posed(self, pose: dict[str, Cell], hidden: set[str]) -> VoxelModel:
        """A copy with whole parts moved by integer offsets (keeps animation frames pixel-consistent)."""
        if not pose and not hidden:
            return self
        out = VoxelModel()
        moved: list[tuple[Cell, Cell, str, str]] = []
        for cell, material in self.voxels.items():
            group = self.groups.get(cell)
            if group in hidden:
                continue
            if group is not None and group in pose:
                dx, dy, dz = pose[group]
                moved.append((cell, (cell[0] + dx, cell[1] + dy, cell[2] + dz), material, group))
            else:
                out.voxels[cell] = material
                if group is not None:
                    out.groups[cell] = group
                if cell in self.normals:
                    out.normals[cell] = self.normals[cell]
                if cell in self.parts:
                    out.parts[cell] = self.parts[cell]
        for old, cell, material, group in moved:  # moved parts draw over static ones
            out.voxels[cell] = material
            out.groups[cell] = group
            if old in self.parts:
                out.parts[cell] = self.parts[old]
            if old in self.normals:
                out.normals[cell] = self.normals[old]
            else:
                out.normals.pop(cell, None)
        return out


# --- normals and shading ----------------------------------------------------------------------

_NEIGHBOURHOOD = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1) if dx or dy or dz]


def _normal(model: VoxelModel, cell: Cell, cache: dict[Cell, Vec]) -> Vec:
    """Smoothed surface normal: points away from occupied neighbours (an occupancy gradient)."""
    if cell in cache:
        return cache[cell]
    x, y, z = cell
    nx = ny = nz = 0.0
    for dx, dy, dz in _NEIGHBOURHOOD:
        if (x + dx, y + dy, z + dz) not in model.voxels:
            weight = 1 / math.sqrt(dx * dx + dy * dy + dz * dz)
            nx += dx * weight
            ny += dy * weight
            nz += dz * weight
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    normal: Vec = (nx / length, ny / length, nz / length) if length > 1e-9 else (0.0, 0.0, 1.0)
    cache[cell] = normal
    return normal


def _shade(material: Material, intensity: float) -> str:
    steps = len(material.keys)
    index = min(steps - 1, max(0, int(intensity * steps)))
    return material.keys[index]


# --- ray traversal ----------------------------------------------------------------------------


def _traverse(
    model: VoxelModel, origin: Vec, direction: Vec, lo: Cell, hi: Cell, t_limit: float = 1e9, skip_part: int | None = None
) -> tuple[Cell, float] | None:
    """First occupied cell along the ray (Amanatides & Woo grid traversal), clipped to [lo, hi]."""
    t_enter, t_exit = 0.0, t_limit
    for axis in range(3):
        o, d = origin[axis], direction[axis]
        a, b = lo[axis], hi[axis] + 1
        if abs(d) < 1e-12:
            if o < a or o > b:
                return None
            continue
        t0, t1 = (a - o) / d, (b - o) / d
        if t0 > t1:
            t0, t1 = t1, t0
        t_enter, t_exit = max(t_enter, t0), min(t_exit, t1)
        if t_enter > t_exit:
            return None
    t = t_enter + 1e-7
    point = [origin[i] + direction[i] * t for i in range(3)]
    cell = [min(max(math.floor(point[i]), lo[i]), hi[i]) for i in range(3)]
    step = [1 if direction[i] > 0 else -1 for i in range(3)]
    t_max = []
    t_delta = []
    for i in range(3):
        if abs(direction[i]) < 1e-12:
            t_max.append(math.inf)
            t_delta.append(math.inf)
        else:
            boundary = cell[i] + (1 if direction[i] > 0 else 0)
            t_max.append(t + (boundary - point[i]) / direction[i])
            t_delta.append(abs(1 / direction[i]))
    voxels = model.voxels
    parts = model.parts
    while True:
        key = (cell[0], cell[1], cell[2])
        if key in voxels and (skip_part is None or parts.get(key) != skip_part):
            return key, t
        axis = 0 if t_max[0] < t_max[1] and t_max[0] < t_max[2] else (1 if t_max[1] < t_max[2] else 2)
        t = t_max[axis]
        if t > t_exit:
            return None
        cell[axis] += step[axis]
        if cell[axis] < lo[axis] or cell[axis] > hi[axis]:
            return None
        t_max[axis] += t_delta[axis]


def _clean(v: float) -> float:
    """Round away last-bit differences between platforms' trig functions (keeps builds byte-stable)."""
    return round(v, 12)


def render_heading(
    model: VoxelModel,
    materials: dict[str, Material],
    *,
    heading: float,
    size: tuple[int, int],
    origin: Vec,
    pivot: tuple[int, int],
    camera: Camera,
    light: Light,
) -> tuple[str, ...]:
    """Render one heading to rows of palette keys. `origin` (model space) lands on `pivot` (pixels)."""
    width, height = size
    if not model.voxels:
        return tuple(TRANSPARENT * width for _ in range(height))
    lo, hi = model.bounds()
    elev = math.radians(camera.elevation)
    ce, se = _clean(math.cos(elev)), _clean(math.sin(elev))
    h = math.radians(heading)
    ch, sh = _clean(math.cos(h)), _clean(math.sin(h))

    def to_model(v: Vec, point: bool) -> Vec:
        # world -> model: rotate by -heading about z, then add the model origin for points
        x, y, z = v
        mx, my = ch * x + sh * y, -sh * x + ch * y
        return (mx + origin[0], my + origin[1], z + origin[2]) if point else (mx, my, z)

    forward: Vec = (0.0, ce, -se)  # camera looks "north" and down
    up: Vec = (0.0, se, ce)
    ray_dir = to_model(forward, False)
    lx, ly, lz = light.direction
    norm = math.sqrt(lx * lx + ly * ly + lz * lz)
    light_world: Vec = (lx / norm, ly / norm, lz / norm)
    light_model = to_model(light_world, False)
    corners = [(x, y, z) for x in (lo[0], hi[0] + 1) for y in (lo[1], hi[1] + 1) for z in (lo[2], hi[2] + 1)]
    reach = 2.0 * max(math.dist(c, origin) for c in corners) + 4  # rays start beyond every voxel

    # Only pixels inside the projected bounding box can hit anything: skip the rest.
    xs_screen: list[float] = []
    ys_screen: list[float] = []
    for cx in (lo[0], hi[0] + 1):
        for cy in (lo[1], hi[1] + 1):
            for cz in (lo[2], hi[2] + 1):
                mx, my, mz = cx - origin[0], cy - origin[1], cz - origin[2]
                wx, wy = ch * mx - sh * my, sh * mx + ch * my  # model -> world (rotate by +heading)
                xs_screen.append(pivot[0] + wx * camera.scale)
                ys_screen.append(pivot[1] - (wy * up[1] + mz * up[2]) * camera.scale)
    x0, x1 = max(0, math.floor(min(xs_screen)) - 1), min(width, math.ceil(max(xs_screen)) + 1)
    y0, y1 = max(0, math.floor(min(ys_screen)) - 1), min(height, math.ceil(max(ys_screen)) + 1)

    normals: dict[Cell, Vec] = {}
    rows: list[str] = []
    for py in range(height):
        row: list[str] = []
        if not y0 <= py < y1:
            rows.append(TRANSPARENT * width)
            continue
        for px in range(width):
            if not x0 <= px < x1:
                row.append(TRANSPARENT)
                continue
            sx = (px + 0.5 - pivot[0]) / camera.scale
            sy = (pivot[1] - (py + 0.5)) / camera.scale
            start = to_model(
                (sx - reach * forward[0], sy * up[1] - reach * forward[1], sy * up[2] - reach * forward[2]), True
            )
            hit = _traverse(model, start, ray_dir, lo, hi)
            if hit is None:
                row.append(TRANSPARENT)
                continue
            cell, _ = hit
            material = materials[model.voxels[cell]]
            if len(material.keys) == 1:
                row.append(material.keys[0])
                continue
            n = model.normals.get(cell) or _normal(model, cell, normals)
            facing = n[0] * light_model[0] + n[1] * light_model[1] + n[2] * light_model[2]
            if material.two_sided:
                facing = abs(facing)
            facing = max(0.0, (facing + light.wrap) / (1 + light.wrap))
            if light.shadows and facing > 0:
                # Shadow ray from just outside the surface towards the light.
                side = 1.0 if not material.two_sided or n[0] * light_model[0] + n[1] * light_model[1] + n[2] * light_model[2] >= 0 else -1.0
                o = (
                    cell[0] + 0.5 + side * n[0] * 1.5,
                    cell[1] + 0.5 + side * n[1] * 1.5,
                    cell[2] + 0.5 + side * n[2] * 1.5,
                )
                if _traverse(model, o, light_model, lo, hi, skip_part=model.parts.get(cell)) is not None:
                    facing *= 1 - light.shadow_strength
            intensity = light.ambient + (1 - light.ambient) * facing
            row.append(_shade(material, intensity))
        rows.append("".join(row))
    return tuple(rows)


def heading_angles(directions: int, start: float = 0.0) -> list[tuple[str, float]]:
    names = DIRECTION_NAMES[directions]
    return [(name, (start + i * 360 / directions) % 360) for i, name in enumerate(names)]
