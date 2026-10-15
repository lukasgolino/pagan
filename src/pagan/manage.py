"""Long-term asset management: catalogue, palette-wide look changes, style versions, status marks.

Edits to source files are made textually (one line at a time) so comments and formatting survive.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pagan.asset import ASSET_SUFFIXES, STATUSES, asset_kind, asset_name_from_path
from pagan.color import oklab_to_rgb, rgb_to_hex, rgb_to_oklab, to_lch, from_lch
from pagan.findings import Finding, PaganError
from pagan.lint import lint_paths, source_files
from pagan.palette import Palette, load_palette_file
from pagan.project import CONFIG_NAME, Project
from pagan.yamlio import LineMap, YamlError, load_yaml, parse_yaml


# --- catalogue --------------------------------------------------------------------------------


@dataclass
class AssetStatus:
    name: str
    kind: str
    path: Path
    description: str | None
    status: str
    style_version: int
    size: tuple[int, int] | None
    frames: int
    animations: int
    errors: int
    warnings: int
    tags: tuple[str, ...]

    def needs(self, current_style: int) -> list[str]:
        todo = []
        if self.errors:
            todo.append("fix errors")
        if self.style_version < current_style:
            todo.append(f"review for style v{current_style}")
        if self.status != "approved":
            todo.append("approve")
        if not self.description or self.description.startswith("TODO"):
            todo.append("describe")
        return todo


def catalogue(project: Project) -> list[AssetStatus]:
    result = lint_paths(project)
    by_path = {a.path.resolve(): a for a in result.assets if a.path is not None}
    out: list[AssetStatus] = []
    for path in result.files:
        kind = asset_kind(path)
        if kind is None:
            continue
        asset = by_path.get(path.resolve())
        findings = [f for f in result.findings if f.path is not None and f.path.resolve() == path.resolve()]
        if asset is not None:
            entry = AssetStatus(
                name=asset.name, kind=asset.kind, path=path, description=asset.description, status=asset.status,
                style_version=asset.style_version, size=asset.size, frames=len(asset.frames),
                animations=len(asset.animations), errors=sum(f.severity == "error" for f in findings),
                warnings=sum(f.severity == "warning" for f in findings), tags=asset.tags,
            )  # fmt: skip
        else:
            raw = _raw_fields(path)
            entry = AssetStatus(
                name=asset_name_from_path(path) or path.stem, kind=kind, path=path,
                description=raw.get("description") if isinstance(raw.get("description"), str) else None,
                status=str(raw.get("status", "draft")), style_version=_int(raw.get("style_version"), 1), size=None,
                frames=0, animations=0, errors=sum(f.severity == "error" for f in findings),
                warnings=sum(f.severity == "warning" for f in findings), tags=(),
            )  # fmt: skip
        out.append(entry)
    return sorted(out, key=lambda e: (e.kind, e.name))


def _int(value: Any, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _raw_fields(path: Path) -> dict[str, Any]:
    try:
        data = load_yaml(path)
    except Exception:  # noqa: BLE001 - the catalogue must list broken files too
        return {}
    return data if isinstance(data, dict) else {}


# --- palette adjustments ----------------------------------------------------------------------


@dataclass(frozen=True)
class Adjustment:
    lightness: float = 0.0  # added to OKLab L (0..1); -0.05 = a bit darker
    contrast: float = 1.0  # lightness spread around the mean: 1.2 = 20% more contrast
    saturation: float = 1.0  # chroma multiplier: 0.6 = more muted/pastel
    hue: float = 0.0  # degrees added to the hue
    warmth: float = 0.0  # shifts hues towards orange (+) or blue (-), in OKLab b units (~0.02 is subtle)

    def is_identity(self) -> bool:
        return self == Adjustment()


def adjust_colors(palette: Palette, keys: list[str], adj: Adjustment) -> dict[str, str]:
    """New hex per key. Lightness/contrast in OKLab keep the palette's ramps ordered and hues stable."""
    labs = {k: rgb_to_oklab(palette.colors[k].rgb) for k in keys}
    mean_l = sum(lab[0] for lab in labs.values()) / len(labs) if labs else 0.5
    out: dict[str, str] = {}
    for key, lab in labs.items():
        L, C, h = to_lch(lab)
        L = mean_l + (L - mean_l) * adj.contrast + adj.lightness
        C = C * adj.saturation
        h = h + adj.hue
        L2, a, b = from_lch(L, C, h)
        b += adj.warmth
        a += adj.warmth * 0.35
        out[key] = rgb_to_hex(oklab_to_rgb((L2, a, b)))
    return out


def apply_palette_hexes(path: Path, new_hexes: dict[str, str], new_name: str | None = None) -> str:
    """Return the palette file's text with each key's hex replaced at its exact position (comments kept)."""
    text = path.read_text(encoding="utf-8")
    data = load_yaml(path)
    if not isinstance(data, LineMap) or not isinstance(data.get("colors"), LineMap):
        raise PaganError([Finding("E005", "can't edit this palette: no colors mapping", path)])
    colors: LineMap = data["colors"]
    edits: list[tuple[int, int, int, str]] = []  # (line, start col, end col, replacement)
    for raw_key, value in colors.items():
        key = str(raw_key)
        if key not in new_hexes:
            continue
        span = (
            value.value_spans.get("hex")
            if isinstance(value, LineMap)
            else colors.value_spans.get(raw_key)
            if isinstance(value, str)
            else None
        )
        if span is None:
            raise PaganError([Finding("E005", f"can't locate the hex for key {key!r}", path, colors.line_of(raw_key))])
        line, start_col, end_col = span
        lines_text = text.split("\n")
        written = lines_text[line - 1][start_col:end_col]
        quote = written[0] if written[:1] in ("'", '"') else ""
        edits.append((line, start_col, end_col, f"{quote}{new_hexes[key]}{quote}"))
    if new_name is not None and isinstance(data.value_spans.get("name"), tuple):
        line, start_col, end_col = data.value_spans["name"]
        edits.append((line, start_col, end_col, new_name))
    return _apply_edits(text, edits)


def _apply_edits(text: str, edits: list[tuple[int, int, int, str]]) -> str:
    """Replace column spans; right-to-left per line so earlier columns stay valid."""
    lines = text.split("\n")
    for line, start_col, end_col, replacement in sorted(edits, key=lambda e: (e[0], -e[1])):
        current = lines[line - 1]
        lines[line - 1] = current[:start_col] + replacement + current[end_col:]
    return "\n".join(lines)


# --- status and style marks -------------------------------------------------------------------


def set_top_level_field(path: Path, field: str, value: str) -> None:
    """Set `field: value` at the top level of a YAML source file, keeping everything else as written.

    The edited text is parsed again before it's written; if the edit wouldn't give a valid file with
    the field set, nothing is changed and an error explains why.
    """
    text = path.read_text(encoding="utf-8")
    data = load_yaml(path)
    if not isinstance(data, LineMap):
        raise PaganError([Finding("E001", "not a mapping; can't edit", path)])
    if text.lstrip().startswith("{"):
        raise PaganError([Finding("E001", f"can't edit {field!r} in a flow-style ({{...}}) file; write it as block YAML", path)])
    if field in data:
        span = data.value_spans.get(field)
        if span is None:
            raise PaganError([Finding("E001", f"can't edit {field!r}: write it as a one-line value", path, data.line_of(field))])
        line, start_col, end_col = span
        current = text.split("\n")[line - 1]
        needs_space = start_col == end_col and not current[:start_col].endswith(" ")
        text = _apply_edits(text, [(line, start_col, end_col, (" " if needs_space else "") + value)])
    else:
        lines = text.split("\n")
        after = data.line_of("name") if "name" in data else 0
        lines.insert(after or 0, f"{field}: {value}")
        text = "\n".join(lines)
    try:
        check = parse_yaml(text)
    except YamlError as exc:
        raise PaganError([Finding("E001", f"editing {field!r} would break the file ({exc.message}); nothing changed", path)]) from None
    if not isinstance(check, dict) or str(check.get(field)) != value:
        raise PaganError([Finding("E001", f"couldn't set {field!r} safely; nothing changed", path)])
    path.write_text(text, encoding="utf-8")


def mark(paths: list[Path], status: str | None, style_version: int | None) -> None:
    if status is not None and status not in STATUSES:
        raise PaganError([Finding("E000", f"status must be one of {', '.join(STATUSES)}")])
    for path in paths:
        if not path.name.endswith(ASSET_SUFFIXES):
            raise PaganError([Finding("E000", "not an asset file", path)])
        if status is not None:
            set_top_level_field(path, "status", status)
        if style_version is not None:
            set_top_level_field(path, "style_version", str(style_version))


def bump_style(project: Project, note: str, today: dt.date | None = None) -> int:
    """Increment pagan.toml's style_version and log the change in STYLE.md's changelog."""
    if project.config_path is None:
        raise PaganError([Finding("E000", f"no {CONFIG_NAME} found")])
    new_version = project.config.style_version + 1
    text = project.config_path.read_text(encoding="utf-8")
    pattern = re.compile(r"^style_version\s*=\s*\d+[^\n]*$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(f"style_version = {new_version}", text, count=1)
    else:
        table = re.search(r"^\[", text, re.MULTILINE)
        at = table.start() if table else len(text)
        text = text[:at] + f"style_version = {new_version}\n\n" + text[at:]
    project.config_path.write_text(text, encoding="utf-8")

    style = project.root / "STYLE.md"
    entry = f"- v{new_version} ({(today or dt.date.today()).isoformat()}): {note.strip()}"
    existing = style.read_text(encoding="utf-8") if style.exists() else "# Style bible\n"
    if "## Changelog" in existing:
        head, tail = existing.split("## Changelog", 1)
        tail_lines = tail.split("\n")
        # Insert after the heading and any intro lines, before the first existing entry (newest first).
        insert = 1
        while insert < len(tail_lines) and not tail_lines[insert].startswith("- v") and not tail_lines[insert].startswith("## "):
            insert += 1
        tail_lines.insert(insert, entry)
        existing = head + "## Changelog" + "\n".join(tail_lines)
    else:
        existing = existing.rstrip("\n") + f"\n\n## Changelog\n\n{entry}\n"
    style.write_text(existing, encoding="utf-8")
    return new_version


def outdated(project: Project) -> list[Path]:
    """Asset files made under an older style version."""
    return [e.path for e in catalogue(project) if e.style_version < project.config.style_version]


def all_asset_files(project: Project) -> list[Path]:
    return [p for p in source_files(project) if p.name.endswith(ASSET_SUFFIXES)]


def load_palette_for_edit(project: Project, name: str) -> Palette:
    path = project.palette_path(name)
    if not path.is_file():
        raise PaganError([Finding("E005", f"unknown palette {name!r}", path)])
    return load_palette_file(path)
