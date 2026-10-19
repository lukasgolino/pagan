"""3D voxel models: text-described shapes rendered by PAGAN into consistent, palette-shaded frames.

A model is built from primitive parts (box, hull, cylinder, ellipsoid, line, sail) and/or literal layer
grids, each with a material (a ramp of palette keys, dark -> light). PAGAN renders it from N headings with
the project's fixed camera and light, so every 3D asset in a project is projected and lit identically.

Coordinates: x forward (the model's front faces +x), y to the model's left, z up; units are voxels.
Heading 0 shows the front pointing right ("e"); headings go counter-clockwise like a compass seen from above.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import chain

import numpy as np

from pagan.palette import TRANSPARENT

Cell = tuple[int, int, int]
Vec = tuple[float, float, float]

DIRECTION_NAMES = {
    1: ["main"],
    4: ["e", "n", "w", "s"],
    8: ["e", "ne", "n", "nw", "w", "sw", "s", "se"],
    16: ["e", "ene", "ne", "nne", "n", "nnw", "nw", "wnw", "w", "wsw", "sw", "ssw", "s", "sse", "se", "ese"],
    32: [f"h{i:02d}" for i in range(32)],  # h00 = east, counter-clockwise in 11.25 degree steps
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


VoxelData = tuple[str, str | None, int | None, Vec | None]  # material, part id, part index, exact normal


@dataclass(frozen=True)
class PartMove:
    """How a pose moves one part: rotate (degrees) about `about`, then shift by whole voxels."""

    offset: Cell = (0, 0, 0)
    roll: float = 0.0  # about the model's x (bow-stern) axis; positive lowers the right (-y) side
    pitch: float = 0.0  # about the y axis; positive tips the front (+x) down
    yaw: float = 0.0  # about the z axis; positive turns counter-clockwise seen from above
    about: Vec | None = None  # rotation centre in model space; None = the part's bottom centre
    # `rig:` parents' moves, applied after this one (nearest parent first), each with an explicit `about`:
    # a child follows its parent. Empty for unrigged parts, which keeps their old (integer-offset) path.
    then: tuple[PartMove, ...] = ()


@dataclass
class Overlay:
    """A hidden part: drawn over the model only in poses that `show` it; never changes the normal frames.

    A carving overlay removes its cells instead (holes, torn cloth) when shown.
    """

    part_id: str
    cells: dict[Cell, VoxelData]
    carve: bool = False


@dataclass
class VoxelModel:
    voxels: dict[Cell, str] = field(default_factory=dict)  # cell -> material name
    groups: dict[Cell, str] = field(default_factory=dict)  # cell -> part id (for poses)
    normals: dict[Cell, Vec] = field(default_factory=dict)  # exact normals from shapes that know them (sails)
    parts: dict[Cell, int] = field(default_factory=dict)  # cell -> index of the part that made it (no self-shadowing)
    hidden_by_default: set[str] = field(default_factory=set)  # part ids only shown by poses that `show` them
    overlays: list[Overlay] = field(default_factory=list)  # the hidden parts, in source order

    def bounds(self) -> tuple[Cell, Cell]:
        xs = [c[0] for c in self.voxels]
        ys = [c[1] for c in self.voxels]
        zs = [c[2] for c in self.voxels]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    def part_ids(self) -> set[str]:
        return set(self.groups.values()) | {o.part_id for o in self.overlays}

    def _data(self, cell: Cell) -> VoxelData:
        return (self.voxels[cell], self.groups.get(cell), self.parts.get(cell), self.normals.get(cell))

    def _put(self, cell: Cell, data: VoxelData) -> None:
        material, group, part, normal = data
        self.voxels[cell] = material
        if group is None:
            self.groups.pop(cell, None)
        else:
            self.groups[cell] = group
        if part is None:
            self.parts.pop(cell, None)
        else:
            self.parts[cell] = part
        if normal is None:
            self.normals.pop(cell, None)
        else:
            self.normals[cell] = normal

    def _remove(self, cell: Cell) -> None:
        self.voxels.pop(cell, None)
        self.groups.pop(cell, None)
        self.parts.pop(cell, None)
        self.normals.pop(cell, None)

    def posed(self, moves: dict[str, PartMove], hidden: set[str]) -> VoxelModel:
        """A copy for one pose: parts in `hidden` left out, parts in `moves` moved (and drawn over the
        static ones), then every shown overlay drawn (or carved) on top in source order."""
        shown = [o for o in self.overlays if o.part_id not in hidden]
        if not moves and not shown and not hidden & set(self.groups.values()):
            return self
        out = VoxelModel()
        moving: dict[str, dict[Cell, VoxelData]] = {}
        for cell in self.voxels:
            group = self.groups.get(cell)
            if group in hidden:
                continue
            if group is not None and group in moves:
                moving.setdefault(group, {})[cell] = self._data(cell)
            else:
                out._put(cell, self._data(cell))
        for group, cells in moving.items():  # moved parts draw over static ones
            for cell, data in move_cells(cells, moves[group]).items():
                out._put(cell, data)
        for overlay in shown:
            cells = overlay.cells if overlay.part_id not in moves else move_cells(overlay.cells, moves[overlay.part_id])
            for cell, data in cells.items():
                if overlay.carve:
                    out._remove(cell)
                else:
                    out._put(cell, data)
        return out


def rotation_matrix(roll: float, pitch: float, yaw: float) -> tuple[Vec, Vec, Vec]:
    """Rz(yaw) . Ry(pitch) . Rx(roll), degrees, right-handed (x forward, y left, z up).

    Entries are rounded like other trig results so builds stay byte-stable across platforms.
    """
    r, p, y = math.radians(roll), math.radians(pitch), math.radians(yaw)
    cr, sr = _clean(math.cos(r)), _clean(math.sin(r))
    cp, sp = _clean(math.cos(p)), _clean(math.sin(p))
    cy, sy = _clean(math.cos(y)), _clean(math.sin(y))
    return (
        (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr),
        (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr),
        (-sp, cp * sr, cp * cr),
    )


def _apply(m: tuple[Vec, Vec, Vec], v: Vec) -> Vec:
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


def _transpose(m: tuple[Vec, Vec, Vec]) -> tuple[Vec, Vec, Vec]:
    return ((m[0][0], m[1][0], m[2][0]), (m[0][1], m[1][1], m[2][1]), (m[0][2], m[1][2], m[2][2]))


def cell_array(cells: Iterable[Cell]) -> np.ndarray:
    """Cells as an (n, 3) int64 array (several times faster than np.array on a list of tuples)."""
    items = cells if isinstance(cells, list | tuple) else list(cells)
    return np.fromiter(chain.from_iterable(items), dtype=np.int64, count=3 * len(items)).reshape(-1, 3)


def bottom_centre(cells: dict[Cell, VoxelData] | set[Cell]) -> Vec:
    """Centre of a part's bounding box at its lowest face: the default hinge for rotating it."""
    xs, ys, zs = ([c[i] for c in cells] for i in range(3))
    return ((min(xs) + max(xs) + 1) / 2, (min(ys) + max(ys) + 1) / 2, float(min(zs)))


def move_cells(cells: dict[Cell, VoxelData], move: PartMove) -> dict[Cell, VoxelData]:
    """Rotate a part about its hinge, then shift it. Rotated parts are resampled both ways (every voxel
    lands somewhere, and gaps the rotation opens are filled from the source), so thin parts stay solid."""
    if move.then:
        return _move_cells_affine(cells, move)
    dx, dy, dz = move.offset
    if not cells or (move.roll, move.pitch, move.yaw) == (0.0, 0.0, 0.0):
        return {(x + dx, y + dy, z + dz): data for (x, y, z), data in cells.items()}
    m = rotation_matrix(move.roll, move.pitch, move.yaw)
    back = _transpose(m)
    cx, cy, cz = move.about if move.about is not None else bottom_centre(cells)

    def rotated(data: VoxelData) -> VoxelData:
        material, group, part, normal = data
        return (material, group, part, _apply(m, normal) if normal is not None else None)

    out: dict[Cell, VoxelData] = {}
    for (x, y, z), data in cells.items():
        q = _apply(m, (x + 0.5 - cx, y + 0.5 - cy, z + 0.5 - cz))
        out[(math.floor(q[0] + cx), math.floor(q[1] + cy), math.floor(q[2] + cz))] = rotated(data)
    lo = [min(c[i] for c in out) - 1 for i in range(3)]
    hi = [max(c[i] for c in out) + 1 for i in range(3)]
    for x in range(lo[0], hi[0] + 1):
        for y in range(lo[1], hi[1] + 1):
            for z in range(lo[2], hi[2] + 1):
                if (x, y, z) in out:
                    continue
                q = _apply(back, (x + 0.5 - cx, y + 0.5 - cy, z + 0.5 - cz))
                source = (math.floor(q[0] + cx), math.floor(q[1] + cy), math.floor(q[2] + cz))
                if source in cells:
                    out[(x, y, z)] = rotated(cells[source])
    return {(x + dx, y + dy, z + dz): data for (x, y, z), data in out.items()}


def move_affine(move: PartMove, centre: Vec) -> tuple[tuple[Vec, Vec, Vec], Vec]:
    """(R, t) with p' = R p + t for a move and its parents' (`then`); `centre` is the default hinge."""
    def one(m: PartMove) -> tuple[tuple[Vec, Vec, Vec], Vec]:
        r = rotation_matrix(m.roll, m.pitch, m.yaw)
        c = m.about if m.about is not None else centre
        rc = _apply(r, c)
        return r, (c[0] + m.offset[0] - rc[0], c[1] + m.offset[1] - rc[1], c[2] + m.offset[2] - rc[2])

    r, t = one(move)
    for parent in move.then:
        pr, pt = one(parent)
        r = _matmul(pr, r)
        moved = _apply(pr, t)
        t = (moved[0] + pt[0], moved[1] + pt[1], moved[2] + pt[2])
    return r, t


def _matmul(a: tuple[Vec, Vec, Vec], b: tuple[Vec, Vec, Vec]) -> tuple[Vec, Vec, Vec]:
    rows = [tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3)]
    return (rows[0], rows[1], rows[2])  # type: ignore[return-value]


def _move_cells_affine(cells: dict[Cell, VoxelData], move: PartMove) -> dict[Cell, VoxelData]:
    """move_cells for a rigged part: its move followed by its parents' (one affine map, resampled both ways)."""
    if not cells:
        return {}
    m, t = move_affine(move, bottom_centre(cells))
    back = _transpose(m)

    def rotated(data: VoxelData) -> VoxelData:
        material, group, part, normal = data
        return (material, group, part, _apply(m, normal) if normal is not None else None)

    out: dict[Cell, VoxelData] = {}
    for (x, y, z), data in cells.items():
        q = _apply(m, (x + 0.5, y + 0.5, z + 0.5))
        out[(math.floor(q[0] + t[0] + 1e-9), math.floor(q[1] + t[1] + 1e-9), math.floor(q[2] + t[2] + 1e-9))] = rotated(data)
    if m == ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
        return out
    lo = [min(c[i] for c in out) - 1 for i in range(3)]
    hi = [max(c[i] for c in out) + 1 for i in range(3)]
    for x in range(lo[0], hi[0] + 1):
        for y in range(lo[1], hi[1] + 1):
            for z in range(lo[2], hi[2] + 1):
                if (x, y, z) in out:
                    continue
                q = _apply(back, (x + 0.5 - t[0], y + 0.5 - t[1], z + 0.5 - t[2]))
                source = (math.floor(q[0] + 1e-9), math.floor(q[1] + 1e-9), math.floor(q[2] + 1e-9))
                if source in cells:
                    out[(x, y, z)] = rotated(cells[source])
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
    roll: float = 0.0,
    pitch: float = 0.0,
) -> tuple[str, ...]:
    """Render one heading to rows of palette keys. `origin` (model space) lands on `pivot` (pixels)."""
    return render_heading_full(
        model, materials, heading=heading, size=size, origin=origin, pivot=pivot, camera=camera, light=light,
        roll=roll, pitch=pitch,
    ).rows  # fmt: skip


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
    roll: float = 0.0,
    pitch: float = 0.0,
) -> Rendered:
    """Like render_heading, plus screen-space normals. `roll`/`pitch` tilt the whole model about `origin`
    (see PartMove for the signs); the view stays exact, nothing is resampled."""
    width, height = size
    keys_out = np.full((height, width), TRANSPARENT, dtype="<U1")
    normals_out = np.zeros((height, width, 3))
    if not model.voxels:
        return Rendered(tuple(TRANSPARENT * width for _ in range(height)), normals_out)
    dense = _dense(model)
    lo, hi = dense.lo, dense.hi
    elev = math.radians(camera.elevation)
    ce, se = _clean(math.cos(elev)), _clean(math.sin(elev))
    world = rotation_matrix(roll, pitch, heading)  # model -> world: tilt, then turn to the heading
    model_from_world = _transpose(world)

    def to_model(v: Vec) -> Vec:  # world -> model direction
        return _apply(model_from_world, v)

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
        wx, wy, wz = _apply(world, (cx - origin[0], cy - origin[1], cz - origin[2]))
        xs_screen.append(pivot[0] + wx * camera.scale)
        ys_screen.append(pivot[1] - (wy * up[1] + wz * up[2]) * camera.scale)
    x0, x1 = max(0, math.floor(min(xs_screen)) - 1), min(width, math.ceil(max(xs_screen)) + 1)
    y0, y1 = max(0, math.floor(min(ys_screen)) - 1), min(height, math.ceil(max(ys_screen)) + 1)
    if x0 >= x1 or y0 >= y1:
        return Rendered(tuple("".join(r) for r in keys_out), normals_out)

    py, px = np.mgrid[y0:y1, x0:x1]
    py, px = py.ravel(), px.ravel()
    sx = (px + 0.5 - pivot[0]) / camera.scale
    sy = (pivot[1] - (py + 0.5)) / camera.scale
    wx, wy, wz = sx - reach * forward[0], sy * up[1] - reach * forward[1], sy * up[2] - reach * forward[2]
    (a0, a1, a2), (b0, b1, b2), (c0, c1, c2) = model_from_world
    starts = np.stack(
        (a0 * wx + a1 * wy + a2 * wz + origin[0], b0 * wx + b1 * wy + b2 * wz + origin[1], c0 * wx + c1 * wy + c2 * wz + origin[2]),
        axis=1,
    )
    hit, cells = _traverse_many(dense, starts, ray_dir)
    py, px, cells = py[hit], px[hit], cells[hit]
    if not len(cells):
        return Rendered(tuple("".join(r) for r in keys_out), normals_out)

    local = cells - lo
    mat_index = dense.material[local[:, 0], local[:, 1], local[:, 2]]
    n = _normals_at(dense, cells)
    two_sided = np.array([materials[name].two_sided for name in dense.material_names])[mat_index]
    flat = np.array([len(materials[name].keys) == 1 for name in dense.material_names])[mat_index]
    intensity = cell_intensity(dense, cells, n, light_model, two_sided, flat, light)

    for i, name in enumerate(dense.material_names):
        mine = mat_index == i
        if not mine.any():
            continue
        keys = materials[name].keys
        keys_out[py[mine], px[mine]] = np.array(keys)[ramp_steps(intensity[mine], len(keys), light.baked)]

    # Screen-space normals for engine lighting: model -> world -> view.
    (a0, a1, a2), (b0, b1, b2), (c0, c1, c2) = world
    wnx = a0 * n[:, 0] + a1 * n[:, 1] + a2 * n[:, 2]
    wny = b0 * n[:, 0] + b1 * n[:, 1] + b2 * n[:, 2]
    wnz = c0 * n[:, 0] + c1 * n[:, 1] + c2 * n[:, 2]
    screen = np.stack((wnx, wny * se + wnz * ce, -wny * ce + wnz * se), axis=1)
    flip = two_sided & (screen[:, 2] < 0)  # cloth faces whichever side the viewer sees
    screen[flip] *= -1
    normals_out[py, px] = screen
    return Rendered(tuple("".join(r) for r in keys_out), normals_out)


def light_intensity(raw_facing: np.ndarray, two_sided: np.ndarray, shadowed: np.ndarray, light: Light) -> np.ndarray:
    """Brightness 0..1 of surfaces facing the light by `raw_facing` (normal . light direction): wrap lighting,
    cast shadows (`shadowed`) and ambient. Sprites and baked meshes both shade with this; PAGAN's Godot ramp
    shader computes the same formula per pixel."""
    facing = np.where(two_sided, np.abs(raw_facing), raw_facing)
    facing = np.maximum(0.0, (facing + light.wrap) / (1 + light.wrap))
    facing = np.where(shadowed, facing * (1 - light.shadow_strength), facing)
    return light.ambient + (1 - light.ambient) * facing


def ramp_steps(intensity: np.ndarray, count: int, baked: bool = True) -> np.ndarray:
    """The ramp step (0 = darkest of `count`) for each brightness. Unbaked: the middle step (flat albedo)."""
    if count == 1:
        return np.zeros(len(intensity), dtype=np.int64)
    if not baked:
        return np.full(len(intensity), count // 2, dtype=np.int64)  # flat albedo: the engine lights it
    return np.clip((intensity * count).astype(np.int64), 0, count - 1)


def cell_intensity(
    dense: _Dense, cells: np.ndarray, n: np.ndarray, light_model: Vec, two_sided: np.ndarray, flat: np.ndarray, light: Light
) -> np.ndarray:
    """light_intensity for voxels `cells` with normals `n`, testing cast shadows towards `light_model`
    (model space) for lit, shaded voxels when the light casts shadows."""
    raw_facing = n @ np.array(light_model)
    shadowed = np.zeros(len(cells), dtype=bool)
    if light.shadows and light.baked:
        facing = np.where(two_sided, np.abs(raw_facing), raw_facing)
        test = (np.maximum(0.0, (facing + light.wrap) / (1 + light.wrap)) > 0) & ~flat
        if test.any():
            local = cells - dense.lo
            side = np.where(~two_sided[test] | (raw_facing[test] >= 0), 1.0, -1.0)
            origins = cells[test] + 0.5 + side[:, None] * n[test] * 1.5
            skip = dense.part[local[test, 0], local[test, 1], local[test, 2]]
            shadowed[np.nonzero(test)[0]], _ = _traverse_many(dense, origins, light_model, skip=skip)
    return light_intensity(raw_facing, two_sided, shadowed, light)


def heading_name(angle: float, directions: int) -> str:
    """Name a heading by the way it actually faces (0 = east, counter-clockwise)."""
    angle %= 360
    compass = DIRECTION_NAMES[16]
    if directions == 32 and abs(angle / 11.25 - round(angle / 11.25)) < 1e-9:
        return f"h{round(angle / 11.25) % 32:02d}"
    if abs(angle / 22.5 - round(angle / 22.5)) < 1e-9:
        return compass[round(angle / 22.5) % 16]
    return f"d{round(angle) % 360:03d}"  # an off-compass angle, in whole degrees


def heading_angles(directions: int, start: float = 0.0) -> list[tuple[str, float]]:
    """(frame name, angle) per heading. Names describe where each frame faces, even with an offset start."""
    if directions == 1:
        return [("main", start % 360)]
    angles = [(start + i * 360 / directions) % 360 for i in range(directions)]
    names = [heading_name(a, directions) for a in angles]
    if len(set(names)) != len(names):  # rounding collided: fall back to indexes
        names = [f"h{i:02d}" for i in range(directions)]
    return list(zip(names, angles, strict=True))
