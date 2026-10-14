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
from pagan.project import Project
from pagan.yamlio import LineMap, YamlError, load_yaml

SPRITE_SUFFIX = ".sprite.yaml"
TILESET_SUFFIX = ".tiles.yaml"
ASSET_SUFFIXES = (SPRITE_SUFFIX, TILESET_SUFFIX)
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
FRAME_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
MAX_SIZE = 1024
DEFAULT_FPS = 8.0
STATUSES = ("draft", "approved")
MAX_PIXEL_FINDINGS = 8  # per frame, so one bad row doesn't drown everything else

Kind = Literal["sprite", "tileset"]
Grid = tuple[str, ...]  # rows of palette keys, "." = transparent
ErrorFn = Callable[[str, str, int | None, str | None], None]

_COMMON_FIELDS = ("name", "description", "palette", "variants", "tags", "status", "style_version")
_SPRITE_FIELDS = (*_COMMON_FIELDS, "size", "pivot", "mirror", "outline", "outline_color", "frames", "animations")
_TILESET_FIELDS = (*_COMMON_FIELDS, "tile_size", "columns", "tiles")


@dataclass(frozen=True)
class Animation:
    name: str
    frames: tuple[str, ...]
    fps: float
    loop: bool


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
    outline_color: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()
    status: str = "draft"
    style_version: int = 1


def asset_kind(path: Path) -> Kind | None:
    if path.name.endswith(SPRITE_SUFFIX):
        return "sprite"
    if path.name.endswith(TILESET_SUFFIX):
        return "tileset"
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


def opaque(grid: Grid, x: int, y: int) -> bool:
    return 0 <= y < len(grid) and 0 <= x < len(grid[y]) and grid[y][x] != TRANSPARENT


def _outline(grid: Grid, color: str) -> Grid:
    out = []
    for y, row in enumerate(grid):
        chars = list(row)
        for x, char in enumerate(row):
            if char == TRANSPARENT and any(
                opaque(grid, x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            ):
                chars[x] = color
        out.append("".join(chars))
    return tuple(out)


def _edge_pixel(grid: Grid) -> tuple[int, int] | None:
    """First opaque pixel touching the canvas edge (an outline there would be clipped)."""
    height = len(grid)
    for y, row in enumerate(grid):
        for x, char in enumerate(row):
            if char != TRANSPARENT and (x == 0 or y == 0 or x == len(row) - 1 or y == height - 1):
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
            error("E001", "missing 'palette' (and pagan.toml has no default_palette)", _line(data), "palette")
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
    return meta


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
) -> tuple[dict[str, Grid], dict[str, int | None], dict[str, str]]:
    """Parse grid frames and derived frames. Returns (frames in source order, lines, derived_from)."""
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
        if not isinstance(name, str) or not FRAME_NAME_RE.match(name):
            error("E001", f"frame name {name!r} must be letters, digits, '_' or '-' (quote names like 'on')", frame_line, where)
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

    def resolve(name: str) -> Grid | None:
        if name in frames:
            return frames[name]
        if name not in derived_specs:
            return None
        spec, spec_line = derived_specs[name]
        where = f"{section_name}.{name}"
        if name in resolving:
            error("E010", "derived frames form a cycle", spec_line, where)
            return None
        resolving.add(name)
        try:
            for key in spec:
                if key not in ("from", "flip", "shift"):
                    error("E001", f"unknown derived-frame field {key!r}; allowed: from, flip, shift", spec_line, where)
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
        finally:
            resolving.discard(name)

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
                error("E006", exc.findings[0].message, vline, where)
                continue

        mapping: dict[str, str] = {}
        ramp_swap = spec.get("ramp_swap", {})
        if not isinstance(ramp_swap, dict):
            error("E006", "ramp_swap must map ramp -> ramp, e.g. { green: fire }", vline, where)
            ok = False
            ramp_swap = {}
        for src, dst in ramp_swap.items():
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


def _darkest(palette: Palette) -> str:
    def luminance(key: str) -> float:
        r, g, b = palette.colors[key].rgb
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    return min(palette.colors, key=luminance)


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
    pivot = (width // 2, height)
    columns = 8
    if kind == "sprite":
        mirror_raw = data.get("mirror", "none")
        if mirror_raw not in ("none", "horizontal"):
            error("E001", "mirror must be none or horizontal", _line(data, "mirror"), "mirror")
        mirror = mirror_raw == "horizontal"

        outline_raw = data.get("outline", "none")
        if outline_raw not in ("none", "auto"):
            error("E001", "outline must be none or auto", _line(data, "outline"), "outline")
        outline = outline_raw == "auto"
        if not outline and project.config.lint.require_outline:
            error("E011", "pagan.toml requires outlines: add `outline: auto`", _line(data), "outline")

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
    )

    animations: dict[str, Animation] = {}
    if kind == "sprite":
        animations = _parse_animations(data.get("animations"), set(frame_lines), _line(data, "animations"), error)

    frames = dict(base_frames)
    if outline and outline_color is not None:
        for frame_name, grid in base_frames.items():
            edge = _edge_pixel(grid)
            if edge is not None:
                x, y = edge
                error(
                    "E007",
                    "outline: auto would be clipped: an opaque pixel touches the canvas edge. "
                    "Leave a 1px transparent border (or grow the canvas)",
                    frame_lines.get(frame_name),
                    f"{frames_field}.{frame_name} row {y + 1} col {x + 1}",
                )
            frames[frame_name] = _outline(grid, outline_color)

    variants: dict[str, Variant] = {}
    if palette is not None:
        used = {c for grid in frames.values() for row in grid for c in row if c != TRANSPARENT}
        variants = _parse_variants(data.get("variants"), palette, project, _line(data, "variants"), used, error)

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
            **meta,
        ),
        findings,
    )


def load_asset(path: Path, project: Project) -> tuple[Asset | None, list[Finding]]:
    kind = asset_kind(path)
    if kind is None:
        return None, [Finding("E000", f"not a PAGAN asset (expected {' or '.join(ASSET_SUFFIXES)})", path)]
    try:
        data = load_yaml(path)
    except YamlError as exc:
        return None, [Finding("E001", exc.message, path, exc.line)]
    return parse_asset(data, path, project, kind)


def load_asset_or_raise(path: Path, project: Project) -> Asset:
    asset, findings = load_asset(path, project)
    if asset is None:
        raise PaganError(findings)
    return asset
