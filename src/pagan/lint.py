"""`pagan lint`: format errors (from parsing) plus style warnings on valid assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pagan import jobs, spritecache
from pagan.asset import ASSET_SUFFIXES, MAX_SHEET_SIDE, Asset, Grid, asset_kind, load_asset
from pagan.findings import Finding, PaganError
from pagan.palette import PALETTE_SUFFIX, TRANSPARENT, load_palette_file
from pagan.progress import note
from pagan.project import Project
from pagan.render import frame_rects, grid_codes, trim_layout
from pagan.timeline import TIMELINE_SUFFIX, AssetCache, load_timeline

WARNING_RULES = {
    "W001": "orphan pixel",
    "W002": "unused frame",
    "W003": "too many ramps",
    "W004": "empty frame",
    "W005": "animation jitter",
    "W006": "made under an older style version",
    "W007": "too much change between animation frames",
    "W008": "too many shades from one ramp",
    "W009": "model overrides the project's mesh voxel_size",
    "W010": "a part's voxels are separate pieces (mesh export)",
    "W011": "rig pivot outside its part (mesh export)",
    "W012": "mesh-only model, but meshes aren't exported",
    "W013": "a model part's id has no voxels left (later parts cover it)",
    "W014": "built sheet over 16384 px on a side",
}


@dataclass
class LintResult:
    files: list[Path]
    findings: list[Finding]
    assets: list[Asset]

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]


def source_files(project: Project, paths: list[Path] | None = None, scenes: bool = True) -> list[Path]:
    """Palette, asset and (with `scenes`) timeline files under `paths` (default: the project's palettes/,
    sprites/, tiles/, models/ and scenes/)."""
    roots = paths or [project.palettes_dir, project.sprites_dir, project.tiles_dir, project.models_dir, project.scenes_dir]
    suffixes = (PALETTE_SUFFIX, *ASSET_SUFFIXES, *((TIMELINE_SUFFIX,) if scenes else ()))
    found: set[Path] = set()
    for root in roots:
        if root.is_file():
            found.add(root)
        elif root.is_dir():
            found.update(p for p in root.rglob("*.yaml") if p.name.endswith(suffixes))
    return sorted(found)


def lint_paths(project: Project, paths: list[Path] | None = None, scenes: bool = True) -> LintResult:
    """Lint sources. `scenes=False` skips timeline files (`pagan build` and the gallery: they're previews only)."""
    files = source_files(project, paths, scenes)
    linted = {f.resolve() for f in files}
    findings: list[Finding] = []
    assets: list[Asset] = []
    parsed: dict[Path, Asset | None] = {}
    timelines: list[Path] = []
    prepared = _prepare_in_parallel(project, files)
    for path in files:
        if path.name.endswith(TIMELINE_SUFFIX):
            timelines.append(path)
            continue
        if path.name.endswith(PALETTE_SUFFIX):
            try:
                load_palette_file(path)
            except PaganError as exc:
                findings.extend(exc.findings)
            continue
        if path in prepared:
            asset, asset_findings, own_findings = prepared[path]
        else:
            asset, asset_findings = load_asset(path, project)
            own_findings = asset_lint(asset, project) if asset is not None else []
        # A broken palette file that is itself being linted is reported once, from the palette.
        kept = [f for f in asset_findings if f.path is None or f.path.resolve() not in linted or f.path == path]
        if asset is not None:  # warnings raised while parsing (W008, W009) obey the asset's `lint: disable` too
            kept = [f for f in kept if not (f.severity == "warning" and f.rule in asset.lint_disable)]
        findings.extend(kept)
        if asset is None and not any(f.severity == "error" for f in kept):
            findings.append(Finding("E005", "this file's palette is invalid; run `pagan lint` on palettes/", path))
        parsed[path.resolve()] = asset
        if asset is not None:
            assets.append(asset)
            findings.extend(own_findings)
    by_name: dict[str, list[Asset]] = {}
    for asset in assets:
        by_name.setdefault(asset.name, []).append(asset)
    for name, group in by_name.items():
        if len(group) < 2:
            continue
        for asset in group:
            others = ", ".join(o.path.name if o.path else "another asset" for o in group if o is not asset)
            findings.append(
                Finding(
                    "E012",
                    f"asset name {name!r} is also used by {others}; names must be unique across sprites, "
                    "tilesets and models (outputs would overwrite each other)",
                    asset.path,
                    None,
                    "name",
                )
            )
    cache = AssetCache(project, parsed)
    for path in timelines:  # after the assets, so the sprites they show are parsed once
        findings.extend(load_timeline(path, project, cache)[1])
    disabled = set(project.config.lint.disable)
    findings = [f for f in findings if f.rule not in disabled]
    return LintResult(files=files, findings=_dedupe(findings), assets=assets)


def asset_lint(asset: Asset, project: Project) -> list[Finding]:
    """An asset's own lint findings (style warnings + supersample checks); cached with big sprites."""
    if asset.cache_key is not None:
        cached = spritecache.load_lint(asset, project)
        if cached is not None:
            return cached
    found = [*lint_asset(asset, project), *_check_supersample(asset, project)]
    if asset.cache_key is not None:
        spritecache.store_lint(asset, project, found)
    return found


Prepared = tuple[Asset | None, list[Finding], list[Finding]]  # asset, parse findings, its own lint findings


def _prepare_one(job: tuple[Path, Project]) -> Prepared:
    """Parse and lint one asset (in a worker process); big ones are cached on the way."""
    path, project = job
    asset, findings = load_asset(path, project)
    return asset, findings, asset_lint(asset, project) if asset is not None else []


def _prepare_in_parallel(project: Project, files: list[Path]) -> dict[Path, Prepared]:
    """Big sprites and tilesets that aren't cached yet are parsed and linted in the process pool (PAGAN_JOBS),
    when there are at least two. Each is done exactly as in this process, so the results are the same."""
    count = jobs.workers()
    if count <= 1:
        return {}
    candidates: list[Path] = []
    for path in files:
        if asset_kind(path) not in ("sprite", "tileset"):
            continue
        try:
            big = path.stat().st_size >= spritecache.CACHE_MIN_PIXELS or b"frames_png" in path.read_bytes()
        except OSError:
            continue
        key = spritecache.source_key(path, project) if big else None
        if key is not None and not spritecache.has(path, project, key):
            candidates.append(path)
    if len(candidates) < 2:
        return {}
    note(f"parsing and linting {len(candidates)} big sprites in {min(count, len(candidates))} processes...")
    try:
        results = list(jobs.pool(count).map(_prepare_one, [(path, project) for path in candidates]))
    except (OSError, RuntimeError):  # no process support here (e.g. a sandbox): do them in this process
        return {}
    return dict(zip(candidates, results, strict=True))


def _check_supersample(asset: Asset, project: Project) -> list[Finding]:
    """Supersampled assets are box-filtered down by N, so the frame size must be a multiple of N."""
    factor = asset.supersample if asset.supersample is not None else project.config.supersample
    width, height = asset.size
    found: list[Finding] = []
    if asset.font is not None and any(v % factor for v in (*asset.font.cell, asset.font.baseline, asset.font.line_height)):
        found.append(Finding("E003", f"font cell, baseline and line_height must be multiples of supersample ({factor})", asset.path, None, "font"))
    if any(m % factor for margins in asset.nine_slice.values() for m in margins):
        found.append(Finding("E003", f"nine_slice margins must be multiples of supersample ({factor})", asset.path, None, "nine_slice"))
    if width % factor == 0 and height % factor == 0:
        return found
    source = "its supersample" if asset.supersample is not None else "pagan.toml supersample"
    field = "tile_size" if asset.kind == "tileset" else "size"
    return [
        *found,
        Finding(
            "E003",
            f"{field} {width}x{height} isn't a multiple of {source} ({factor}): the build shrinks every frame by "
            f"{factor}. Use a size divisible by {factor}",
            asset.path,
            None,
            field,
        ),
    ]


def _dedupe(findings: list[Finding]) -> list[Finding]:
    return list(dict.fromkeys(findings))


def lint_asset(asset: Asset, project: Project) -> list[Finding]:
    """Style warnings for one parsed asset, minus those its `lint:` section turns off."""
    found: list[tuple[Finding, tuple[str, ...]]] = []  # each finding with the frames/animations it's about
    section = "tiles" if asset.kind == "tileset" else "frames"

    def warn(rule: str, message: str, frame: str | None = None, where: str | None = None, row: int | None = None) -> None:
        line = asset.frame_lines.get(frame) if frame is not None else None
        if line is not None and row is not None and frame not in asset.png_frames:
            line += 1 + row  # grids are block scalars starting on the line after the frame name
        finding = Finding(rule, message, asset.path, line, where or (f"{section}.{frame}" if frame else None))
        found.append((finding, (frame,) if frame else ()))

    def add(finding: Finding, *targets: str) -> None:
        found.append((finding, targets))

    # Mirrored sprites: report pixels in the authored left half only, in authored coordinates.
    authored_width = -(-asset.size[0] // 2) if asset.mirror else asset.size[0]

    for name, grid in asset.base_frames.items():
        if name in asset.derived_from:
            continue  # derived frames repeat their source's pixels; report problems once
        if not any(row.strip(TRANSPARENT) for row in grid):
            warn("W004", "frame is fully transparent", name)
            continue
        if asset.kind == "model":
            continue  # a rendered orphan (e.g. a spar tip seen end-on) can't be fixed pixel by pixel
        for x, y in _orphans(grid):
            if x >= authored_width:
                continue
            warn(
                "W001",
                "orphan pixel: a single opaque pixel with no opaque neighbours; usually a mistake",
                name,
                f"{section}.{name} row {y + 1} col {x + 1}",
                row=y,
            )

    if asset.kind == "sprite" and asset.animations:
        used = {f for anim in asset.animations.values() for f in anim.frames}
        used |= set(asset.derived_from.values())
        for name in asset.frames:
            if name not in used:
                warn("W002", "frame isn't used by any animation", name)

    lint_config = project.config.lint
    limit = lint_config.max_ramps_per_model if asset.kind == "model" else lint_config.max_ramps_per_sprite
    whose = "the project limit"
    if asset.lint_max_ramps is not None:
        limit, whose = asset.lint_max_ramps, "this asset's lint.max_ramps"
    ramps = _ramps_used(asset)
    if len(ramps) > limit:
        add(
            Finding(
                "W003",
                f"uses colors from {len(ramps)} ramps ({', '.join(ramps)}); {whose} is {limit}. "
                "Fewer ramps per asset keeps the look cohesive (a sheet of unrelated items can raise its own "
                "budget: lint: { max_ramps: N })",
                asset.path,
                None,
                "palette",
            )
        )

    for anim in asset.animations.values():
        boxes = [_bbox(asset.frames[f]) for f in anim.frames]
        areas = [(b[2] - b[0] + 1) * (b[3] - b[1] + 1) for b in boxes if b is not None]
        if len(areas) > 1 and max(areas) > 2 * min(areas):
            add(
                Finding(
                    "W005",
                    "frames' visible areas differ by more than 2x; check for jitter or a missing body part",
                    asset.path,
                    None,
                    f"animations.{anim.name}",
                ),
                anim.name,
            )

    if not asset.mesh_only:
        factor = asset.supersample if asset.supersample is not None else project.config.supersample
        if asset.trim:  # the packed layout is already in output pixels
            cells = [f.rect for f in trim_layout(asset, factor).values()]
            sheet_w, sheet_h = max(x + w for x, _, w, _ in cells), max(y + h for _, y, _, h in cells)
        else:
            rects = frame_rects(asset).values()
            sheet_w = max(x + w for x, _, w, _ in rects) // factor
            sheet_h = max(y + h for _, y, _, h in rects) // factor
        if max(sheet_w, sheet_h) > MAX_SHEET_SIDE:
            hint = "set sheet_columns to balance it, " if asset.kind == "sprite" else ""
            add(
                Finding(
                    "W014",
                    f"the built sheet is {sheet_w}x{sheet_h} px; textures over {MAX_SHEET_SIDE} px on a side fail to load in "
                    f"many engines (Godot included). {hint}split the asset, or use fewer/smaller frames",
                    asset.path,
                    None,
                    "sheet_columns" if asset.kind == "sprite" else ("columns" if asset.kind == "tileset" else "size"),
                )
            )

    max_steps = project.config.lint.max_ramp_steps
    if max_steps and asset.kind != "model":  # models are checked per material when they're parsed
        used = {c for grid in asset.base_frames.values() for row in grid for c in row if c != TRANSPARENT}
        for ramp in ramps:
            steps = [k for k in asset.palette.ramps[ramp] if k in used]
            if len(steps) > max_steps:
                add(
                    Finding(
                        "W008",
                        f"uses {len(steps)} shades of ramp {ramp!r} ({', '.join(steps)}); the project allows "
                        f"{max_steps} per material (STYLE.md shading rules)",
                        asset.path,
                        None,
                        "palette",
                    )
                )

    limit_change = project.config.lint.max_frame_change
    for anim in asset.animations.values():
        pairs = list(zip(anim.frames, anim.frames[1:]))
        start = anim.loop_from or 0  # the loop seam: last frame -> first looping frame
        if anim.loop and len(anim.frames) - start > 2:
            pairs.append((anim.frames[-1], anim.frames[start]))
        for a, b in pairs:
            if a == b:
                continue
            change, (dx, dy) = frame_change(asset.frames[a], asset.frames[b])
            if change > limit_change:
                moved = f" (best alignment: moved {dx:+d},{dy:+d})" if dx or dy else ""
                add(
                    Finding(
                        "W007",
                        f"{a} -> {b}: {change:.0%} of pixels change{moved}; the project limit is "
                        f"{limit_change:.0%}. Keep unchanged parts on exactly the same pixels (see the "
                        "preview's changes row)",
                        asset.path,
                        asset.frame_lines.get(b),
                        f"animations.{anim.name}",
                    ),
                    anim.name,
                    b,
                )

    current = project.config.style_version
    if asset.style_version < current:
        add(
            Finding(
                "W006",
                f"made under style v{asset.style_version}, the project is at v{current}: review it against the "
                f"STYLE.md changelog, update it, then set style_version: {current}",
                asset.path,
                None,
                "style_version",
            )
        )
    return [
        finding
        for finding, targets in found
        if finding.rule not in asset.lint_disable
        and not any(finding.rule in asset.lint_disable_for.get(t, ()) for t in targets)
    ]


def frame_change(a: Grid, b: Grid, max_shift: int = 2) -> tuple[float, tuple[int, int]]:
    """Share of pixels that differ between two frames, after the best whole-sprite shift (|d| <= max_shift).

    Counted over pixels opaque in either frame; a pure 1px bob therefore scores ~0.
    """
    ga = grid_codes(a).astype(np.int32)
    gb = grid_codes(b).astype(np.int32)
    clear = ord(TRANSPARENT)
    if not ((ga != clear).any() or (gb != clear).any()):
        return 0.0, (0, 0)
    m = max_shift
    pa = np.pad(ga, m, constant_values=clear)
    pb = np.pad(gb, m, constant_values=clear)
    height, width = pa.shape
    best = (2.0, (0, 0))
    shifts = sorted(((dx, dy) for dx in range(-m, m + 1) for dy in range(-m, m + 1)), key=lambda d: (abs(d[0]) + abs(d[1]), d))
    for dx, dy in shifts:  # smallest movements first, so ties keep the smaller move
        # b's pixel at (x + dx, y + dy) is compared with a's pixel at (x, y)
        moved = np.full_like(pb, clear)
        ys, ye = max(0, -dy), min(height, height - dy)
        xs, xe = max(0, -dx), min(width, width - dx)
        moved[ys:ye, xs:xe] = pb[ys + dy : ye + dy, xs + dx : xe + dx]
        union = (pa != clear) | (moved != clear)
        total = int(union.sum())
        score = int(((pa != moved) & union).sum()) / total if total else 0.0
        if score < best[0]:
            best = (score, (dx, dy))
            if score == 0:
                break
    return best


def _orphans(grid: Grid) -> list[tuple[int, int]]:
    """Opaque pixels without an opaque neighbour in 8 directions, as (x, y) in row-major order (numpy: big frames
    are megapixels)."""
    if not grid:
        return []
    solid = grid_codes(grid) != ord(TRANSPARENT)
    padded = np.pad(solid, 1)
    height, width = solid.shape
    neighbours = np.zeros_like(solid)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx or dy:
                neighbours |= padded[1 + dy : 1 + dy + height, 1 + dx : 1 + dx + width]
    return [(int(x), int(y)) for y, x in np.argwhere(solid & ~neighbours)]


def _bbox(grid: Grid) -> tuple[int, int, int, int] | None:
    if not grid or not grid[0]:
        return None
    solid = grid_codes(grid) != ord(TRANSPARENT)
    if not solid.any():
        return None
    ys, xs = np.nonzero(solid)
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


def _ramps_used(asset: Asset) -> list[str]:
    """Smallest set of ramps (greedy) covering the asset's colors; colors in no ramp are ignored. A model's
    flat one-key materials (LEDs, screens: `{ keys: ["a"] }`) aren't shading ramps, so their keys don't count
    unless a shaded material uses them too."""
    used = set().union(*(set(row) for grid in asset.base_frames.values() for row in grid)) - {TRANSPARENT}
    if asset.mesh is not None:
        materials = asset.mesh.materials.values()
        shaded = {k for m in materials if len(set(m.keys)) > 1 for k in m.keys}
        used -= {m.keys[0] for m in materials if len(set(m.keys)) == 1} - shaded - {asset.outline_color}
    ramps = {name: set(keys) for name, keys in asset.palette.ramps.items()}
    uncovered = {k for k in used if any(k in keys for keys in ramps.values())}
    chosen: list[str] = []
    while uncovered:
        best = max(ramps, key=lambda r: (len(ramps[r] & uncovered), -list(ramps).index(r)))
        chosen.append(best)
        uncovered -= ramps[best]
    return chosen
