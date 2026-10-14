"""`.model.yaml` files: parse a voxel model description and render it into a regular Asset.

Rendering is the slow part, so results are cached in `<project>/.pagan-cache/` keyed by everything that
affects the pixels (the file, its materials, camera, light and the renderer version).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pagan.asset import (
    MODEL_SUFFIX,
    NAME_RE,
    Animation,
    Asset,
    Grid,
    _darkest,
    _edge_pixel,
    _line,
    _outline,
    _parse_metadata,
    _parse_size,
    _parse_variants,
    _resolve_palette,
)
from pagan.findings import Finding, has_errors
from pagan.palette import TRANSPARENT, Palette
from pagan.project import Project
from pagan.voxel import DIRECTION_NAMES, Camera, Cell, Light, Material, VoxelModel, heading_angles, render_heading

RENDERER_VERSION = "3"  # bump when rendering changes, to invalidate caches
PART_TYPES = ("box", "hull", "cylinder", "ellipsoid", "line", "sail", "layers")
_MODEL_FIELDS = (
    "name", "description", "palette", "variants", "tags", "status", "style_version",
    "size", "pivot", "origin", "outline", "outline_color", "directions", "heading",
    "camera", "light", "materials", "parts", "animations",
)  # fmt: skip

ErrorFn = Callable[[str, str, int | None, str | None], None]


# --- small validators -------------------------------------------------------------------------


def _get(mapping: dict[str, Any], key: str, default: Any = None) -> Any:
    """dict.get typed as Any (validated by the caller), so numeric checks narrow cleanly."""
    return mapping.get(key, default)


def _num(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _vec(value: Any, n: int = 3) -> tuple[float, ...] | None:
    if isinstance(value, list) and len(value) == n and all(_num(v) for v in value):
        return tuple(float(v) for v in value)
    return None


def _ivec(value: Any, n: int = 3) -> tuple[int, ...] | None:
    if isinstance(value, list) and len(value) == n and all(isinstance(v, int) and not isinstance(v, bool) for v in value):
        return tuple(value)
    return None


# --- materials --------------------------------------------------------------------------------


def _parse_materials(raw: Any, palette: Palette, line: int | None, error: ErrorFn) -> dict[str, Material]:
    materials: dict[str, Material] = {}
    if not isinstance(raw, dict) or not raw:
        error("E013", "materials must map a name to { ramp: <ramp> } or { keys: [...] }", line, "materials")
        return materials
    for name, spec in raw.items():
        mline = _line(raw, name)
        where = f"materials.{name}"
        if not isinstance(name, str) or not NAME_RE.match(name):
            error("E013", "material names must be lowercase letters, digits, '_' or '-'", mline, where)
            continue
        if isinstance(spec, str):
            spec = {"ramp": spec}
        if not isinstance(spec, dict):
            error("E013", "a material is { ramp: name } or { keys: [dark, ..., light] }", mline, where)
            continue
        for key in spec:
            if key not in ("ramp", "keys", "two_sided"):
                error("E013", f"unknown material field {key!r}; allowed: ramp, keys, two_sided", mline, where)
        keys: tuple[str, ...] | None = None
        if "ramp" in spec:
            ramp = spec["ramp"]
            if not isinstance(ramp, str) or ramp not in palette.ramps:
                known = ", ".join(palette.ramps) or "none"
                error("E013", f"unknown ramp {ramp!r} (palette ramps: {known})", mline, where)
                continue
            keys = palette.ramps[ramp]
        if "keys" in spec:
            raw_keys = spec["keys"]
            if isinstance(raw_keys, str | int):
                raw_keys = [raw_keys]
            if not isinstance(raw_keys, list) or not raw_keys:
                error("E013", "keys must be a list of palette keys, dark -> light", mline, where)
                continue
            normalized = tuple(str(k) for k in raw_keys)
            unknown = [k for k in normalized if k not in palette.colors]
            if unknown:
                error("E005", f"material uses unknown palette key(s) {', '.join(unknown)}", mline, where)
                continue
            keys = normalized
        if keys is None:
            error("E013", "a material needs ramp or keys", mline, where)
            continue
        two_sided = _get(spec, "two_sided", False)
        if not isinstance(two_sided, bool):
            error("E013", "two_sided must be true or false", mline, where)
            continue
        materials[name] = Material(name=name, keys=keys, two_sided=two_sided)
    return materials


# --- primitives -------------------------------------------------------------------------------


MAX_PART_CELLS = 2_000_000  # per shape, checked before filling
MAX_MODEL_VOXELS = 2_000_000


class _Builder:
    def __init__(self, model: VoxelModel, error: ErrorFn, materials: dict[str, Material]) -> None:
        self.model = model
        self.error = error
        self.materials = materials
        self.pending_normals: dict[Cell, tuple[float, float, float]] = {}

    def build(self, parts: Any, line: int | None) -> None:
        if not isinstance(parts, list) or not parts:
            self.error("E013", "parts must be a non-empty list, e.g. - box: { from: [0,0,0], to: [3,3,3], material: wood }", line, "parts")
            return
        for index, part in enumerate(parts):
            where = f"parts[{index}]"
            pline = _line(part) or line
            if not isinstance(part, dict) or len([k for k in part if k in PART_TYPES]) != 1:
                self.error("E013", f"each part needs exactly one shape: {', '.join(PART_TYPES)}", pline, where)
                continue
            shape = next(k for k in part if k in PART_TYPES)
            for key in part:
                if key not in (shape, "id", "mirror", "carve", "hidden"):
                    self.error("E013", f"unknown part field {key!r}; allowed: {shape}, id, mirror, carve, hidden", pline, where)
            spec = part[shape]
            if not isinstance(spec, dict):
                self.error("E013", f"{shape} needs a mapping of options", pline, where)
                continue
            part_id = part.get("id")
            if part_id is not None and (not isinstance(part_id, str) or not NAME_RE.match(part_id)):
                self.error("E013", "part id must be lowercase letters, digits, '_' or '-'", pline, where)
                continue
            mirror = part.get("mirror", False)
            if mirror not in (False, True, "y"):
                self.error("E013", "mirror must be true (reflect across y = 0) or false", pline, where)
                continue
            carve = part.get("carve", False)
            if not isinstance(carve, bool):
                self.error("E013", "carve must be true or false", pline, where)
                continue
            hidden = part.get("hidden", False)
            if not isinstance(hidden, bool) or (hidden and part_id is None):
                self.error("E013", "hidden: true needs an id (poses reveal it with show: [id])", pline, where)
                continue
            if hidden and part_id is not None:
                self.model.hidden_by_default.add(part_id)
            self.pending_normals = {}
            volume = _estimated_cells(shape, spec)
            if volume > MAX_PART_CELLS:
                self.error("E013", f"this {shape} would fill ~{volume:,.0f} voxels (limit {MAX_PART_CELLS:,}); make it smaller", pline, where)
                continue
            cells = getattr(self, f"_{shape}")(spec, pline, f"{where}.{shape}")
            if cells is None:
                continue
            shape_normals = self.pending_normals
            if mirror:
                cells = {**cells, **{(x, -y, z): m for (x, y, z), m in cells.items()}}
                shape_normals = {**shape_normals, **{(x, -y, z): (n[0], -n[1], n[2]) for (x, y, z), n in shape_normals.items()}}
            for cell, material in cells.items():
                if carve:
                    self.model.voxels.pop(cell, None)
                    self.model.groups.pop(cell, None)
                    self.model.normals.pop(cell, None)
                    self.model.parts.pop(cell, None)
                else:
                    self.model.voxels[cell] = material
                    if part_id is not None:
                        self.model.groups[cell] = part_id
                    else:
                        self.model.groups.pop(cell, None)
                    self.model.parts[cell] = index
                    if cell in shape_normals:
                        self.model.normals[cell] = shape_normals[cell]
                    else:
                        self.model.normals.pop(cell, None)
            if len(self.model.voxels) > MAX_MODEL_VOXELS:
                self.error("E013", f"the model has over {MAX_MODEL_VOXELS:,} voxels; make it smaller", pline, where)
                return

    # Each shape returns {cell: material} or None after reporting an error.

    def _material(self, spec: dict[str, Any], key: str, line: int | None, where: str, required: bool = True) -> str | None:
        value = _get(spec, key)
        if value is None:
            if required:
                self.error("E013", f"missing {key}", line, where)
            return None
        if not isinstance(value, str) or value not in self.materials:
            self.error("E013", f"unknown material {value!r} (defined: {', '.join(self.materials) or 'none'})", line, where)
            return None
        return str(value)

    def _check_fields(self, spec: dict[str, Any], allowed: tuple[str, ...], line: int | None, where: str) -> bool:
        bad = [k for k in spec if k not in allowed]
        if bad:
            self.error("E013", f"unknown field(s) {', '.join(map(str, bad))}; allowed: {', '.join(allowed)}", line, where)
        return not bad

    def _with_top_and_rim(
        self, cells: set[Cell], material: str, spec: dict[str, Any], line: int | None, where: str
    ) -> dict[Cell, str] | None:
        top = self._material(spec, "top", line, where, required=False)
        rim = self._material(spec, "rim", line, where, required=False)
        if ("top" in spec and top is None) or ("rim" in spec and rim is None):
            return None
        out = {c: material for c in cells}
        if top is not None or rim is not None:
            tops = {c for c in cells if (c[0], c[1], c[2] + 1) not in cells}
            for c in tops:
                if top is not None:
                    out[c] = top
                if rim is not None:
                    x, y, z = c
                    if any((x + dx, y + dy, z) not in cells for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                        out[(x, y, z + 1)] = rim
        return out

    def _box(self, spec: dict[str, Any], line: int | None, where: str) -> dict[Cell, str] | None:
        if not self._check_fields(spec, ("from", "to", "material", "top", "rim"), line, where):
            return None
        a, b = _ivec(_get(spec, "from")), _ivec(_get(spec, "to"))
        material = self._material(spec, "material", line, where)
        if a is None or b is None:
            self.error("E013", "box needs from: [x, y, z] and to: [x, y, z] (whole voxels, inclusive)", line, where)
            return None
        if material is None:
            return None
        lo = [min(a[i], b[i]) for i in range(3)]
        hi = [max(a[i], b[i]) for i in range(3)]
        cells = {
            (x, y, z)
            for x in range(lo[0], hi[0] + 1)
            for y in range(lo[1], hi[1] + 1)
            for z in range(lo[2], hi[2] + 1)
        }
        return self._with_top_and_rim(cells, material, spec, line, where)

    def _hull(self, spec: dict[str, Any], line: int | None, where: str) -> dict[Cell, str] | None:
        allowed = ("from", "length", "beam", "height", "bow", "stern", "material", "top", "rim")
        if not self._check_fields(spec, allowed, line, where):
            return None
        at = _ivec(_get(spec, "from"))
        material = self._material(spec, "material", line, where)
        length, beam, height = _get(spec, "length"), _get(spec, "beam"), _get(spec, "height")
        bow, stern = _get(spec, "bow", 0.35), _get(spec, "stern", 0.1)
        if at is None or not all(_num(v) and v > 0 for v in (length, beam, height)):
            self.error("E013", "hull needs from: [x, y_center, z], length, beam and height (positive numbers)", line, where)
            return None
        if not (_num(bow) and _num(stern) and 0 <= bow < 1 and 0 <= stern < 1 and bow + stern <= 1):
            self.error("E013", "bow and stern are fractions of the length (0..1, together at most 1)", line, where)
            return None
        if material is None:
            return None
        length, beam, height, bow, stern = float(length), float(beam), float(height), float(bow), float(stern)
        x0, yc, z0 = at
        half = beam / 2
        cells: set[Cell] = set()
        for x in range(x0, x0 + math.ceil(length)):
            u = (x - x0 + 0.5) / length
            if bow > 0 and u > 1 - bow:
                hw = half * math.sqrt(max(0.0, 1 - ((u - (1 - bow)) / bow) ** 2))
            elif stern > 0 and u < stern:
                hw = half * (0.75 + 0.25 * u / stern)
            else:
                hw = half
            for z in range(z0, z0 + math.ceil(height)):
                layer_hw = hw * (0.8 if z == z0 else 1.0)  # rounded keel
                reach = math.floor(layer_hw - 0.5 + 1e-9)
                for y in range(yc - reach, yc + reach + 1):
                    cells.add((x, y, z))
        if not cells:
            self.error("E013", "hull is too small to fill any voxels", line, where)
            return None
        return self._with_top_and_rim(cells, material, spec, line, where)

    def _cylinder(self, spec: dict[str, Any], line: int | None, where: str) -> dict[Cell, str] | None:
        if not self._check_fields(spec, ("base", "height", "radius", "axis", "material", "top", "rim"), line, where):
            return None
        base = _ivec(_get(spec, "base"))
        height, radius = _get(spec, "height"), _get(spec, "radius", 0)
        axis = _get(spec, "axis", "z")
        material = self._material(spec, "material", line, where)
        if base is None or not (_num(height) and height > 0) or not (_num(radius) and radius >= 0) or axis not in ("x", "y", "z"):
            self.error("E013", "cylinder needs base: [x, y, z], height > 0, radius >= 0, axis x|y|z", line, where)
            return None
        if material is None:
            return None
        height, radius = float(height), float(radius)
        r = math.floor(radius)
        cells: set[Cell] = set()
        for along in range(math.ceil(height)):
            for a in range(-r, r + 1):
                for b in range(-r, r + 1):
                    if a * a + b * b <= radius * radius + 1e-9:
                        if axis == "z":
                            cells.add((base[0] + a, base[1] + b, base[2] + along))
                        elif axis == "x":
                            cells.add((base[0] + along, base[1] + a, base[2] + b))
                        else:
                            cells.add((base[0] + a, base[1] + along, base[2] + b))
        return self._with_top_and_rim(cells, material, spec, line, where)

    def _ellipsoid(self, spec: dict[str, Any], line: int | None, where: str) -> dict[Cell, str] | None:
        if not self._check_fields(spec, ("center", "radii", "material", "top", "rim"), line, where):
            return None
        center, radii = _vec(_get(spec, "center")), _vec(_get(spec, "radii"))
        material = self._material(spec, "material", line, where)
        if center is None or radii is None or min(radii) <= 0:
            self.error("E013", "ellipsoid needs center: [x, y, z] and radii: [rx, ry, rz] (positive)", line, where)
            return None
        if material is None:
            return None
        cells: set[Cell] = set()
        lo = [math.floor(center[i] - radii[i]) for i in range(3)]
        hi = [math.ceil(center[i] + radii[i]) for i in range(3)]
        for x in range(lo[0], hi[0] + 1):
            for y in range(lo[1], hi[1] + 1):
                for z in range(lo[2], hi[2] + 1):
                    d = sum(((c - center[i]) / radii[i]) ** 2 for i, c in enumerate((x, y, z)))
                    if d <= 1 + 1e-9:
                        cells.add((x, y, z))
        return self._with_top_and_rim(cells, material, spec, line, where)

    def _line(self, spec: dict[str, Any], line: int | None, where: str) -> dict[Cell, str] | None:
        if not self._check_fields(spec, ("from", "to", "radius", "material"), line, where):
            return None
        a, b = _vec(_get(spec, "from")), _vec(_get(spec, "to"))
        radius = _get(spec, "radius", 0)
        material = self._material(spec, "material", line, where)
        if a is None or b is None or not (_num(radius) and radius >= 0):
            self.error("E013", "line needs from: [x, y, z], to: [x, y, z] and optional radius >= 0", line, where)
            return None
        if material is None:
            return None
        steps = max(1, math.ceil(math.dist(a, b) * 4))
        radius = float(radius)
        r = math.floor(radius)
        cells: dict[Cell, str] = {}
        for i in range(steps + 1):
            t = i / steps
            p = [a[k] + (b[k] - a[k]) * t for k in range(3)]
            cx, cy, cz = (math.floor(v + 0.5) for v in p)
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    for dz in range(-r, r + 1):
                        if dx * dx + dy * dy + dz * dz <= radius * radius + 1e-9:
                            cells[(cx + dx, cy + dy, cz + dz)] = material
        return cells

    def _sail(self, spec: dict[str, Any], line: int | None, where: str) -> dict[Cell, str] | None:
        allowed = ("at", "width", "height", "bulge", "brace", "material", "yard")
        if not self._check_fields(spec, allowed, line, where):
            return None
        at = _ivec(_get(spec, "at"))
        width, height = _get(spec, "width"), _get(spec, "height")
        bulge, brace = _get(spec, "bulge", 2), _get(spec, "brace", 0)
        material = self._material(spec, "material", line, where)
        yard = self._material(spec, "yard", line, where, required=False)
        if at is None or not (_num(width) and width > 0 and _num(height) and height > 0) or not _num(bulge) or not _num(brace):
            self.error("E013", "sail needs at: [x, y, z_bottom] (the mast), width, height, and optional bulge, brace (degrees)", line, where)
            return None
        if material is None or ("yard" in spec and yard is None):
            return None
        width, height, bulge = float(width), float(height), float(bulge)
        angle = math.radians(brace)
        ca, sa = math.cos(angle), math.sin(angle)
        half = width / 2
        rows = math.ceil(height)
        cells: dict[Cell, str] = {}

        def put(u: float, v: float, z: int, mat: str, normal: tuple[float, float, float] | None = None) -> None:
            x = at[0] + v * ca + u * sa
            y = at[1] - v * sa + u * ca
            cell = (math.floor(x + 0.5), math.floor(y + 0.5), z)
            cells[cell] = mat
            if normal is not None:
                self.pending_normals[cell] = normal

        def bulge_at(u: float, row: float) -> float:
            fullness = math.sin(math.pi * (row + 0.5) / rows)
            return bulge * (1 - (u / (half + 0.5)) ** 2) * fullness

        steps = max(1, math.ceil(width * 4))
        for row in range(rows):
            z = at[2] + row
            for i in range(steps + 1):
                u = -half + width * i / steps
                v = 1 + bulge_at(u, row)
                # Exact normal of the curved cloth: the forward axis tilted by the bulge's slopes.
                dv_du = (bulge_at(u + 0.1, row) - bulge_at(u - 0.1, row)) / 0.2
                dv_dz = (bulge_at(u, row + 0.1) - bulge_at(u, row - 0.1)) / 0.2
                nu, nv, nz = -dv_du, 1.0, -dv_dz
                length = math.sqrt(nu * nu + nv * nv + nz * nz)
                nu, nv, nz = nu / length, nv / length, nz / length
                normal = (nv * ca + nu * sa, -nv * sa + nu * ca, nz)
                put(u, v, z, material, normal)
                put(u, v + 0.6, z, material, normal)  # two voxels thick: no gaps for rays to slip through
        if yard is not None:
            for i in range(steps + 9):
                u = -half - 1 + (width + 2) * i / (steps + 8)
                put(u, 0, at[2] + rows, yard)
        return cells

    def _layers(self, spec: dict[str, Any], line: int | None, where: str) -> dict[Cell, str] | None:
        if not self._check_fields(spec, ("at", "legend", "grids"), line, where):
            return None
        at = _ivec(_get(spec, "at"))
        legend, grids = _get(spec, "legend"), _get(spec, "grids")
        if at is None or not isinstance(legend, dict) or not isinstance(grids, list) or not grids:
            self.error(
                "E013",
                "layers needs at: [x, y, z], legend: { char: material }, grids: [bottom layer, ..., top layer]",
                line,
                where,
            )
            return None
        ok = True
        for char, material in legend.items():
            if not isinstance(char, str) or len(char) != 1 or char == TRANSPARENT:
                self.error("E013", f"legend keys must be single characters other than '.', got {char!r}", line, where)
                ok = False
            elif not isinstance(material, str) or material not in self.materials:
                self.error("E013", f"legend: unknown material {material!r}", line, where)
                ok = False
        if not ok:
            return None
        cells: dict[Cell, str] = {}
        for layer, grid in enumerate(grids):
            if not isinstance(grid, str):
                self.error("E013", f"grids[{layer}] must be a block of text rows", line, where)
                return None
            for row, text in enumerate(r for r in grid.split("\n") if r.strip()):
                for col, char in enumerate(text.rstrip()):
                    if char == TRANSPARENT:
                        continue
                    if char not in legend:
                        self.error("E013", f"grids[{layer}] row {row + 1} col {col + 1}: {char!r} isn't in the legend", line, where)
                        return None
                    # Grids are seen from above with the model's front to the right: rows run towards -y.
                    cells[(at[0] + col, at[1] - row, at[2] + layer)] = legend[char]
        return cells


def _estimated_cells(shape: str, spec: dict[str, Any]) -> float:
    """Upper bound on the voxels a shape fills, from its parameters (inf if they're absurd)."""

    def size(key: str, default: float = 1.0) -> float:
        value = spec.get(key, default)
        return abs(float(value)) if _num(value) else default

    def extent(a: Any, b: Any) -> float:
        if isinstance(a, list) and isinstance(b, list) and len(a) == len(b) == 3 and all(_num(v) for v in a + b):
            return math.prod(abs(float(x) - float(y)) + 1 for x, y in zip(a, b, strict=True))
        return 1.0

    if shape == "box":
        return extent(spec.get("from"), spec.get("to"))
    if shape == "hull":
        return (size("length") + 1) * (size("beam") + 1) * (size("height") + 1)
    if shape == "cylinder":
        return (size("height") + 1) * (2 * size("radius", 0) + 1) ** 2
    if shape == "ellipsoid":
        radii = spec.get("radii")
        if isinstance(radii, list) and all(_num(v) for v in radii):
            return math.prod(2 * abs(float(r)) + 1 for r in radii)
        return 1.0
    if shape == "line":
        a, b = spec.get("from"), spec.get("to")
        length = math.dist(a, b) if isinstance(a, list) and isinstance(b, list) and len(a) == len(b) == 3 and all(_num(v) for v in a + b) else 1.0
        return (length + 1) * (2 * size("radius", 0) + 1) ** 3
    if shape == "sail":
        return (size("width") + 9) * (size("height") + 1) * 4
    return 0.0  # layers: bounded by the text itself


# --- poses ------------------------------------------------------------------------------------


def _parse_poses(
    raw: Any, line: int | None, ids: set[str], error: ErrorFn, hidden_by_default: set[str] | None = None
) -> dict[str, tuple[float, bool, list[tuple[dict[str, Cell], set[str]]]]]:
    """animations: { name: { fps, loop, poses: [ { part_id: { offset: [...] }, hide: [ids], show: [ids] } ] } }

    Each pose's hidden set = parts hidden by default, minus `show`, plus `hide`.
    """
    hidden_by_default = hidden_by_default or set()
    out: dict[str, tuple[float, bool, list[tuple[dict[str, Cell], set[str]]]]] = {}
    if raw is None:
        return out
    if not isinstance(raw, dict):
        error("E013", "animations must map a name to { fps, loop, poses: [...] }", line, "animations")
        return out
    for name, spec in raw.items():
        aline = _line(raw, name)
        where = f"animations.{name}"
        if not isinstance(name, str) or not NAME_RE.match(name):
            error("E013", "animation names must be lowercase letters, digits, '_' or '-'", aline, where)
            continue
        if not isinstance(spec, dict) or not isinstance(_get(spec, "poses"), list) or not spec["poses"]:
            error("E013", "an animation needs poses: a list with one pose per frame", aline, where)
            continue
        fps, loop = _get(spec, "fps", 8), _get(spec, "loop", True)
        if not _num(fps) or not 0 < fps <= 120 or not isinstance(loop, bool):
            error("E013", "fps must be 0-120 and loop true/false", aline, where)
            continue
        poses: list[tuple[dict[str, Cell], set[str]]] = []
        for index, pose in enumerate(spec["poses"]):
            pose = pose or {}
            if not isinstance(pose, dict):
                error("E013", f"poses[{index}] must be a mapping of part id -> {{ offset: [dx, dy, dz] }}", aline, where)
                break
            offsets: dict[str, Cell] = {}
            hide: set[str] = set()
            show: set[str] = set()
            for part_id, change in pose.items():
                if part_id in ("hide", "show"):
                    if not isinstance(change, list) or not all(isinstance(c, str) and c in ids for c in change):
                        error("E013", f"poses[{index}].{part_id} must list part ids ({', '.join(sorted(ids)) or 'none defined'})", aline, where)
                    elif part_id == "hide":
                        hide = set(change)
                    else:
                        show = set(change)
                    continue
                if part_id not in ids:
                    error("E013", f"poses[{index}]: unknown part id {part_id!r} (ids: {', '.join(sorted(ids)) or 'none'})", aline, where)
                    continue
                offset = _ivec(change.get("offset")) if isinstance(change, dict) else None
                if offset is None:
                    error("E013", f"poses[{index}].{part_id} needs offset: [dx, dy, dz] in whole voxels", aline, where)
                    continue
                offsets[part_id] = (offset[0], offset[1], offset[2])
            poses.append((offsets, (hidden_by_default - show) | hide))
        out[name] = (float(fps), loop, poses)
    return out


# --- render settings --------------------------------------------------------------------------


def _camera_and_light(project: Project, data: dict[str, Any], error: ErrorFn) -> tuple[Camera, Light]:
    base_camera, base_light = project.config.camera, project.config.light
    camera_raw, light_raw = data.get("camera", {}), data.get("light", {})
    elevation, scale = base_camera.elevation, base_camera.scale
    if not isinstance(camera_raw, dict):
        error("E013", "camera must be { elevation: degrees, scale: pixels per voxel }", _line(data, "camera"), "camera")
    else:
        elevation = camera_raw.get("elevation", elevation)
        scale = camera_raw.get("scale", scale)
        if not (_num(elevation) and 10 <= elevation <= 90 and _num(scale) and 0.25 <= scale <= 16):
            error("E013", "camera elevation must be 10-90 degrees and scale 0.25-16", _line(data, "camera"), "camera")
            elevation, scale = base_camera.elevation, base_camera.scale
    direction, ambient, shadows = base_light.direction, base_light.ambient, base_light.shadows
    if not isinstance(light_raw, dict):
        error("E013", "light must be { direction: [x, y, z], ambient: 0-1, shadows: bool }", _line(data, "light"), "light")
    else:
        vec = _vec(light_raw.get("direction", list(direction)))
        ambient = light_raw.get("ambient", ambient)
        shadows = light_raw.get("shadows", shadows)
        if vec is None or not any(vec) or not (_num(ambient) and 0 <= ambient < 1) or not isinstance(shadows, bool):
            error("E013", "light direction must be [x, y, z] (not all 0), ambient 0-1, shadows true/false", _line(data, "light"), "light")
        else:
            direction = (vec[0], vec[1], vec[2])
    return Camera(float(elevation), float(scale)), Light(direction, float(ambient), bool(shadows))


# --- entry point ------------------------------------------------------------------------------


def parse_model(data: Any, path: Path | None, project: Project, source_text: str = "") -> tuple[Asset | None, list[Finding]]:
    findings: list[Finding] = []

    def error(rule: str, message: str, line: int | None, where: str | None = None) -> None:
        findings.append(Finding(rule, message, path, line, where))

    if not isinstance(data, dict):
        error("E001", "a model file must be a mapping", None)
        return None, findings
    for key in data:
        if key not in _MODEL_FIELDS:
            error("E001", f"unknown field {key!r}; allowed: {', '.join(_MODEL_FIELDS)}", _line(data, key), str(key))

    name = data.get("name")
    expected = path.name[: -len(MODEL_SUFFIX)] if path is not None and path.name.endswith(MODEL_SUFFIX) else None
    if not isinstance(name, str) or not NAME_RE.match(name):
        error("E001", "missing or invalid 'name' (lowercase letters, digits, '_' or '-')", _line(data, "name"), "name")
        name = expected or "unnamed"
    elif expected is not None and name != expected:
        error("E001", f"name {name!r} doesn't match the file name; expected {expected!r}", _line(data, "name"), "name")

    palette = _resolve_palette(data, path, project, error, findings)
    meta = _parse_metadata(data, error)
    if "size" not in data:
        error("E001", "missing required field 'size' (the frame size in pixels)", _line(data), "size")
        return None, findings
    size = _parse_size(data["size"], "size", _line(data, "size"), error)
    if size is None or palette is None:
        return None, findings
    width, height = size

    pivot = (width // 2, round(height * 0.62))
    if "pivot" in data:
        raw_pivot = _ivec(data["pivot"], 2)
        if raw_pivot is None or not (0 <= raw_pivot[0] <= width and 0 <= raw_pivot[1] <= height):
            error("E008", f"pivot must be [x, y] inside the {width}x{height} frame", _line(data, "pivot"), "pivot")
        else:
            pivot = (raw_pivot[0], raw_pivot[1])

    directions = data.get("directions", 8)
    if isinstance(directions, bool) or not isinstance(directions, int) or directions not in DIRECTION_NAMES:
        error("E013", "directions must be 1, 4, 8 or 16", _line(data, "directions"), "directions")
        directions = 8
    heading = data.get("heading", 0 if directions > 1 else 270)
    if not _num(heading):
        error("E013", "heading must be degrees (0 = front faces right, 90 = away, 270 = towards the camera)", _line(data, "heading"), "heading")
        heading = 0

    outline_raw = data.get("outline", "auto")
    if outline_raw not in ("none", "auto"):
        error("E001", "outline must be none or auto", _line(data, "outline"), "outline")
    outline = outline_raw == "auto"
    outline_color = str(data["outline_color"]) if "outline_color" in data else _darkest(palette)
    if outline_color not in palette.colors:
        error("E005", f"outline_color {outline_color!r} isn't a palette key", _line(data, "outline_color"), "outline_color")

    camera, light = _camera_and_light(project, data, error)
    materials = _parse_materials(data.get("materials"), palette, _line(data, "materials"), error)
    max_steps = project.config.lint.max_ramp_steps
    if max_steps:
        for material in materials.values():
            if len(material.keys) > max_steps:
                findings.append(
                    Finding(
                        "W008",
                        f"material {material.name!r} has {len(material.keys)} shades; the project allows {max_steps} "
                        "per material (STYLE.md shading rules)",
                        path,
                        _line(data["materials"], material.name),
                        f"materials.{material.name}",
                    )
                )
    model = VoxelModel()
    if materials:
        _Builder(model, error, materials).build(data.get("parts"), _line(data, "parts"))
        if not model.voxels and not has_errors(findings):
            error("E013", "the model has no voxels (everything was carved away?)", _line(data, "parts"), "parts")
    poses = _parse_poses(
        data.get("animations"), _line(data, "animations"), set(model.groups.values()), error, model.hidden_by_default
    )
    for anim_name in poses:
        if anim_name in DIRECTION_NAMES.get(directions, []):
            error("E013", f"animation name {anim_name!r} is also a heading name; pick another", _line(data, "animations"), f"animations.{anim_name}")

    origin_raw = data.get("origin")
    origin: tuple[float, float, float] | None = None
    if origin_raw is not None:
        vec = _vec(origin_raw)
        if vec is None:
            error("E013", "origin must be [x, y, z]: the model point that lands on the pivot", _line(data, "origin"), "origin")
        else:
            origin = (vec[0], vec[1], vec[2])

    if has_errors(findings):
        return None, findings

    lo, hi = model.bounds()
    if origin is None:
        origin = ((lo[0] + hi[0] + 1) / 2, (lo[1] + hi[1] + 1) / 2, float(lo[2]))

    jobs: list[tuple[str, float, dict[str, Cell], set[str]]] = []
    animations: dict[str, Animation] = {}
    for direction_name, angle in heading_angles(directions, float(heading)):
        jobs.append((direction_name, angle, {}, set(model.hidden_by_default)))
        animations[direction_name] = Animation(direction_name, (direction_name,), 1.0, True)
        for anim_name, (fps, loop, pose_list) in poses.items():
            frame_names = []
            for index, (offsets, hidden) in enumerate(pose_list):
                frame = f"{anim_name}_{direction_name}_{index}" if directions > 1 else f"{anim_name}_{index}"
                jobs.append((frame, angle, offsets, hidden))
                frame_names.append(frame)
            anim_key = f"{anim_name}_{direction_name}" if directions > 1 else anim_name
            animations[anim_key] = Animation(anim_key, tuple(frame_names), fps, loop)

    material_keys = {m.name: [list(m.keys), m.two_sided] for m in materials.values()}
    cache_key = hashlib.sha256(
        json.dumps(
            [RENDERER_VERSION, source_text, material_keys, camera.__dict__, light.__dict__, origin, pivot, size, heading, directions],
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()[:24]
    base_frames = _cached_render(project, name, cache_key, model, materials, jobs, size, origin, pivot, camera, light)

    frames: dict[str, Grid] = {}
    for frame_name, grid in base_frames.items():
        if outline:
            edge = _edge_pixel(grid)
            if edge is not None:
                error(
                    "E007",
                    f"frame {frame_name}: the model touches the frame edge (pixel {edge[0]},{edge[1]}), so the outline "
                    "would be clipped. Grow size, move pivot/origin, or lower camera scale",
                    _line(data, "size"),
                    "size",
                )
                break
            frames[frame_name] = _outline(grid, outline_color)
        else:
            frames[frame_name] = grid

    used = {c for grid in frames.values() for row in grid for c in row if c != TRANSPARENT}
    variants = _parse_variants(data.get("variants"), palette, project, _line(data, "variants"), used, error)
    if has_errors(findings):
        return None, findings
    model_line = _line(data, "parts")
    return (
        Asset(
            kind="model",
            name=name,
            path=path,
            palette=palette,
            size=size,
            frames=frames,
            base_frames=dict(base_frames),
            frame_lines={f: model_line for f in frames},
            derived_from={},
            animations=animations,
            variants=variants,
            pivot=pivot,
            outline=outline,
            outline_color=outline_color,
            **meta,
        ),
        findings,
    )


def _cached_render(
    project: Project,
    name: str,
    key: str,
    model: VoxelModel,
    materials: dict[str, Material],
    jobs: list[tuple[str, float, dict[str, Cell], set[str]]],
    size: tuple[int, int],
    origin: tuple[float, float, float],
    pivot: tuple[int, int],
    camera: Camera,
    light: Light,
) -> dict[str, Grid]:
    cache_file = project.root / ".pagan-cache" / "models" / f"{name}-{key}.json"
    if cache_file.is_file():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            width, height = size
            if isinstance(cached, dict) and all(
                isinstance(cached.get(job[0]), list)
                and len(cached[job[0]]) == height
                and all(isinstance(row, str) and len(row) == width for row in cached[job[0]])
                for job in jobs
            ):
                return {job[0]: tuple(cached[job[0]]) for job in jobs}
        except (OSError, ValueError):
            pass  # unreadable or malformed cache: render again
    frames: dict[str, Grid] = {}
    for frame_name, angle, offsets, hidden in jobs:
        posed = model.posed(offsets, hidden)
        frames[frame_name] = render_heading(
            posed, materials, heading=angle, size=size, origin=origin, pivot=pivot, camera=camera, light=light
        )
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        for stale in cache_file.parent.glob(f"{name}-*.json"):
            if stale.stem.rsplit("-", 1)[0] == name:  # not "ship-big-..." when caching "ship"
                stale.unlink()
        cache_file.write_text(json.dumps({f: list(rows) for f, rows in frames.items()}), encoding="utf-8")
    except OSError:
        pass  # caching is an optimisation only
    return frames
