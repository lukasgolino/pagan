"""Palettes: the colors a sprite may use, keyed by single characters, grouped into shading ramps."""

from __future__ import annotations

import re
import string
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pagan.findings import Finding, PaganError, has_errors
from pagan.yamlio import LineMap, YamlError, load_yaml

TRANSPARENT = "."
KEY_CHARS = frozenset(string.digits + string.ascii_letters)
PALETTE_SUFFIX = ".pal.yaml"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_FIELDS = ("name", "colors", "ramps")
_COLOR_FIELDS = ("hex", "name")

# error(rule, message, line, where)
ErrorFn = Callable[[str, str, int | None, str | None], None]


@dataclass(frozen=True)
class Color:
    key: str
    hex: str  # normalized lowercase "#rrggbb"
    name: str | None = None

    @property
    def rgb(self) -> tuple[int, int, int]:
        return (int(self.hex[1:3], 16), int(self.hex[3:5], 16), int(self.hex[5:7], 16))


@dataclass(frozen=True)
class Palette:
    name: str | None  # None for an unnamed inline palette
    colors: dict[str, Color]  # in source order
    ramps: dict[str, tuple[str, ...]]  # shadow -> highlight
    path: Path | None = None


def _line(data: Any, key: Any = None) -> int | None:
    if isinstance(data, LineMap):
        return data.line_of(key) if key is not None else data.line
    return None


def _normalize_key(raw: Any) -> str | None:
    """YAML reads an unquoted 5 as an int; accept digits 0-9 as keys anyway."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int) and 0 <= raw <= 9:
        return str(raw)
    if isinstance(raw, str):
        return raw
    return None


def parse_palette(
    data: Any, path: Path | None = None, *, expected_name: str | None = None, inline: bool = False
) -> tuple[Palette | None, list[Finding]]:
    """Validate palette data (a palette file's content, or a sprite's inline palette).

    Returns the palette (None if there were errors) and all findings.
    """
    findings: list[Finding] = []

    def error(rule: str, message: str, line: int | None, where: str | None = None) -> None:
        findings.append(Finding(rule, message, path, line, where))

    if not isinstance(data, dict):
        error("E001", "palette must be a mapping with a 'colors' section", _line(data))
        return None, findings

    for field in data:
        if field not in _FIELDS:
            error("E001", f"unknown field {field!r}; allowed fields: {', '.join(_FIELDS)}", _line(data, field))

    name = data.get("name")
    if name is None and not inline:
        error("E001", "missing required field 'name'", _line(data))
    elif name is not None:
        if not isinstance(name, str) or not NAME_RE.match(name):
            error("E001", "name must be lowercase letters, digits, '_' or '-'", _line(data, "name"), "name")
        elif expected_name is not None and name != expected_name:
            error(
                "E005",
                f"name {name!r} doesn't match the file name; expected {expected_name!r}",
                _line(data, "name"),
                "name",
            )

    colors: dict[str, Color] = {}
    raw_colors = data.get("colors")
    if raw_colors is None:
        error("E001", "missing required field 'colors'", _line(data))
    elif not isinstance(raw_colors, dict) or not raw_colors:
        error("E001", "'colors' must be a non-empty mapping of key -> color", _line(data, "colors"), "colors")
    else:
        for raw_key, raw_value in raw_colors.items():
            line = _line(raw_colors, raw_key)
            key = _normalize_key(raw_key)
            where = f"colors.{key if key is not None else raw_key}"
            if key == TRANSPARENT:
                error("E005", "'.' is reserved for transparent and can't be a palette color", line, where)
                continue
            if key is None or len(key) != 1 or key not in KEY_CHARS:
                error("E005", f"color key {raw_key!r} must be one character: 0-9, a-z or A-Z", line, where)
                continue
            if key in colors:
                error("E005", f"duplicate color key {key!r}", line, where)
                continue
            color = _parse_color(key, raw_value, line, where, error)
            if color is not None:
                colors[key] = color

    # Keys written in the colors section, valid or not; invalid ones were already reported above.
    declared = {k for k in map(_normalize_key, raw_colors)} if isinstance(raw_colors, dict) else set()
    ramps: dict[str, tuple[str, ...]] = {}
    raw_ramps = data.get("ramps")
    if raw_ramps is not None:
        if not isinstance(raw_ramps, dict):
            error("E005", "'ramps' must be a mapping of ramp name -> list of color keys", _line(data, "ramps"), "ramps")
        else:
            for ramp_name, entries in raw_ramps.items():
                line = _line(raw_ramps, ramp_name)
                where = f"ramps.{ramp_name}"
                if not isinstance(ramp_name, str):
                    error("E005", f"ramp name {ramp_name!r} must be text", line, where)
                    continue
                if not isinstance(entries, list) or not entries:
                    error("E005", "a ramp must be a non-empty list of color keys, shadow -> highlight", line, where)
                    continue
                keys: list[str] = []
                for entry in entries:
                    key = _normalize_key(entry)
                    if key is None or key not in colors:
                        if key is None or key not in declared:
                            error("E005", f"ramp uses unknown color key {entry!r}", line, where)
                        continue
                    if key in keys:
                        error("E005", f"color key {key!r} appears twice in the ramp", line, where)
                        continue
                    keys.append(key)
                ramps[ramp_name] = tuple(keys)

    if has_errors(findings):
        return None, findings
    return Palette(name=name, colors=colors, ramps=ramps, path=path), findings


def _parse_color(key: str, raw: Any, line: int | None, where: str, error: ErrorFn) -> Color | None:
    color_name: Any = None
    if isinstance(raw, str):
        hex_value: Any = raw
    elif isinstance(raw, dict):
        for field in raw:
            if field not in _COLOR_FIELDS:
                error("E001", f"unknown color field {field!r}; allowed: hex, name", line, where)
        hex_value = raw.get("hex")
        color_name = raw.get("name")
    elif raw is None:
        error(
            "E005",
            'color is empty. If you wrote an unquoted hex like #aabbcc, YAML treats "#" as a comment; '
            'quote it: "#aabbcc"',
            line,
            where,
        )
        return None
    else:
        error("E005", 'color must be "#rrggbb" or { hex: "#rrggbb", name: ... }', line, where)
        return None

    if hex_value is None:
        error(
            "E005",
            'missing hex. If you wrote hex: #aabbcc without quotes, YAML treats "#" as a comment; '
            'write hex: "#aabbcc"',
            line,
            f"{where}.hex",
        )
        return None
    if not isinstance(hex_value, str) or not _HEX_RE.match(hex_value):
        error("E005", f'bad hex {hex_value!r}; expected "#rrggbb"', line, f"{where}.hex")
        return None
    if color_name is not None and not isinstance(color_name, str):
        error("E005", "color name must be text", line, f"{where}.name")
        return None
    return Color(key=key, hex=hex_value.lower(), name=color_name)


def palette_name_from_path(path: Path) -> str | None:
    if path.name.endswith(PALETTE_SUFFIX):
        return path.name[: -len(PALETTE_SUFFIX)]
    return None


def load_palette_file(path: Path) -> Palette:
    """Load and validate a palette file. Raises PaganError with findings on any error."""
    try:
        data = load_yaml(path)
    except YamlError as exc:
        raise PaganError([Finding("E001", exc.message, path, exc.line)]) from None
    palette, findings = parse_palette(data, path, expected_name=palette_name_from_path(path))
    if palette is None:
        raise PaganError(findings)
    return palette
