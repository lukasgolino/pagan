"""Voxel models as real 3D meshes: binary glTF (`.glb`) with a palette ramp texture, part nodes and animations.

Coordinates: PAGAN model space is x = front, y = left, z = up (voxels). glTF is +Y up with the model's front
facing +Z, so a model point (x, y, z) becomes (y, z, x) * voxel_size (a rotation: front -> +Z, left -> +X,
up -> +Y). `origin` in the model file is the mesh origin.

Geometry: faces between filled voxels of the same node are culled, the rest are merged into rectangles per
face direction and surface (greedy meshing), and every vertex that lands on another rectangle's edge is
inserted into that edge (no T-junctions, so no cracks at low resolution). Normals are flat (the voxel look).

Colours: every surface points into a ramp texture with one row per material ramp and columns dark -> light
(each row's steps stretched over a width every ramp length divides, so `u = brightness` picks exactly the
step the sprite renderer would). UV.x sits on the middle step, so any glTF viewer shows sensible flat colours;
PAGAN's Godot shader picks the column from the engine's lighting instead ([mesh] shading = "ramp").
"""

from __future__ import annotations

import math
from itertools import groupby
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image

from pagan.gltf import ARRAY_BUFFER, CLAMP_TO_EDGE, ELEMENT_ARRAY_BUFFER, NEAREST, Document, f32
from pagan.model import ROOT_ID, MeshSource, RigPart, part_cells
from pagan.palette import Palette
from pagan.voxel import (
    Cell,
    Light,
    PartMove,
    Vec,
    VoxelModel,
    _dense,
    _normals_at,
    bottom_centre,
    cell_array,
    cell_intensity,
    move_affine,
    ramp_steps,
    rotation_matrix,
)

MAX_RAMP_WIDTH = 256  # ramp texture columns (the least common multiple of the ramp lengths, up to this)


# --- surfaces and the ramp texture -------------------------------------------------------------------


@dataclass(frozen=True)
class Surface:
    """What one voxel face looks like: its ramp row, a baked step (None = picked by lighting) and sidedness."""

    row: int
    step: int | None
    two_sided: bool


def ramp_rows(source: MeshSource) -> list[tuple[str, ...]]:
    """The ramp texture's rows: each material ramp (keys, dark -> light) used by the model, in file order."""
    used = set(source.model.voxels.values()) | {m for o in source.model.overlays for m, _, _, _ in o.cells.values()}
    rows: list[tuple[str, ...]] = []
    for material in source.materials.values():
        if material.name in used and material.keys not in rows:
            rows.append(material.keys)
    return rows


def ramp_width(rows: list[tuple[str, ...]]) -> int:
    """Columns: a multiple of every ramp's length (each step gets whole columns), at most MAX_RAMP_WIDTH."""
    width = 1
    for keys in rows:
        width = math.lcm(width, len(keys))
    return min(width, MAX_RAMP_WIDTH) if width > 1 else 1


def ramp_image(rows: list[tuple[str, ...]], palette: Palette, keys: dict[str, str] | None = None) -> Image.Image:
    """The ramp texture: row r holds rows[r]'s colours, step j at columns [j*W/k, (j+1)*W/k). `keys` maps
    base keys to a variant's keys (colours come from `palette`, the variant's palette)."""
    width = ramp_width(rows)
    pixels = np.zeros((max(1, len(rows)), width, 3), dtype=np.uint8)
    for r, ramp in enumerate(rows):
        for column in range(width):
            key = ramp[column * len(ramp) // width]
            hexcode = palette.colors[(keys or {}).get(key, key)].hex
            pixels[r, column] = (int(hexcode[1:3], 16), int(hexcode[3:5], 16), int(hexcode[5:7], 16))
    return Image.fromarray(pixels, "RGB")


def surface_uv(surface: Surface, rows: list[tuple[str, ...]]) -> tuple[float, float]:
    """UV of a surface: its row's centre; x on its baked step, else on the middle step."""
    count = len(rows[surface.row])
    step = surface.step if surface.step is not None else count // 2
    return ((step + 0.5) / count, (surface.row + 0.5) / len(rows))


# --- greedy meshing ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Quad:
    """A merged rectangle of faces: normal along `axis` (0 x, 1 y, 2 z) with `sign`, in the plane
    axis = `plane`, spanning [u0, u1] x [v0, v1] on the next two axes (cyclic), all in model voxels."""

    axis: int
    sign: int
    plane: int
    u0: int
    u1: int
    v0: int
    v1: int
    label: int


def greedy_quads(labels: np.ndarray, lo: tuple[int, int, int] = (0, 0, 0)) -> list[Quad]:
    """Visible faces of a labelled voxel block (-1 = empty), merged into rectangles of one label.

    A face is visible where its neighbour is empty (faces between filled voxels are culled). Rectangles grow
    along v (runs, vectorised), then over consecutive rows u with the identical run. `lo` offsets the block.
    """
    solid = labels >= 0
    padded = np.pad(solid, 1, constant_values=False)
    quads: list[Quad] = []
    for axis in range(3):
        order = (axis, (axis + 1) % 3, (axis + 2) % 3)
        for sign in (1, -1):
            shift = [slice(1, -1)] * 3
            shift[axis] = slice(2, None) if sign > 0 else slice(0, -2)
            visible = solid & ~padded[tuple(shift)]
            if not visible.any():
                continue
            mask = np.where(visible, labels, -1).transpose(order)
            k_size, u_size, v_size = mask.shape
            rows = mask.reshape(-1, v_size)
            occupied_rows = np.nonzero((rows >= 0).any(axis=1))[0]
            rows = rows[occupied_rows]
            change = np.ones(rows.shape, dtype=bool)
            change[:, 1:] = rows[:, 1:] != rows[:, :-1]
            row_of, start = np.nonzero(change)
            end = np.empty_like(start)
            end[:-1] = np.where(row_of[1:] == row_of[:-1], start[1:], v_size)
            end[-1:] = v_size
            label = rows[row_of, start]
            keep = label >= 0
            flat_row = occupied_rows[row_of[keep]]
            runs = zip(
                (flat_row // u_size).tolist(), (flat_row % u_size).tolist(), start[keep].tolist(), end[keep].tolist(), label[keep].tolist(),
                strict=True,
            )  # fmt: skip
            offset = (lo[order[0]] + (1 if sign > 0 else 0), lo[order[1]], lo[order[2]])

            def close(row: tuple[int, int], items: dict[tuple[int, int, int], int]) -> None:
                k, last_u = row
                for (v0, v1, lab), u0 in items.items():
                    quads.append(
                        Quad(axis, sign, k + offset[0], u0 + offset[1], last_u + 1 + offset[1], v0 + offset[2], v1 + offset[2], lab)
                    )

            active: dict[tuple[int, int, int], int] = {}  # open rectangles: (v0, v1, label) -> first row u
            previous: tuple[int, int] | None = None
            for row, group in groupby(runs, key=lambda run: (run[0], run[1])):
                continued = previous is not None and previous[0] == row[0] and previous[1] == row[1] - 1
                if not continued and previous is not None:
                    close(previous, active)
                    active = {}
                grown: dict[tuple[int, int, int], int] = {}
                for _, u, v0, v1, lab in group:
                    grown[(v0, v1, lab)] = active.pop((v0, v1, lab), u)
                if previous is not None and continued:
                    close(previous, active)  # rectangles this row doesn't continue end on the previous row
                active, previous = grown, row
            if previous is not None:
                close(previous, active)
    return quads


# --- triangles (no T-junctions) ------------------------------------------------------------------


def _corners(quad: Quad) -> list[tuple[int, int, int]]:
    """The quad's corners counter-clockwise seen from outside (along its normal)."""
    order = (quad.axis, (quad.axis + 1) % 3, (quad.axis + 2) % 3)
    uv = [(quad.u0, quad.v0), (quad.u1, quad.v0), (quad.u1, quad.v1), (quad.u0, quad.v1)]
    if quad.sign < 0:
        uv.reverse()
    out = []
    for u, v in uv:
        point = [0, 0, 0]
        point[order[0]], point[order[1]], point[order[2]] = quad.plane, u, v
        out.append((point[0], point[1], point[2]))
    return out


def polygons(quads: list[Quad]) -> list[list[tuple[int, int, int]]]:
    """Each quad's boundary, counter-clockwise, with every other quad's corner that lies inside one of its
    edges inserted there (the vertices a T-junction would otherwise leave unshared)."""
    corners = [_corners(q) for q in quads]
    if not corners:
        return []
    points = np.array([c for quad in corners for c in quad], dtype=np.int64)
    lo = points.min(axis=0)
    span = points.max(axis=0) - lo + 1
    rel = points - lo
    # Per axis b: every corner as one sortable number (its line = the other two coordinates, then b).
    index: list[np.ndarray] = []
    for b in range(3):
        o1, o2 = (b + 1) % 3, (b + 2) % 3
        index.append(np.unique((rel[:, o1] * span[o2] + rel[:, o2]) * span[b] + rel[:, b]))
    edges_from = np.array([c for quad in corners for c in quad], dtype=np.int64) - lo
    edges_to = np.array([c for quad in corners for c in quad[1:] + quad[:1]], dtype=np.int64) - lo
    axis_of = np.argmax(edges_from != edges_to, axis=1)
    inserted: dict[int, list[tuple[int, int, int]]] = {}
    for b in range(3):
        on_axis = np.nonzero(axis_of == b)[0]
        if not on_axis.size:
            continue
        o1, o2 = (b + 1) % 3, (b + 2) % 3
        a, z = edges_from[on_axis], edges_to[on_axis]
        line = (a[:, o1] * span[o2] + a[:, o2]) * span[b]
        low, high = np.minimum(a[:, b], z[:, b]), np.maximum(a[:, b], z[:, b])
        codes = index[b]
        first = np.searchsorted(codes, line + low, side="right")
        last = np.searchsorted(codes, line + high, side="left")
        for edge in np.nonzero(last > first)[0]:
            values = (codes[first[edge] : last[edge]] % span[b]).tolist()
            if a[edge, b] > z[edge, b]:
                values.reverse()
            start = edges_from[on_axis[edge]]
            extra = []
            for value in values:
                p = start.copy()
                p[b] = value
                extra.append((int(p[0] + lo[0]), int(p[1] + lo[1]), int(p[2] + lo[2])))
            inserted[int(on_axis[edge])] = extra
    out = []
    for q, quad in enumerate(corners):
        boundary: list[tuple[int, int, int]] = []
        for i, corner in enumerate(quad):
            boundary.append(corner)
            boundary.extend(inserted.get(4 * q + i, ()))
        out.append(boundary)
    return out


@dataclass
class Primitive:
    """Triangles of one glTF primitive: positions in model voxels (not yet moved to the node), per-vertex
    normal axis/sign and UV."""

    positions: list[tuple[float, float, float]] = field(default_factory=list)
    normals: list[tuple[int, int]] = field(default_factory=list)  # (axis, sign)
    uvs: list[tuple[float, float]] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)


def triangulate(quads: list[Quad], uv_of: dict[int, tuple[float, float]], boundaries: list[list[tuple[int, int, int]]] | None = None) -> Primitive:
    """Triangles for quads: two per plain rectangle; a rectangle with inserted edge vertices is fanned from
    its centre (no slivers, every edge vertex shared). `boundaries` default to polygons(quads)."""
    prim = Primitive()
    for quad, boundary in zip(quads, boundaries if boundaries is not None else polygons(quads), strict=True):
        uv = uv_of[quad.label]
        base = len(prim.positions)
        prim.positions.extend((float(x), float(y), float(z)) for x, y, z in boundary)
        if len(boundary) == 4:
            prim.indices.extend((base, base + 1, base + 2, base, base + 2, base + 3))
            count = 4
        else:
            c0, c2 = _corners(quad)[0], _corners(quad)[2]
            prim.positions.append(((c0[0] + c2[0]) / 2, (c0[1] + c2[1]) / 2, (c0[2] + c2[2]) / 2))
            centre = base + len(boundary)
            for i in range(len(boundary)):
                prim.indices.extend((centre, base + i, base + (i + 1) % len(boundary)))
            count = len(boundary) + 1
        prim.normals.extend([(quad.axis, quad.sign)] * count)
        prim.uvs.extend([uv] * count)
    return prim


# --- model -> nodes -----------------------------------------------------------------------------------


def to_gltf(v: Vec, scale: float) -> tuple[float, float, float]:
    """A model-space vector in glTF space (metres): front x -> +Z, left y -> +X, up z -> +Y."""
    return (v[1] * scale, v[2] * scale, v[0] * scale)


def _matrix_to_gltf(m: tuple[Vec, Vec, Vec]) -> list[list[float]]:
    perm = (1, 2, 0)  # glTF axis i is model axis perm[i]
    return [[m[perm[i]][perm[j]] for j in range(3)] for i in range(3)]


def quaternion(m: tuple[Vec, Vec, Vec]) -> tuple[float, float, float, float]:
    """glTF rotation (x, y, z, w) of a model-space rotation matrix, with w >= 0."""
    r = _matrix_to_gltf(m)
    trace = r[0][0] + r[1][1] + r[2][2]
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        q = ((r[2][1] - r[1][2]) / s, (r[0][2] - r[2][0]) / s, (r[1][0] - r[0][1]) / s, 0.25 * s)
    elif r[0][0] > r[1][1] and r[0][0] > r[2][2]:
        s = math.sqrt(1.0 + r[0][0] - r[1][1] - r[2][2]) * 2
        q = (0.25 * s, (r[0][1] + r[1][0]) / s, (r[0][2] + r[2][0]) / s, (r[2][1] - r[1][2]) / s)
    elif r[1][1] > r[2][2]:
        s = math.sqrt(1.0 + r[1][1] - r[0][0] - r[2][2]) * 2
        q = ((r[0][1] + r[1][0]) / s, 0.25 * s, (r[1][2] + r[2][1]) / s, (r[0][2] - r[2][0]) / s)
    else:
        s = math.sqrt(1.0 + r[2][2] - r[0][0] - r[1][1]) * 2
        q = ((r[0][2] + r[2][0]) / s, (r[1][2] + r[2][1]) / s, 0.25 * s, (r[1][0] - r[0][1]) / s)
    if q[3] < 0 or (q[3] == 0 and next((c for c in q if c), 0) < 0):
        q = (-q[0], -q[1], -q[2], -q[3])
    length = math.sqrt(sum(c * c for c in q))
    return (round(q[0] / length, 9) + 0.0, round(q[1] / length, 9) + 0.0, round(q[2] / length, 9) + 0.0, round(q[3] / length, 9) + 0.0)


@dataclass
class Node:
    """One part as a mesh node: its voxels, pivot (model space) and place in the hierarchy."""

    part_id: str
    cells: set[Cell]
    pivot: Vec
    parent: str | None  # None for the root
    rig: RigPart
    hidden: bool  # hidden by default (hidden parts and their rig children)
    children: list[str] = field(default_factory=list)


def nodes_of(source: MeshSource) -> dict[str, Node]:
    """Every part id as a node, root first, then depth-first with children in id order."""
    cells = part_cells(source.model)
    ids = sorted((set(cells) | source.model.part_ids()) - {ROOT_ID})
    raw: dict[str, Node] = {
        ROOT_ID: Node(ROOT_ID, cells.get(ROOT_ID, set()), source.origin, None, source.rig.get(ROOT_ID, RigPart()), False)
    }
    for part_id in ids:
        rig = source.rig.get(part_id, RigPart())
        mine = cells.get(part_id, set())
        pivot = rig.pivot if rig.pivot is not None else (bottom_centre(mine) if mine else source.origin)
        raw[part_id] = Node(part_id, mine, pivot, rig.parent or ROOT_ID, rig, part_id in source.hidden)
    for part_id in ids:
        parent = raw[part_id].parent
        assert parent is not None
        raw[parent].children.append(part_id)
    ordered: dict[str, Node] = {}

    def visit(part_id: str) -> None:
        ordered[part_id] = raw[part_id]
        for child in raw[part_id].children:
            visit(child)

    visit(ROOT_ID)
    return ordered


def node_path(nodes: dict[str, Node], part_id: str, names: dict[str, str]) -> str:
    chain = [part_id]
    while nodes[chain[-1]].parent is not None:
        parent = nodes[chain[-1]].parent
        assert parent is not None
        chain.append(parent)
    return "/".join(names[p] for p in reversed(chain))


def _labels(
    source: MeshSource, rows: list[tuple[str, ...]], shading: str, cells: np.ndarray, materials: list[str], everything: VoxelModel | None
) -> tuple[np.ndarray, list[Surface]]:
    """Surface label per voxel (`cells`, made of `materials`) and the surfaces, sorted. Baked shading picks each
    voxel's step from the project light like the sprite renderer at heading 0 (same functions), with the
    normals and shadows of the whole model (`everything`: every part shown)."""
    names = sorted(set(materials))
    code = {name: i for i, name in enumerate(names)}
    mat = np.fromiter((code[m] for m in materials), dtype=np.int64, count=len(materials))
    row = np.array([rows.index(source.materials[n].keys) for n in names], dtype=np.int64)[mat]
    two = np.array([source.materials[n].two_sided for n in names], dtype=np.int64)[mat]
    step = np.full(len(materials), -1, dtype=np.int64)
    if shading == "baked" and everything is not None and len(cells):
        dense = _dense(everything)
        light = source.light
        lx, ly, lz = light.direction
        norm = math.sqrt(lx * lx + ly * ly + lz * lz)
        normals = _normals_at(dense, cells)
        flat = np.array([len(source.materials[n].keys) == 1 for n in names])[mat]
        baked = Light(light.direction, light.ambient, light.shadows, light.wrap, True, light.shadow_strength)
        intensity = cell_intensity(dense, cells, normals, (lx / norm, ly / norm, lz / norm), two.astype(bool), flat, baked)
        local = cells - dense.lo
        shown = np.array(dense.material_names)[dense.material[local[:, 0], local[:, 1], local[:, 2]]]
        for i, name in enumerate(names):
            mine = (mat == i) & (shown == name)  # baked from what shows there (an overlay may cover a voxel)
            if mine.any():
                step[mine] = ramp_steps(intensity[mine], len(source.materials[name].keys))
    width = max(len(r) for r in rows) + 1
    keys = (row * width + step + 1) * 2 + two
    unique, labels = np.unique(keys, return_inverse=True)
    surfaces = [Surface(int(k // 2 // width), int(k // 2 % width) - 1 if k // 2 % width else None, bool(k % 2)) for k in unique.tolist()]
    return labels.astype(np.int32), surfaces


@dataclass
class NodeMesh:
    """A node's triangles per glTF material (0 = one-sided, 1 = two-sided)."""

    primitives: dict[int, Primitive]
    triangles: int


def mesh_node(cells: np.ndarray, labels: np.ndarray, surfaces: list[Surface], rows: list[tuple[str, ...]]) -> NodeMesh:
    """Triangles for one node's voxels (`cells` (n, 3), each with a label into `surfaces`)."""
    if not len(cells):
        return NodeMesh({}, 0)
    lo, hi = cells.min(axis=0), cells.max(axis=0)
    grid = np.full(tuple((hi - lo + 1).tolist()), -1, dtype=np.int32)
    local = cells - lo
    grid[local[:, 0], local[:, 1], local[:, 2]] = labels
    quads = greedy_quads(grid, (int(lo[0]), int(lo[1]), int(lo[2])))
    boundaries = polygons(quads)  # edge vertices from every quad of the node, one- and two-sided alike
    uv_of = {i: surface_uv(s, rows) for i, s in enumerate(surfaces)}
    primitives: dict[int, Primitive] = {}
    for material in (0, 1):
        mine = [i for i, q in enumerate(quads) if surfaces[q.label].two_sided == bool(material)]
        if mine:
            primitives[material] = triangulate([quads[i] for i in mine], uv_of, [boundaries[i] for i in mine])
    return NodeMesh(primitives, sum(len(p.indices) // 3 for p in primitives.values()))


# --- animations -----------------------------------------------------------------------------------


def local_transform(node: Node, parent_pivot: Vec, move: PartMove | None, centre: Vec) -> tuple[Vec, tuple[Vec, Vec, Vec]]:
    """A node's translation (model space, voxels, relative to its parent's pivot) and rotation for one pose.
    Only the part's own move: its rig parents' moves reach it through the hierarchy."""
    if move is None:
        identity = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        p = node.pivot
        return (p[0] - parent_pivot[0], p[1] - parent_pivot[1], p[2] - parent_pivot[2]), identity
    own = PartMove(move.offset, move.roll, move.pitch, move.yaw, move.about)
    r, t = move_affine(own, centre)
    p = node.pivot
    moved = (
        r[0][0] * p[0] + r[0][1] * p[1] + r[0][2] * p[2] + t[0],
        r[1][0] * p[0] + r[1][1] * p[1] + r[1][2] * p[2] + t[1],
        r[2][0] * p[0] + r[2][1] * p[1] + r[2][2] * p[2] + t[2],
    )
    return (moved[0] - parent_pivot[0], moved[1] - parent_pivot[1], moved[2] - parent_pivot[2]), r


def loop_name(name: str, loop: bool) -> str:
    """The glTF animation name: Godot's importer loops animations whose names end in "-loop"."""
    return f"{name}-loop" if loop else name


# --- the document ---------------------------------------------------------------------------------


@dataclass
class MeshExport:
    glb: bytes
    ramp: Image.Image
    rows: list[tuple[str, ...]]
    info: dict[str, Any]  # manifest data (without file paths)
    surfaces: dict[str, list[bool]]  # node path -> its surfaces in order: two-sided or not


def export_mesh(
    source: MeshSource,
    palette: Palette,
    voxel_size: float,
    shading: str,
    generator: str,
    collision_suffixes: bool = False,
    ramp_file: str | None = None,
) -> MeshExport:
    """The model as a .glb (`ramp_file`: the ramp texture's file name next to it, default <name>.ramp.png)."""
    ramp_file = ramp_file or f"{source.name}.ramp.png"
    rows = ramp_rows(source)
    ramp = ramp_image(rows, palette)
    nodes = nodes_of(source)
    # Each node's voxels -> material (an overlay's own material, not what's under it in the static model).
    overlay_cells = {o.part_id: o.cells for o in source.model.overlays}
    everything = source.model.posed({}, set()) if shading == "baked" else None  # every part shown, as rest
    node_arrays: dict[str, tuple[np.ndarray, np.ndarray, list[Surface]]] = {}
    for part_id, node in nodes.items():
        if part_id in overlay_cells:
            voxels = {c: d[0] for c, d in overlay_cells[part_id].items()}
        elif part_id == ROOT_ID and node.cells and len(node.cells) == len(source.model.voxels):
            voxels = source.model.voxels  # the usual big case: every voxel is the root's
        else:
            voxels = {c: source.model.voxels[c] for c in node.cells}
        cells = cell_array(voxels)
        labels, surfaces_of_node = _labels(source, rows, shading, cells, list(voxels.values()), everything)
        node_arrays[part_id] = (cells, labels, surfaces_of_node)

    doc = Document(generator)
    doc.add("samplers", {"magFilter": NEAREST, "minFilter": NEAREST, "wrapS": CLAMP_TO_EDGE, "wrapT": CLAMP_TO_EDGE})
    # The ramp texture sits next to the .glb (shared with engine materials and variant swaps), not inside it:
    # engines that extract embedded images (Godot) would otherwise write extra files into the output folder.
    image = doc.add("images", {"uri": ramp_file, "name": f"{source.name}.ramp"})
    doc.add("textures", {"sampler": 0, "source": image})
    material_ids: dict[int, int] = {}
    unlit = shading == "baked"

    def material(two_sided: int) -> int:
        if two_sided not in material_ids:
            item: dict[str, Any] = {
                "name": source.name + ("_two_sided" if two_sided else ""),
                "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicFactor": 0.0, "roughnessFactor": 1.0},
                "extras": {"pagan_shading": shading, "pagan_two_sided": bool(two_sided)},
            }
            if unlit:
                item["extensions"] = {"KHR_materials_unlit": {}}
            material_ids[two_sided] = doc.add("materials", item)
        return material_ids[two_sided]

    names = {p: _node_name(p, nodes[p].rig.collision, collision_suffixes) for p in nodes}
    surfaces: dict[str, list[bool]] = {}
    node_index = {part_id: i for i, part_id in enumerate(nodes)}
    triangles = vertices = 0
    gltf_nodes: list[dict[str, Any]] = []
    parts_info: dict[str, Any] = {}
    extra_nodes: list[dict[str, Any]] = []  # collision boxes (collision_suffixes), appended after the parts
    for part_id, node in nodes.items():
        parent_pivot = nodes[node.parent].pivot if node.parent is not None else source.origin
        mesh = mesh_node(*node_arrays[part_id], rows)
        item: dict[str, Any] = {"name": names[part_id]}
        translation = to_gltf((node.pivot[0] - parent_pivot[0], node.pivot[1] - parent_pivot[1], node.pivot[2] - parent_pivot[2]), voxel_size)
        if any(translation):
            item["translation"] = [f32(v) for v in translation]
        if node.hidden:  # KHR_node_visibility (Godot imports it as `visible`); viewers without it show the part
            item["extensions"] = {"KHR_node_visibility": {"visible": False}}
        extras: dict[str, Any] = {k: v for k, v in node.rig.meta}
        extras["pagan_part"] = part_id
        if node.rig.collision != "none":
            extras["pagan_collision"] = node.rig.collision
        if node.hidden:
            extras["pagan_hidden"] = True
        item["extras"] = extras
        children = [node_index[c] for c in node.children]
        if children:
            item["children"] = children
        if mesh.primitives:
            primitives = []
            for mat, prim in sorted(mesh.primitives.items()):
                primitives.append(_primitive(doc, prim, node.pivot, voxel_size, material(mat)))
                vertices += len(prim.positions)
            item["mesh"] = doc.add("meshes", {"name": part_id, "primitives": primitives})
            triangles += mesh.triangles
            surfaces[node_path(nodes, part_id, {p: p for p in nodes})] = [bool(m) for m in sorted(mesh.primitives)]
        gltf_nodes.append(item)
        if collision_suffixes and node.rig.collision == "box" and node.cells:
            extra_nodes.append({"of": part_id, "cells": node.cells, "pivot": node.pivot})
        aabb = _aabb(node_arrays[part_id][0], source.origin, voxel_size) if node.cells else None
        parts_info[part_id] = {
            "node": node_path(nodes, part_id, {p: p for p in nodes}),  # as engines show it (Godot strips collision suffixes)
            "parent": node.parent,
            "pivot": [f32(v) for v in to_gltf(tuple(node.pivot[i] - source.origin[i] for i in range(3)), voxel_size)],  # type: ignore[arg-type]
            "aabb": aabb,
            "voxels": len(node.cells),
            "triangles": mesh.triangles,
            "meta": {k: v for k, v in node.rig.meta},
            "collision": node.rig.collision,
            "hidden": node.hidden,
        }
    for box in extra_nodes:
        owner = gltf_nodes[node_index[box["of"]]]
        index = len(gltf_nodes)
        gltf_nodes.append(_collision_box(doc, box["of"], box["cells"], box["pivot"], voxel_size))
        owner.setdefault("children", []).append(index)
    for item in gltf_nodes:
        doc.add("nodes", item)
    doc.add("scenes", {"name": source.name, "nodes": [0], "extras": {"pagan_model": source.name, "pagan_voxel_size": voxel_size}})
    doc.json["scene"] = 0
    animations, showing = _animations(doc, source, nodes, node_index, voxel_size)
    for part_id in showing:  # animated visibility targets the node's KHR_node_visibility flag
        extensions = doc.json["nodes"][node_index[part_id]].setdefault("extensions", {})
        extensions.setdefault("KHR_node_visibility", {"visible": True})
    used = [name for name, on in (
        ("KHR_animation_pointer", bool(showing)),
        ("KHR_materials_unlit", unlit),
        ("KHR_node_visibility", bool(showing) or any(n.hidden for n in nodes.values())),
    ) if on]  # fmt: skip
    if used:
        doc.json["extensionsUsed"] = used
    all_cells = np.concatenate([a[0] for a in node_arrays.values()])
    info = {
        "voxel_size": voxel_size,
        "shading": shading,
        "bounds": _aabb(all_cells, source.origin, voxel_size) if len(all_cells) else None,
        "triangles": triangles,
        "vertices": vertices,
        "root": names[ROOT_ID],
        "parts": parts_info,
        "animations": animations,
        "animation_order": list(source.animations),
        "ramp_rows": ["".join(r) for r in rows],
    }
    return MeshExport(doc.glb(), ramp, rows, info, surfaces)


def _node_name(part_id: str, collision: str, suffixes: bool) -> str:
    if suffixes and collision == "convex":
        return f"{part_id}-convcol"
    return part_id


def _aabb(cells: np.ndarray, origin: Vec, voxel_size: float) -> dict[str, list[float]]:
    low, high = cells.min(axis=0).tolist(), cells.max(axis=0).tolist()
    lo = tuple(low[i] - origin[i] for i in range(3))
    hi = tuple(high[i] + 1 - origin[i] for i in range(3))
    a, b = to_gltf(lo, voxel_size), to_gltf(hi, voxel_size)
    return {"min": [f32(min(x, y)) for x, y in zip(a, b, strict=True)], "max": [f32(max(x, y)) for x, y in zip(a, b, strict=True)]}


_NORMALS = {(axis, sign): to_gltf(tuple(float(sign) if i == axis else 0.0 for i in range(3)), 1.0) for axis in range(3) for sign in (1, -1)}  # type: ignore[arg-type]


def _primitive(doc: Document, prim: Primitive, pivot: Vec, voxel_size: float, material: int) -> dict[str, Any]:
    p = np.array(prim.positions, dtype=np.float64) - np.array(pivot)
    positions = np.stack((p[:, 1], p[:, 2], p[:, 0]), axis=1) * voxel_size
    normals = np.array([_NORMALS[n] for n in prim.normals], dtype=np.float64)
    attributes = {
        "POSITION": doc.accessor(positions.astype(np.float32), target=ARRAY_BUFFER, bounds=True),
        "NORMAL": doc.accessor(normals.astype(np.float32), target=ARRAY_BUFFER),
        "TEXCOORD_0": doc.accessor(np.array(prim.uvs, dtype=np.float32), target=ARRAY_BUFFER),
    }
    indices = doc.accessor(np.array(prim.indices, dtype=np.int64), target=ELEMENT_ARRAY_BUFFER)
    return {"attributes": attributes, "indices": indices, "material": material, "mode": 4}


def _collision_box(doc: Document, part_id: str, cells: set[Cell], pivot: Vec, voxel_size: float) -> dict[str, Any]:
    """A box mesh around a part, named for Godot's -colonly suffix (Godot makes it a collision shape only)."""
    lo = [min(c[i] for c in cells) for i in range(3)]
    hi = [max(c[i] for c in cells) + 1 for i in range(3)]
    quads = [Quad(axis, sign, (hi if sign > 0 else lo)[axis], lo[(axis + 1) % 3], hi[(axis + 1) % 3], lo[(axis + 2) % 3], hi[(axis + 2) % 3], 0)
             for axis in range(3) for sign in (1, -1)]  # fmt: skip
    prim = triangulate(quads, {0: (0.0, 0.0)})
    p = np.array(prim.positions, dtype=np.float64) - np.array(pivot)
    positions = np.stack((p[:, 1], p[:, 2], p[:, 0]), axis=1) * voxel_size
    attributes = {"POSITION": doc.accessor(positions.astype(np.float32), target=ARRAY_BUFFER, bounds=True)}
    indices = doc.accessor(np.array(prim.indices, dtype=np.int64), target=ELEMENT_ARRAY_BUFFER)
    mesh = doc.add("meshes", {"name": f"{part_id}_box", "primitives": [{"attributes": attributes, "indices": indices, "mode": 4}]})
    return {"name": f"{part_id}_box-colonly", "mesh": mesh, "extras": {"pagan_part": part_id, "pagan_collision": "box"}}


def _animations(
    doc: Document, source: MeshSource, nodes: dict[str, Node], node_index: dict[str, int], voxel_size: float
) -> tuple[dict[str, Any], set[str]]:
    """One glTF animation per model animation. Every animated node is keyed in every animation (translation,
    rotation, visibility), so switching animations never leaves a part where another one put it. Returns the
    manifest's animations and the parts whose visibility is animated."""
    if not source.animations:
        return {}, set()
    centres = {p: bottom_centre(n.cells) if n.cells and n.parent is not None else n.pivot for p, n in nodes.items()}
    identity = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))

    def state(pose_moves: dict[str, PartMove], hidden: frozenset[str], roll: float, pitch: float) -> dict[str, tuple[Any, Any, float]]:
        out: dict[str, tuple[Any, Any, float]] = {}
        for part_id, node in nodes.items():
            if node.parent is None:
                out[part_id] = ((0.0, 0.0, 0.0), rotation_matrix(roll, pitch, 0.0) if roll or pitch else identity, 1.0)
                continue
            parent_pivot = nodes[node.parent].pivot
            t, r = local_transform(node, parent_pivot, pose_moves.get(part_id), centres[part_id])
            out[part_id] = (t, r, 0.0 if part_id in hidden else 1.0)  # 0.0 = hidden
        return out

    rest = state({}, source.hidden, 0.0, 0.0)
    states: dict[str, list[dict[str, tuple[Any, Any, float]]]] = {}
    for name, anim in source.animations.items():
        states[name] = [state(dict(p.moves), p.hidden, p.roll, p.pitch) for p in anim.poses]
    every = [s for frames in states.values() for s in frames]
    moving = {p for p in nodes if any(s[p][:2] != rest[p][:2] for s in every)}
    showing = {p for p in nodes if any(s[p][2] != rest[p][2] for s in every)}
    animated = [p for p in nodes if p in moving or p in showing]
    info: dict[str, Any] = {}
    for name, anim in source.animations.items():
        frames = states[name]
        gltf_name = loop_name(name, anim.loop)
        info[name] = {
            "gltf_name": gltf_name,
            "fps": anim.fps,
            "loop": anim.loop,
            "frames": len(frames),
            "interpolation": anim.interpolation,
            "duration": round(len(frames) / anim.fps, 6),
        }
        if not animated:
            continue
        linear = anim.interpolation == "linear"
        closing = frames[0] if (linear and anim.loop) else frames[-1]
        keyed = [*frames, closing]
        times = doc.accessor(np.array([i / anim.fps for i in range(len(keyed))], dtype=np.float32), bounds=True)
        samplers: list[dict[str, Any]] = []
        channels: list[dict[str, Any]] = []
        for part_id in animated:
            translations = np.array([to_gltf(s[part_id][0], voxel_size) for s in keyed], dtype=np.float32)
            rotations = [quaternion(s[part_id][1]) for s in keyed]
            for i in range(1, len(rotations)):  # shortest way round for linear blending
                if sum(a * b for a, b in zip(rotations[i - 1], rotations[i], strict=True)) < 0:
                    rotations[i] = (-rotations[i][0], -rotations[i][1], -rotations[i][2], -rotations[i][3])
            mode = "LINEAR" if linear else "STEP"
            if part_id in moving:
                for path, values in (("translation", translations), ("rotation", np.array(rotations, dtype=np.float32))):
                    samplers.append({"input": times, "output": doc.accessor(values), "interpolation": mode})
                    channels.append({"sampler": len(samplers) - 1, "target": {"node": node_index[part_id], "path": path}})
            if part_id in showing:  # shown / hidden: KHR_node_visibility's flag through KHR_animation_pointer, never blended
                visible = np.array([s[part_id][2] > 0 for s in keyed], dtype=np.uint8)
                samplers.append({"input": times, "output": doc.accessor(visible, byte=True), "interpolation": "STEP"})
                pointer = f"/nodes/{node_index[part_id]}/extensions/KHR_node_visibility/visible"
                channels.append({"sampler": len(samplers) - 1, "target": {"path": "pointer", "extensions": {"KHR_animation_pointer": {"pointer": pointer}}}})
        doc.add(
            "animations",
            {"name": gltf_name, "samplers": samplers, "channels": channels, "extras": {"pagan_name": name, "fps": anim.fps, "loop": anim.loop}},
        )
    return info, showing

