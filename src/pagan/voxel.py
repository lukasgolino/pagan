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

import numpy as np

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
    baked: bool = True  # False: flat colors (middle ramp step) + normal maps, for engines with their own lighting
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


@dataclass
class _Dense:
    """The model as dense arrays over its bounds (built once per pose, shared by every heading)."""

    lo: np.ndarray  # (3,) int
    hi: np.ndarray  # (3,) int
    occupied: np.ndarray  # (X, Y, Z) bool
    material: np.ndarray  # (X, Y, Z) int16 index into `material_names`, -1 = empty
    part: np.ndarray  # (X, Y, Z) int32 part index, -1 = none
    exact: np.ndarray  # (X, Y, Z) bool: has an exact normal
    exact_normal: np.ndarray  # (X, Y, Z, 3) float
    material_names: list[str]


def _dense(model: VoxelModel) -> _Dense:
    cached = getattr(model, "_dense_cache", None)
    if isinstance(cached, _Dense):
        return cached
    lo_t, hi_t = model.bounds()
    lo, hi = np.array(lo_t), np.array(hi_t)
    shape = tuple(int(v) for v in hi - lo + 1)
    names = sorted(set(model.voxels.values()))
    index = {name: i for i, name in enumerate(names)}
    occupied = np.zeros(shape, dtype=bool)
    material = np.full(shape, -1, dtype=np.int16)
    part = np.full(shape, -1, dtype=np.int32)
    exact = np.zeros(shape, dtype=bool)
    exact_normal = np.zeros((*shape, 3), dtype=np.float64)
    cells = np.array(list(model.voxels.keys()), dtype=np.int64) - lo
    occupied[cells[:, 0], cells[:, 1], cells[:, 2]] = True
    material[cells[:, 0], cells[:, 1], cells[:, 2]] = [index[m] for m in model.voxels.values()]
    if model.parts:
        pcells = np.array(list(model.parts.keys()), dtype=np.int64) - lo
        part[pcells[:, 0], pcells[:, 1], pcells[:, 2]] = list(model.parts.values())
    if model.normals:
        ncells = np.array(list(model.normals.keys()), dtype=np.int64) - lo
        exact[ncells[:, 0], ncells[:, 1], ncells[:, 2]] = True
        exact_normal[ncells[:, 0], ncells[:, 1], ncells[:, 2]] = np.array(list(model.normals.values()))
    dense = _Dense(lo, hi, occupied, material, part, exact, exact_normal, names)
    object.__setattr__(model, "_dense_cache", dense)
    return dense


def _normals_at(dense: _Dense, cells: np.ndarray) -> np.ndarray:
    """Smoothed normals (occupancy gradient: away from occupied neighbours), or exact ones where known."""
    padded = np.pad(dense.occupied, 1, constant_values=False)
    local = cells - dense.lo + 1
    n = np.zeros((len(cells), 3), dtype=np.float64)
    for dx, dy, dz in _NEIGHBOURHOOD:  # same order as the scalar version, so sums round identically
        empty = ~padded[local[:, 0] + dx, local[:, 1] + dy, local[:, 2] + dz]
        weight = 1 / math.sqrt(dx * dx + dy * dy + dz * dz)
        n[:, 0] += np.where(empty, dx * weight, 0.0)
        n[:, 1] += np.where(empty, dy * weight, 0.0)
        n[:, 2] += np.where(empty, dz * weight, 0.0)
    length = np.sqrt(n[:, 0] * n[:, 0] + n[:, 1] * n[:, 1] + n[:, 2] * n[:, 2])
    flat = length <= 1e-9
    safe = np.where(flat, 1.0, length)
    n = n / safe[:, None]
    n[flat] = (0.0, 0.0, 1.0)
    idx = cells - dense.lo
    has_exact = dense.exact[idx[:, 0], idx[:, 1], idx[:, 2]]
    n[has_exact] = dense.exact_normal[idx[has_exact, 0], idx[has_exact, 1], idx[has_exact, 2]]
    return n


# --- ray traversal ----------------------------------------------------------------------------


def _traverse_many(
    dense: _Dense, origins: np.ndarray, direction: tuple[float, float, float], skip: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """First occupied cell along each ray (Amanatides & Woo traversal, all rays in lockstep).

    All rays share `direction` (orthographic camera / directional light). `skip[i]` ignores voxels of
    that part (no self-shadowing). Returns (hit mask, hit cells).
    """
    count = len(origins)
    lo, hi = dense.lo, dense.hi
    t_enter = np.zeros(count)
    t_exit = np.full(count, 1e9)
    valid = np.ones(count, dtype=bool)
    for axis in range(3):
        o, d = origins[:, axis], direction[axis]
        a, b = float(lo[axis]), float(hi[axis] + 1)
        if abs(d) < 1e-12:
            valid &= (o >= a) & (o <= b)
            continue
        t0, t1 = (a - o) / d, (b - o) / d
        t_enter = np.maximum(t_enter, np.minimum(t0, t1))
        t_exit = np.minimum(t_exit, np.maximum(t0, t1))
    valid &= t_enter <= t_exit
    t = t_enter + 1e-7
    point = origins + np.array(direction)[None, :] * t[:, None]
    cell = np.clip(np.floor(point).astype(np.int64), lo, hi)
    step = np.array([1 if d > 0 else -1 for d in direction], dtype=np.int64)
    t_max = np.empty((count, 3))
    t_delta = np.empty(3)
    for axis in range(3):
        d = direction[axis]
        if abs(d) < 1e-12:
            t_max[:, axis] = np.inf
            t_delta[axis] = np.inf
        else:
            boundary = cell[:, axis] + (1 if d > 0 else 0)
            t_max[:, axis] = t + (boundary - point[:, axis]) / d
            t_delta[axis] = abs(1 / d)

    hit = np.zeros(count, dtype=bool)
    hit_cell = np.zeros((count, 3), dtype=np.int64)
    active = np.nonzero(valid)[0]
    while active.size:
        local = cell[active] - lo
        occupied = dense.occupied[local[:, 0], local[:, 1], local[:, 2]]
        if skip is not None:
            occupied &= dense.part[local[:, 0], local[:, 1], local[:, 2]] != skip[active]
        done = active[occupied]
        hit[done] = True
        hit_cell[done] = cell[done]
        active = active[~occupied]
        if not active.size:
            break
        tm = t_max[active]
        first = (tm[:, 0] < tm[:, 1]) & (tm[:, 0] < tm[:, 2])
        second = ~first & (tm[:, 1] < tm[:, 2])
        axis_of = np.where(first, 0, np.where(second, 1, 2))
        rows = np.arange(active.size)
        t_next = tm[rows, axis_of]
        cell[active, axis_of] += step[axis_of]
        moved = cell[active, axis_of]
        leaving = (t_next > t_exit[active]) | (moved < lo[axis_of]) | (moved > hi[axis_of])
        t_max[active, axis_of] += t_delta[axis_of]
        active = active[~leaving]
    return hit, hit_cell


def _clean(v: float) -> float:
    """Round away last-bit differences between platforms' trig functions (keeps builds byte-stable)."""
    return round(v, 12)


@dataclass
class Rendered:
    rows: tuple[str, ...]
    normals: np.ndarray  # (H, W, 3) screen-space normals (x right, y up, z towards the viewer); 0 where empty


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
    return render_heading_full(
        model, materials, heading=heading, size=size, origin=origin, pivot=pivot, camera=camera, light=light
    ).rows


def render_heading_full(
    model: VoxelModel,
    materials: dict[str, Material],
    *,
    heading: float,
    size: tuple[int, int],
    origin: Vec,
    pivot: tuple[int, int],
    camera: Camera,
    light: Light,
) -> Rendered:
    width, height = size
    keys_out = np.full((height, width), TRANSPARENT, dtype="<U1")
    normals_out = np.zeros((height, width, 3))
    if not model.voxels:
        return Rendered(tuple(TRANSPARENT * width for _ in range(height)), normals_out)
    dense = _dense(model)
    lo, hi = dense.lo, dense.hi
    elev = math.radians(camera.elevation)
    ce, se = _clean(math.cos(elev)), _clean(math.sin(elev))
    h = math.radians(heading)
    ch, sh = _clean(math.cos(h)), _clean(math.sin(h))

    def to_model(v: Vec) -> Vec:  # world -> model direction: rotate by -heading about z
        x, y, z = v
        return (ch * x + sh * y, -sh * x + ch * y, z)

    forward: Vec = (0.0, ce, -se)  # camera looks "north" and down
    up: Vec = (0.0, se, ce)
    ray_dir = to_model(forward)
    lx, ly, lz = light.direction
    norm = math.sqrt(lx * lx + ly * ly + lz * lz)
    light_model = to_model((lx / norm, ly / norm, lz / norm))
    corners = [(float(x), float(y), float(z)) for x in (lo[0], hi[0] + 1) for y in (lo[1], hi[1] + 1) for z in (lo[2], hi[2] + 1)]
    reach = 2.0 * max(math.dist(c, origin) for c in corners) + 4  # rays start beyond every voxel

    # Only pixels inside the projected bounding box can hit anything.
    xs_screen, ys_screen = [], []
    for cx, cy, cz in corners:
        mx, my, mz = cx - origin[0], cy - origin[1], cz - origin[2]
        wx, wy = ch * mx - sh * my, sh * mx + ch * my  # model -> world (rotate by +heading)
        xs_screen.append(pivot[0] + wx * camera.scale)
        ys_screen.append(pivot[1] - (wy * up[1] + mz * up[2]) * camera.scale)
    x0, x1 = max(0, math.floor(min(xs_screen)) - 1), min(width, math.ceil(max(xs_screen)) + 1)
    y0, y1 = max(0, math.floor(min(ys_screen)) - 1), min(height, math.ceil(max(ys_screen)) + 1)
    if x0 >= x1 or y0 >= y1:
        return Rendered(tuple("".join(r) for r in keys_out), normals_out)

    py, px = np.mgrid[y0:y1, x0:x1]
    py, px = py.ravel(), px.ravel()
    sx = (px + 0.5 - pivot[0]) / camera.scale
    sy = (pivot[1] - (py + 0.5)) / camera.scale
    wx, wy, wz = sx - reach * forward[0], sy * up[1] - reach * forward[1], sy * up[2] - reach * forward[2]
    starts = np.stack((ch * wx + sh * wy + origin[0], -sh * wx + ch * wy + origin[1], wz + origin[2]), axis=1)
    hit, cells = _traverse_many(dense, starts, ray_dir)
    py, px, cells = py[hit], px[hit], cells[hit]
    if not len(cells):
        return Rendered(tuple("".join(r) for r in keys_out), normals_out)

    local = cells - lo
    mat_index = dense.material[local[:, 0], local[:, 1], local[:, 2]]
    n = _normals_at(dense, cells)
    lm = np.array(light_model)
    raw_facing = n @ lm
    two_sided = np.array([materials[name].two_sided for name in dense.material_names])[mat_index]
    facing = np.where(two_sided, np.abs(raw_facing), raw_facing)
    facing = np.maximum(0.0, (facing + light.wrap) / (1 + light.wrap))
    flat = np.array([len(materials[name].keys) == 1 for name in dense.material_names])[mat_index]
    if light.shadows and light.baked:
        test = (facing > 0) & ~flat
        if test.any():
            side = np.where(~two_sided[test] | (raw_facing[test] >= 0), 1.0, -1.0)
            origins = cells[test] + 0.5 + side[:, None] * n[test] * 1.5
            skip = dense.part[local[test, 0], local[test, 1], local[test, 2]]
            shadowed, _ = _traverse_many(dense, origins, light_model, skip=skip)
            factor = np.where(shadowed, 1 - light.shadow_strength, 1.0)
            facing[np.nonzero(test)[0]] *= factor
    intensity = light.ambient + (1 - light.ambient) * facing

    for i, name in enumerate(dense.material_names):
        mine = mat_index == i
        if not mine.any():
            continue
        keys = materials[name].keys
        if len(keys) == 1:
            chosen = np.zeros(mine.sum(), dtype=np.int64)
        elif not light.baked:
            chosen = np.full(mine.sum(), len(keys) // 2, dtype=np.int64)  # flat albedo: the engine lights it
        else:
            chosen = np.clip((intensity[mine] * len(keys)).astype(np.int64), 0, len(keys) - 1)
        keys_out[py[mine], px[mine]] = np.array(keys)[chosen]

    # Screen-space normals for engine lighting: model -> world (rotate by +heading) -> view.
    wnx, wny, wnz = ch * n[:, 0] - sh * n[:, 1], sh * n[:, 0] + ch * n[:, 1], n[:, 2]
    screen = np.stack((wnx, wny * se + wnz * ce, -wny * ce + wnz * se), axis=1)
    flip = two_sided & (screen[:, 2] < 0)  # cloth faces whichever side the viewer sees
    screen[flip] *= -1
    normals_out[py, px] = screen
    return Rendered(tuple("".join(r) for r in keys_out), normals_out)


def heading_angles(directions: int, start: float = 0.0) -> list[tuple[str, float]]:
    names = DIRECTION_NAMES[directions]
    return [(name, (start + i * 360 / directions) % 360) for i, name in enumerate(names)]
