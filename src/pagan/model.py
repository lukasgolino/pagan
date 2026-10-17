"""`.model.yaml` files: parse a voxel model description and render it into a regular Asset.

Rendering is the slow part, so results are cached in `<project>/.pagan-cache/` keyed by everything that
affects the pixels (the file, its materials, camera, light and the renderer version).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

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
    _parse_lint,
    _parse_metadata,
    _parse_size,
    _parse_variant_axes,
    _parse_variants,
    _resolve_palette,
    check_base_variant,
)
from pagan.findings import Finding, has_errors
from pagan.palette import TRANSPARENT, Palette
from pagan.project import Project, parse_render
from pagan.yamlio import LineMap, YamlError, load_yaml
from pagan.voxel import (
    DIRECTION_NAMES,
    Camera,
    Cell,
    Light,
    Material,
    Overlay,
    PartMove,
    VoxelData,
    VoxelModel,
    heading_angles,
    render_heading,
    render_heading_full,
)

RENDERER_VERSION = "4"  # bump when rendering changes, to invalidate caches
PART_TYPES = ("box", "hull", "cylinder", "ellipsoid", "line", "sail", "triangle", "layers")
_MODEL_FIELDS = (
    "name", "description", "palette", "variants", "tags", "status", "style_version",
    "size", "pivot", "origin", "outline", "outline_color", "directions", "heading",
    "camera", "light", "materials", "parts", "animations", "lint", "variant_axes",
    "extends", "remove", "template", "base_variant", "supersample",
)  # fmt: skip
# Not inherited through `extends`: what the asset is, and how it's built/reviewed.
_OWN_FIELDS = ("name", "description", "tags", "status", "style_version", "lint", "template", "extends", "remove")
_MERGED_FIELDS = ("materials", "animations", "variants", "variant_axes")  # merged by name, the extending file wins
MAX_EXTENDS_DEPTH = 8

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
        self.hidden_ids: dict[str, int | None] = {}
        self.visible_ids: dict[str, int | None] = {}

    def build(self, parts: Any, line: int | None) -> None:
        self._build(parts, line)
        for part_id in sorted(self.hidden_ids.keys() & self.visible_ids.keys()):
            self.error(
                "E013",
                f"id {part_id!r} is used by hidden and visible parts; give the hidden part(s) their own id "
                "(a pose shows or hides a whole id)",
                self.hidden_ids[part_id],
                "parts",
            )

    def _build(self, parts: Any, line: int | None) -> None:
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
            if part_id is not None:
                (self.hidden_ids if hidden else self.visible_ids).setdefault(part_id, pline)
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
            if hidden and part_id is not None:
                # A hidden part is a layer of its own: shown (or carved) by poses, never touching the normal frames.
                layer: dict[Cell, VoxelData] = {c: (m, part_id, index, shape_normals.get(c)) for c, m in cells.items()}
                self.model.overlays.append(Overlay(part_id, layer, carve))
            for cell, material in cells.items() if not hidden else ():
                if carve:  # removes everything placed before it, hidden layers included
                    self.model._remove(cell)
                    for overlay in self.model.overlays:
                        overlay.cells.pop(cell, None)
                else:
                    self.model._put(cell, (material, part_id, index, shape_normals.get(cell)))
            total = len(self.model.voxels) + sum(len(o.cells) for o in self.model.overlays)
            if total > MAX_MODEL_VOXELS:
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
        cells: set[Cell] = set()
        for x in range(x0, x0 + math.ceil(length)):
            for z in range(z0, z0 + math.ceil(height)):
                reach = hull_reach(x - x0, length, beam, bow, stern, keel=z == z0)
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
        allowed = ("at", "width", "height", "bulge", "brace", "rig", "material", "yard")
        if not self._check_fields(spec, allowed, line, where):
            return None
        rig = _get(spec, "rig", "square")
        if rig not in ("square", "fore-aft"):
            self.error("E013", "rig must be square (across the hull, hung forward of the mast) or fore-aft (along the hull, aft of the mast)", line, where)
            return None
        at = _ivec(_get(spec, "at"))
        width, height = _get(spec, "width"), _get(spec, "height")
        bulge, brace = _get(spec, "bulge", 2), _get(spec, "brace", 0)
        material = self._material(spec, "material", line, where)
        yard = self._material(spec, "yard", line, where, required=False)
        if at is None or not (_num(width) and width > 0 and _num(height) and height > 0) or not _num(bulge) or not _num(brace):
            self.error("E013", "sail needs at: [x, y, z] (the mast where the sail's bottom edge meets it), width, height, and optional bulge, brace (degrees), rig", line, where)
            return None
        if material is None or ("yard" in spec and yard is None):
            return None
        cells: dict[Cell, str] = {}
        for cell in sail_cells(at, float(width), float(height), float(bulge), float(brace), rig, yard=yard is not None):
            if cell.normal is None:  # the yard
                cells[cell.cell] = str(yard)
            else:
                cells[cell.cell] = material
                self.pending_normals[cell.cell] = cell.normal
        return cells

    def _triangle(self, spec: dict[str, Any], line: int | None, where: str) -> dict[Cell, str] | None:
        """A flat filled triangle (jibs, lateen sails, fins, roof gables), with an exact normal."""
        if not self._check_fields(spec, ("points", "material", "thickness"), line, where):
            return None
        points = _get(spec, "points")
        thickness = _get(spec, "thickness", 1)
        material = self._material(spec, "material", line, where)
        corners = [_vec(p) for p in points] if isinstance(points, list) and len(points) == 3 else None
        if corners is None or any(c is None for c in corners) or not (isinstance(thickness, int) and 1 <= thickness <= 4):
            self.error("E013", "triangle needs points: [[x,y,z], [x,y,z], [x,y,z]] and optional thickness 1-4", line, where)
            return None
        if material is None:
            return None
        a, b, c = (tuple(float(v) for v in p) for p in corners if p is not None)
        ab = [b[i] - a[i] for i in range(3)]
        ac = [c[i] - a[i] for i in range(3)]
        n = (ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0])
        length = math.sqrt(sum(v * v for v in n))
        if length < 1e-9:
            self.error("E013", "triangle points are in a line", line, where)
            return None
        normal = (n[0] / length, n[1] / length, n[2] / length)
        steps = max(1, math.ceil(max(math.dist(a, b), math.dist(a, c), math.dist(b, c)) * 4))
        cells: dict[Cell, str] = {}
        for i in range(steps + 1):
            for j in range(steps + 1 - i):
                s_, t_ = i / steps, j / steps
                p = [a[k] + ab[k] * s_ + ac[k] * t_ for k in range(3)]
                for layer in range(thickness):
                    q = [p[k] + normal[k] * (layer * 0.6) for k in range(3)]
                    cell = (math.floor(q[0] + 0.5), math.floor(q[1] + 0.5), math.floor(q[2] + 0.5))
                    cells[cell] = material
                    self.pending_normals[cell] = normal
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


def hull_reach(x: int, length: float, beam: float, bow: float = 0.35, stern: float = 0.1, keel: bool = False) -> int:
    """How far the `hull` primitive reaches either side of its centre line at column `x` (0 = the stern end
    of `from`): it fills y = centre - reach .. centre + reach. `keel` = the bottom layer, which is narrower."""
    u = (x + 0.5) / length
    half = beam / 2
    if bow > 0 and u > 1 - bow:
        hw = half * math.sqrt(max(0.0, 1 - ((u - (1 - bow)) / bow) ** 2))
    elif stern > 0 and u < stern:
        hw = half * (0.75 + 0.25 * u / stern)
    else:
        hw = half
    layer_hw = hw * (0.8 if keel else 1.0)  # rounded keel
    return math.floor(layer_hw - 0.5 + 1e-9)


@dataclass(frozen=True)
class SailCell:
    """One voxel of a `sail`: where it is, and where on the cloth it came from.

    `u` runs across the cloth (from -width/2 to +width/2; for fore-aft rigs from -width at the leech to 0
    at the mast), `row` counts up from the foot. Yard voxels have `row` = height and no normal.
    """

    cell: Cell
    u: float
    row: int
    normal: tuple[float, float, float] | None


def sail_cells(
    at: tuple[int, ...], width: float, height: float, bulge: float = 2, brace: float = 0, rig: str = "square", yard: bool = False
) -> list[SailCell]:
    """The voxels the `sail` primitive fills, in the order it fills them (later ones win a shared cell)."""
    fore_aft = rig == "fore-aft"
    # Square sails span the hull's width; fore-and-aft sails lie along it, luff at the mast, reaching aft.
    angle = math.radians(brace + (90 if fore_aft else 0))
    ca, sa = math.cos(angle), math.sin(angle)
    half = width / 2
    centre = -half if fore_aft else 0.0
    lift = 0.0 if fore_aft else 1.0
    rows = math.ceil(height)
    out: list[SailCell] = []

    def place(u: float, v: float) -> tuple[int, int]:
        x = at[0] + v * ca + u * sa
        y = at[1] - v * sa + u * ca
        return math.floor(x + 0.5), math.floor(y + 0.5)

    def bulge_at(u: float, row: float) -> float:
        fullness = math.sin(math.pi * (row + 0.5) / rows)
        return bulge * (1 - ((u - centre) / (half + 0.5)) ** 2) * fullness

    steps = max(1, math.ceil(width * 4))
    for row in range(rows):
        z = at[2] + row
        for i in range(steps + 1):
            u = centre - half + width * i / steps
            v = lift + bulge_at(u, row)
            # Exact normal of the curved cloth: the forward axis tilted by the bulge's slopes.
            dv_du = (bulge_at(u + 0.1, row) - bulge_at(u - 0.1, row)) / 0.2
            dv_dz = (bulge_at(u, row + 0.1) - bulge_at(u, row - 0.1)) / 0.2
            nu, nv, nz = -dv_du, 1.0, -dv_dz
            length = math.sqrt(nu * nu + nv * nv + nz * nz)
            nu, nv, nz = nu / length, nv / length, nz / length
            normal = (nv * ca + nu * sa, -nv * sa + nu * ca, nz)
            for depth in (v, v + 0.6):  # two voxels thick: no gaps for rays to slip through
                out.append(SailCell((*place(u, depth), z), u, row, normal))
    if yard:  # square: the yard across the top; fore-and-aft: the gaff along the top
        for i in range(steps + 9):
            u = centre - half - 1 + (width + 2) * i / (steps + 8)
            out.append(SailCell((*place(u, 0), at[2] + rows), u, rows, None))
    return out


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
    if shape == "triangle":
        pts = spec.get("points")
        if isinstance(pts, list) and len(pts) == 3 and all(isinstance(p, list) and len(p) == 3 and all(_num(v) for v in p) for p in pts):
            span = max(math.dist(p, q) for p in pts for q in pts)
            return (span + 1) ** 2 * 4
        return 1.0
    return 0.0  # layers: bounded by the text itself


# --- poses ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Pose:
    """One animation frame of a model: parts moved/hidden/shown, and the whole model tilted."""

    moves: tuple[tuple[str, PartMove], ...] = ()
    hidden: frozenset[str] = frozenset()
    roll: float = 0.0
    pitch: float = 0.0


_MOVE_FIELDS = ("offset", "roll", "pitch", "yaw", "about")


def _angle(value: Any) -> bool:
    return _num(value) and -360 <= value <= 360


def _parse_poses(
    raw: Any, line: int | None, ids: set[str], error: ErrorFn, hidden_by_default: set[str] | None = None
) -> dict[str, tuple[float, bool, list[Pose]]]:
    """animations: { name: { fps, loop, poses: [ { roll, pitch, part_id: { offset, roll, pitch, yaw, about },
    hide: [ids], show: [ids] } ] } }

    Each pose's hidden set = parts hidden by default, minus `show`, plus `hide`.
    """
    hidden_by_default = hidden_by_default or set()
    out: dict[str, tuple[float, bool, list[Pose]]] = {}
    if raw is None:
        return out
    if not isinstance(raw, dict):
        error("E013", "animations must map a name to { fps, loop, poses: [...] }", line, "animations")
        return out
    known = ", ".join(sorted(ids)) or "none defined"
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
        poses: list[Pose] = []
        for index, pose in enumerate(spec["poses"]):
            pose = pose or {}
            pwhere = f"{where}.poses[{index}]"
            if not isinstance(pose, dict):
                error("E013", "a pose is a mapping: part id -> { offset, roll, pitch, yaw, about }, plus roll, pitch, hide, show", aline, pwhere)
                break
            moves: dict[str, PartMove] = {}
            hide: set[str] = set()
            show: set[str] = set()
            tilt = {"roll": 0.0, "pitch": 0.0}
            for part_id, change in pose.items():
                if part_id in ("hide", "show"):
                    if not isinstance(change, list) or not all(isinstance(c, str) and c in ids for c in change):
                        error("E013", f"{part_id} must list part ids ({known})", aline, f"{pwhere}.{part_id}")
                    elif part_id == "hide":
                        hide = set(change)
                    else:
                        show = set(change)
                    continue
                if part_id in ("roll", "pitch"):
                    if not _angle(change):
                        error("E013", f"{part_id} tilts the whole model: degrees, -360..360", aline, f"{pwhere}.{part_id}")
                    else:
                        tilt[part_id] = float(change)
                    continue
                if part_id not in ids:
                    error("E013", f"unknown part id {part_id!r} (ids: {known}); a pose also takes roll, pitch, hide, show", aline, f"{pwhere}.{part_id}")
                    continue
                move = _parse_move(change, aline, f"{pwhere}.{part_id}", error)
                if move is not None:
                    moves[part_id] = move
            poses.append(Pose(tuple(sorted(moves.items())), frozenset((hidden_by_default - show) | hide), tilt["roll"], tilt["pitch"]))
        out[name] = (float(fps), loop, poses)
    return out


def _parse_move(change: Any, line: int | None, where: str, error: ErrorFn) -> PartMove | None:
    usage = "a part's pose is { offset: [dx, dy, dz] (whole voxels), roll/pitch/yaw: degrees, about: [x, y, z] (hinge) }"
    if not isinstance(change, dict) or not change or any(k not in _MOVE_FIELDS for k in change):
        error("E013", usage, line, where)
        return None
    offset = _ivec(change.get("offset", [0, 0, 0]))
    angles = [change.get(k, 0) for k in ("roll", "pitch", "yaw")]
    about = _vec(change["about"]) if "about" in change else None
    if offset is None or not all(_angle(a) for a in angles) or ("about" in change and about is None):
        error("E013", usage, line, where)
        return None
    return PartMove(
        (offset[0], offset[1], offset[2]),
        float(angles[0]),
        float(angles[1]),
        float(angles[2]),
        (about[0], about[1], about[2]) if about is not None else None,
    )


# --- render settings --------------------------------------------------------------------------


def _camera_and_light(project: Project, data: dict[str, Any], error: ErrorFn) -> tuple[Camera, Light]:
    """A model may override any [camera]/[light] setting; the rest come from pagan.toml."""

    def report(message: str, where: str) -> None:
        error("E013", f"{message} (model override)", _line(data, where.split(".")[0]), where)

    return parse_render(
        data.get("camera", {}), data.get("light", {}), report, project.config.camera, project.config.light
    )


# --- entry point ------------------------------------------------------------------------------


@dataclass
class _Setup:
    """A parsed model, ready to render: everything except the pixels."""

    name: str
    data: dict[str, Any]
    palette: Palette
    meta: dict[str, Any]
    size: tuple[int, int]
    pivot: tuple[int, int]
    origin: tuple[float, float, float]
    outline: bool
    outline_color: str
    camera: Camera
    light: Light
    materials: dict[str, Material]
    model: VoxelModel
    jobs: list[tuple[str, float, Pose]]  # frame name, heading angle, pose
    animations: dict[str, Animation]
    pose_names: list[str]  # the file's animation names (each rendered per heading)
    directions: int
    heading: float


def _setup(data: Any, path: Path | None, project: Project, error: ErrorFn, findings: list[Finding]) -> _Setup | None:
    if not isinstance(data, dict):
        error("E001", "a model file must be a mapping", None, None)
        return None
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
        return None
    size = _parse_size(data["size"], "size", _line(data, "size"), error)
    if size is None or palette is None:
        return None
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
        error("E013", "directions must be 1, 4, 8, 16 or 32", _line(data, "directions"), "directions")
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
    poses = _parse_poses(data.get("animations"), _line(data, "animations"), model.part_ids(), error, model.hidden_by_default)
    heading_names = {n for n, _ in heading_angles(directions, float(heading))} if _num(heading) else set()
    for anim_name in poses:
        if anim_name in heading_names:
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
        return None

    if origin is None:  # the centre of everything the file builds, hidden parts included
        cells = [*model.voxels, *(c for o in model.overlays for c in o.cells)]
        lo = tuple(min(c[i] for c in cells) for i in range(3))
        hi = tuple(max(c[i] for c in cells) for i in range(3))
        origin = ((lo[0] + hi[0] + 1) / 2, (lo[1] + hi[1] + 1) / 2, float(lo[2]))

    base = Pose(hidden=frozenset(model.hidden_by_default))
    jobs: list[tuple[str, float, Pose]] = []
    animations: dict[str, Animation] = {}
    for direction_name, angle in heading_angles(directions, float(heading)):
        jobs.append((direction_name, angle, base))
        animations[direction_name] = Animation(direction_name, (direction_name,), 1.0, True)
        for anim_name, (fps, loop, pose_list) in poses.items():
            frame_names = []
            for index, pose in enumerate(pose_list):
                frame = f"{anim_name}_{direction_name}_{index}" if directions > 1 else f"{anim_name}_{index}"
                jobs.append((frame, angle, pose))
                frame_names.append(frame)
            anim_key = f"{anim_name}_{direction_name}" if directions > 1 else anim_name
            animations[anim_key] = Animation(anim_key, tuple(frame_names), fps, loop)

    return _Setup(
        name, data, palette, meta, size, pivot, origin, outline, outline_color, camera, light, materials, model,
        jobs, animations, list(poses), directions, float(heading),
    )  # fmt: skip


def _render_jobs(
    setup: _Setup, size: tuple[int, int], pivot: tuple[int, int], full: bool = False
) -> dict[str, Any]:
    """Render every job: rows of keys per frame (or Rendered objects with normals when `full`)."""
    out: dict[str, Any] = {}
    posed_models: dict[tuple[Any, ...], VoxelModel] = {}
    for frame_name, angle, pose in setup.jobs:
        key = (pose.moves, pose.hidden)
        if key not in posed_models:
            posed_models[key] = setup.model.posed(dict(pose.moves), set(pose.hidden))
        render = render_heading_full if full else render_heading
        out[frame_name] = render(
            posed_models[key], setup.materials, heading=angle, size=size, origin=setup.origin, pivot=pivot,
            camera=setup.camera, light=setup.light, roll=pose.roll, pitch=pose.pitch,
        )  # fmt: skip
    return out


def resolve_extends(
    data: Any, path: Path | None, project: Project, error: ErrorFn, seen: tuple[str, ...] = ()
) -> tuple[Any, list[str]]:
    """Merge `extends: <base model>` into the file's data. Returns (merged data, the base files' texts).

    The base's fields are inherited except its identity/review fields (_OWN_FIELDS); materials,
    animations and variants merge by name (this file wins); parts are the base's, minus those whose id
    is in `remove`, followed by this file's.
    """
    if not isinstance(data, dict) or "extends" not in data:
        if isinstance(data, dict) and "remove" in data:
            error("E013", "remove lists base part ids to drop; it needs extends: <base model>", _line(data, "remove"), "remove")
        return data, []
    base_name = data["extends"]
    line = _line(data, "extends")
    if not isinstance(base_name, str) or not NAME_RE.match(base_name):
        error("E013", "extends must be the name of another model in models/", line, "extends")
        return data, []
    if base_name in seen or len(seen) >= MAX_EXTENDS_DEPTH:
        error("E013", f"extends forms a cycle or is too deep: {' -> '.join((*seen, base_name))}", line, "extends")
        return data, []
    base_path = project.models_dir / f"{base_name}{MODEL_SUFFIX}"
    try:
        base_text = base_path.read_text(encoding="utf-8")
        base = load_yaml(base_path)
    except (OSError, YamlError) as exc:
        reason = exc.message if isinstance(exc, YamlError) else "no such file"
        error("E013", f"extends: can't read base model {base_name!r} ({base_path.name}): {reason}", line, "extends")
        return data, []
    if not isinstance(base, dict):
        error("E013", f"extends: base model {base_name!r} isn't a mapping", line, "extends")
        return data, []
    own_name = data.get("name") if isinstance(data.get("name"), str) else (path.name if path else "?")
    base, texts = resolve_extends(base, base_path, project, error, (*seen, str(own_name)))

    remove = data.get("remove", [])
    base_parts = base.get("parts", []) if isinstance(base.get("parts", []), list) else []
    base_ids = {p.get("id") for p in base_parts if isinstance(p, dict)}
    if not isinstance(remove, list) or not all(isinstance(r, str) for r in remove):
        error("E013", "remove must list part ids of the base model", _line(data, "remove"), "remove")
        remove = []
    for part_id in remove:
        if part_id not in base_ids:
            known = ", ".join(sorted(i for i in base_ids if isinstance(i, str))) or "none"
            error("E013", f"remove: the base model has no part id {part_id!r} (ids: {known})", _line(data, "remove"), "remove")

    merged = LineMap()
    merged.line = data.line if isinstance(data, LineMap) else None
    for key, value in base.items():
        if key not in _OWN_FIELDS:
            merged[key] = value
    for key, value in data.items():
        if key in _MERGED_FIELDS and isinstance(value, dict) and isinstance(merged.get(key), dict):
            combined = LineMap()
            combined.line = value.line if isinstance(value, LineMap) else None
            combined.update(merged[key])
            combined.update(value)
            if isinstance(value, LineMap):
                combined.key_lines.update(value.key_lines)
            value = combined
        elif key == "parts":
            continue
        merged[key] = value
        if isinstance(data, LineMap) and key in data.key_lines:
            merged.key_lines[key] = data.key_lines[key]
    own_parts = data.get("parts", [])
    kept = [p for p in base_parts if not (isinstance(p, dict) and p.get("id") in remove)]
    merged["parts"] = kept + (own_parts if isinstance(own_parts, list) else [own_parts])
    if isinstance(data, LineMap) and "parts" in data.key_lines:
        merged.key_lines["parts"] = data.key_lines["parts"]
    return merged, [*texts, base_text]


def parse_model(data: Any, path: Path | None, project: Project, source_text: str = "") -> tuple[Asset | None, list[Finding]]:
    findings: list[Finding] = []

    def error(rule: str, message: str, line: int | None, where: str | None = None) -> None:
        findings.append(Finding(rule, message, path, line, where))

    template = data.get("template", False) if isinstance(data, dict) else False
    if not isinstance(template, bool):
        error("E013", "template must be true (a base for `extends`, not built itself) or false", _line(data, "template"), "template")
    data, base_texts = resolve_extends(data, path, project, error)
    source_text = "\n---\n".join([*base_texts, source_text])
    setup = _setup(data, path, project, error, findings)
    if setup is None:
        return None, findings
    data, size, pivot, camera, light = setup.data, setup.size, setup.pivot, setup.camera, setup.light
    material_keys = {m.name: [list(m.keys), m.two_sided] for m in setup.materials.values()}
    cache_key = hashlib.sha256(
        json.dumps(
            [RENDERER_VERSION, source_text, material_keys, camera.__dict__, light.__dict__, setup.origin, pivot, size, setup.heading, setup.directions],
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()[:24]
    base_frames = _cached_render(project, setup, cache_key)

    frames: dict[str, Grid] = {}
    clipped = [name for name, grid in base_frames.items() if setup.outline and _edge_pixel(grid) is not None]
    if clipped:
        first = clipped[0]
        edge = _edge_pixel(base_frames[first])
        assert edge is not None
        more = f" (and {len(clipped) - 1} more frames)" if len(clipped) > 1 else ""
        error(
            "E007",
            f"frame {first}{more}: the model touches the frame edge (pixel {edge[0]},{edge[1]}), so the outline "
            "would be clipped. Run `pagan fit` for a size and pivot that fit every frame, or lower camera scale",
            _line(data, "size"),
            "size",
        )
    for frame_name, grid in base_frames.items():
        frames[frame_name] = _outline(grid, setup.outline_color) if setup.outline else grid

    used = {c for grid in frames.values() for row in grid for c in row if c != TRANSPARENT}
    variants = _parse_variants(data.get("variants"), setup.palette, project, _line(data, "variants"), used, error)
    variant_axes, combos = _parse_variant_axes(data.get("variant_axes"), setup.palette, project, _line(data, "variant_axes"), used, variants, error)
    variants.update(combos)
    check_base_variant(setup.meta["base_variant"], variants, _line(data, "base_variant"), error)
    lint_targets: dict[str, tuple[str, ...]] = {name: (name,) for name in [*frames, *setup.animations]}
    for pose_name in setup.pose_names:  # `damaged` covers damaged_<heading> and its frames
        covered = [a for a in setup.animations if a == pose_name or a.startswith(f"{pose_name}_")]
        lint_targets.setdefault(pose_name, tuple(t for a in covered for t in (a, *setup.animations[a].frames)))
    lint_disable, lint_disable_for = _parse_lint(data.get("lint"), _line(data, "lint"), lint_targets, error)
    if has_errors(findings):
        return None, findings

    def normal_maps() -> dict[str, Any]:
        """Screen-space normals per frame (rendered on demand, e.g. for the "normals" exporter)."""
        out: dict[str, Any] = {}
        for frame_name, rendered in _render_jobs(setup, size, pivot, full=True).items():
            normals = rendered.normals.copy()
            outlined = (normals == 0).all(axis=2) & np.array([[c != "." for c in row] for row in frames[frame_name]])
            normals[outlined] = (0.0, 0.0, 1.0)  # outline pixels face the viewer
            out[frame_name] = normals
        return out

    return (
        Asset(
            kind="model",
            name=setup.name,
            path=path,
            palette=setup.palette,
            size=size,
            frames=frames,
            base_frames=dict(base_frames),
            frame_lines={f: None for f in frames},  # rendered: no source line per frame
            derived_from={},
            animations=setup.animations,
            variants=variants,
            pivot=pivot,
            outline=setup.outline,
            outline_color=setup.outline_color,
            normal_maps=normal_maps,
            lint_disable=lint_disable,
            lint_disable_for=lint_disable_for,
            template=template is True,
            variant_axes=variant_axes,
            **setup.meta,
        ),
        findings,
    )


@dataclass
class Fit:
    """`pagan fit`: the smallest frame that holds every heading and pose, with the origin kept on the pivot."""

    name: str
    size: tuple[int, int]
    pivot: tuple[int, int]
    current_size: tuple[int, int]
    current_pivot: tuple[int, int]
    clipped: list[str]  # frames that don't fit the current size/pivot
    margin: int


def fit_model(path: Path, project: Project, margin: int = 0) -> tuple[Fit | None, list[Finding]]:
    """Render every frame on a canvas big enough for anything, and measure what's actually drawn."""
    findings: list[Finding] = []

    def error(rule: str, message: str, line: int | None, where: str | None = None) -> None:
        findings.append(Finding(rule, message, path, line, where))

    try:
        data = load_yaml(path)
    except YamlError as exc:
        return None, [Finding("E001", exc.message, path, exc.line)]
    data, _ = resolve_extends(data, path, project, error)
    setup = _setup(data, path, project, error, findings)
    if setup is None:
        return None, findings
    cells = [*setup.model.voxels, *(c for o in setup.model.overlays for c in o.cells)]
    reach = max(math.dist((x + dx, y + dy, z + dz), setup.origin) for x, y, z in cells for dx in (0, 1) for dy in (0, 1) for dz in (0, 1))
    reach += max((abs(o) for _, _, pose in setup.jobs for _, move in pose.moves for o in move.offset), default=0)
    reach *= 2 if any(m.roll or m.pitch or m.yaw for _, _, pose in setup.jobs for _, m in pose.moves) else 1
    half = math.ceil(reach * setup.camera.scale) + 4
    canvas, centre = (2 * half, 2 * half), (half, half)
    border = (1 if setup.outline else 0) + margin
    boxes: dict[str, tuple[int, int, int, int]] = {}  # frame -> drawn x0, y0, x1, y1 relative to the pivot
    for frame, grid in _render_jobs(setup, canvas, centre).items():
        points = [(x, y) for y, row in enumerate(grid) for x, c in enumerate(row) if c != TRANSPARENT]
        if points:
            xs, ys = [x for x, _ in points], [y for _, y in points]
            boxes[frame] = (min(xs) - centre[0], min(ys) - centre[1], max(xs) - centre[0], max(ys) - centre[1])
    if not boxes:
        return None, [*findings, Finding("E013", "nothing to fit: no frame draws any pixels", path, None, "parts")]
    x0, y0 = min(b[0] for b in boxes.values()), min(b[1] for b in boxes.values())
    x1, y1 = max(b[2] for b in boxes.values()), max(b[3] for b in boxes.values())
    size = (x1 - x0 + 1 + 2 * border, y1 - y0 + 1 + 2 * border)
    pivot = (border - x0, border - y0)
    edge = 1 if setup.outline else 0  # outlined frames need a free pixel around the model
    (w, h), (px, py) = setup.size, setup.pivot
    clipped = [
        frame
        for frame, (a, b, c, d) in boxes.items()
        if px + a < edge or py + b < edge or px + c > w - 1 - edge or py + d > h - 1 - edge
    ]
    return Fit(setup.name, size, pivot, setup.size, setup.pivot, clipped, margin), findings


def _cached_render(project: Project, setup: _Setup, key: str) -> dict[str, Grid]:
    name, (width, height) = setup.name, setup.size
    cache_file = project.root / ".pagan-cache" / "models" / f"{name}-{key}.json"
    if cache_file.is_file():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and all(
                isinstance(cached.get(job[0]), list)
                and len(cached[job[0]]) == height
                and all(isinstance(row, str) and len(row) == width for row in cached[job[0]])
                for job in setup.jobs
            ):
                return {job[0]: tuple(cached[job[0]]) for job in setup.jobs}
        except (OSError, ValueError):
            pass  # unreadable or malformed cache: render again
    frames: dict[str, Grid] = _render_jobs(setup, setup.size, setup.pivot)
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        for stale in cache_file.parent.glob(f"{name}-*.json"):
            if stale.stem.rsplit("-", 1)[0] == name:  # not "ship-big-..." when caching "ship"
                stale.unlink()
        cache_file.write_text(json.dumps({f: list(rows) for f, rows in frames.items()}), encoding="utf-8")
    except OSError:
        pass  # caching is an optimisation only
    return frames
