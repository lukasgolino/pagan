"""PAGAN projects: a directory with a pagan.toml plus palettes/, sprites/ and tiles/."""

from __future__ import annotations

import math
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pagan.findings import Finding, PaganError
from pagan.palette import NAME_RE, PALETTE_SUFFIX, Palette, load_palette_file
from pagan.voxel import Camera, Light

CONFIG_NAME = "pagan.toml"
PALETTE_MODES = ("strict", "open")
EXPORTERS = ("png", "godot", "normals")

PaletteMode = Literal["strict", "open"]


@dataclass(frozen=True)
class LintConfig:
    max_ramps_per_sprite: int = 3
    max_frame_change: float = 0.4  # W007: share of pixels that may change between animation frames
    max_ramp_steps: int = 0  # W008: most keys an asset may use from one ramp (0 = no limit)
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
    camera: Camera = field(default_factory=Camera)
    light: Light = field(default_factory=Light)


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
    def models_dir(self) -> Path:
        return self.root / "models"

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
    except UnicodeDecodeError:
        raise PaganError([Finding("E001", "config is not valid UTF-8 text", config_path)]) from None
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
    allowed = (
        "palette_mode", "default_palette", "output_dir", "preview_dir", "export", "style_version", "lint", "camera", "light",
    )  # fmt: skip
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
    camera, light = _parse_render(data.get("camera", {}), data.get("light", {}), error)

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
        camera=camera,
        light=light,
    )


def _parse_lint(data: Any, error: Callable[[str, str], None]) -> LintConfig:
    defaults = LintConfig()
    if not isinstance(data, dict):
        error("[lint] must be a table", "lint")
        return defaults
    allowed = ("max_ramps_per_sprite", "max_frame_change", "max_ramp_steps", "disable", "require_outline")
    for key in data:
        if key not in allowed:
            error(f"unknown lint setting {key!r}; allowed: {', '.join(allowed)}", f"lint.{key}")

    max_ramps = data.get("max_ramps_per_sprite", defaults.max_ramps_per_sprite)
    if isinstance(max_ramps, bool) or not isinstance(max_ramps, int) or max_ramps < 1:
        error("max_ramps_per_sprite must be a positive integer", "lint.max_ramps_per_sprite")
        max_ramps = defaults.max_ramps_per_sprite

    max_change = data.get("max_frame_change", defaults.max_frame_change)
    if isinstance(max_change, bool) or not isinstance(max_change, int | float) or not 0 < max_change <= 1:
        error("max_frame_change must be a number between 0 and 1", "lint.max_frame_change")
        max_change = defaults.max_frame_change

    max_steps = data.get("max_ramp_steps", defaults.max_ramp_steps)
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 0:
        error("max_ramp_steps must be 0 (no limit) or a positive integer", "lint.max_ramp_steps")
        max_steps = defaults.max_ramp_steps

    disable = data.get("disable", [])
    if not isinstance(disable, list) or not all(isinstance(r, str) and re.fullmatch(r"W\d{3}", r) for r in disable):
        error('disable must be a list of warning rule ids, e.g. ["W001"] (errors can\'t be disabled)', "lint.disable")
        disable = []

    require_outline = data.get("require_outline", defaults.require_outline)
    if not isinstance(require_outline, bool):
        error("require_outline must be true or false", "lint.require_outline")
        require_outline = defaults.require_outline

    return LintConfig(
        max_ramps_per_sprite=max_ramps,
        max_frame_change=float(max_change),
        max_ramp_steps=max_steps,
        disable=tuple(disable),
        require_outline=require_outline,
    )


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _parse_render(camera_raw: Any, light_raw: Any, error: Callable[[str, str], None]) -> tuple[Camera, Light]:
    camera, light = Camera(), Light()
    if not isinstance(camera_raw, dict):
        error("[camera] must be a table", "camera")
    else:
        for key in camera_raw:
            if key not in ("elevation", "scale"):
                error(f"unknown camera setting {key!r}; allowed: elevation, scale", f"camera.{key}")
        elevation = camera_raw.get("elevation", camera.elevation)
        scale = camera_raw.get("scale", camera.scale)
        if not (_number(elevation) and 10 <= elevation <= 90):
            error("camera.elevation must be 10-90 degrees above the horizon (90 = straight down)", "camera.elevation")
        elif not (_number(scale) and 0.25 <= scale <= 16):
            error("camera.scale must be 0.25-16 pixels per voxel", "camera.scale")
        else:
            camera = Camera(float(elevation), float(scale))
    if not isinstance(light_raw, dict):
        error("[light] must be a table", "light")
    else:
        allowed = ("direction", "ambient", "shadows", "shadow_strength", "wrap", "baked")
        for key in light_raw:
            if key not in allowed:
                error(f"unknown light setting {key!r}; allowed: {', '.join(allowed)}", f"light.{key}")
        direction = light_raw.get("direction", list(light.direction))
        ambient = light_raw.get("ambient", light.ambient)
        shadows = light_raw.get("shadows", light.shadows)
        strength = light_raw.get("shadow_strength", light.shadow_strength)
        wrap = light_raw.get("wrap", light.wrap)
        baked = light_raw.get("baked", light.baked)
        if not (isinstance(direction, list) and len(direction) == 3 and all(_number(v) for v in direction) and any(direction)):
            error("light.direction must be [x, y, z] pointing towards the light (x right, y up-screen, z up)", "light.direction")
        elif not (_number(ambient) and 0 <= ambient < 1):
            error("light.ambient must be between 0 and 1", "light.ambient")
        elif not isinstance(shadows, bool):
            error("light.shadows must be true or false", "light.shadows")
        elif not (_number(strength) and 0 <= strength <= 1):
            error("light.shadow_strength must be between 0 and 1", "light.shadow_strength")
        elif not (_number(wrap) and 0 <= wrap <= 1):
            error("light.wrap must be between 0 and 1", "light.wrap")
        elif not isinstance(baked, bool):
            error("light.baked must be true or false", "light.baked")
        else:
            light = Light(
                direction=(float(direction[0]), float(direction[1]), float(direction[2])),
                ambient=float(ambient),
                shadows=shadows,
                wrap=float(wrap),
                baked=baked,
                shadow_strength=float(strength),
            )
    return camera, light
