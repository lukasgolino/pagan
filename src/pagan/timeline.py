"""Timeline previews: several sprites composed in time (`scenes/<name>.timeline.yaml`).

A timeline places animated sprites (or 3D models' frames) on a canvas, each with its own start time, alpha,
fades, a straight move and a follow-up animation, and renders the result to frames, a GIF and a contact sheet
of chosen times. It is a preview only: nothing here feeds `pagan build` or the manifest.

Times are exact fractions (decimal inputs are read as written, so `start: 0.1` is 1/10 s), so which
animation frame shows at which time never depends on float rounding.
"""

from __future__ import annotations

import difflib
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from pagan.asset import MAX_SIZE, MODEL_SUFFIX, NAME_RE, SPRITE_SUFFIX, TILESET_SUFFIX, Asset, load_asset
from pagan.findings import Finding
from pagan.preview import PreviewOptions, _labelled_grid, auto_scale, upscale
from pagan.project import Project
from pagan.render import downsample, frame_image, save_png, supersample_factor
from pagan.yamlio import LineMap, YamlError, load_yaml

TIMELINE_SUFFIX = ".timeline.yaml"
RULE = "E016"
MAX_FPS = 120
MAX_FRAMES = 3600  # rendered frames per timeline (2 minutes at 30 fps)
FILE_FIELDS = ("size", "fps", "duration", "layers", "background")
LAYER_FIELDS = ("sprite", "anim", "at", "start", "duration", "alpha", "fade_in", "fade_out", "from", "to", "then", "variant")

RGBA = tuple[int, int, int, int]
ErrorFn = Callable[[str, int | None, str], None]


@dataclass(frozen=True)
class Clip:
    """What a layer plays: an animation's frames with their end times (seconds from the clip's start), or one
    still frame (ends = (None,), never finishes)."""

    name: str
    frames: tuple[str, ...]
    ends: tuple[Fraction, ...]
    loop: bool
    still: bool = False

    @property
    def length(self) -> Fraction:
        return self.ends[-1]

    def frame_at(self, t: Fraction) -> str | None:
        """The frame shown `t` seconds in; None once a one-shot has ended."""
        if self.still:
            return self.frames[0]
        if self.loop:
            t %= self.length
        elif t >= self.length:
            return None
        for frame, end in zip(self.frames, self.ends, strict=True):
            if t < end:
                return frame
        return self.frames[-1]


@dataclass(frozen=True)
class Layer:
    asset: Asset
    clip: Clip
    then: Clip | None
    variant: str | None
    start: Fraction
    end: Fraction | None  # None = shown to the end of the timeline
    alpha: Fraction
    fade_in: Fraction
    fade_out: Fraction
    origin: tuple[int, int]  # `at`, or `from` for a move
    target: tuple[int, int] | None  # `to`
    move: Fraction | None  # how long the move takes
    factor: int  # the asset's supersample: frames are shown as built

    def frame_at(self, local: Fraction) -> str:
        frame = self.clip.frame_at(local)
        if frame is not None:
            return frame
        if self.then is not None:
            then = self.then.frame_at(local - self.clip.length)
            if then is not None:
                return then
            return self.then.frames[-1]
        return self.clip.frames[-1]  # a one-shot holds its last frame

    def position_at(self, local: Fraction) -> tuple[Fraction, Fraction]:
        x, y = self.origin
        if self.target is None or self.move is None:
            return Fraction(x), Fraction(y)
        progress = min(Fraction(1), local / self.move)
        tx, ty = self.target
        return x + (tx - x) * progress, y + (ty - y) * progress

    def opacity_at(self, t: Fraction, local: Fraction, timeline_end: Fraction) -> Fraction:
        k = self.alpha
        if self.fade_in > 0:
            k *= min(Fraction(1), local / self.fade_in)
        if self.fade_out > 0:
            end = self.end if self.end is not None else timeline_end
            k *= max(Fraction(0), min(Fraction(1), (end - t) / self.fade_out))
        return k


@dataclass(frozen=True)
class Timeline:
    name: str
    path: Path
    size: tuple[int, int]
    fps: Fraction
    duration: Fraction
    layers: tuple[Layer, ...]
    background: RGBA | None = None
    _images: dict[tuple[str, str, str | None], tuple[Image.Image, Fraction, Fraction]] = field(
        default_factory=dict, compare=False, repr=False
    )

    @property
    def frame_count(self) -> int:
        return math.ceil(self.duration * self.fps)

    def frame_time(self, index: int) -> Fraction:
        return index / self.fps

    def _sprite(self, layer: Layer, frame: str) -> tuple[Image.Image, Fraction, Fraction]:
        """A frame as built (box-filtered by supersample) and the pivot in its pixels."""
        key = (layer.asset.name, frame, layer.variant)
        if key not in self._images:
            image = downsample(frame_image(layer.asset, frame, layer.variant), layer.factor)
            px, py = layer.asset.pivot
            self._images[key] = (image, Fraction(px, layer.factor), Fraction(py, layer.factor))
        return self._images[key]

    def render(self, t: Fraction) -> Image.Image:
        """The timeline at `t` seconds: layers in list order, alpha-composited, at 1x."""
        canvas = Image.new("RGBA", self.size, self.background or (0, 0, 0, 0))
        for layer in self.layers:
            if t < layer.start or (layer.end is not None and t >= layer.end):
                continue
            local = t - layer.start
            opacity = layer.opacity_at(t, local, self.duration)
            if opacity <= 0:
                continue
            image, px, py = self._sprite(layer, layer.frame_at(local))
            x, y = layer.position_at(local)
            _paste(canvas, _faded(image, opacity), _round(x - px), _round(y - py))
        return canvas


def _round(value: Fraction) -> int:
    """Round half up (the same on every machine, unlike banker's rounding surprises)."""
    return math.floor(value + Fraction(1, 2))


def _faded(image: Image.Image, opacity: Fraction) -> Image.Image:
    if opacity >= 1:
        return image
    table = np.array([_round(a * opacity) for a in range(256)], dtype=np.uint8)
    data = np.asarray(image).copy()
    data[..., 3] = table[data[..., 3]]
    return Image.fromarray(data, "RGBA")


def _paste(canvas: Image.Image, image: Image.Image, x: int, y: int) -> None:
    """Alpha-composite `image` with its top-left at (x, y), clipped to the canvas (x, y may be negative)."""
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + image.width, canvas.width), min(y + image.height, canvas.height)
    if x0 >= x1 or y0 >= y1:
        return
    canvas.alpha_composite(image.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))


# --- loading ----------------------------------------------------------------------------------


def timeline_name(path: Path) -> str | None:
    return path.name[: -len(TIMELINE_SUFFIX)] if path.name.endswith(TIMELINE_SUFFIX) else None


def exact(value: Any) -> Fraction:
    """A YAML number as an exact fraction, read as written (0.1 is 1/10)."""
    return Fraction(value) if isinstance(value, int) else Fraction(repr(value))


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _is_point(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in value)


def find_asset_file(project: Project, name: str) -> Path | None:
    """The source file of the asset called `name` in sprites/, models/ or tiles/ (any depth)."""
    for folder, suffix in (
        (project.sprites_dir, SPRITE_SUFFIX),
        (project.models_dir, MODEL_SUFFIX),
        (project.tiles_dir, TILESET_SUFFIX),
    ):
        direct = folder / f"{name}{suffix}"
        if direct.is_file():
            return direct
        if folder.is_dir():
            found = sorted(folder.rglob(f"{name}{suffix}"))
            if found:
                return found[0]
    return None


def _known_names(project: Project) -> list[str]:
    names: set[str] = set()
    for folder, suffix in ((project.sprites_dir, SPRITE_SUFFIX), (project.models_dir, MODEL_SUFFIX)):
        if folder.is_dir():
            names.update(p.name[: -len(suffix)] for p in folder.rglob(f"*{suffix}"))
    return sorted(names)


def _suggest(name: str, choices: list[str]) -> str:
    close = difflib.get_close_matches(name, choices, n=1)
    listed = ", ".join(choices[:20]) + (", ..." if len(choices) > 20 else "") if choices else "none"
    hint = f"; did you mean {close[0]!r}?" if close else ""
    return f"{hint} (known: {listed})"


class AssetCache:
    """Assets by source path, loaded once. Lint pre-fills it with what it already parsed."""

    def __init__(self, project: Project, loaded: dict[Path, Asset | None] | None = None) -> None:
        self.project = project
        self.loaded: dict[Path, Asset | None] = dict(loaded or {})

    def get(self, path: Path) -> Asset | None:
        key = path.resolve()
        if key not in self.loaded:
            self.loaded[key] = load_asset(path, self.project)[0]
        return self.loaded[key]


def load_timeline(path: Path, project: Project, cache: AssetCache | None = None) -> tuple[Timeline | None, list[Finding]]:
    """Parse and check a timeline; every problem is collected (E016, E001 for YAML)."""
    findings: list[Finding] = []
    cache = cache or AssetCache(project)

    def error(message: str, line: int | None, where: str) -> None:
        findings.append(Finding(RULE, message, path, line, where))

    name = timeline_name(path)
    if name is None or not NAME_RE.match(name):
        return None, [Finding(RULE, f"a timeline file is <name>{TIMELINE_SUFFIX} (lowercase letters, digits, '_' or '-')", path)]
    try:
        data = load_yaml(path)
    except YamlError as exc:
        return None, [Finding("E001", exc.message, path, exc.line)]
    if not isinstance(data, LineMap):
        return None, [Finding(RULE, "a timeline is a mapping: size, fps, duration, layers (optional background)", path, 1)]

    for key in data:
        if key not in FILE_FIELDS:
            error(f"unknown field {key!r}; allowed: {', '.join(FILE_FIELDS)}", data.line_of(key), str(key))
    for key in ("size", "fps", "duration", "layers"):
        if key not in data:
            error(f"missing {key!r} (a timeline needs size: [w, h], fps, duration (seconds) and layers)", data.line, key)

    size: tuple[int, int] | None = None
    raw: Any = data.get("size")
    if "size" in data:
        if _is_point(raw) and all(1 <= v <= MAX_SIZE for v in raw):
            size = (raw[0], raw[1])
        else:
            error(f"size must be [width, height] in whole pixels, 1-{MAX_SIZE}", data.line_of("size"), "size")

    fps: Fraction | None = None
    if "fps" in data:
        raw = data["fps"]
        if _is_number(raw) and 0 < raw <= MAX_FPS:
            fps = exact(raw)
        else:
            error(f"fps must be a number above 0, up to {MAX_FPS}", data.line_of("fps"), "fps")

    duration: Fraction | None = None
    if "duration" in data:
        raw = data["duration"]
        if _is_number(raw) and raw > 0:
            duration = exact(raw)
        else:
            error("duration must be a number of seconds above 0", data.line_of("duration"), "duration")
    if fps is not None and duration is not None and math.ceil(duration * fps) > MAX_FRAMES:
        error(f"duration x fps is {math.ceil(duration * fps)} frames; at most {MAX_FRAMES}: shorten it or lower fps", data.line_of("duration"), "duration")
        duration = None

    background: RGBA | None = None
    if "background" in data:
        raw = data["background"]
        if isinstance(raw, str) and len(raw) == 7 and raw.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in raw[1:]):
            background = (int(raw[1:3], 16), int(raw[3:5], 16), int(raw[5:7], 16), 255)
        else:
            error('background must be "#rrggbb" (quoted: an unquoted # starts a YAML comment)', data.line_of("background"), "background")

    layers: list[Layer] = []
    raw_layers = data.get("layers")
    if "layers" in data:
        if not isinstance(raw_layers, list) or not raw_layers:
            error("layers must be a non-empty list of { sprite, anim, at, ... }", data.line_of("layers"), "layers")
        else:
            known: list[str] | None = None
            for i, spec in enumerate(raw_layers):
                where = f"layers.{i}"
                if not isinstance(spec, LineMap):
                    error("a layer is a mapping: { sprite: NAME, anim: NAME, at: [x, y], ... }", data.line_of("layers"), where)
                    continue
                if known is None and isinstance(spec.get("sprite"), str) and find_asset_file(project, spec["sprite"]) is None:
                    known = _known_names(project)
                layer = _parse_layer(spec, where, project, cache, known or [], error)
                if layer is not None:
                    layers.append(layer)

    if findings or size is None or fps is None or duration is None:
        return None, findings
    return Timeline(name, path, size, fps, duration, tuple(layers), background), findings


def _parse_layer(spec: LineMap, where: str, project: Project, cache: AssetCache, known: list[str], error: ErrorFn) -> Layer | None:
    ok = True

    def bad(message: str, key: str | None = None) -> None:
        nonlocal ok
        ok = False
        error(message, spec.line_of(key) if key is not None else spec.line, f"{where}.{key}" if key else where)

    for key in spec:
        if key not in LAYER_FIELDS:
            bad(f"unknown layer field {key!r}; allowed: {', '.join(LAYER_FIELDS)}", key)

    def time(key: str, default: Fraction | None, positive: bool = False) -> Fraction | None:
        if key not in spec:
            return default
        raw = spec[key]
        if not _is_number(raw) or raw < 0 or (positive and raw == 0):
            bad(f"{key} must be a number of seconds, {'above' if positive else 'at least'} 0", key)
            return default
        return exact(raw)

    start = time("start", Fraction(0))
    duration = time("duration", None, positive=True)
    fade_in = time("fade_in", Fraction(0))
    fade_out = time("fade_out", Fraction(0))
    alpha = Fraction(1)
    if "alpha" in spec:
        if _is_number(spec["alpha"]) and 0 <= spec["alpha"] <= 1:
            alpha = exact(spec["alpha"])
        else:
            bad("alpha must be a number from 0 (invisible) to 1 (opaque)", "alpha")

    points: dict[str, tuple[int, int]] = {}
    for key in ("at", "from", "to"):
        if key in spec:
            if _is_point(spec[key]):
                points[key] = (spec[key][0], spec[key][1])
            else:
                bad(f"{key} must be [x, y] in whole pixels on the timeline canvas (where the sprite's pivot goes)", key)
    moving = "from" in spec or "to" in spec
    if moving:
        if "at" in spec:
            bad("give either at (a fixed place) or from + to (a move), not both", "at")
        if "from" not in spec or "to" not in spec:
            bad("a move needs both from and to (and duration: how long the move takes)", "from" if "from" in spec else "to")
        if "duration" not in spec:
            bad("from/to needs duration: how many seconds the move from `from` to `to` takes", "from")
    elif "at" not in spec:
        bad("missing at: [x, y] (where the sprite's pivot goes), or from + to + duration for a move")

    asset: Asset | None = None
    name = spec.get("sprite")
    if not isinstance(name, str):
        bad("missing sprite: the name of a sprite (or 3D model) in this project", "sprite" if "sprite" in spec else None)
    else:
        path = find_asset_file(project, name)
        if path is None:
            bad(f"unknown sprite {name!r}: no sprites/{name}{SPRITE_SUFFIX} or models/{name}{MODEL_SUFFIX}{_suggest(name, known)}", "sprite")
        elif path.name.endswith(TILESET_SUFFIX):
            bad(f"{name!r} is a tileset; a layer shows a sprite or a 3D model (preview tile layouts with `pagan preview {name} --scene FILE`)", "sprite")
        else:
            asset = cache.get(path)
            if asset is None:
                bad(f"sprite {name!r} has errors; fix them first (`pagan lint {path}`)", "sprite")
            elif asset.mesh_only:
                bad(f"{name!r} is mesh-only (directions: 0): it has no frames to show", "sprite")
                asset = None

    variant: str | None = None
    if "variant" in spec:
        raw = spec["variant"]
        if not isinstance(raw, str):
            bad("variant must be a variant name", "variant")
        elif asset is not None and raw not in asset.variants:
            hint = _suggest(raw, list(asset.variants)).replace("known:", "variants:")
            bad(f"{asset.name} has no variant {raw!r}{hint}", "variant")
        else:
            variant = raw

    clip = then = None
    if "anim" not in spec:
        bad("missing anim: the animation to play (or a frame name, shown still)")
    elif asset is not None:
        clip = _clip(asset, spec["anim"], lambda m: bad(m, "anim"))
    if "then" in spec and asset is not None:
        then = _clip(asset, spec["then"], lambda m: bad(m, "then"))
        if clip is not None and (clip.loop or clip.still):
            bad(f"then plays after a one-shot animation ends, but {clip.name!r} never ends ({'a still frame' if clip.still else 'loop: true'})", "then")

    if not ok or asset is None or clip is None or start is None or fade_in is None or fade_out is None:
        return None
    end = start + duration if duration is not None and not moving else None
    return Layer(
        asset=asset,
        clip=clip,
        then=then,
        variant=variant,
        start=start,
        end=end,
        alpha=alpha,
        fade_in=fade_in,
        fade_out=fade_out,
        origin=points["from"] if moving else points["at"],
        target=points["to"] if moving else None,
        move=duration if moving else None,
        factor=supersample_factor(asset, project),
    )


def _clip(asset: Asset, name: Any, bad: Callable[[str], None]) -> Clip | None:
    """An animation of the asset by name, else one of its frames (shown still)."""
    if not isinstance(name, str):
        bad("must be an animation (or frame) name")
        return None
    anim = asset.animations.get(name)
    if anim is not None:
        fps = exact(anim.fps)
        steps = [exact(d) for d in anim.durations] if anim.durations else [Fraction(1)] * len(anim.frames)
        ends, total = [], Fraction(0)
        for step in steps:
            total += step / fps
            ends.append(total)
        return Clip(name, anim.frames, tuple(ends), anim.loop)
    if name in asset.frames:
        return Clip(name, (name,), (Fraction(0),), loop=False, still=True)
    choices = list(asset.animations) or list(asset.frames)
    what = "animations" if asset.animations else "frames"
    close = difflib.get_close_matches(name, [*asset.animations, *asset.frames], n=1)
    hint = f"; did you mean {close[0]!r}?" if close else ""
    bad(f"{asset.name} has no animation or frame {name!r}{hint} ({what}: {', '.join(choices[:20])}{', ...' if len(choices) > 20 else ''})")
    return None


# --- previews ---------------------------------------------------------------------------------


def parse_times(text: str) -> list[Fraction]:
    """`--at 0.5,2.0` -> exact times. ValueError with a message on bad input."""
    times: list[Fraction] = []
    for part in text.split(","):
        part = part.strip()
        try:
            value = Fraction(part)
        except (ValueError, ZeroDivisionError):
            raise ValueError(f"--at: {part!r} isn't a time in seconds (e.g. --at 0.5,2.0)") from None
        if value < 0:
            raise ValueError(f"--at: {part} is negative")
        times.append(value)
    return times


def gif_durations(fps: Fraction, count: int) -> list[int]:
    """Milliseconds per frame on GIF's 10 ms clock, rounded from the exact frame times so the total doesn't drift
    (at most 50 fps: browsers slow down faster GIFs)."""
    ticks = [_round(i * 100 / fps) * 10 for i in range(count + 1)]
    return [max(20, b - a) for a, b in zip(ticks, ticks[1:], strict=False)]


@dataclass
class TimelinePreview:
    name: str
    folder: Path
    frames: list[Path]
    gif: Path
    scale: int
    at: Path | None = None


def write_timeline_previews(timeline: Timeline, out_dir: Path, options: PreviewOptions, at: list[Fraction] | None = None) -> TimelinePreview:
    """<out_dir>/<name>.timeline/: frames/f0000.png..., timeline.gif and, for `at` times, at.png (a contact
    sheet). The folder name has a dot, which asset names can't, so it never meets an asset's previews."""
    folder = out_dir / f"{timeline.name}.timeline"
    scale = options.scale or auto_scale(timeline.size)
    frames_dir = folder / "frames"
    for stale in sorted(frames_dir.glob("f*.png")) if frames_dir.is_dir() else []:
        stale.unlink()  # a shorter timeline mustn't leave old frames behind
    # GIFs only have 1-bit alpha, so they always get an opaque background.
    opaque = PreviewOptions(scale=scale, grid=options.grid, background="checker" if options.background == "none" else options.background)
    frames: list[Path] = []
    gif_frames: list[Image.Image] = []
    for i in range(timeline.frame_count):
        image = timeline.render(timeline.frame_time(i))
        path = frames_dir / f"f{i:04d}.png"
        save_png(upscale(image, scale, options), path)
        frames.append(path)
        gif_frames.append(upscale(image, scale, opaque).convert("RGB"))
    gif = folder / "timeline.gif"
    gif_frames[0].save(gif, save_all=True, append_images=gif_frames[1:], duration=gif_durations(timeline.fps, len(gif_frames)), loop=0, disposal=1)
    result = TimelinePreview(timeline.name, folder, frames, gif, scale)
    if at:
        cells = [(f"{float(t):g}s", upscale(timeline.render(t), scale, options)) for t in at]
        w, h = timeline.size
        title = f"{timeline.name}  {w}x{h}  x{scale}"
        subtitle = f"{float(timeline.duration):g}s @ {float(timeline.fps):g}fps, {len(timeline.layers)} layers"
        result.at = folder / "at.png"
        save_png(_labelled_grid(title, subtitle, [("", cells)]), result.at)
    return result
