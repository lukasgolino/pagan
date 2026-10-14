"""PAGAN projects: a directory with a pagan.toml plus palettes/, sprites/ and tiles/."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pagan.findings import Finding, PaganError
from pagan.palette import NAME_RE, PALETTE_SUFFIX, Palette, load_palette_file

CONFIG_NAME = "pagan.toml"
PALETTE_MODES = ("strict", "open")
EXPORTERS = ("png", "godot")

PaletteMode = Literal["strict", "open"]


@dataclass(frozen=True)
class LintConfig:
    max_ramps_per_sprite: int = 3
    disable: tuple[str, ...] = ()
    require_outline: bool = False


@dataclass(frozen=True)
class Config:
    palette_mode: PaletteMode = "strict"
    default_palette: str | None = None
    output_dir: str = "build"
    preview_dir: str = "previews"
    export: tuple[str, ...] = ("png",)
    style_version: int = 1
    lint: LintConfig = field(default_factory=LintConfig)


@dataclass(frozen=True)
class Project:
    root: Path
    config: Config
    config_path: Path | None  # None when running without a pagan.toml
    _palettes: dict[str, Palette] = field(default_factory=dict, compare=False, repr=False)

    @property
    def palettes_dir(self) -> Path:
        return self.root / "palettes"

    @property
    def sprites_dir(self) -> Path:
        return self.root / "sprites"

    @property
    def tiles_dir(self) -> Path:
        return self.root / "tiles"

    @property
    def preview_dir(self) -> Path:
        return self.root / self.config.preview_dir

    @property
    def output_dir(self) -> Path:
        return self.root / self.config.output_dir

    def palette_path(self, name: str) -> Path:
        return self.palettes_dir / f"{name}{PALETTE_SUFFIX}"

    def palette_names(self) -> list[str]:
        if not self.palettes_dir.is_dir():
            return []
        return sorted(p.name[: -len(PALETTE_SUFFIX)] for p in self.palettes_dir.glob(f"*{PALETTE_SUFFIX}"))

    def load_palette(self, name: str) -> Palette:
        """Load a palette by name (cached per project). Raises PaganError."""
        if name in self._palettes:
            return self._palettes[name]
        path = self.palette_path(name)
        if not path.is_file():
            known = ", ".join(self.palette_names()) or "none"
            raise PaganError(
                [Finding("E005", f"unknown palette {name!r}: {path} doesn't exist (palettes: {known})", self.config_path)]
            )
        palette = load_palette_file(path)
        self._palettes[name] = palette
        return palette


def find_project_root(start: Path) -> Path | None:
    """Find the nearest directory at or above `start` containing pagan.toml."""
    start = start.resolve()
    for directory in (start, *start.parents):
        if (directory / CONFIG_NAME).is_file():
            return directory
    return None


def load_project(root: Path) -> Project:
    config_path = root / CONFIG_NAME
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PaganError([Finding("E001", f"cannot read config: {exc.strerror}", config_path)]) from None
    except tomllib.TOMLDecodeError as exc:
        raise PaganError([Finding("E001", f"invalid TOML: {exc}", config_path)]) from None
    return Project(root=root.resolve(), config=parse_config(data, config_path), config_path=config_path)


def discover_project(start: Path | None = None) -> Project:
    """The project containing `start` (default: cwd), or an open-mode project rooted there if none."""
    start = start or Path.cwd()
    root = find_project_root(start)
    if root is None:
        return Project(root=start.resolve(), config=Config(palette_mode="open"), config_path=None)
    return load_project(root)


def parse_config(data: dict[str, Any], path: Path) -> Config:
    findings: list[Finding] = []

    def error(message: str, where: str) -> None:
        findings.append(Finding("E001", message, path, None, where))

    defaults = Config()
    allowed = ("palette_mode", "default_palette", "output_dir", "preview_dir", "export", "style_version", "lint")
    for key in data:
        if key not in allowed:
            error(f"unknown setting {key!r}; allowed: {', '.join(allowed)}", key)

    palette_mode = data.get("palette_mode", defaults.palette_mode)
    if palette_mode not in PALETTE_MODES:
        error(f"palette_mode must be one of {', '.join(PALETTE_MODES)}", "palette_mode")
        palette_mode = defaults.palette_mode

    default_palette = data.get("default_palette")
    if default_palette is not None and (not isinstance(default_palette, str) or not NAME_RE.match(default_palette)):
        error("default_palette must be a palette name (lowercase letters, digits, '_' or '-')", "default_palette")
        default_palette = None

    dirs: dict[str, str] = {}
    for key in ("output_dir", "preview_dir"):
        value = data.get(key, getattr(defaults, key))
        if not isinstance(value, str) or not value:
            error(f"{key} must be a non-empty path", key)
            value = getattr(defaults, key)
        dirs[key] = value

    export = data.get("export", list(defaults.export))
    if not isinstance(export, list) or not all(isinstance(e, str) and e in EXPORTERS for e in export):
        error(f"export must be a list drawn from {', '.join(EXPORTERS)}", "export")
        export = list(defaults.export)

    style_version = data.get("style_version", defaults.style_version)
    if isinstance(style_version, bool) or not isinstance(style_version, int) or style_version < 1:
        error("style_version must be a positive integer", "style_version")
        style_version = defaults.style_version

    lint = _parse_lint(data.get("lint", {}), error)

    if findings:
        raise PaganError(findings)
    return Config(
        palette_mode=palette_mode,
        default_palette=default_palette,
        output_dir=dirs["output_dir"],
        preview_dir=dirs["preview_dir"],
        export=tuple(export),
        style_version=style_version,
        lint=lint,
    )


def _parse_lint(data: Any, error: Callable[[str, str], None]) -> LintConfig:
    defaults = LintConfig()
    if not isinstance(data, dict):
        error("[lint] must be a table", "lint")
        return defaults
    allowed = ("max_ramps_per_sprite", "disable", "require_outline")
    for key in data:
        if key not in allowed:
            error(f"unknown lint setting {key!r}; allowed: {', '.join(allowed)}", f"lint.{key}")

    max_ramps = data.get("max_ramps_per_sprite", defaults.max_ramps_per_sprite)
    if isinstance(max_ramps, bool) or not isinstance(max_ramps, int) or max_ramps < 1:
        error("max_ramps_per_sprite must be a positive integer", "lint.max_ramps_per_sprite")
        max_ramps = defaults.max_ramps_per_sprite

    disable = data.get("disable", [])
    if not isinstance(disable, list) or not all(isinstance(r, str) and re.fullmatch(r"W\d{3}", r) for r in disable):
        error('disable must be a list of warning rule ids, e.g. ["W001"] (errors can\'t be disabled)', "lint.disable")
        disable = []

    require_outline = data.get("require_outline", defaults.require_outline)
    if not isinstance(require_outline, bool):
        error("require_outline must be true or false", "lint.require_outline")
        require_outline = defaults.require_outline

    return LintConfig(max_ramps_per_sprite=max_ramps, disable=tuple(disable), require_outline=require_outline)
