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

Refresh = Literal["all", "models", "build", "lint", "none"]


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
    Setting("export", ["png"], 'build outputs: "png" (sheets + manifest), "godot" (SpriteFrames .tres), "normals" (normal maps for 3D models)', "build"),
    Setting("style_version", 1, "current style version; assets made under older ones get W006 (use `pagan style bump`)", "lint"),
    Setting("camera.elevation", 42.0, "3D camera angle above the horizon in degrees: 90 = straight down, ~40 = top-down 3/4, ~15 = side-on", "models"),
    Setting("camera.scale", 1.0, "pixels per voxel for 3D models", "models"),
    Setting("light.direction", [-0.5, 0.45, 0.75], "direction towards the light: x right, y up the screen, z up (default: top-left)", "models"),
    Setting("light.ambient", 0.2, "brightness of unlit surfaces 0-1 (lower = darker shadows, more contrast)", "models"),
    Setting("light.shadows", True, "parts cast shadows on each other", "models"),
    Setting("light.shadow_strength", 0.65, "how dark cast shadows are, 0-1", "models"),
    Setting("light.wrap", 0.3, "how far light wraps around curves, 0-1 (higher = softer shading)", "models"),
    Setting("light.baked", True, "true: shading baked into the pixels; false: flat colors for engines with their own lighting (add \"normals\" to export)", "models"),
    Setting("lint.max_ramps_per_sprite", 3, "W003: most ramps one 2D sprite/tileset may use", "lint"),
    Setting("lint.max_ramps_per_model", 6, "W003: most ramps one 3D model may use (more materials: hull, sails, team colours)", "lint"),
    Setting("lint.max_frame_change", 0.4, "W007: share of pixels that may change between animation frames", "lint"),
    Setting("lint.max_ramp_steps", 0, "W008: most shades per ramp/material (0 = no limit)", "lint"),
    Setting("lint.disable", [], "warning ids to turn off", "lint"),
    Setting("lint.require_outline", False, "E011: every sprite must use outline: auto", "lint"),
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
        return tomllib.loads(f"v = {text}")["v"]
    except tomllib.TOMLDecodeError:
        return text


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


def set_in_toml(text: str, key: str, value: Any) -> str:
    """Set a (possibly dotted) key in TOML text, keeping layout and comments."""
    table, _, name = key.rpartition(".")
    lines = text.split("\n")
    current_table = ""
    table_start: int | None = 0 if not table else None
    table_end = len(lines)
    for i, line in enumerate(lines):
        header = re.match(r"^\s*\[([^\[\]]+)\]\s*(#.*)?$", line)
        if header:
            if table and current_table == table and table_start is not None:
                table_end = i
                break
            current_table = header.group(1).strip()
            if current_table == table:
                table_start = i + 1
            elif not table:
                table_end = i
                break
            continue
        if current_table == table:
            code, comment = _split_comment(line)
            match = re.match(rf"^(\s*){re.escape(name)}(\s*=\s*)", code)
            if match:
                gap = code[len(code.rstrip()) :]  # keep the spacing before a trailing comment
                lines[i] = f"{match.group(1)}{name}{match.group(2)}{toml_value(value)}{gap}{comment}"
                return "\n".join(lines)
    entry = f"{name} = {toml_value(value)}"
    if table_start is None:  # table doesn't exist yet: append it
        suffix = "" if text.endswith("\n") else "\n"
        return f"{text}{suffix}\n[{table}]\n{entry}\n"
    insert = table_end
    while insert > table_start and not lines[insert - 1].strip():
        insert -= 1
    lines.insert(insert, entry)
    return "\n".join(lines)


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

