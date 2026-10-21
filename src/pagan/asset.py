"""Sprites and tilesets: palette-keyed pixel grids plus animations, variants and metadata.

Parsing collects every finding it can rather than stopping at the first. The resulting `Asset` holds
fully resolved frames: mirrored, derived (`from`/`flip`/`shift`) and outlined.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pagan.findings import Finding, PaganError, has_errors
from pagan.palette import TRANSPARENT, Palette, parse_palette
from pagan.project import MAX_SUPERSAMPLE, Project
from pagan.yamlio import LineMap, YamlError, load_yaml

SPRITE_SUFFIX = ".sprite.yaml"
TILESET_SUFFIX = ".tiles.yaml"
MODEL_SUFFIX = ".model.yaml"
ASSET_SUFFIXES = (SPRITE_SUFFIX, TILESET_SUFFIX, MODEL_SUFFIX)
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
FRAME_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
MAX_SIZE = 1024
DEFAULT_FPS = 8.0
STATUSES = ("draft", "approved")
MAX_PIXEL_FINDINGS = 8  # per frame, so one bad row doesn't drown everything else

Kind = Literal["sprite", "tileset", "model"]
Grid = tuple[str, ...]  # rows of palette keys, "." = transparent
ErrorFn = Callable[[str, str, int | None, str | None], None]

_COMMON_FIELDS = (
    "name", "description", "palette", "variants", "variant_axes", "base_variant", "tags", "status", "style_version", "lint",
    "supersample",
)  # fmt: skip
WARNING_ID_RE = re.compile(r"^W\d{3}$")
_SPRITE_FIELDS = (
    *_COMMON_FIELDS, "size", "pivot", "mirror", "outline", "outline_color", "shadow", "frames", "animations", "nine_slice",
    "font",
)  # fmt: skip
MAX_OUTLINE_WIDTH = 8  # per ring
_FONT_FIELDS = ("glyphs", "cell", "baseline", "line_height", "advance", "spacing", "space")
Margins = tuple[int, int, int, int]  # left, top, right, bottom
_TILESET_FIELDS = (*_COMMON_FIELDS, "tile_size", "columns", "tiles", "animations", "export_textures")


@dataclass(frozen=True)
class Animation:
    name: str
    frames: tuple[str, ...]
    fps: float
    loop: bool
    new_row: bool = False  # tile animations: start on a new atlas row (column 0)


@dataclass(frozen=True)
class Textures:
    """`export_textures` on a tileset: tiles (and groups of tiles) built as their own repeatable PNGs, for 3D
    surfaces (an atlas region can't repeat). A group is rows of tile names laid out as one texture."""

    tiles: tuple[str, ...]
    groups: dict[str, tuple[tuple[str, ...], ...]]
    triplanar: bool = False


@dataclass(frozen=True)
class Font:
    """`font:` on a sprite: its frames (or cells cut from them) are glyphs, in `glyphs` order."""

    glyphs: str
    cell: tuple[int, int]  # glyph cell size; the frame size when each frame is one glyph
    baseline: int  # pixels from the cell's top to the baseline (the ascent)
    line_height: int
    advance: int | None  # fixed advance; None = each glyph's drawn width + spacing
    spacing: int
    space: int  # advance of a blank glyph (" ") when advance is auto


@dataclass(frozen=True)
class Variant:
    """A recolor. `keys` maps source key -> key in `palette` (keys not listed map to themselves)."""

    name: str
    keys: dict[str, str]
    palette: Palette


@dataclass(frozen=True)
class Asset:
    kind: Kind
    name: str
    path: Path | None
    palette: Palette
    size: tuple[int, int]  # width, height of one frame / tile
    frames: dict[str, Grid]  # final pixels, in source order
    base_frames: dict[str, Grid]  # before outline
    frame_lines: dict[str, int | None]
    derived_from: dict[str, str]  # frame -> the frame it was derived from
    animations: dict[str, Animation] = field(default_factory=dict)
    variants: dict[str, Variant] = field(default_factory=dict)
    pivot: tuple[int, int] = (0, 0)
    columns: int = 8  # tilesets: atlas layout
    mirror: bool = False
    outline: bool = False
    outline_color: str | None = None  # the first (innermost) outline ring's colour
    outlines: tuple[tuple[int, str], ...] = ()  # sprites: (width, colour) rings, innermost first; () = no outline
    shadow: tuple[int, int, str] | None = None  # sprites: drop shadow (dx, dy, colour) under the outlined pixels
    description: str | None = None
    tags: tuple[str, ...] = ()
    status: str = "draft"
    style_version: int = 1
    # `lint:` in the file: warnings off for the whole asset, and per frame/tile/animation name
    lint_disable: frozenset[str] = frozenset()
    lint_disable_for: dict[str, frozenset[str]] = field(default_factory=dict)
    lint_max_ramps: int | None = None  # `lint: { max_ramps: N }`: W003's limit for this asset
    template: bool = False  # models: only a base for `extends`; linted, never built
    # `variant_axes`: axis -> option -> recolour; every combination is also in `variants` as "<a>+<b>"
    variant_axes: dict[str, dict[str, Variant]] = field(default_factory=dict)
    base_variant: str | None = None  # the name the base colours go by among the variants (e.g. "cyan")
    supersample: int | None = None  # authored at N x the output size; None = the project's setting
    nine_slice: dict[str, Margins] = field(default_factory=dict)  # frame -> 9-slice margins (sprites)
    font: Font | None = None  # sprites: the frames are a font's glyphs
    textures: Textures | None = None  # tilesets: `export_textures` (repeatable PNGs for 3D surfaces)
    # 3D models only: renders screen-space normal maps per frame on demand (H x W x 3 arrays)
    normal_maps: Callable[[], dict[str, Any]] | None = field(default=None, compare=False, repr=False)
    # 3D models only: what mesh export needs (pagan.model.MeshSource); mesh_only = `directions: 0` (no sprites)
    mesh: Any = field(default=None, compare=False, repr=False)
    mesh_only: bool = False


def asset_kind(path: Path) -> Kind | None:
    if path.name.endswith(SPRITE_SUFFIX):
        return "sprite"
    if path.name.endswith(TILESET_SUFFIX):
        return "tileset"
    if path.name.endswith(MODEL_SUFFIX):
        return "model"
    return None


def asset_name_from_path(path: Path) -> str | None:
    for suffix in ASSET_SUFFIXES:
        if path.name.endswith(suffix):
            return path.name[: -len(suffix)]
    return None


def _line(data: Any, key: Any = None) -> int | None:
    if isinstance(data, LineMap):
        return data.line_of(key) if key is not None else data.line
    return None


# --- grids ------------------------------------------------------------------------------------


def _split_rows(raw: Any) -> list[str] | None:
    if isinstance(raw, str):
        rows = [row.rstrip() for row in raw.split("\n")]
        while rows and rows[-1] == "":
            rows.pop()
        return rows
    if isinstance(raw, list) and all(isinstance(r, str) for r in raw):
        return [r.rstrip() for r in raw]
    return None


def _parse_grid(
    raw: Any,
    *,
    width: int,
    height: int,
    keys: set[str],
    where: str,
    line: int | None,
    mirror_note: str,
    error: ErrorFn,
) -> Grid | None:
    rows = _split_rows(raw)
    if rows is None:
        error("E001", "a frame must be a block of text rows (use `name: |` then the rows)", line, where)
        return None
    first_row_line = line + 1 if line is not None and isinstance(raw, str) else None

    def row_line(i: int) -> int | None:
        return first_row_line + i if first_row_line is not None else line

    ok = True
    if len(rows) != height:
        error("E003", f"has {len(rows)} rows, expected {height}", line, where)
        ok = False
    reported = 0
    for i, row in enumerate(rows):
        if len(row) != width:
            error("E003", f"row {i + 1} is {len(row)} wide, expected {width}{mirror_note}", row_line(i), where)
            ok = False
        for j, char in enumerate(row):
            if char != TRANSPARENT and char not in keys:
                ok = False
                if reported < MAX_PIXEL_FINDINGS:
                    hint = " (spaces aren't allowed; use '.' for transparent)" if char.isspace() else ""
                    error(
                        "E002",
                        f"unknown pixel {char!r}: not '.' and not a palette key{hint}",
                        row_line(i),
                        f"{where} row {i + 1} col {j + 1}",
                    )
                reported += 1
    return tuple(rows) if ok else None


def _mirror(grid: Grid, width: int) -> Grid:
    """Reflect the authored left half; for odd widths the center column isn't duplicated."""
    return tuple(row + row[: width // 2][::-1] for row in grid)


def _flip(grid: Grid, how: str) -> Grid:
    if how in ("horizontal", "both"):
        grid = tuple(row[::-1] for row in grid)
    if how in ("vertical", "both"):
        grid = grid[::-1]
    return grid


def _shift(grid: Grid, dx: int, dy: int) -> Grid | None:
    """Move pixels; None if an opaque pixel would leave the canvas."""
    height, width = len(grid), len(grid[0]) if grid else 0
    out = [[TRANSPARENT] * width for _ in range(height)]
    for y, row in enumerate(grid):
        for x, char in enumerate(row):
            if char == TRANSPARENT:
                continue
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                return None
            out[ny][nx] = char
    return tuple("".join(r) for r in out)


MAX_DERIVED_SCALE = 8


def _transform(grid: Grid, scale: tuple[float, float], rotate: float, about: tuple[float, float]) -> Grid | None:
    """Scale then rotate (degrees, clockwise on screen) about a point in pixel-edge coordinates, nearest neighbour:
    each output pixel takes the source pixel under its centre mapped back. None if an opaque pixel would leave the
    canvas. Trig and the mapped coordinates are rounded so results are the same on every machine."""
    import math

    height, width = len(grid), len(grid[0]) if grid else 0
    sx, sy = scale
    angle = math.radians(rotate)
    cos, sin = round(math.cos(angle), 12), round(math.sin(angle), 12)
    ax, ay = about

    def forward(x: float, y: float) -> tuple[float, float]:
        dx, dy = (x - ax) * sx, (y - ay) * sy
        return (ax + dx * cos - dy * sin, ay + dx * sin + dy * cos)

    # Map back every pixel the whole transformed canvas covers, so an opaque pixel landing outside is caught.
    corners = [forward(x, y) for x in (0, width) for y in (0, height)]
    left, top = min(0, math.floor(min(c[0] for c in corners))), min(0, math.floor(min(c[1] for c in corners)))
    right, bottom = max(width, math.ceil(max(c[0] for c in corners))), max(height, math.ceil(max(c[1] for c in corners)))
    import numpy as np  # local import, like the wide outlines

    ys, xs = np.mgrid[top:bottom, left:right]
    dx, dy = xs + 0.5 - ax, ys + 0.5 - ay
    ux, uy = dx * cos + dy * sin, -dx * sin + dy * cos  # rotate back
    src_x = np.floor(np.round(ax + ux / sx, 9)).astype(np.int64)
    src_y = np.floor(np.round(ay + uy / sy, 9)).astype(np.int64)
    inside = (src_x >= 0) & (src_x < width) & (src_y >= 0) & (src_y < height)
    source = np.array([list(row) for row in grid])
    chars = np.full(xs.shape, TRANSPARENT)
    chars[inside] = source[src_y[inside], src_x[inside]]
    canvas = (xs >= 0) & (xs < width) & (ys >= 0) & (ys < height)
    if (chars[~canvas] != TRANSPARENT).any():
        return None
    out = ["".join(row) for row in chars[-top : -top + height, -left : -left + width]]
    return tuple(out)


def opaque(grid: Grid, x: int, y: int) -> bool:
    return 0 <= y < len(grid) and 0 <= x < len(grid[y]) and grid[y][x] != TRANSPARENT


def _outline(grid: Grid, color: str) -> Grid:
    """Paint `color` on transparent pixels 4-adjacent to opaque ones."""
    height = len(grid)
    width = len(grid[0]) if grid else 0
    rows = [list(row) for row in grid]
    for y, row in enumerate(grid):
        for x, char in enumerate(row):
            if char == TRANSPARENT:
                continue
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < width and 0 <= ny < height and grid[ny][nx] == TRANSPARENT:
                    rows[ny][nx] = color
    return tuple("".join(r) for r in rows)


def _outline_ring(grid: Grid, color: str, width: int) -> Grid:
    """Paint `color` on transparent pixels within `width` pixels (centre to centre, Euclidean) of an opaque one:
    width 1 is the 4-adjacent outline, wider rings get round corners."""
    if width == 1:
        return _outline(grid, color)
    import numpy as np  # local import: only wide outlines need it

    height, row_width = len(grid), len(grid[0]) if grid else 0
    solid = np.array([[c != TRANSPARENT for c in row] for row in grid], dtype=bool)
    padded = np.pad(solid, width)
    near = np.zeros_like(solid)
    for dy in range(-width, width + 1):
        for dx in range(-width, width + 1):
            if dx * dx + dy * dy <= width * width:
                near |= padded[width + dy : width + dy + height, width + dx : width + dx + row_width]
    paint = near & ~solid
    return tuple("".join(color if paint[y, x] else c for x, c in enumerate(row)) for y, row in enumerate(grid))


def _drop_shadow(grid: Grid, dx: int, dy: int, color: str) -> Grid:
    """The opaque pixels' silhouette moved by (dx, dy) in `color`, under them (only on transparent pixels)."""
    height = len(grid)
    rows = [list(row) for row in grid]
    for y, row in enumerate(grid):
        for x, char in enumerate(row):
            nx, ny = x + dx, y + dy
            if char != TRANSPARENT and 0 <= ny < height and 0 <= nx < len(row) and grid[ny][nx] == TRANSPARENT:
                rows[ny][nx] = color
    return tuple("".join(r) for r in rows)


def _edge_pixel(grid: Grid, margin: int = 1) -> tuple[int, int] | None:
    """First opaque pixel closer than `margin` to the canvas edge (an outline that wide there would be clipped)."""
    height = len(grid)
    for y, row in enumerate(grid):
        for x, char in enumerate(row):
            if char != TRANSPARENT and min(x, y, len(row) - 1 - x, height - 1 - y) < margin:
                return (x, y)
    return None


def _shadow_clipped(grid: Grid, dx: int, dy: int) -> tuple[int, int] | None:
    """First opaque pixel whose shadow would land off the canvas."""
    height = len(grid)
    for y, row in enumerate(grid):
        for x, char in enumerate(row):
            if char != TRANSPARENT and not (0 <= x + dx < len(row) and 0 <= y + dy < height):
                return (x, y)
    return None


# --- field helpers ----------------------------------------------------------------------------


def _parse_size(raw: Any, field_name: str, line: int | None, error: ErrorFn) -> tuple[int, int] | None:
    if isinstance(raw, str):
        match = re.fullmatch(r"(\d+)x(\d+)", raw.strip())
        raw = [int(match.group(1)), int(match.group(2))] if match else None
    if (
        isinstance(raw, list)
        and len(raw) == 2
        and all(isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= MAX_SIZE for v in raw)
    ):
        return (raw[0], raw[1])
    error("E001", f"{field_name} must be [width, height] (or \"16x16\"), each 1-{MAX_SIZE}", line, field_name)
    return None


def _resolve_palette(
    data: dict[str, Any], path: Path | None, project: Project, error: ErrorFn, findings: list[Finding]
) -> Palette | None:
    raw = data.get("palette")
    line = _line(data, "palette")
    if raw is None:
        if project.config.default_palette is None:
            reason = "pagan.toml has no default_palette" if project.config_path else "no pagan.toml found, so no default_palette"
            error("E001", f"missing 'palette' ({reason})", _line(data), "palette")
            return None
        raw = project.config.default_palette
    if isinstance(raw, str):
        try:
            return project.load_palette(raw)
        except PaganError as exc:
            # Re-anchor "unknown palette" to this file; keep findings from inside a broken palette file.
            for f in exc.findings:
                if f.path == project.config_path:
                    error(f.rule, f.message, line, "palette")
                else:
                    findings.append(f)
            return None
    if isinstance(raw, dict):
        if project.config.palette_mode == "strict" and project.config_path is not None:
            error(
                "E009",
                "inline palettes aren't allowed in strict mode; use a palette file, "
                "or set palette_mode = \"open\" in pagan.toml",
                line,
                "palette",
            )
            return None
        palette, palette_findings = parse_palette(raw, path, inline=True)
        findings.extend(Finding(f.rule, f.message, f.path, f.line, f"palette.{f.where}" if f.where else "palette") for f in palette_findings)
        return palette
    error("E001", "palette must be a palette name or an inline palette mapping", line, "palette")
    return None


def _parse_metadata(data: dict[str, Any], error: ErrorFn) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    description = data.get("description")
    if description is not None and not isinstance(description, str):
        error("E001", "description must be text", _line(data, "description"), "description")
    meta["description"] = description.strip() if isinstance(description, str) else None

    tags = data.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        error("E001", "tags must be a list of words", _line(data, "tags"), "tags")
        tags = []
    meta["tags"] = tuple(tags)

    status = data.get("status", "draft")
    if status not in STATUSES:
        error("E001", f"status must be one of {', '.join(STATUSES)}", _line(data, "status"), "status")
        status = "draft"
    meta["status"] = status

    style_version = data.get("style_version", 1)
    if isinstance(style_version, bool) or not isinstance(style_version, int) or style_version < 1:
        error("E001", "style_version must be a positive integer", _line(data, "style_version"), "style_version")
        style_version = 1
    meta["style_version"] = style_version

    base_variant = data.get("base_variant")
    if base_variant is not None and not (isinstance(base_variant, str) and NAME_RE.match(base_variant)):
        error("E006", "base_variant must be a variant name (lowercase letters, digits, '_' or '-')", _line(data, "base_variant"), "base_variant")
        base_variant = None
    meta["base_variant"] = base_variant

    supersample = data.get("supersample")
    if supersample is not None and (
        isinstance(supersample, bool) or not isinstance(supersample, int) or not 1 <= supersample <= MAX_SUPERSAMPLE
    ):
        error("E001", f"supersample must be a whole number 1-{MAX_SUPERSAMPLE}", _line(data, "supersample"), "supersample")
        supersample = None
    meta["supersample"] = supersample
    return meta


def check_base_variant(base_variant: str | None, variants: dict[str, Variant], line: int | None, error: ErrorFn) -> None:
    if base_variant is not None and base_variant in variants:
        error("E006", f"base_variant {base_variant!r} is also a variant's name; rename one", line, "base_variant")


@dataclass(frozen=True)
class LintSettings:
    """An asset's `lint:` section."""

    disable: frozenset[str] = frozenset()
    disable_for: dict[str, frozenset[str]] = field(default_factory=dict)
    max_ramps: int | None = None  # W003 budget for this asset (None = the project's)


def _parse_lint(raw: Any, line: int | None, targets: dict[str, tuple[str, ...]], error: ErrorFn) -> LintSettings:
    """`lint: { disable: [W007], for: { name: [W004] }, max_ramps: 9 }`: lint settings for this asset only.

    `targets` maps each name allowed under `for` to the frame/animation names it covers.
    """
    if raw is None:
        return LintSettings()
    usage = "lint must be { disable: [W007, ...], for: { <frame, tile or animation>: [W004, ...] }, max_ramps: N }"
    if not isinstance(raw, dict):
        error("E001", usage, line, "lint")
        return LintSettings()

    def rules(value: Any, where: str) -> frozenset[str] | None:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or not all(isinstance(r, str) and WARNING_ID_RE.match(r) for r in value):
            error("E001", "list warning ids, e.g. [W007, W005] (errors can't be disabled)", _line(raw, where.split(".")[1]) or line, where)
            return None
        return frozenset(value)

    disable: frozenset[str] = frozenset()
    per_name: dict[str, frozenset[str]] = {}
    for key in raw:
        if key not in ("disable", "for", "max_ramps"):
            error("E001", f"unknown lint field {key!r}; allowed: disable, for, max_ramps", _line(raw, key) or line, f"lint.{key}")
    max_ramps = raw.get("max_ramps")
    if max_ramps is not None and (isinstance(max_ramps, bool) or not isinstance(max_ramps, int) or max_ramps < 1):
        error("E001", "lint.max_ramps must be a whole number of ramps, 1 or more (W003's limit for this asset)", _line(raw, "max_ramps") or line, "lint.max_ramps")
        max_ramps = None
    if "disable" in raw:
        disable = rules(raw["disable"], "lint.disable") or frozenset()
    if "for" in raw:
        section = raw["for"]
        if not isinstance(section, dict):
            error("E001", usage, _line(raw, "for") or line, "lint.for")
            return LintSettings(disable, per_name, max_ramps)
        for name, value in section.items():
            where = f"lint.for.{name}"
            if not isinstance(name, str) or name not in targets:
                error("E001", f"lint.for: {name!r} isn't a frame, tile or animation of this asset", _line(section, name) or line, where)
                continue
            found = rules(value, where)
            if found is None:
                continue
            for target in targets[name]:
                per_name[target] = per_name.get(target, frozenset()) | found
    return LintSettings(disable, per_name, max_ramps)


def _parse_frames(
    section: Any,
    section_name: str,
    *,
    width: int,
    height: int,
    mirror: bool,
    palette: Palette | None,
    line: int | None,
    error: ErrorFn,
    pivot: tuple[int, int] | None = None,
) -> tuple[dict[str, Grid], dict[str, int | None], dict[str, str]]:
    """Parse grid frames and derived frames. Returns (frames in source order, lines, derived_from).

    `pivot` is what `about: pivot` means for derived frames (sprites); without one it's the centre."""
    frames: dict[str, Grid] = {}
    lines: dict[str, int | None] = {}
    derived_specs: dict[str, tuple[dict[str, Any], int | None]] = {}
    order: list[str] = []

    if not isinstance(section, dict) or not section:
        error("E001", f"'{section_name}' must be a non-empty mapping of name -> pixel rows", line, section_name)
        return frames, lines, {}

    keys = set(palette.colors) if palette is not None else set()
    authored_width = -(-width // 2) if mirror else width
    mirror_note = f" (mirror: horizontal, so author only the left {authored_width} columns)" if mirror else ""

    for name, raw in section.items():
        frame_line = _line(section, name)
        where = f"{section_name}.{name}"
        if not isinstance(name, str):
            error(
                "E001",
                f"YAML read this frame name as a {type(name).__name__} ({name!r}); quote it, e.g. \"{name}\":",
                frame_line,
                where,
            )
            continue
        if not FRAME_NAME_RE.match(name):
            error("E001", f"frame name {name!r} must be letters, digits, '_' or '-'", frame_line, where)
            continue
        order.append(name)
        lines[name] = frame_line
        if isinstance(raw, dict):
            derived_specs[name] = (raw, frame_line)
            continue
        if palette is None:
            continue  # can't check pixels without a palette; that error is already reported
        grid = _parse_grid(
            raw,
            width=authored_width,
            height=height,
            keys=keys,
            where=where,
            line=frame_line,
            mirror_note=mirror_note,
            error=error,
        )
        if grid is not None:
            frames[name] = _mirror(grid, width) if mirror else grid

    derived_from: dict[str, str] = {}
    resolving: set[str] = set()
    failed: set[str] = set()

    def resolve(name: str) -> Grid | None:
        if name in frames:
            return frames[name]
        if name not in derived_specs or name in failed:
            return None
        spec, spec_line = derived_specs[name]
        where = f"{section_name}.{name}"
        if name in resolving:
            error("E010", "derived frames form a cycle", spec_line, where)
            failed.add(name)
            return None
        resolving.add(name)
        result: Grid | None = None
        try:
            result = _derive(name, spec, spec_line, where)
            return result
        finally:
            resolving.discard(name)
            if result is None:
                failed.add(name)

    def _derive(name: str, spec: dict[str, Any], spec_line: int | None, where: str) -> Grid | None:
        for key in spec:
            if key not in ("from", "flip", "scale", "rotate", "about", "shift"):
                error("E001", f"unknown derived-frame field {key!r}; allowed: from, flip, scale, rotate, about, shift", spec_line, where)
        source = spec.get("from")
        if not isinstance(source, str):
            error("E010", "a derived frame needs `from: <frame name>`", spec_line, where)
            return None
        if source not in derived_specs and source not in lines:
            error("E010", f"derived from unknown frame {source!r}", spec_line, where)
            return None
        grid = resolve(source)
        if grid is None:
            return None  # the source frame's own error was reported
        flip = spec.get("flip", "none")
        if flip not in ("none", "horizontal", "vertical", "both"):
            error("E010", "flip must be none, horizontal, vertical or both", spec_line, where)
            return None
        grid = _flip(grid, flip)
        if "scale" in spec or "rotate" in spec:
            transformed = _derive_transform(spec, grid, spec_line, where)
            if transformed is None:
                return None
            grid = transformed
        elif "about" in spec:
            error("E010", "about is the point to scale/rotate around; add scale or rotate", spec_line, where)
            return None
        shift = spec.get("shift", [0, 0])
        if not (
            isinstance(shift, list)
            and len(shift) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) for v in shift)
        ):
            error("E010", "shift must be [dx, dy] (whole pixels; +x right, +y down)", spec_line, where)
            return None
        shifted = _shift(grid, shift[0], shift[1])
        if shifted is None:
            error("E010", f"shift {shift} pushes opaque pixels off the canvas", spec_line, where)
            return None
        frames[name] = shifted
        derived_from[name] = source
        return shifted

    def _derive_transform(spec: dict[str, Any], grid: Grid, spec_line: int | None, where: str) -> Grid | None:
        raw_scale = spec.get("scale", 1)
        factors = raw_scale if isinstance(raw_scale, list) else [raw_scale, raw_scale]
        if not (
            len(factors) == 2
            and all(isinstance(v, int | float) and not isinstance(v, bool) and 0 < v <= MAX_DERIVED_SCALE for v in factors)
        ):
            error("E010", f"scale must be a number or [x, y], each above 0 and at most {MAX_DERIVED_SCALE} (use flip to mirror)", spec_line, where)
            return None
        rotate = spec.get("rotate", 0)
        if isinstance(rotate, bool) or not isinstance(rotate, int | float) or not -360 <= rotate <= 360:
            error("E010", "rotate must be degrees, -360 to 360 (positive = clockwise)", spec_line, where)
            return None
        raw_about = spec.get("about", "pivot")
        if raw_about == "pivot":
            about = (float(pivot[0]), float(pivot[1])) if pivot is not None else (width / 2, height / 2)
        elif raw_about in ("center", "centre"):
            about = (width / 2, height / 2)
        elif (
            isinstance(raw_about, list)
            and len(raw_about) == 2
            and all(isinstance(v, int | float) and not isinstance(v, bool) for v in raw_about)
        ):
            about = (float(raw_about[0]), float(raw_about[1]))
        else:
            error("E010", "about must be pivot, center or [x, y] (pixel-edge coordinates, like pivot)", spec_line, where)
            return None
        result = _transform(grid, (float(factors[0]), float(factors[1])), float(rotate), about)
        if result is None:
            error("E010", f"scale/rotate about {list(about)} pushes opaque pixels off the canvas; grow the canvas or move `about`", spec_line, where)
        return result

    for name in derived_specs:
        resolve(name)

    ordered = {name: frames[name] for name in order if name in frames}
    return ordered, lines, derived_from


def _parse_variants(
    raw: Any, palette: Palette, project: Project, line: int | None, used_keys: set[str], error: ErrorFn
) -> dict[str, Variant]:
    variants: dict[str, Variant] = {}
    if raw is None:
        return variants
    if not isinstance(raw, dict):
        error("E006", "variants must be a mapping of variant name -> swap", line, "variants")
        return variants
    for name, spec in raw.items():
        vline = _line(raw, name)
        where = f"variants.{name}"
        if not isinstance(name, str) or not NAME_RE.match(name):
            error("E006", "variant name must be lowercase letters, digits, '_' or '-'", vline, where)
            continue
        if not isinstance(spec, dict) or not spec:
            error("E006", "a variant needs ramp_swap, key_swap and/or palette", vline, where)
            continue
        ok = True
        for key in spec:
            if key not in ("ramp_swap", "key_swap", "palette"):
                error("E006", f"unknown variant field {key!r}; allowed: ramp_swap, key_swap, palette", vline, where)
                ok = False

        target = palette
        if "palette" in spec:
            if not isinstance(spec["palette"], str):
                error("E006", "variant palette must be a palette name", vline, where)
                continue
            try:
                target = project.load_palette(spec["palette"])
            except PaganError as exc:
                error("E006", f"variant palette {spec['palette']!r} can't be used: {exc.findings[0].message}", vline, where)
                continue

        mapping: dict[str, str] = {}
        ramp_swap = spec.get("ramp_swap", {})
        if not isinstance(ramp_swap, dict):
            error("E006", "ramp_swap must map ramp -> ramp, e.g. { green: fire }", vline, where)
            ok = False
            ramp_swap = {}
        for src, dst in ramp_swap.items():
            if not isinstance(src, str) or not isinstance(dst, str):
                error("E006", f"ramp_swap entries must be ramp names, got {src!r}: {dst!r}", vline, where)
                ok = False
                continue
            if src not in palette.ramps:
                error("E006", f"ramp_swap: unknown ramp {src!r}", vline, where)
                ok = False
                continue
            if dst not in target.ramps:
                error("E006", f"ramp_swap: unknown target ramp {dst!r}", vline, where)
                ok = False
                continue
            src_keys, dst_keys = palette.ramps[src], target.ramps[dst]
            if len(src_keys) != len(dst_keys):
                error(
                    "E006",
                    f"ramp_swap: {src!r} has {len(src_keys)} colors but {dst!r} has {len(dst_keys)}; "
                    "ramps must be the same length",
                    vline,
                    where,
                )
                ok = False
                continue
            mapping.update(zip(src_keys, dst_keys, strict=True))

        key_swap = spec.get("key_swap", {})
        if not isinstance(key_swap, dict):
            error("E006", 'key_swap must map key -> key, e.g. { "5": "a" }', vline, where)
            ok = False
            key_swap = {}
        for src, dst in key_swap.items():
            src_s, dst_s = str(src), str(dst)
            if src_s not in palette.colors:
                error("E006", f"key_swap: unknown source key {src_s!r}", vline, where)
                ok = False
            elif dst_s not in target.colors:
                error("E006", f"key_swap: unknown target key {dst_s!r}", vline, where)
                ok = False
            else:
                mapping[src_s] = dst_s

        if target is not palette:
            missing = sorted(k for k in used_keys if mapping.get(k, k) not in target.colors)
            if missing:
                error(
                    "E006",
                    f"palette {target.name!r} has no color for key(s) {', '.join(missing)}; add key_swap entries",
                    vline,
                    where,
                )
                ok = False
        if ok:
            variants[name] = Variant(name=name, keys=mapping, palette=target)
    return variants


def with_palette_variants(
    raw: Any, palette: Palette, tags: tuple[str, ...], line: int | None, error: ErrorFn
) -> tuple[Any, bool]:
    """The asset's `variants:` with its palette's variants added (the asset's own of the same name win;
    `name: false` turns an inherited one off). Returns (variants, whether any palette variant applies)."""
    inherited = {name: v.spec() for name, v in palette.variants.items() if v.applies_to(tags)}
    if raw is None:
        return (inherited or None), bool(inherited)
    if not isinstance(raw, dict):
        return raw, False  # reported by _parse_variants
    merged: dict[Any, Any] = {**inherited}
    for name, spec in raw.items():
        if spec is False:
            if name not in palette.variants:
                error("E006", f"{name}: false turns off a palette variant, but palette {palette.name!r} has no variant {name!r}", _line(raw, name) or line, f"variants.{name}")
            merged.pop(name, None)
        else:
            merged[name] = spec
    return (merged or None), any(name in merged for name in inherited)


MAX_VARIANT_COMBINATIONS = 256


def _parse_variant_axes(
    raw: Any, palette: Palette, project: Project, line: int | None, used_keys: set[str], plain: dict[str, Variant], error: ErrorFn
) -> tuple[dict[str, dict[str, Variant]], dict[str, Variant]]:
    """`variant_axes: { team: { red: {ramp_swap: ...}, blue: ... }, trim: { gold: ..., steel: ... } }`.

    Independent recolours that combine: axes must change disjoint keys, so any choice per axis is just
    every chosen swap applied together. Returns (axes, combinations named "red+gold" in axis order).
    """
    import itertools

    if raw is None:
        return {}, {}
    if not isinstance(raw, dict) or not raw:
        error("E006", "variant_axes must map an axis name to { option: recolour, ... }", line, "variant_axes")
        return {}, {}
    axes: dict[str, dict[str, Variant]] = {}
    changed_by: dict[str, str] = {}  # key -> the axis that changes it
    ok = True
    for axis, options in raw.items():
        aline = _line(raw, axis) or line
        where = f"variant_axes.{axis}"
        if not isinstance(axis, str) or not NAME_RE.match(axis):
            error("E006", "axis names must be lowercase letters, digits, '_' or '-'", aline, where)
            ok = False
            continue
        if not isinstance(options, dict) or not options:
            error("E006", "an axis maps option names to recolours, e.g. { red: { ramp_swap: { team: red } } }", aline, where)
            ok = False
            continue
        if any(isinstance(spec, dict) and "palette" in spec for spec in options.values()):
            error("E006", "axis options recolour with ramp_swap/key_swap only (a whole palette can't combine with other axes)", aline, where)
            ok = False
            continue
        def axis_error(rule: str, message: str, ln: int | None, w: str | None, where: str = where) -> None:
            error(rule, message, ln, f"{where}.{(w or '').partition('.')[2]}".rstrip("."))

        recolours = {k: v for k, v in options.items() if v not in ({}, None)}  # {} = this axis left as is
        parsed = _parse_variants(recolours, palette, project, aline, used_keys, axis_error) if recolours else {}
        if len(parsed) != len(recolours):
            ok = False
            continue
        variants = {
            str(k): parsed[k] if k in parsed else Variant(name=str(k), keys={}, palette=palette) for k in options
        }
        bad = [k for k in variants if not NAME_RE.match(k)]
        if bad:
            error("E006", f"option names must be lowercase letters, digits, '_' or '-': {', '.join(bad)}", aline, where)
            ok = False
            continue
        for variant in variants.values():
            for key, target in variant.keys.items():
                if target != key and changed_by.setdefault(key, axis) != axis:
                    error("E006", f"axes {changed_by[key]!r} and {axis!r} both recolour key {key!r}; axes must change different keys so they combine", aline, where)
                    ok = False
        axes[axis] = variants
    if not ok:
        return {}, {}
    count = 1
    for options in axes.values():
        count *= len(options)
    if count > MAX_VARIANT_COMBINATIONS:
        error("E006", f"variant_axes make {count} combinations (limit {MAX_VARIANT_COMBINATIONS})", line, "variant_axes")
        return {}, {}
    combos: dict[str, Variant] = {}
    for choice in itertools.product(*(options.values() for options in axes.values())):
        name = "+".join(v.name for v in choice)
        keys: dict[str, str] = {}
        for v in choice:
            keys.update({k: t for k, t in v.keys.items() if t != k})
        if name in plain:
            error("E006", f"variant {name!r} is defined in variants and made by variant_axes; rename one", line, "variant_axes")
            return {}, {}
        combos[name] = Variant(name=name, keys=keys, palette=palette)
    return axes, combos


def _parse_animations(raw: Any, frames_known: set[str], line: int | None, error: ErrorFn) -> dict[str, Animation]:
    animations: dict[str, Animation] = {}
    if raw is None:
        return animations
    if not isinstance(raw, dict):
        error("E001", "animations must be a mapping of name -> { frames: [...], fps: N, loop: true }", line, "animations")
        return animations
    for name, spec in raw.items():
        aline = _line(raw, name)
        where = f"animations.{name}"
        if not isinstance(name, str) or not FRAME_NAME_RE.match(name):
            error("E001", f"animation name {name!r} must be letters, digits, '_' or '-'", aline, where)
            continue
        if isinstance(spec, list):
            spec = {"frames": spec}
        if not isinstance(spec, dict):
            error("E001", "an animation must be { frames: [...], fps: N, loop: true }", aline, where)
            continue
        for key in spec:
            if key not in ("frames", "fps", "loop"):
                error("E001", f"unknown animation field {key!r}; allowed: frames, fps, loop", aline, where)
        frame_list = spec.get("frames")
        if not isinstance(frame_list, list) or not frame_list or not all(isinstance(f, str) for f in frame_list):
            error("E001", "animation frames must be a non-empty list of frame names", aline, where)
            continue
        missing = [f for f in frame_list if f not in frames_known]
        for frame in dict.fromkeys(missing):
            error("E004", f"animation uses missing frame {frame!r}", aline, where)
        fps = spec.get("fps", DEFAULT_FPS)
        if isinstance(fps, bool) or not isinstance(fps, int | float) or not 0 < fps <= 120:
            error("E001", "fps must be a number between 0 and 120", aline, where)
            continue
        loop = spec.get("loop", True)
        if not isinstance(loop, bool):
            error("E001", "loop must be true or false", aline, where)
            continue
        if not missing:
            animations[name] = Animation(name=name, frames=tuple(frame_list), fps=float(fps), loop=loop)
    return animations


def _parse_tile_animations(
    raw: Any, tiles: dict[str, int | None], line: int | None, error: ErrorFn
) -> dict[str, Animation]:
    """Tileset `animations: { water: { frames: [water_0, water_1, ...], fps: 4 } }`: animated tiles.

    The animation's name becomes the tile's name; its frames are laid out side by side in the atlas
    (engines such as Godot animate a tile by stepping through neighbouring cells), from column 0 of a
    fresh row with `new_row: true`. Tile animations always loop. Each tile can be a frame of one animation only.
    """
    animations: dict[str, Animation] = {}
    if raw is None:
        return animations
    if not isinstance(raw, dict):
        error("E001", "animations must map a tile name to { frames: [tile, ...], fps: N }", line, "animations")
        return animations
    claimed: dict[str, str] = {}
    for name, spec in raw.items():
        aline = _line(raw, name) or line
        where = f"animations.{name}"
        if not isinstance(name, str) or not FRAME_NAME_RE.match(name):
            error("E001", f"animation name {name!r} must be letters, digits, '_' or '-'", aline, where)
            continue
        if isinstance(spec, list):
            spec = {"frames": spec}
        if not isinstance(spec, dict):
            error("E001", "a tile animation is { frames: [tile, ...], fps: N }", aline, where)
            continue
        extra = [k for k in spec if k not in ("frames", "fps", "new_row")]
        if extra:
            hint = " (tile animations always loop)" if "loop" in extra else ""
            error("E001", f"unknown tile animation field(s) {', '.join(map(str, extra))}; allowed: frames, fps, new_row{hint}", aline, where)
            continue
        new_row = spec.get("new_row", False)
        if not isinstance(new_row, bool):
            error("E001", "new_row must be true (start this animation at column 0 of a new atlas row) or false", aline, where)
            continue
        frame_list = spec.get("frames")
        if not isinstance(frame_list, list) or len(frame_list) < 2 or not all(isinstance(f, str) for f in frame_list):
            error("E001", "a tile animation needs frames: a list of at least 2 tile names", aline, where)
            continue
        missing = [f for f in dict.fromkeys(frame_list) if f not in tiles]
        for frame in missing:
            error("E004", f"animation uses missing tile {frame!r}", aline, where)
        repeated = sorted({f for f in frame_list if frame_list.count(f) > 1})
        if repeated:
            error("E001", f"tile animation repeats {', '.join(repeated)}; each frame is its own atlas cell, so list it once", aline, where)
        taken = [f for f in frame_list if f in claimed]
        for frame in dict.fromkeys(taken):
            error("E001", f"tile {frame!r} is already a frame of animation {claimed[frame]!r}; a tile can animate in one animation only", aline, where)
        if name in tiles and name != frame_list[0]:
            error("E001", f"animation name {name!r} is also a tile name; name it after its first frame or pick another name", aline, where)
            continue
        fps = spec.get("fps", DEFAULT_FPS)
        if isinstance(fps, bool) or not isinstance(fps, int | float) or not 0 < fps <= 120:
            error("E001", "fps must be a number between 0 and 120", aline, where)
            continue
        if missing or repeated or taken:
            continue
        for frame in frame_list:
            claimed[frame] = name
        animations[name] = Animation(name=name, frames=tuple(frame_list), fps=float(fps), loop=True, new_row=new_row)
    return animations


def _expand_mirrored_animations(
    raw: Any,
    frames: dict[str, Grid],
    lines: dict[str, int | None],
    derived_from: dict[str, str],
    line: int | None,
    error: ErrorFn,
) -> Any:
    """Turn `walk_right: { from: walk_left, flip: horizontal }` into generated frames + a plain animation.

    Generated frames are named `<animation>_<i>`; fps and loop default to the source animation's.
    """
    if not isinstance(raw, dict):
        return raw
    expanded = dict(raw)
    for name, spec in raw.items():
        if not (isinstance(spec, dict) and "from" in spec):
            continue
        where = f"animations.{name}"
        aline = _line(raw, name) or line
        extra = [k for k in spec if k not in ("from", "flip", "shift", "fps", "loop")]
        if extra:
            error("E001", f"unknown field(s) {', '.join(map(str, extra))}; a mirrored animation takes from, flip, shift, fps, loop", aline, where)
            expanded.pop(name)
            continue
        source = raw.get(spec["from"]) if isinstance(spec["from"], str) else None
        if isinstance(source, list):
            source = {"frames": source}
        if not isinstance(source, dict) or "from" in source or not isinstance(source.get("frames"), list):
            error("E004", f"{spec['from']!r} isn't an animation with frames to copy (mirrored animations can't chain)", aline, where)
            expanded.pop(name)
            continue
        flip, shift = spec.get("flip", "none"), spec.get("shift", [0, 0])
        if flip not in ("none", "horizontal", "vertical", "both") or not (
            isinstance(shift, list) and len(shift) == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in shift)
        ):
            error("E010", "flip must be none/horizontal/vertical/both and shift [dx, dy]", aline, where)
            expanded.pop(name)
            continue
        new_frames: list[str] = []
        for index, frame in enumerate(source["frames"]):
            if not isinstance(frame, str) or frame not in frames:
                new_frames = []
                break  # the source animation's own missing frame is reported for it
            generated = f"{name}_{index}"
            if generated in frames or generated in lines:
                error("E001", f"generated frame {generated!r} clashes with an existing frame; rename one", aline, where)
                new_frames = []
                break
            grid = _shift(_flip(frames[frame], flip), shift[0], shift[1])
            if grid is None:
                error("E010", f"shift {shift} pushes opaque pixels of {frame!r} off the canvas", aline, where)
                new_frames = []
                break
            frames[generated] = grid
            lines[generated] = aline
            derived_from[generated] = frame
            new_frames.append(generated)
        if not new_frames:
            expanded.pop(name)
            continue
        expanded[name] = {
            "frames": new_frames,
            "fps": spec.get("fps", source.get("fps", DEFAULT_FPS)),
            "loop": spec.get("loop", source.get("loop", True)),
        }
    return expanded


def _darkest(palette: Palette) -> str:
    """The default outline colour: the darkest opaque colour (a translucent shadow colour would make a see-through outline)."""

    def luminance(key: str) -> float:
        r, g, b = palette.colors[key].rgb
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    opaque_keys = [k for k, c in palette.colors.items() if c.alpha == 255]
    return min(opaque_keys or palette.colors, key=luminance)


# --- entry points -----------------------------------------------------------------------------


def parse_asset(data: Any, path: Path | None, project: Project, kind: Kind) -> tuple[Asset | None, list[Finding]]:
    findings: list[Finding] = []

    def error(rule: str, message: str, line: int | None, where: str | None = None) -> None:
        findings.append(Finding(rule, message, path, line, where))

    if not isinstance(data, dict):
        error("E001", f"a {kind} file must be a mapping", _line(data))
        return None, findings

    allowed = _SPRITE_FIELDS if kind == "sprite" else _TILESET_FIELDS
    for key in data:
        if key not in allowed:
            error("E001", f"unknown field {key!r}; allowed: {', '.join(allowed)}", _line(data, key), str(key))

    name = data.get("name")
    expected = asset_name_from_path(path) if path is not None else None
    if not isinstance(name, str) or not NAME_RE.match(name):
        error("E001", "missing or invalid 'name' (lowercase letters, digits, '_' or '-')", _line(data, "name"), "name")
        name = expected or "unnamed"
    elif expected is not None and name != expected:
        error("E001", f"name {name!r} doesn't match the file name; expected {expected!r}", _line(data, "name"), "name")

    palette = _resolve_palette(data, path, project, error, findings)
    meta = _parse_metadata(data, error)

    size_field, frames_field = ("size", "frames") if kind == "sprite" else ("tile_size", "tiles")
    if size_field not in data:
        error("E001", f"missing required field {size_field!r}", _line(data), size_field)
        return None, findings
    size = _parse_size(data[size_field], size_field, _line(data, size_field), error)
    if size is None:
        return None, findings
    width, height = size

    mirror = False
    outline = False
    outline_color: str | None = None
    outlines: tuple[tuple[int, str], ...] = ()
    shadow: tuple[int, int, str] | None = None
    pivot = (width // 2, height)
    columns = 8
    if kind == "sprite":
        mirror_raw = data.get("mirror", "none")
        if mirror_raw not in ("none", "horizontal"):
            error("E001", "mirror must be none or horizontal", _line(data, "mirror"), "mirror")
        mirror = mirror_raw == "horizontal"

        if palette is not None:
            raw_color = data.get("outline_color")
            if raw_color is None:
                outline_color = _darkest(palette)
            else:
                raw_color = str(raw_color)
                if raw_color not in palette.colors:
                    error("E005", f"outline_color {raw_color!r} isn't a palette key", _line(data, "outline_color"), "outline_color")
                else:
                    outline_color = raw_color
        outlines = _parse_outlines(data.get("outline", "none"), palette, outline_color, _line(data, "outline"), error)
        outline = bool(outlines)
        if outlines:
            outline_color = outlines[0][1]
        if not outline and project.config.lint.require_outline:
            error("E011", "pagan.toml requires outlines: add `outline: auto`", _line(data), "outline")
        if "shadow" in data:
            shadow = _parse_shadow(data["shadow"], palette, _line(data, "shadow"), error)

        if "pivot" in data:
            raw_pivot = data["pivot"]
            pline = _line(data, "pivot")
            if not (
                isinstance(raw_pivot, list)
                and len(raw_pivot) == 2
                and all(isinstance(v, int) and not isinstance(v, bool) for v in raw_pivot)
            ):
                error("E008", "pivot must be [x, y] in pixels", pline, "pivot")
            elif not (0 <= raw_pivot[0] <= width and 0 <= raw_pivot[1] <= height):
                error("E008", f"pivot {raw_pivot} is outside the {width}x{height} canvas", pline, "pivot")
            else:
                pivot = (raw_pivot[0], raw_pivot[1])
    else:
        raw_columns = data.get("columns", 8)
        if isinstance(raw_columns, bool) or not isinstance(raw_columns, int) or raw_columns < 1:
            error("E001", "columns must be a positive integer", _line(data, "columns"), "columns")
        else:
            columns = raw_columns

    if frames_field not in data:
        error("E001", f"missing required field {frames_field!r}", _line(data), frames_field)
        return None, findings
    base_frames, frame_lines, derived_from = _parse_frames(
        data[frames_field],
        frames_field,
        width=width,
        height=height,
        mirror=mirror,
        palette=palette,
        line=_line(data, frames_field),
        error=error,
        pivot=pivot if kind == "sprite" else None,
    )

    animations: dict[str, Animation] = {}
    if kind == "sprite":
        raw_animations = _expand_mirrored_animations(
            data.get("animations"), base_frames, frame_lines, derived_from, _line(data, "animations"), error
        )
        animations = _parse_animations(raw_animations, set(frame_lines), _line(data, "animations"), error)
    else:
        animations = _parse_tile_animations(data.get("animations"), frame_lines, _line(data, "animations"), error)
    lint_targets: dict[str, tuple[str, ...]] = {n: (n,) for n in [*frame_lines, *animations]}
    lint = _parse_lint(data.get("lint"), _line(data, "lint"), lint_targets, error)

    frames = dict(base_frames)
    if outlines or shadow is not None:
        clipped: set[str] = set()
        authored_width = -(-width // 2) if mirror else width
        border = sum(w for w, _ in outlines)

        def clip_error(frame_name: str, pixel: tuple[int, int], message: str) -> None:
            clipped.add(frame_name)
            # Report each problem once: not again for frames derived from an already-reported one.
            if derived_from.get(frame_name) in clipped:
                return
            x, y = pixel
            if mirror and x >= authored_width:  # mirrored half: point at the column the author wrote
                x = width - 1 - x
            error("E007", message, frame_lines.get(frame_name), f"{frames_field}.{frame_name} row {y + 1} col {x + 1}")

        for frame_name, grid in base_frames.items():
            edge = _edge_pixel(grid, border) if outlines else None
            if edge is not None:
                if border == 1:
                    message = "outline: auto would be clipped: an opaque pixel touches the canvas edge. Leave a 1px transparent border (or grow the canvas)"
                else:
                    message = f"the outline ({border}px in all) would be clipped: an opaque pixel is closer than {border}px to the canvas edge. Leave a {border}px transparent border (or grow the canvas)"
                clip_error(frame_name, edge, message)
            for ring_width, ring_color in outlines:
                grid = _outline_ring(grid, ring_color, ring_width)
            if shadow is not None and edge is None:
                off = _shadow_clipped(grid, shadow[0], shadow[1])
                if off is not None:
                    clip_error(frame_name, off, f"shadow offset {[shadow[0], shadow[1]]} would push the shadow off the canvas. Leave room on that side (or grow the canvas)")
                grid = _drop_shadow(grid, *shadow)
            frames[frame_name] = grid

    variants: dict[str, Variant] = {}
    variant_axes: dict[str, dict[str, Variant]] = {}
    if palette is not None:
        used = {c for grid in frames.values() for row in grid for c in row if c != TRANSPARENT}
        translucent = sorted(k for k in used if palette.colors[k].alpha < 255)
        if translucent and project.config.lint.require_opaque:
            error("E015", f"pagan.toml requires opaque colours (require_opaque), but this {kind} uses translucent key(s) {', '.join(translucent)}", _line(data, "palette") or _line(data), "palette")
        raw_variants, inherited = with_palette_variants(data.get("variants"), palette, meta["tags"], _line(data, "variants"), error)
        if inherited and meta["base_variant"] is None:
            meta["base_variant"] = palette.base_variant
        variants = _parse_variants(raw_variants, palette, project, _line(data, "variants"), used, error)
        variant_axes, combos = _parse_variant_axes(data.get("variant_axes"), palette, project, _line(data, "variant_axes"), used, variants, error)
        variants.update(combos)
        check_base_variant(meta["base_variant"], variants, _line(data, "base_variant"), error)

    nine_slice: dict[str, Margins] = {}
    font: Font | None = None
    textures: Textures | None = None
    if kind == "tileset" and data.get("export_textures") not in (None, False):
        textures = _parse_textures(data["export_textures"], frames, animations, _line(data, "export_textures"), error)
    if kind == "sprite":
        nine_slice = _parse_nine_slice(data.get("nine_slice"), list(frames), size, _line(data, "nine_slice"), error)
        if "font" in data:
            font = _parse_font(data["font"], frames, size, _line(data, "font"), error)

    if has_errors(findings) or palette is None:
        return None, findings
    return (
        Asset(
            kind=kind,
            name=name,
            path=path,
            palette=palette,
            size=size,
            frames=frames,
            base_frames=base_frames,
            frame_lines=frame_lines,
            derived_from=derived_from,
            animations=animations,
            variants=variants,
            pivot=pivot,
            columns=columns,
            mirror=mirror,
            outline=outline,
            outline_color=outline_color,
            outlines=outlines,
            shadow=shadow,
            lint_disable=lint.disable,
            lint_disable_for=lint.disable_for,
            lint_max_ramps=lint.max_ramps,
            variant_axes=variant_axes,
            nine_slice=nine_slice,
            font=font,
            textures=textures,
            **meta,
        ),
        findings,
    )


def _parse_outlines(
    raw: Any, palette: Palette | None, default_color: str | None, line: int | None, error: ErrorFn
) -> tuple[tuple[int, str], ...]:
    """`outline: none | auto | { width: 3, color: "0" } | [ { width: 2, color: "0" }, { width: 1, color: "7" } ]`.

    A list stacks rings outwards (the first hugs the sprite). `auto` = `{ width: 1 }`; a ring without `color`
    uses `outline_color`.
    """
    usage = 'outline must be none, auto, { width: N, color: "<key>" } or a list of those (innermost first)'
    if raw == "none":
        return ()
    if raw == "auto":
        raw = [{}]
    elif isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        error("E001", usage, line, "outline")
        return ()
    rings: list[tuple[int, str]] = []
    for i, ring in enumerate(raw):
        where = "outline" if len(raw) == 1 else f"outline.{i}"
        if not isinstance(ring, dict) or any(k not in ("width", "color") for k in ring):
            error("E001", usage, line, where)
            return ()
        ring_width = ring.get("width", 1)
        if isinstance(ring_width, bool) or not isinstance(ring_width, int) or not 1 <= ring_width <= MAX_OUTLINE_WIDTH:
            error("E001", f"outline width must be a whole number of pixels, 1-{MAX_OUTLINE_WIDTH}", line, f"{where}.width")
            return ()
        color = str(ring["color"]) if "color" in ring else default_color
        if palette is not None and (color is None or color not in palette.colors):
            error("E005", f"outline color {color!r} isn't a palette key", line, f"{where}.color")
            return ()
        if color is not None:
            rings.append((ring_width, color))
    return tuple(rings)


def _parse_shadow(raw: Any, palette: Palette | None, line: int | None, error: ErrorFn) -> tuple[int, int, str] | None:
    """`shadow: { offset: [3, 4], color: "s" }`: a drop shadow of the (outlined) sprite, `offset` pixels away."""
    usage = 'shadow must be { offset: [dx, dy], color: "<key>" } (whole pixels; +x right, +y down)'
    if not isinstance(raw, dict) or set(raw) != {"offset", "color"}:
        error("E001", usage, line, "shadow")
        return None
    offset = raw["offset"]
    if not (isinstance(offset, list) and len(offset) == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in offset)) or offset == [0, 0]:
        error("E001", usage + "; not [0, 0]", line, "shadow.offset")
        return None
    color = str(raw["color"])
    if palette is not None and color not in palette.colors:
        error("E005", f"shadow color {color!r} isn't a palette key", line, "shadow.color")
        return None
    return (offset[0], offset[1], color)


def _parse_textures(raw: Any, frames: dict[str, Grid], animations: dict[str, Animation], line: int | None, error: ErrorFn) -> Textures | None:
    """export_textures: true (every tile) | { tiles: all | none | [names], groups: { name: "rows of tile names" },
    triplanar: bool }. Animation frames aren't tiles of their own, so `all` leaves them out."""
    usage = 'export_textures is true, or { tiles: all | none | [tile, ...], groups: { name: "rows of tile names" }, triplanar: true }'
    in_animations = {f for a in animations.values() for f in a.frames}
    every = tuple(name for name in frames if name not in in_animations)
    if raw is True:
        return Textures(every, {})
    if not isinstance(raw, dict):
        error("E001", usage, line, "export_textures")
        return None
    bad = [k for k in raw if k not in ("tiles", "groups", "triplanar")]
    if bad:
        error("E001", f"unknown export_textures field(s) {', '.join(map(str, bad))}; {usage}", line, "export_textures")
        return None
    tiles_raw = raw.get("tiles", "all" if "groups" not in raw else "none")
    if tiles_raw == "all":
        tiles = every
    elif tiles_raw == "none":
        tiles = ()
    elif isinstance(tiles_raw, list) and all(isinstance(t, str) for t in tiles_raw):
        unknown = [t for t in tiles_raw if t not in frames]
        if unknown:
            error("E001", f"export_textures.tiles: no tile(s) {', '.join(unknown)}", line, "export_textures.tiles")
            return None
        tiles = tuple(tiles_raw)
    else:
        error("E001", usage, line, "export_textures.tiles")
        return None
    groups: dict[str, tuple[tuple[str, ...], ...]] = {}
    raw_groups = raw.get("groups", {})
    if not isinstance(raw_groups, dict):
        error("E001", usage, line, "export_textures.groups")
        return None
    for name, layout in raw_groups.items():
        where = f"export_textures.groups.{name}"
        if not isinstance(name, str) or not NAME_RE.match(name) or name in frames:
            error("E001", "a group name is lowercase letters, digits, '_' or '-', and not a tile's name", line, where)
            continue
        rows = tuple(tuple(r.split()) for r in layout.split("\n") if r.strip()) if isinstance(layout, str) else ()
        if not rows or len({len(r) for r in rows}) != 1:
            error("E001", "a group is rows of tile names separated by spaces, every row the same length", line, where)
            continue
        unknown = sorted({t for r in rows for t in r if t not in frames})
        if unknown:
            error("E001", f"no tile(s) {', '.join(unknown)} (a texture can't have holes: no '.')", line, where)
            continue
        groups[name] = rows
    triplanar = raw.get("triplanar", False)
    if not isinstance(triplanar, bool):
        error("E001", "triplanar must be true or false (Godot: project the texture in world space, no UVs needed)", line, "export_textures.triplanar")
        return None
    return Textures(tiles, groups, triplanar)


def _parse_nine_slice(raw: Any, frames: list[str], size: tuple[int, int], line: int | None, error: ErrorFn) -> dict[str, Margins]:
    """`nine_slice: [left, top, right, bottom]` (every frame) or `{ frame: [l, t, r, b], ... }` (those frames).

    The margins are the fixed borders of a 9-slice (NinePatchRect) frame; the build carries them into the manifest.
    """
    if raw is None:
        return {}
    width, height = size
    usage = "nine_slice must be [left, top, right, bottom] margins in pixels, or { frame: [l, t, r, b], ... }"

    def margins(value: Any, where: str, ln: int | None) -> Margins | None:
        if not (isinstance(value, list) and len(value) == 4 and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in value)):
            error("E001", usage, ln, where)
            return None
        left, top, right, bottom = value
        if left + right >= width or top + bottom >= height:
            error("E001", f"nine_slice {value} leaves no centre in a {width}x{height} frame: left + right must be under {width}, top + bottom under {height}", ln, where)
            return None
        return (left, top, right, bottom)

    if isinstance(raw, list):
        found = margins(raw, "nine_slice", line)
        return {name: found for name in frames} if found is not None else {}
    if not isinstance(raw, dict) or not raw:
        error("E001", usage, line, "nine_slice")
        return {}
    out: dict[str, Margins] = {}
    for name, value in raw.items():
        where = f"nine_slice.{name}"
        if name not in frames:
            error("E001", f"nine_slice: {name!r} isn't a frame of this sprite", _line(raw, name) or line, where)
            continue
        found = margins(value, where, _line(raw, name) or line)
        if found is not None:
            out[name] = found
    return out


def _parse_font(raw: Any, frames: dict[str, Grid], size: tuple[int, int], line: int | None, error: ErrorFn) -> Font | None:
    """`font: { glyphs: "ABC...", cell: [6, 8], baseline: 7, advance: auto, spacing: 1, space: 3 }`."""
    usage = "font must be { glyphs: \"ABC...\", cell: [w, h], baseline: N, line_height: N, advance: auto | N, spacing: N, space: N }"
    if not isinstance(raw, dict):
        error("E001", usage, line, "font")
        return None
    ok = True
    for key in raw:
        if key not in _FONT_FIELDS:
            error("E001", f"unknown font field {key!r}; allowed: {', '.join(_FONT_FIELDS)}", _line(raw, key) or line, f"font.{key}")
            ok = False

    def where_line(key: str) -> int | None:
        return _line(raw, key) or line

    glyphs = raw.get("glyphs")
    if isinstance(glyphs, list) and all(isinstance(g, str) for g in glyphs):
        glyphs = "".join(glyphs)  # rows of glyphs, e.g. one string per sheet row
    if not isinstance(glyphs, str) or not glyphs:
        error("E001", "font.glyphs must be the characters in glyph order: a string, or a list of strings (joined)", where_line("glyphs"), "font.glyphs")
        return None
    repeated = sorted({c for c in glyphs if glyphs.count(c) > 1})
    if repeated:
        error("E001", f"font.glyphs repeats {' '.join(repr(c) for c in repeated)}; each character needs one glyph", where_line("glyphs"), "font.glyphs")
        ok = False
    width, height = size
    cell = size
    if "cell" in raw:
        parsed = _parse_size(raw["cell"], "font.cell", where_line("cell"), error)
        if parsed is None:
            return None
        if width % parsed[0] or height % parsed[1]:
            error("E001", f"font.cell {parsed[0]}x{parsed[1]} must divide the {width}x{height} frame into whole cells", where_line("cell"), "font.cell")
            return None
        cell = parsed
    cell_w, cell_h = cell

    def number(key: str, default: int, low: int, high: int) -> int:
        nonlocal ok
        value = raw.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            error("E001", f"font.{key} must be a whole number {low}-{high}", where_line(key), f"font.{key}")
            ok = False
            return default
        return value

    baseline = number("baseline", cell_h, 1, cell_h)
    line_height = number("line_height", cell_h, 1, 4 * cell_h)
    spacing = number("spacing", 1, 0, cell_w)
    space = number("space", -(-cell_w // 2), 0, 4 * cell_w)
    advance = None if raw.get("advance") == "auto" else number("advance", cell_w, 1, 4 * cell_w)
    cells = len(frames) * (width // cell_w) * (height // cell_h)
    if len(glyphs) > cells:
        error("E001", f"font.glyphs has {len(glyphs)} characters but the frames hold {cells} glyph cells", where_line("glyphs"), "font.glyphs")
        return None
    font = Font(glyphs, cell, baseline, line_height, advance, spacing, space)
    for index, (frame, grid) in enumerate(glyph_cells(font, frames, size)):
        if index >= len(glyphs) and any(c != TRANSPARENT for row in grid for c in row):
            error("E001", f"frame {frame!r} has drawn glyph cells past the {len(glyphs)} characters in font.glyphs; add their characters", where_line("glyphs"), "font.glyphs")
            ok = False
            break
    return font if ok else None


def glyph_cells(font: Font, frames: dict[str, Grid], size: tuple[int, int]) -> list[tuple[str, Grid]]:
    """Every glyph cell in order (frame by frame, each cut row by row): (frame name, cell pixels)."""
    cell_w, cell_h = font.cell
    out: list[tuple[str, Grid]] = []
    for name, grid in frames.items():
        for top in range(0, size[1], cell_h):
            for left in range(0, size[0], cell_w):
                out.append((name, tuple(row[left : left + cell_w] for row in grid[top : top + cell_h])))
    return out


def load_asset(path: Path, project: Project) -> tuple[Asset | None, list[Finding]]:
    kind = asset_kind(path)
    if kind is None:
        return None, [Finding("E000", f"not a PAGAN asset (expected {' or '.join(ASSET_SUFFIXES)})", path)]
    try:
        data = load_yaml(path)
    except YamlError as exc:
        return None, [Finding("E001", exc.message, path, exc.line)]
    if kind == "model":
        from pagan.model import parse_model  # local import: model builds on this module

        return parse_model(data, path, project, path.read_text(encoding="utf-8"))
    return parse_asset(data, path, project, kind)


def load_asset_or_raise(path: Path, project: Project) -> Asset:
    asset, findings = load_asset(path, project)
    if asset is None:
        raise PaganError(findings)
    return asset
