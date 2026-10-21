"""Project settings: one registry of every `pagan.toml` setting (default, meaning, what it refreshes),
plus safe editing for `pagan config set`.

Settings are the project's saved, shared choices (camera angle, light, palette...). Changing one and
rebuilding refreshes every asset it affects: 3D models re-render, palette changes recolor everything.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from typing import Any, Literal

from pagan.findings import Finding, PaganError
from pagan.project import Config, Project, parse_config

Refresh = Literal["all", "models", "meshes", "build", "lint", "none"]


@dataclass(frozen=True)
class Setting:
    key: str  # dotted: "camera.elevation"
    default: Any
    meaning: str
    refresh: Refresh  # what changes when this setting changes

    @property
    def table(self) -> str | None:
        return self.key.split(".")[0] if "." in self.key else None

    @property
    def name(self) -> str:
        return self.key.split(".")[-1]


SETTINGS: tuple[Setting, ...] = (
    Setting("palette_mode", "strict", '"strict": assets use palette files only; "open": inline palettes allowed', "lint"),
    Setting("default_palette", None, "palette for assets that don't name one; switching it recolors all of them", "all"),
    Setting("output_dir", "build", "where `pagan build` writes final assets (e.g. a game engine's asset folder)", "build"),
    Setting("preview_dir", "previews", "scratch folder for previews", "none"),
    Setting("export", ["png"], 'extra build outputs: "godot" (SpriteFrames/TileSet .tres), "normals" (normal maps for 3D models), "mesh" (3D models as .glb meshes for 3D games); "png" sheets + manifest are always written', "build"),
    Setting("variant_sheets", True, "build a sheet (+ .tres) per variant; false: variants are only colour swap tables in manifest.json, for games that recolour in a shader", "build"),
    Setting("supersample", 1, "sources are drawn at N x the size the game gets; build box-filters them down to smooth, anti-aliased PNGs (for freely rotated, non-pixel-art sprites; 1 = off, pixel-exact)", "build"),
    Setting("style_version", 1, "current style version; assets made under older ones get W006 (use `pagan style bump`)", "lint"),
    Setting("camera.elevation", 42.0, "3D camera angle above the horizon in degrees: 90 = straight down, ~40 = top-down 3/4, ~15 = side-on", "models"),
    Setting("camera.scale", 1.0, "pixels per voxel for 3D models", "models"),
    Setting("light.direction", [-0.5, 0.45, 0.75], "direction towards the light: x right, y up the screen, z up (default: top-left)", "models"),
    Setting("light.ambient", 0.2, "brightness of unlit surfaces 0-1 (lower = darker shadows, more contrast)", "models"),
    Setting("light.shadows", True, "parts cast shadows on each other", "models"),
    Setting("light.shadow_strength", 0.65, "how dark cast shadows are, 0-1", "models"),
    Setting("light.wrap", 0.3, "how far light wraps around curves, 0-1 (higher = softer shading)", "models"),
    Setting("light.baked", True, "true: shading baked into the pixels; false: flat colors for engines with their own lighting (add \"normals\" to export)", "models"),
    Setting("godot.mipmaps", False, "Godot imports the PNGs with mipmaps (for sprites drawn scaled down or rotated); written into each PNG's .import", "build"),
    Setting("godot.filter", "inherit", 'SpriteFrames texture filter: "inherit" (node/project setting decides), "nearest" (crisp pixels), "linear" (smooth)', "build"),
    Setting("mesh.voxel_size", 0.0625, "metres per voxel when 3D models export as meshes (0.0625 = 16 voxels per metre); pick it per game from the closest camera distance", "meshes"),
    Setting("mesh.shading", "ramp", '"ramp": palette-locked lighting in the engine (PAGAN ramp shader); "baked": project light baked per face (no shader); "flat": middle ramp step, engine lights it', "meshes"),
    Setting("mesh.collision_suffixes", False, "name collision parts with Godot's -col/-convcol/-colonly suffixes (changes node names)", "meshes"),
    Setting("lint.max_ramps_per_sprite", 3, "W003: most ramps one 2D sprite/tileset may use", "lint"),
    Setting("lint.max_ramps_per_model", 6, "W003: most ramps one 3D model may use (more materials: hull, sails, team colours)", "lint"),
    Setting("lint.max_frame_change", 0.4, "W007: share of pixels that may change between animation frames", "lint"),
    Setting("lint.max_ramp_steps", 0, "W008: most shades per ramp/material (0 = no limit)", "lint"),
    Setting("lint.disable", [], "warning ids to turn off", "lint"),
    Setting("lint.require_outline", False, "E011: every sprite must use outline: auto", "lint"),
    Setting("lint.require_opaque", False, 'E015: sprites and tilesets may not use translucent ("#rrggbbaa") colours', "lint"),
)
BY_KEY = {s.key: s for s in SETTINGS}


def current_value(config: Config, key: str) -> Any:
    table, _, name = key.rpartition(".")
    source: Any = getattr(config, table) if table else config
    value = getattr(source, name)
    if isinstance(value, tuple):
        return list(value)
    return value


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    raise ValueError(f"can't write {value!r} to TOML")


def parse_value(text: str) -> Any:
    """Parse a command-line value as TOML (`42`, `true`, `[1, 2]`, `"x"`); bare words become strings."""
    try:
        value = tomllib.loads(f"v = {text}")["v"]
    except tomllib.TOMLDecodeError:
        return text
    # Dates, times and inline tables aren't setting values: treat the text as a plain string.
    return value if isinstance(value, bool | int | float | str | list) else text


def _split_comment(line: str) -> tuple[str, str]:
    """Split a TOML line into code and trailing comment (ignoring # inside strings)."""
    quote: str | None = None
    for i, char in enumerate(line):
        if quote:
            if char == "\\" and quote == '"':
                continue
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == "#":
            return line[:i], line[i:]
    return line, ""


def _bracket_depth(code: str) -> int:
    depth, quote = 0, None
    for char in code:
        if quote:
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
    return depth


def _sections(lines: list[str]) -> list[tuple[str, int, int]]:
    """(table name, first line, end line) for the root ("") and every [table]."""
    found: list[tuple[str, int, int]] = []
    name, start = "", 0
    for i, line in enumerate(lines):
        header = re.match(r"^\s*\[([^\[\]]+)\]\s*(#.*)?$", line)
        if header:
            found.append((name, start, i))
            name, start = header.group(1).strip(), i + 1
    found.append((name, start, len(lines)))
    return found


def set_in_toml(text: str, key: str, value: Any) -> str:
    """Set a (possibly dotted) key in TOML text, keeping layout and comments.

    Replaces an existing value (also one spread over several lines), else a commented-out
    `# key = ...` template line, else adds the key at the end of its table (creating the table).
    """
    return _edit_toml(text, key, f"{key.rpartition('.')[2]} = {toml_value(value)}")


def remove_from_toml(text: str, key: str) -> str:
    """Comment out a key so its default applies again (the line stays as a template)."""
    return _edit_toml(text, key, None)


def _edit_toml(text: str, key: str, entry: str | None) -> str:
    table, _, name = key.rpartition(".")
    lines = text.split("\n")
    section = next((sec for sec in _sections(lines) if sec[0] == table), None)
    if section is not None:
        _, first, end = section
        for i in range(first, end):
            code, comment = _split_comment(lines[i])
            match = re.match(rf"^(\s*){re.escape(name)}\s*=", code)
            if not match:
                continue
            last = i
            while _bracket_depth("".join(_split_comment(l)[0] for l in lines[i : last + 1])) > 0 and last + 1 < end:
                last += 1  # a value spread over several lines
            if entry is None:
                replacement = [f"{match.group(1)}# {name} = {code.split('=', 1)[1].strip()}"] if last == i else []
                lines[i : last + 1] = replacement
            else:
                gap = code[len(code.rstrip()) :] if last == i else ""
                lines[i : last + 1] = [f"{match.group(1)}{entry}{gap}{comment if last == i else ''}"]
            return "\n".join(lines)
        if entry is None:
            return text
        for i in range(first, end):  # a commented-out template line: `# default_palette = "my_palette"`
            template = re.match(rf"^(\s*)#\s*{re.escape(name)}\s*=", lines[i])
            if template:
                lines[i] = f"{template.group(1)}{entry}"
                return "\n".join(lines)
        insert = end
        while insert > first and (not lines[insert - 1].strip() or lines[insert - 1].lstrip().startswith("#")):
            insert -= 1  # after the table's last setting, before trailing blanks/comments of the next table
        lines.insert(insert, entry)
        return "\n".join(lines)
    if entry is None:
        return text
    suffix = "" if text.endswith("\n") else "\n"
    return f"{text}{suffix}\n[{table}]\n{entry}\n"


@dataclass
class Change:
    key: str
    old: Any
    new: Any
    refresh: Refresh


def set_setting(project: Project, key: str, raw_value: str) -> Change:
    """Validate and save a setting; raises PaganError (and changes nothing) if the result is invalid."""
    if project.config_path is None:
        raise PaganError([Finding("E000", "no pagan.toml found; run `pagan init` first")])
    if key not in BY_KEY:
        raise PaganError([Finding("E000", f"unknown setting {key!r}; see `pagan config show`")])
    value = parse_value(raw_value)
    setting = BY_KEY[key]
    if isinstance(setting.default, list) and isinstance(value, str):
        # Lists can also be written comma-separated: png,godot  ->  ["png", "godot"]
        value = [parse_value(part.strip()) for part in value.split(",") if part.strip()]
    text = project.config_path.read_text(encoding="utf-8")
    updated = set_in_toml(text, key, value)
    try:
        data = tomllib.loads(updated)
    except tomllib.TOMLDecodeError as exc:
        raise PaganError([Finding("E001", f"that value doesn't make valid TOML: {exc}", project.config_path)]) from None
    try:
        new_config = parse_config(data, project.config_path)  # raises with a precise message if invalid
    except PaganError as exc:
        example = toml_value(setting.default if setting.default is not None else "name")
        hint = f" (value syntax is TOML, e.g. pagan config set {key} '{example}')"
        raise PaganError([Finding(f.rule, f.message + hint, f.path, f.line, f.where) for f in exc.findings]) from None
    if key == "default_palette" and value is not None and not project.palette_path(str(value)).is_file():
        known = ", ".join(project.palette_names()) or "none"
        raise PaganError([Finding("E005", f"no palette {value!r} (palettes: {known})", project.config_path)])
    old = current_value(project.config, key)
    project.config_path.write_text(updated, encoding="utf-8")
    return Change(key, old, current_value(new_config, key), BY_KEY[key].refresh)


def unset_setting(project: Project, key: str) -> Change:
    """Return a setting to its default by commenting it out of pagan.toml."""
    if project.config_path is None:
        raise PaganError([Finding("E000", "no pagan.toml found; run `pagan init` first")])
    if key not in BY_KEY:
        raise PaganError([Finding("E000", f"unknown setting {key!r}; see `pagan config show`")])
    updated = remove_from_toml(project.config_path.read_text(encoding="utf-8"), key)
    new_config = parse_config(tomllib.loads(updated), project.config_path)
    old = current_value(project.config, key)
    project.config_path.write_text(updated, encoding="utf-8")
    return Change(key, old, current_value(new_config, key), BY_KEY[key].refresh)


def describe(config: Config) -> list[dict[str, Any]]:
    return [
        {
            "key": s.key,
            "value": current_value(config, s.key),
            "default": s.default,
            "is_default": current_value(config, s.key) == s.default,
            "meaning": s.meaning,
            "refreshes": s.refresh,
        }
        for s in SETTINGS
    ]

