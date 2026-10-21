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
EXPORTERS = ("png", "godot", "normals", "mesh")
MESH_SHADINGS = ("ramp", "baked", "flat")
GODOT_FILTERS = ("inherit", "nearest", "linear")
MAX_SUPERSAMPLE = 8

PaletteMode = Literal["strict", "open"]


@dataclass(frozen=True)
class LintConfig:
    max_ramps_per_sprite: int = 3
    max_ramps_per_model: int = 6  # models mix more materials (hull, sails, team colours...)
    max_frame_change: float = 0.4  # W007: share of pixels that may change between animation frames
    max_ramp_steps: int = 0  # W008: most keys an asset may use from one ramp (0 = no limit)
    disable: tuple[str, ...] = ()
    require_outline: bool = False
    require_opaque: bool = False  # E015: no translucent ("#rrggbbaa") colours in sprites and tilesets


@dataclass(frozen=True)
class GodotConfig:
    mipmaps: bool = False  # written into each PNG's .import (mipmaps/generate)
    filter: str = "inherit"  # SpriteFrames texture filter: inherit (the node/project decides), nearest, linear


@dataclass(frozen=True)
class MeshConfig:
    """`[mesh]`: how 3D models export as meshes (`export` has "mesh")."""

    voxel_size: float = 0.0625  # metres per voxel (16 voxels per metre), chosen per game
    shading: str = "ramp"  # ramp: palette-locked engine lighting (shader); baked: steps baked per face; flat: middle step
    collision_suffixes: bool = False  # name collision parts with Godot's -col / -convcol / -colonly suffixes


@dataclass(frozen=True)
class Config:
    palette_mode: PaletteMode = "strict"
    default_palette: str | None = None
    output_dir: str = "build"
    preview_dir: str = "previews"
    export: tuple[str, ...] = ("png",)
    style_version: int = 1
    variant_sheets: bool = True  # False: variants are only swap tables in the manifest (recolour in a shader)
    supersample: int = 1  # sources are authored at N x the output size; build box-filters them down
    lint: LintConfig = field(default_factory=LintConfig)
    camera: Camera = field(default_factory=Camera)
    light: Light = field(default_factory=Light)
    godot: GodotConfig = field(default_factory=GodotConfig)
    mesh: MeshConfig = field(default_factory=MeshConfig)


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
        "palette_mode", "default_palette", "output_dir", "preview_dir", "export", "style_version", "variant_sheets",
        "supersample", "lint", "camera", "light", "godot", "mesh",
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

    variant_sheets = data.get("variant_sheets", defaults.variant_sheets)
    if not isinstance(variant_sheets, bool):
        error("variant_sheets must be true or false", "variant_sheets")
        variant_sheets = defaults.variant_sheets

    supersample = data.get("supersample", defaults.supersample)
    if isinstance(supersample, bool) or not isinstance(supersample, int) or not 1 <= supersample <= MAX_SUPERSAMPLE:
        error(f"supersample must be a whole number 1-{MAX_SUPERSAMPLE} (1 = off)", "supersample")
        supersample = defaults.supersample

    godot = _parse_godot(data.get("godot", {}), error)
    mesh = _parse_mesh(data.get("mesh", {}), error)
    lint = _parse_lint(data.get("lint", {}), error)
    camera, light = parse_render(data.get("camera", {}), data.get("light", {}), error)

    if findings:
        raise PaganError(findings)
    return Config(
        palette_mode=palette_mode,
        default_palette=default_palette,
        output_dir=dirs["output_dir"],
        preview_dir=dirs["preview_dir"],
        export=tuple(export),
        style_version=style_version,
        variant_sheets=variant_sheets,
        supersample=supersample,
        lint=lint,
        camera=camera,
        light=light,
        godot=godot,
        mesh=mesh,
    )


MIN_VOXEL_SIZE, MAX_VOXEL_SIZE = 0.001, 10.0


def valid_voxel_size(value: Any) -> bool:
    return _number(value) and MIN_VOXEL_SIZE <= value <= MAX_VOXEL_SIZE


def _parse_mesh(data: Any, error: Callable[[str, str], None]) -> MeshConfig:
    defaults = MeshConfig()
    if not isinstance(data, dict):
        error("[mesh] must be a table", "mesh")
        return defaults
    allowed = ("voxel_size", "shading", "collision_suffixes")
    for key in data:
        if key not in allowed:
            error(f"unknown mesh setting {key!r}; allowed: {', '.join(allowed)}", f"mesh.{key}")
    voxel_size = data.get("voxel_size", defaults.voxel_size)
    if not valid_voxel_size(voxel_size):
        error(f"mesh.voxel_size must be metres per voxel, {MIN_VOXEL_SIZE}-{MAX_VOXEL_SIZE} (0.0625 = 16 voxels per metre)", "mesh.voxel_size")
        voxel_size = defaults.voxel_size
    shading = data.get("shading", defaults.shading)
    if shading not in MESH_SHADINGS:
        error(f"mesh.shading must be one of {', '.join(MESH_SHADINGS)}", "mesh.shading")
        shading = defaults.shading
    suffixes = data.get("collision_suffixes", defaults.collision_suffixes)
    if not isinstance(suffixes, bool):
        error("mesh.collision_suffixes must be true or false", "mesh.collision_suffixes")
        suffixes = defaults.collision_suffixes
    return MeshConfig(voxel_size=float(voxel_size), shading=shading, collision_suffixes=suffixes)


def _parse_godot(data: Any, error: Callable[[str, str], None]) -> GodotConfig:
    defaults = GodotConfig()
    if not isinstance(data, dict):
        error("[godot] must be a table", "godot")
        return defaults
    for key in data:
        if key not in ("mipmaps", "filter"):
            error(f"unknown godot setting {key!r}; allowed: mipmaps, filter", f"godot.{key}")
    mipmaps = data.get("mipmaps", defaults.mipmaps)
    if not isinstance(mipmaps, bool):
        error("godot.mipmaps must be true or false", "godot.mipmaps")
        mipmaps = defaults.mipmaps
    texture_filter = data.get("filter", defaults.filter)
    if texture_filter not in GODOT_FILTERS:
        error(f"godot.filter must be one of {', '.join(GODOT_FILTERS)}", "godot.filter")
        texture_filter = defaults.filter
    return GodotConfig(mipmaps=mipmaps, filter=texture_filter)


def _parse_lint(data: Any, error: Callable[[str, str], None]) -> LintConfig:
    defaults = LintConfig()
    if not isinstance(data, dict):
        error("[lint] must be a table", "lint")
        return defaults
    allowed = ("max_ramps_per_sprite", "max_ramps_per_model", "max_frame_change", "max_ramp_steps", "disable", "require_outline", "require_opaque")
    for key in data:
        if key not in allowed:
            error(f"unknown lint setting {key!r}; allowed: {', '.join(allowed)}", f"lint.{key}")

    max_ramps = data.get("max_ramps_per_sprite", defaults.max_ramps_per_sprite)
    if isinstance(max_ramps, bool) or not isinstance(max_ramps, int) or max_ramps < 1:
        error("max_ramps_per_sprite must be a positive integer", "lint.max_ramps_per_sprite")
        max_ramps = defaults.max_ramps_per_sprite

    max_model_ramps = data.get("max_ramps_per_model", defaults.max_ramps_per_model)
    if isinstance(max_model_ramps, bool) or not isinstance(max_model_ramps, int) or max_model_ramps < 1:
        error("max_ramps_per_model must be a positive integer", "lint.max_ramps_per_model")
        max_model_ramps = defaults.max_ramps_per_model

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

    require_opaque = data.get("require_opaque", defaults.require_opaque)
    if not isinstance(require_opaque, bool):
        error("require_opaque must be true or false", "lint.require_opaque")
        require_opaque = defaults.require_opaque

    return LintConfig(
        max_ramps_per_sprite=max_ramps,
        max_ramps_per_model=max_model_ramps,
        max_frame_change=float(max_change),
        max_ramp_steps=max_steps,
        disable=tuple(disable),
        require_outline=require_outline,
        require_opaque=require_opaque,
    )


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def parse_render(
    camera_raw: Any,
    light_raw: Any,
    error: Callable[[str, str], None],
    base_camera: Camera | None = None,
    base_light: Light | None = None,
) -> tuple[Camera, Light]:
    """Parse [camera]/[light] tables. Missing keys keep the base values (defaults, or the project's
    settings when a model overrides some of them)."""
    camera, light = base_camera or Camera(), base_light or Light()
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
