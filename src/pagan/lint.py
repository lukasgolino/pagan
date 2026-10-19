"""`pagan lint`: format errors (from parsing) plus style warnings on valid assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pagan.asset import ASSET_SUFFIXES, Asset, Grid, load_asset, opaque
from pagan.findings import Finding, PaganError
from pagan.palette import PALETTE_SUFFIX, TRANSPARENT, load_palette_file
from pagan.project import Project

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


def source_files(project: Project, paths: list[Path] | None = None) -> list[Path]:
    """Palette and asset files under `paths` (default: the project's palettes/, sprites/, tiles/, models/)."""
    roots = paths or [project.palettes_dir, project.sprites_dir, project.tiles_dir, project.models_dir]
    suffixes = (PALETTE_SUFFIX, *ASSET_SUFFIXES)
    found: set[Path] = set()
    for root in roots:
        if root.is_file():
            found.add(root)
        elif root.is_dir():
            found.update(p for p in root.rglob("*.yaml") if p.name.endswith(suffixes))
    return sorted(found)


def lint_paths(project: Project, paths: list[Path] | None = None) -> LintResult:
    files = source_files(project, paths)
    linted = {f.resolve() for f in files}
    findings: list[Finding] = []
    assets: list[Asset] = []
    for path in files:
        if path.name.endswith(PALETTE_SUFFIX):
            try:
                load_palette_file(path)
            except PaganError as exc:
                findings.extend(exc.findings)
            continue
        asset, asset_findings = load_asset(path, project)
        # A broken palette file that is itself being linted is reported once, from the palette.
        kept = [f for f in asset_findings if f.path is None or f.path.resolve() not in linted or f.path == path]
        if asset is not None:  # warnings raised while parsing (W008, W009) obey the asset's `lint: disable` too
            kept = [f for f in kept if not (f.severity == "warning" and f.rule in asset.lint_disable)]
        findings.extend(kept)
        if asset is None and not any(f.severity == "error" for f in kept):
            findings.append(Finding("E005", "this file's palette is invalid; run `pagan lint` on palettes/", path))
        if asset is not None:
            assets.append(asset)
            findings.extend(lint_asset(asset, project))
            findings.extend(_check_supersample(asset, project))
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
    disabled = set(project.config.lint.disable)
    findings = [f for f in findings if f.rule not in disabled]
    return LintResult(files=files, findings=_dedupe(findings), assets=assets)


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
        if line is not None and row is not None:
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
        if all(c == TRANSPARENT for row in grid for c in row):
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
        if anim.loop and len(anim.frames) > 2:
            pairs.append((anim.frames[-1], anim.frames[0]))
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
    ga = np.array([[ord(c) for c in row] for row in a], dtype=np.int32)
    gb = np.array([[ord(c) for c in row] for row in b], dtype=np.int32)
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
    out = []
    for y, row in enumerate(grid):
        for x, char in enumerate(row):
            if char != TRANSPARENT and not any(
                opaque(grid, x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy
            ):
                out.append((x, y))
    return out


def _bbox(grid: Grid) -> tuple[int, int, int, int] | None:
    points = [(x, y) for y, row in enumerate(grid) for x, c in enumerate(row) if c != TRANSPARENT]
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _ramps_used(asset: Asset) -> list[str]:
    """Smallest set of ramps (greedy) covering the asset's colors; colors in no ramp are ignored."""
    used = {c for grid in asset.base_frames.values() for row in grid for c in row if c != TRANSPARENT}
    ramps = {name: set(keys) for name, keys in asset.palette.ramps.items()}
    uncovered = {k for k in used if any(k in keys for keys in ramps.values())}
    chosen: list[str] = []
    while uncovered:
        best = max(ramps, key=lambda r: (len(ramps[r] & uncovered), -list(ramps).index(r)))
        chosen.append(best)
        uncovered -= ramps[best]
    return chosen
