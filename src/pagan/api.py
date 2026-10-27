"""`pagan.api`: the stable Python API for generator scripts.

Generators (effects, terrain sets, ship families) should build on this module instead of copying PAGAN
internals: the geometry here *is* what the primitives use, so a script can't drift from the renderer.
Everything in `__all__` is covered by PAGAN's versioning rules (CHANGELOG.md): a change to it is a
version bump, and `API_VERSION` goes up when something here changes incompatibly.

    from pagan import api

    c = api.Canvas(16, 16)
    c.ellipse(8, 8, 6, 5, lambda dx, dy: api.ramp_pick("rstuv", api.sphere_light(dx, dy)))
    c.fade(0.3, seed=2)
    api.write("sprites/puff.sprite.yaml", api.sprite_yaml("puff", (16, 16), {"a": c}))
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFont

from pagan.asset import Asset, font_glyphs, glyph_advance, load_asset_or_raise
from pagan.lint import _orphans
from pagan.model import SailCell, _Builder, hull_reach, sail_cells
from pagan.palette import TRANSPARENT, Palette
from pagan.project import Project, discover_project
from pagan.render import frame_image
from pagan.voxel import Cell, Material, VoxelModel, heading_angles

API_VERSION = 2  # 2: ellipse/ring exclude pixel centres exactly on the edge

__all__ = [
    "API_VERSION",
    "Canvas",
    "SailCell",
    "bevel",
    "compose",
    "corner_tiles",
    "directional_frames",
    "distance_field",
    "dither",
    "hash01",
    "hull_reach",
    "light_2d",
    "load",
    "open_project",
    "palette",
    "periodic_noise",
    "polygon_distance",
    "ramp_pick",
    "rotate_points",
    "sail_cells",
    "shape_cells",
    "smoothstep",
    "sphere_light",
    "sprite_yaml",
    "text_mask",
    "TextMask",
    "tileset_yaml",
    "write",
]

Key = str | Callable[[float, float], str | None]  # a palette key, or (dx, dy) -> key/None per pixel
EdgeKey = str | Callable[[float], str | None]  # a palette key, or distance-to-edge -> key/None per pixel
Point = tuple[float, float]


# --- projects and assets ------------------------------------------------------------------------


def open_project(path: str | Path = ".") -> Project:
    """The PAGAN project containing `path` (open mode rooted there if there's no pagan.toml)."""
    return discover_project(Path(path))


def load(path: str | Path, project: Project | None = None) -> Asset:
    """Parse a sprite, tileset or model file into its final frames (raises PaganError on errors)."""
    path = Path(path)
    return load_asset_or_raise(path, project or open_project(path.parent))


def palette(name: str, project: Project) -> Palette:
    """A palette by name: `.colors[key].hex`, `.ramps[name]` (keys dark -> light)."""
    return project.load_palette(name)


# --- 2D drawing --------------------------------------------------------------------------------


class Canvas:
    """A grid of palette keys ("." = transparent) with the shapes effects and props are made of.

    Coordinates are pixels, x right, y down; shape centres may be fractional (8.0 = between pixels 7 and 8).
    Drawing outside the canvas is clipped.
    """

    def __init__(self, width: int, height: int, fill: str = TRANSPARENT) -> None:
        self.width, self.height = width, height
        self.pixels = [[fill] * width for _ in range(height)]

    @classmethod
    def from_rows(cls, rows: Sequence[str] | str) -> Canvas:
        lines = rows.strip("\n").split("\n") if isinstance(rows, str) else list(rows)
        canvas = cls(max((len(r) for r in lines), default=0), len(lines))
        for y, row in enumerate(lines):
            for x, key in enumerate(row):
                canvas.pixels[y][x] = key
        return canvas

    @classmethod
    def from_array(cls, array: Any, keys: Sequence[str] | str | None = None) -> Canvas:
        """A canvas from a 2D numpy array (rows = y): of palette keys ("." = transparent), or of integers that
        index `keys` (negative = transparent), e.g. `Canvas.from_array(np.digitize(shade, bins) - 1, "rstuv")`."""
        data = np.asarray(array)
        if data.ndim != 2:
            raise ValueError(f"from_array needs a 2D array (height x width), got shape {data.shape}")
        if keys is not None:
            if not np.issubdtype(data.dtype, np.integer):
                raise ValueError("with keys, the array holds integer indexes into keys")
            if data.size and data.max() >= len(keys):
                raise ValueError(f"index {int(data.max())} is out of range for {len(keys)} keys")
            lookup = np.array([*keys, TRANSPARENT])
            data = lookup[np.where(data < 0, len(keys), data)]
        canvas = cls(data.shape[1], data.shape[0])
        canvas.pixels = [[str(k) for k in row] for row in data.tolist()]
        return canvas

    def to_array(self) -> Any:
        """The pixels as a 2D numpy array of keys (dtype '<U1'; "." = transparent)."""
        return np.array(self.pixels, dtype="<U1").reshape(self.height, self.width)

    def mask(self) -> Any:
        """A boolean 2D array: True where a pixel is opaque (for `distance_field` and `bevel`)."""
        return self.to_array() != TRANSPARENT

    def text(self, font: Asset, text: str, x: int, y: int, scale: int = 1, key: str | None = None) -> Canvas:
        """Write `text` with a project font sprite (`font:`), its top-left at (x, y), each glyph pixel `scale` x
        `scale`; advances and offsets as in the build's font metrics. `key` paints every glyph pixel one key (else
        the font's)."""
        if font.font is None:
            raise ValueError(f"{font.name!r} isn't a font sprite (it has no font: section)")
        metrics = font.font
        glyphs = {char: grid for char, _, _, grid in font_glyphs(metrics, font.frames, font.size)}
        pen = x
        for char in text:
            grid = glyphs.get(char)
            if grid is None:
                raise ValueError(f"font {font.name!r} has no glyph for {char!r}")
            ox, oy = metrics.offsets.get(char, (0, 0))
            left, top = pen + ox * scale, y + oy * scale
            for gy, row in enumerate(grid):
                for gx, value in enumerate(row):
                    if value != TRANSPARENT:
                        self.rect(left + gx * scale, top + gy * scale, left + gx * scale + scale - 1, top + gy * scale + scale - 1, key or value)
            pen += glyph_advance(metrics, char, grid) * scale
        return self

    def copy(self) -> Canvas:
        return Canvas.from_rows(self.rows())

    def rows(self) -> list[str]:
        return ["".join(row) for row in self.pixels]

    def get(self, x: int, y: int) -> str:
        return self.pixels[y][x] if 0 <= x < self.width and 0 <= y < self.height else TRANSPARENT

    def put(self, x: float, y: float, key: str) -> None:
        """Set the pixel containing point (x, y)."""
        ix, iy = math.floor(x), math.floor(y)
        if 0 <= ix < self.width and 0 <= iy < self.height:
            self.pixels[iy][ix] = key

    def _paint(self, x: int, y: int, key: Key, dx: float, dy: float) -> None:
        value = key(dx, dy) if callable(key) else key
        if value is not None:
            self.put(x, y, value)

    def rect(self, x0: int, y0: int, x1: int, y1: int, key: Key) -> Canvas:
        """Fill pixels x0..x1, y0..y1 (inclusive). A callable key gets (dx, dy) in -1..1 across the box."""
        for y in range(min(y0, y1), max(y0, y1) + 1):
            for x in range(min(x0, x1), max(x0, x1) + 1):
                dx = (x + 0.5 - (x0 + x1 + 1) / 2) / max(1, abs(x1 - x0) + 1) * 2
                dy = (y + 0.5 - (y0 + y1 + 1) / 2) / max(1, abs(y1 - y0) + 1) * 2
                self._paint(x, y, key, dx, dy)
        return self

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, key: Key) -> Canvas:
        """Fill pixels whose centres lie strictly inside the ellipse (a centre exactly on the edge, as with
        radius 15.5 around 16, would stick out as a 1px nub). A callable key gets the pixel's offset from
        the centre in radii (dx, dy in -1..1), e.g. for sphere shading with `sphere_light`."""
        for y in range(math.floor(cy - ry), math.ceil(cy + ry) + 1):
            for x in range(math.floor(cx - rx), math.ceil(cx + rx) + 1):
                dx, dy = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
                if dx * dx + dy * dy < 1 - 1e-9:
                    self._paint(x, y, key, dx, dy)
        return self

    def circle(self, cx: float, cy: float, r: float, key: Key) -> Canvas:
        return self.ellipse(cx, cy, r, r, key)

    def ring(self, cx: float, cy: float, rx: float, ry: float, thickness: float, key: Key) -> Canvas:
        """An elliptical band `thickness` pixels wide, inside the ellipse's edge (shock waves, ripples)."""
        inner_x, inner_y = max(0.0, rx - thickness), max(0.0, ry - thickness)
        for y in range(math.floor(cy - ry), math.ceil(cy + ry) + 1):
            for x in range(math.floor(cx - rx), math.ceil(cx + rx) + 1):
                dx, dy = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
                if dx * dx + dy * dy >= 1 - 1e-9:
                    continue
                if inner_x > 0 and inner_y > 0:
                    ix, iy = (x + 0.5 - cx) / inner_x, (y + 0.5 - cy) / inner_y
                    if ix * ix + iy * iy < 1 - 1e-9:
                        continue
                self._paint(x, y, key, dx, dy)
        return self

    def line(self, x0: float, y0: float, x1: float, y1: float, key: str, width: float = 1) -> Canvas:
        """A line between two points (pixel centres: pass 3.5 for the middle of pixel 3). Width 1 steps
        pixel by pixel; a wider line fills every pixel whose centre is within width/2 of the segment
        (round ends), e.g. for thick strokes and laser beams."""
        if width <= 1:
            steps = max(1, math.ceil(max(abs(x1 - x0), abs(y1 - y0))))
            for i in range(steps + 1):
                t = i / steps
                self.put(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, key)
            return self
        half = width / 2
        for y in range(math.floor(min(y0, y1) - half), math.ceil(max(y0, y1) + half) + 1):
            for x in range(math.floor(min(x0, x1) - half), math.ceil(max(x0, x1) + half) + 1):
                if _segment_distance(x + 0.5, y + 0.5, (x0, y0), (x1, y1)) < half - 1e-9:
                    self.put(x, y, key)
        return self

    def polygon(self, points: Sequence[Point], key: EdgeKey) -> Canvas:
        """Fill pixels whose centres lie inside the polygon (even-odd rule; points in order, either winding).
        A callable key gets the pixel centre's distance to the nearest edge in pixels (0 at the outline,
        growing inwards), so rims, bevels and inner glows are one function:
        `c.polygon(ship, lambda d: "rim" if d < 2 else "fill")`."""
        if len(points) < 3:
            raise ValueError("a polygon needs at least 3 points")
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        for y in range(math.floor(min(ys)), math.ceil(max(ys)) + 1):
            for x in range(math.floor(min(xs)), math.ceil(max(xs)) + 1):
                depth = polygon_distance(points, x + 0.5, y + 0.5)
                if depth > 1e-9:
                    value = key(depth) if callable(key) else key
                    if value is not None:
                        self.put(x, y, value)
        return self

    def triangle(self, a: Point, b: Point, c: Point, key: EdgeKey) -> Canvas:
        """A filled triangle; see `polygon`."""
        return self.polygon([a, b, c], key)

    def blit(self, other: Canvas, x: int, y: int) -> Canvas:
        """Draw `other` with its top-left at (x, y); its transparent pixels leave this canvas alone."""
        for oy, row in enumerate(other.pixels):
            for ox, key in enumerate(row):
                if key != TRANSPARENT:
                    self.put(x + ox, y + oy, key)
        return self

    def flip(self, how: str = "horizontal") -> Canvas:
        if how in ("horizontal", "both"):
            self.pixels = [row[::-1] for row in self.pixels]
        if how in ("vertical", "both"):
            self.pixels = self.pixels[::-1]
        return self

    def opaque(self) -> list[tuple[int, int]]:
        return [(x, y) for y, row in enumerate(self.pixels) for x, k in enumerate(row) if k != TRANSPARENT]

    def fade(self, amount: float, seed: int = 0, noise: float = 0.55) -> Canvas:
        """Remove `amount` (0..1) of the opaque pixels, outermost first, broken up by noise so the edge
        dissolves rather than shrinking (smoke and flashes fading out). `noise` = 0 removes strictly by distance."""
        points = self.opaque()
        count = int(len(points) * max(0.0, min(1.0, amount)))
        if not count:
            return self
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        reach = max(math.hypot(x - cx, y - cy) for x, y in points) or 1.0
        score = {p: noise * hash01(p[0], p[1], seed) + (1 - noise) * math.hypot(p[0] - cx, p[1] - cy) / reach for p in points}
        for x, y in sorted(points, key=lambda p: (-score[p], p))[:count]:
            self.pixels[y][x] = TRANSPARENT
        return self

    def scatter(
        self, count: int, key: str, seed: int = 0, box: tuple[int, int, int, int] | None = None, size: int = 1
    ) -> Canvas:
        """`count` particles of `size`x`size` pixels at hashed (repeatable) spots inside box (x0, y0, x1, y1)."""
        x0, y0, x1, y1 = box or (0, 0, self.width - 1, self.height - 1)
        for i in range(count):
            x = x0 + math.floor(hash01(i, 1, seed) * (x1 - x0 + 1))
            y = y0 + math.floor(hash01(i, 2, seed) * (y1 - y0 + 1))
            self.rect(x, y, x + size - 1, y + size - 1, key)
        return self

    def orphans(self) -> list[tuple[int, int]]:
        """Pixels `pagan lint` reports as W001 (opaque, no opaque neighbour in 8 directions)."""
        return _orphans(tuple(self.rows()))

    def remove_orphans(self) -> Canvas:
        for x, y in self.orphans():
            self.pixels[y][x] = TRANSPARENT
        return self

    def pair_orphans(self) -> Canvas:
        """Give each lone pixel a partner (below, right, above or left), so specks read as 2px bits."""
        for x, y in self.orphans():
            for nx, ny in ((x, y + 1), (x + 1, y), (x, y - 1), (x - 1, y)):
                if 0 <= nx < self.width and 0 <= ny < self.height:
                    self.pixels[ny][nx] = self.pixels[y][x]
                    break
        return self


# --- geometry ---------------------------------------------------------------------------------


def _segment_distance(px: float, py: float, a: Point, b: Point) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def polygon_distance(points: Sequence[Point], x: float, y: float) -> float:
    """Signed distance from (x, y) to the polygon's outline: positive inside, negative outside (even-odd
    rule). Pixel centres are (x + 0.5, y + 0.5). This is what `Canvas.polygon` fills and passes to its key."""
    inside = False
    nearest = math.inf
    for i, a in enumerate(points):
        b = points[i - 1]
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
            inside = not inside
        nearest = min(nearest, _segment_distance(x, y, a, b))
    return nearest if inside else -nearest


# --- 2D headings ------------------------------------------------------------------------------


def rotate_points(points: Sequence[Point], degrees: float, about: Point) -> list[Point]:
    """Turn a shape drawn facing east (right) to face heading `degrees`, counter-clockwise on screen (y down):
    0 = east, 90 = north (up), like model headings. Rounded to 12 decimals, so output is the same everywhere."""
    angle = math.radians(degrees)
    cos, sin = round(math.cos(angle), 12), round(math.sin(angle), 12)
    cx, cy = about
    return [
        (round(cx + (x - cx) * cos + (y - cy) * sin, 12), round(cy - (x - cx) * sin + (y - cy) * cos, 12))
        for x, y in points
    ]


def directional_frames(
    draw: Callable[[Canvas, float], None], size: tuple[int, int], directions: int = 8, heading: float = 0.0
) -> dict[str, Canvas]:
    """One frame per heading for a 2D (vector-drawn) sprite, named like model headings (e, ne, n, ...; h00-h31
    for 32), so 2D and 3D assets share frame names. `draw(canvas, angle)` paints the shape turned to `angle`
    degrees, usually through `rotate_points`:

        def gull(c, angle):
            c.polygon(api.rotate_points(WING, angle, (6, 6)), "w")
        frames = api.directional_frames(gull, (12, 12), 8)   # {"e": Canvas, "ne": ..., ...}
    """
    if directions not in (1, 4, 8, 16, 32):
        raise ValueError("directions must be 1, 4, 8, 16 or 32")
    frames: dict[str, Canvas] = {}
    for name, angle in heading_angles(directions, heading):
        canvas = Canvas(*size)
        draw(canvas, angle)
        frames[name] = canvas
    return frames


# --- noise and shading ------------------------------------------------------------------------


def hash01(x: int, y: int, seed: int = 0) -> float:
    """A repeatable pseudo-random number in 0..1 for integer (x, y, seed). Same on every machine."""
    n = (x * 374761393 + y * 668265263 + seed * 982451653) & 0xFFFFFFFF
    n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
    return (n & 0xFFFF) / 65535


def periodic_noise(x: float, y: float, period: float, seed: int = 0) -> float:
    """Smooth noise in about -1..1 that repeats every `period` pixels in x and y: tiles stay seamless."""
    k = 2 * math.pi / period
    s = seed * 1.7
    return (
        0.5 * math.sin(k * x + s) * math.cos(k * y + s * 0.5)
        + 0.3 * math.sin(k * 2 * (x + y) + s * 1.3)
        + 0.2 * math.cos(k * 3 * x - k * 2 * y + s * 2.1)
    )


def smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def ramp_pick(keys: Sequence[str], t: float) -> str:
    """The key at brightness t (0 = darkest/first, 1 = lightest/last) of a ramp."""
    return keys[max(0, min(len(keys) - 1, round(t * (len(keys) - 1))))]


def light_2d(project: Project | None = None) -> tuple[float, float, float]:
    """The project's [light] direction for flat sprites: unit (x right, y down, z towards the viewer),
    so hand-made 2D shading matches the light on 3D models."""
    lx, ly, lz = (project.config.light.direction if project is not None else (-0.5, 0.45, 0.75))
    norm = math.sqrt(lx * lx + ly * ly + lz * lz)
    return (lx / norm, -ly / norm, lz / norm)


def sphere_light(dx: float, dy: float, light: tuple[float, float, float] | None = None, wrap: float = 0.3) -> float:
    """Brightness 0..1 of a sphere at offset (dx, dy) in radii from its centre (as `Canvas.ellipse` passes),
    lit with PAGAN's wrap lighting like the 3D renderer."""
    lx, ly, lz = light or light_2d()
    nz = math.sqrt(max(0.0, 1 - dx * dx - dy * dy))
    facing = dx * lx + dy * ly + nz * lz
    return max(0.0, min(1.0, (facing + wrap) / (1 + wrap)))


_BAYER_2 = np.array([[0, 2], [3, 1]])


def _bayer(size: int) -> Any:
    """The ordered-dither threshold matrix (2, 4 or 8 wide), as thresholds in 0..1."""
    if size not in (2, 4, 8):
        raise ValueError("matrix must be 2, 4 or 8")
    matrix = _BAYER_2
    while matrix.shape[0] < size:
        matrix = np.block([[4 * matrix, 4 * matrix + 2], [4 * matrix + 3, 4 * matrix + 1]])
    return (matrix + 0.5) / (size * size)


def dither(keys: Sequence[str], t: Any, x: Any, y: Any, matrix: int = 4) -> Any:
    """Ordered (Bayer) dithering between a ramp's steps: brightness t (0 = first key, 1 = last) at pixel (x, y).
    Between two steps, the share of pixels taking the lighter one follows t, in a fixed pattern. Scalars give a
    key; numpy arrays (t, x, y broadcast together, e.g. from `np.mgrid`) give an array of keys for `Canvas.from_array`."""
    level = np.clip(np.asarray(t, dtype=float), 0.0, 1.0) * (len(keys) - 1)
    base = np.floor(level)
    threshold = _bayer(matrix)[np.asarray(y) % matrix, np.asarray(x) % matrix]
    index = np.minimum(base + (level - base > threshold), len(keys) - 1).astype(np.int64)
    picked = np.array(list(keys))[index]
    return str(picked) if picked.ndim == 0 else picked


def _edt_1d(f: list[float]) -> list[float]:
    """Squared distance transform of one line (Felzenszwalb & Huttenlocher): min over q of (p - q)^2 + f[q]."""
    n = len(f)
    hull = [0] * n  # parabolas of the lower envelope
    bounds = [0.0] * (n + 1)  # where each one starts
    k = 0
    bounds[0], bounds[1] = -math.inf, math.inf
    for q in range(1, n):
        cross = ((f[q] + q * q) - (f[hull[k]] + hull[k] * hull[k])) / (2 * q - 2 * hull[k])
        while cross <= bounds[k]:
            k -= 1
            cross = ((f[q] + q * q) - (f[hull[k]] + hull[k] * hull[k])) / (2 * q - 2 * hull[k])
        k += 1
        hull[k] = q
        bounds[k], bounds[k + 1] = cross, math.inf
    out = [0.0] * n
    k = 0
    for p in range(n):
        while bounds[k + 1] < p:
            k += 1
        out[p] = (p - hull[k]) ** 2 + f[hull[k]]
    return out


def _distance_to(targets: Any) -> Any:
    """Exact Euclidean distance (pixel centre to centre) from every pixel to the nearest True pixel of `targets`."""
    height, width = targets.shape
    big = float((width + height) ** 2)
    columns = np.where(targets, 0.0, big)
    for x in range(width):  # along y, then along x: the transform is separable
        columns[:, x] = _edt_1d(columns[:, x].tolist())
    for y in range(height):
        columns[y, :] = _edt_1d(columns[y, :].tolist())
    return np.sqrt(columns)


def distance_field(mask: Any) -> Any:
    """Signed distance field of a boolean mask (e.g. `Canvas.mask()`): inside, the distance from a pixel centre to
    the nearest outside pixel's centre (1 on the edge row); outside, minus the distance to the nearest inside
    pixel. For rims, bevels, outlines and glows on big canvases, in one numpy pass instead of per pixel."""
    inside = np.asarray(mask, dtype=bool)
    if inside.ndim != 2:
        raise ValueError("distance_field needs a 2D mask")
    if not inside.any():
        return -np.full(inside.shape, float(sum(inside.shape)))
    if inside.all():
        return np.full(inside.shape, float(sum(inside.shape)))
    return np.where(inside, _distance_to(~inside), -_distance_to(inside))


def bevel(mask: Any, width: float, light: tuple[float, float, float] | None = None) -> Any:
    """A bevelled shape's brightness 0..1 per pixel (0 outside): the edge rises over `width` pixels to a flat
    top, lit by `light` (x right, y down, z to the viewer; default the project-style light of `light_2d`). Feed it
    to `ramp_pick` or `dither`."""
    if width <= 0:
        raise ValueError("width must be above 0")
    inside = np.asarray(mask, dtype=bool)
    height = np.clip(distance_field(inside), 0.0, float(width))
    gy, gx = np.gradient(height)
    lx, ly, lz = light or light_2d()
    norm = np.sqrt(gx * gx + gy * gy + 1.0)
    shade = (-gx * lx - gy * ly + lz) / norm / math.sqrt(lx * lx + ly * ly + lz * lz)
    return np.where(inside, np.clip(shade, 0.0, 1.0), 0.0)


# --- text from real typefaces -------------------------------------------------------------------

_ANCHORS = {"baseline_left": "ls", "baseline_centre": "ms", "baseline_center": "ms", "baseline_right": "rs"}
_AXIS_TAGS = {"wght": "weight", "wdth": "width", "slnt": "slant", "ital": "italic", "opsz": "optical size"}


@dataclass(frozen=True)
class TextMask:
    """Text rasterised from a TTF/OTF. `coverage` is H x W floats 0..1 (anti-aliased ink); `origin` is where the
    anchor point lies in it (pixel-edge coordinates, like a pivot: paste the mask at `(x, y) - origin` to put the
    anchor on (x, y)); `advance` is how far the pen moves after the text, in output pixels (kerning included);
    `bbox` is (x0, y0, x1, y1) of the ink inside the mask, x1/y1 exclusive."""

    coverage: Any
    origin: tuple[int, int]
    advance: float
    bbox: tuple[int, int, int, int]

    def mask(self, threshold: float = 0.5) -> Any:
        """Boolean ink mask: coverage at or above `threshold` (for `distance_field`, `bevel`, `Canvas.from_array`)."""
        return np.asarray(self.coverage) >= threshold


def _load_font(font: str | Path | ImageFont.FreeTypeFont, size: int) -> ImageFont.FreeTypeFont:
    if isinstance(font, ImageFont.FreeTypeFont):
        return font.font_variant(size=size)
    return ImageFont.truetype(str(font), size)


def _set_variation(face: ImageFont.FreeTypeFont, variation: Mapping[str, float] | str | None) -> None:
    """A named instance ("Bold"), or axis values by OpenType tag (wght, wdth, slnt, ital, opsz) or axis name."""
    if variation is None:
        return
    if isinstance(variation, str):
        face.set_variation_by_name(variation)
        return
    try:
        axes = face.get_variation_axes()
    except OSError as exc:
        raise ValueError("variation needs a variable font; this font has no variation axes") from exc
    names = [str(a["name"].decode() if isinstance(a["name"], bytes) else a["name"]).lower() for a in axes]
    values = [float(a["default"] or 0) for a in axes]
    for key, value in variation.items():
        wanted = _AXIS_TAGS.get(key, key).lower()
        if wanted not in names:
            raise ValueError(f"font has no axis {key!r} (axes: {', '.join(names)})")
        values[names.index(wanted)] = float(value)
    face.set_variation_by_axes(values)


def text_mask(
    text: str,
    font: str | Path | ImageFont.FreeTypeFont,
    *,
    cap_height: float | None = None,
    size: float | None = None,
    variation: Mapping[str, float] | str | None = None,
    anchor: str = "baseline_left",
    rotate: float = 0.0,
    scale: tuple[float, float] | float = 1.0,
    supersample: int = 4,
) -> TextMask:
    """Rasterise `text` from a TTF/OTF (path, or a Pillow FreeTypeFont) into a coverage mask for pixel lettering.

    Size it by `cap_height` (pixels from the baseline to the top of "H": letters line up with the rest of the art)
    or by `size` (the font size in pixels). `anchor` is baseline_left (default), baseline_centre, baseline_right or
    any Pillow anchor ("mm", "lt", ...). `rotate` (degrees, + = clockwise) and `scale` ((x, y) or one number) turn
    the text about the anchor, so the frames of a tilting letter stay aligned with its rest frame. The text is drawn
    at `supersample` x the size and box-filtered down, the same result on every machine with the same font file.
    """
    if (cap_height is None) == (size is None):
        raise ValueError("give exactly one of cap_height or size")
    if supersample < 1:
        raise ValueError("supersample must be 1 or more")
    sx, sy = (float(scale), float(scale)) if isinstance(scale, int | float) else (float(scale[0]), float(scale[1]))
    if sx <= 0 or sy <= 0:
        raise ValueError("scale must be above 0")
    pil_anchor = _ANCHORS.get(anchor, anchor)
    if size is None:
        assert cap_height is not None
        probe = _load_font(font, 1000)
        _set_variation(probe, variation)
        cap = -probe.getbbox("H", anchor="ls")[1]
        if cap <= 0:
            raise ValueError("this font has no 'H' to measure the cap height by; pass size instead")
        size = cap_height * 1000 / cap
    ss = supersample
    face = _load_font(font, max(1, round(size * ss)))
    _set_variation(face, variation)
    box = face.getbbox(text, anchor=pil_anchor)
    left, top, right, bottom = math.floor(box[0]), math.floor(box[1]), math.ceil(box[2]), math.ceil(box[3])
    advance = face.getlength(text) / ss
    # Hi-res canvas with the anchor on a pixel edge that is a multiple of ss, so it lands on an output pixel edge.
    angle = math.radians(rotate)
    cos, sin = round(math.cos(angle), 12), round(math.sin(angle), 12)
    corners = [((x * sx) * cos - (y * sy) * sin, (x * sx) * sin + (y * sy) * cos) for x in (left, right) for y in (top, bottom)]
    pad = 2 * ss
    x0 = math.floor((min(c[0] for c in corners) - pad) / ss) * ss
    y0 = math.floor((min(c[1] for c in corners) - pad) / ss) * ss
    x1 = math.ceil((max(c[0] for c in corners) + pad) / ss) * ss
    y1 = math.ceil((max(c[1] for c in corners) + pad) / ss) * ss
    glyph_pad = 2 * ss
    glyphs = Image.new("L", (right - left + 2 * glyph_pad, bottom - top + 2 * glyph_pad), 0)
    ImageDraw.Draw(glyphs).text((glyph_pad - left, glyph_pad - top), text, font=face, fill=255, anchor=pil_anchor)
    if rotate == 0 and sx == 1 and sy == 1:
        hi = Image.new("L", (x1 - x0, y1 - y0), 0)
        hi.paste(glyphs, (left - glyph_pad - x0, top - glyph_pad - y0))
    else:
        # Output pixel (u, v) -> anchor-relative q = (u + x0, v + y0) -> undo rotate, then scale -> glyph image.
        a, b = cos / sx, sin / sx
        d, e = -sin / sy, cos / sy
        ox, oy = glyph_pad - left, glyph_pad - top
        matrix = (a, b, a * x0 + b * y0 + ox, d, e, d * x0 + e * y0 + oy)
        hi = glyphs.transform((x1 - x0, y1 - y0), Image.Transform.AFFINE, matrix, resample=Image.Resampling.BILINEAR)
    data = np.asarray(hi, dtype=np.float64) / 255.0
    h, w = data.shape[0] // ss, data.shape[1] // ss
    coverage = np.round(data.reshape(h, ss, w, ss).mean(axis=(1, 3)), 9)
    ink = np.argwhere(coverage > 0)
    bbox = (0, 0, 0, 0) if not len(ink) else (int(ink[:, 1].min()), int(ink[:, 0].min()), int(ink[:, 1].max()) + 1, int(ink[:, 0].max()) + 1)
    return TextMask(coverage=coverage, origin=(-x0 // ss, -y0 // ss), advance=round(advance * sx, 6), bbox=bbox)


# --- terrain ------------------------------------------------------------------------------------

CornerPaint = Callable[[Callable[[int, int], float], int, int, tuple[int, int, int, int]], str]


def corner_tiles(
    prefix: str, size: int, paint: CornerPaint, seed: int = 0, amp: float = 0.16
) -> dict[str, Canvas]:
    """The 16 tiles of a corner (Wang / Godot "Match Corners") transition set between two terrains.

    Tiles are named `<prefix>_<NW><NE><SW><SE>`, a bit being 1 where the "upper" terrain fills that
    corner (`shore_0000` .. `shore_1111`). For each pixel, `paint(field, x, y, corners)` returns the key;
    `field(x, y)` (clamped to the tile) is ~0 for the lower and ~1 for the upper terrain, blended
    smoothly between the corners plus seamless noise of strength `amp` — so `field(x, y) >= 0.5` is
    the edge, and neighbouring tiles that share corners meet without seams.
    """
    tiles: dict[str, Canvas] = {}
    for i in range(16):
        corners = ((i >> 3) & 1, (i >> 2) & 1, (i >> 1) & 1, i & 1)
        nw, ne, sw, se = corners
        weights = [smoothstep((i + 0.5) / size) for i in range(size)]
        values = [
            [
                (nw * (1 - u) + ne * u) * (1 - v) + (sw * (1 - u) + se * u) * v + amp * periodic_noise(x, y, size, seed)
                for x, u in enumerate(weights)
            ]
            for y, v in enumerate(weights)
        ]

        def field(x: int, y: int, values: list[list[float]] = values) -> float:
            return values[max(0, min(size - 1, y))][max(0, min(size - 1, x))]

        canvas = Canvas(size, size)
        for y in range(size):
            for x in range(size):
                canvas.pixels[y][x] = paint(field, x, y, corners)
        tiles[f"{prefix}_{''.join(map(str, corners))}"] = canvas
    return tiles


def compose(tileset: Asset, layout: Sequence[str] | str, variant: str | None = None) -> Image.Image:
    """A scene made of tiles, to check seams between *different* tiles: `layout` rows hold tile names
    separated by spaces ("." = empty). Layer several by alpha-compositing the results."""
    rows = [r.split() for r in (layout.strip("\n").split("\n") if isinstance(layout, str) else layout) if r.strip()]
    width, height = tileset.size
    image = Image.new("RGBA", (max((len(r) for r in rows), default=0) * width, len(rows) * height), (0, 0, 0, 0))
    unknown = sorted({name for row in rows for name in row if name != TRANSPARENT and name not in tileset.frames})
    if unknown:
        raise ValueError(f"{tileset.name} has no tile(s) {', '.join(unknown)}")
    for ty, row in enumerate(rows):
        for tx, name in enumerate(row):
            if name != TRANSPARENT:
                tile = frame_image(tileset, name, variant)
                image.alpha_composite(tile, (tx * width, ty * height))
    return image


# --- 3D geometry (what the model primitives fill) ----------------------------------------------


def shape_cells(shape: str, spec: Mapping[str, Any], materials: Sequence[str] | None = None) -> dict[Cell, str]:
    """The voxels a model primitive fills, exactly as a `.model.yaml` part would: e.g.
    `shape_cells("hull", {"from": [-13, 0, 0], "length": 27, "beam": 9, "height": 4, "material": "hull"})`.
    `materials` lists the material names the spec may use (default: the ones it mentions)."""
    names = list(materials) if materials is not None else [v for v in spec.values() if isinstance(v, str)]
    errors: list[str] = []
    model = VoxelModel()
    builder = _Builder(model, lambda _rule, message, _line, where: errors.append(f"{where}: {message}"),
                       {n: Material(n, ("0",)) for n in names})  # fmt: skip
    builder.build([{shape: dict(spec)}], None)
    if errors:
        raise ValueError("; ".join(errors))
    return dict(model.voxels)


# --- writing source files ---------------------------------------------------------------------

_PLAIN_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_YAML_WORDS = {"y", "n", "yes", "no", "on", "off", "true", "false", "null"}

Frame = Canvas | Sequence[str] | str


def _rows(frame: Frame) -> list[str]:
    if isinstance(frame, Canvas):
        return frame.rows()
    if isinstance(frame, str):
        return frame.strip("\n").split("\n")
    return list(frame)


def _key(name: str) -> str:
    return name if _PLAIN_NAME.match(name) and name.lower() not in _YAML_WORDS else f'"{name}"'


def _plain(value: Any) -> Any:
    """numpy numbers and arrays (and containers of them) as plain Python values, which YAML can write."""
    if isinstance(value, np.generic | np.ndarray):
        return value.tolist()
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value


def _fields(fields: Mapping[str, Any]) -> list[str]:
    out = []
    for key, value in fields.items():
        if value is None:
            continue
        value = _plain(value)
        text = yaml.safe_dump({key: value}, default_flow_style=True, sort_keys=False, allow_unicode=True, width=10**6)
        out.append(text.strip()[1:-1].strip())  # "{key: value}" -> "key: value"
    return out


def _grids(section: str, frames: Mapping[str, Frame], size: tuple[int, int]) -> list[str]:
    lines = [f"{section}:"]
    for name, frame in frames.items():
        rows = _rows(frame)
        if len(rows) != size[1] or any(len(r) != size[0] for r in rows):
            raise ValueError(f"{section}.{name} is {max(map(len, rows), default=0)}x{len(rows)}, expected {size[0]}x{size[1]}")
        lines.append(f"  {_key(name)}: |")
        lines += [f"    {row}" for row in rows]
    return lines


def _animations(animations: Mapping[str, Mapping[str, Any]] | None) -> list[str]:
    if not animations:
        return []
    lines = ["animations:"]
    for name, spec in animations.items():
        body = yaml.safe_dump(_plain(dict(spec)), default_flow_style=True, sort_keys=False, width=10**6).strip()
        lines.append(f"  {_key(name)}: {body}")
    return lines


def sprite_yaml(
    name: str,
    size: tuple[int, int],
    frames: Mapping[str, Frame],
    animations: Mapping[str, Mapping[str, Any]] | None = None,
    **fields: Any,
) -> str:
    """A `.sprite.yaml` file's text. `fields` are any other sprite fields (palette, pivot, outline,
    description, tags, status, lint, ...); `animations` maps a name to {frames: [...], fps, loop}."""
    head = _fields({"name": name, **{k: v for k, v in fields.items() if k != "size"}, "size": list(size)})
    return "\n".join([*head, *_grids("frames", frames, size), *_animations(animations)]) + "\n"


def tileset_yaml(
    name: str,
    tile_size: tuple[int, int],
    tiles: Mapping[str, Frame],
    animations: Mapping[str, Mapping[str, Any]] | None = None,
    **fields: Any,
) -> str:
    """A `.tiles.yaml` file's text (`columns`, `palette`, `lint`, ... go in `fields`)."""
    head = _fields({"name": name, **fields, "tile_size": list(tile_size)})
    return "\n".join([*head, *_grids("tiles", tiles, tile_size), *_animations(animations)]) + "\n"


def write(path: str | Path, text: str) -> Path:
    """Write a generated source file (only if it changed, so editors and builds don't churn)."""
    path = Path(path)
    if not (path.is_file() and path.read_text(encoding="utf-8") == text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return path

