"""`pagan build`: lint, then write final assets (sheets, manifest, engine resources) to the output dir.

Output is deterministic: same sources -> byte-identical files, so projects can commit it. Files that
PAGAN generated before but no longer produces (recorded in the previous manifest) are removed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from pagan import __version__
from pagan.asset import Animation, Asset, Variant
from pagan.exporters.godot import (
    AtlasTile,
    centered_offset,
    find_godot_project,
    res_path,
    sprite_frames_tres,
    tileset_tres,
)
from pagan.findings import Finding
from pagan.lint import LintResult, lint_paths
from pagan.palette import TRANSPARENT
from pagan.project import Project
from pagan.render import frame_rects, save_png, sheet_image, tile_cells

MANIFEST = "manifest.json"


@dataclass
class BuildResult:
    lint: LintResult
    written: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    errors: list[Finding] = field(default_factory=list)
    manifest: Path | None = None
    godot_root: Path | None = None


def _animations_for(asset: Asset) -> list[Animation]:
    """Animations to export; a sprite without any gets one single-frame animation per frame."""
    if asset.animations:
        return list(asset.animations.values())
    return [Animation(name, (name,), 1.0, True) for name in asset.frames]


def _write(path: Path, data: bytes, result: BuildResult) -> None:
    """Only touch files whose content changed, so engines don't re-import everything on every build."""
    if path.is_file() and path.read_bytes() == data:
        result.unchanged.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    result.written.append(path)


def _png_bytes(image: Any, scratch: Path) -> bytes:
    save_png(image, scratch)
    data = scratch.read_bytes()
    scratch.unlink()
    return data


def build(project: Project) -> BuildResult:
    """Build the whole project (a partial build would leave an incomplete manifest)."""
    lint = lint_paths(project)
    result = BuildResult(lint=lint)
    if lint.errors:
        result.errors = lint.errors
        return result

    out = project.output_dir
    exporters = set(project.config.export)
    godot_root: Path | None = None
    if "godot" in exporters:
        godot_root = find_godot_project(out)
        if godot_root is None:
            result.errors.append(
                Finding(
                    "E000",
                    f"export includes \"godot\" but output_dir ({out}) isn't inside a Godot project (no project.godot "
                    "found in it or any parent). Point output_dir into your Godot project, e.g. ../game/assets/generated",
                    project.config_path,
                )
            )
            return result
        result.godot_root = godot_root

    out.mkdir(parents=True, exist_ok=True)
    scratch = out / ".pagan-tmp.png"
    previous = _previous_outputs(out)
    entries: dict[str, Any] = {}
    produced: set[Path] = set()

    for asset in sorted((a for a in lint.assets if not a.template), key=lambda a: a.name):
        folder = out / ("tiles" if asset.kind == "tileset" else "sprites")
        rects = frame_rects(asset)
        animations = _animations_for(asset) if asset.kind != "tileset" else []
        normal_sheet: Path | None = None
        if "normals" in exporters and asset.normal_maps is not None:
            normal_sheet = folder / f"{asset.name}.normal.png"
            _write(normal_sheet, _png_bytes(_normal_sheet(asset, rects), scratch), result)
            produced.add(normal_sheet.resolve())

        def emit(variant: str | None) -> dict[str, Any]:
            stem = asset.name if variant is None else f"{asset.name}.{variant}"
            sheet = folder / f"{stem}.png"
            _write(sheet, _png_bytes(sheet_image(asset, variant), scratch), result)
            produced.add(sheet.resolve())
            info: dict[str, Any] = {"sheet": _ref(sheet, out, godot_root)}
            if godot_root is not None:
                tres = folder / f"{stem}.tres"
                if asset.kind == "tileset":
                    text = tileset_tres(res_path(sheet, godot_root), asset.size, _atlas_tiles(asset))
                    info["godot_tileset"] = res_path(tres, godot_root)
                else:
                    normal_res = res_path(normal_sheet, godot_root) if normal_sheet is not None else None
                    text = sprite_frames_tres(res_path(sheet, godot_root), rects, animations, normal_res)
                    info["godot_sprite_frames"] = res_path(tres, godot_root)
                _write(tres, text.encode("utf-8"), result)
                produced.add(tres.resolve())
            return info

        entry: dict[str, Any] = {
            "kind": asset.kind,
            "description": asset.description,
            "tags": list(asset.tags),
            "status": asset.status,
            "style_version": asset.style_version,
            "palette": asset.palette.name,
            "size": list(asset.size),
            **emit(None),
            "frames": {name: list(rect) for name, rect in rects.items()},
        }
        if asset.kind == "tileset":
            entry["columns"] = asset.columns
            entry["tiles"] = {name: list(cell) for name, cell in _tile_names(asset).items()}
            if asset.animations:
                entry["animations"] = {
                    a.name: {"frames": list(a.frames), "fps": a.fps, "loop": True} for a in asset.animations.values()
                }
        else:
            entry["pivot"] = list(asset.pivot)
            entry["godot_offset"] = list(centered_offset(asset.size, asset.pivot))
            entry["animations"] = {
                a.name: {"frames": list(a.frames), "fps": a.fps, "loop": a.loop} for a in animations
            }
        if asset.kind == "model":
            entry["headings"] = [a.name for a in asset.animations.values() if a.frames == (a.name,)]
        if normal_sheet is not None:
            entry["normal_sheet"] = _ref(normal_sheet, out, godot_root)
        variants: dict[str, Any] = {}
        axis_options = {f"{axis}.{name}": v for axis, options in asset.variant_axes.items() for name, v in options.items()}
        for v in [*asset.variants, *axis_options]:
            variant = asset.variants[v] if v in asset.variants else axis_options[v]
            swap, exact = variant_swap(asset, variant)
            if not exact and not project.config.variant_sheets:
                result.errors.append(
                    Finding(
                        "E006",
                        f"variant {variant.name!r} can't be a colour swap: keys that share a colour in the base palette get "
                        "different colours in the variant. Give those keys distinct colours, or set "
                        "variant_sheets = true",
                        asset.path,
                        None,
                        f"variant_axes.{v}" if v in axis_options else f"variants.{v}",
                    )
                )
            if v in axis_options or ("+" in v and not project.config.variant_sheets):
                continue  # axis options are listed per axis; without sheets the game composes them
            info = emit(v) if project.config.variant_sheets else {}
            variants[v] = {**info, "swap": swap, "swap_exact": exact}
        entry["variants"] = variants
        if asset.variant_axes:
            entry["variant_axes"] = {
                axis: {name: dict(zip(("swap", "swap_exact"), variant_swap(asset, v), strict=True)) for name, v in options.items()}
                for axis, options in asset.variant_axes.items()
            }
        entries[asset.name] = entry

    if result.errors:
        return result
    manifest = {
        "generator": f"pagan {__version__}",
        "note": "Generated by `pagan build`. Do not edit: change the sources and rebuild.",
        "assets": entries,
        "files": sorted(_ref(p, out, None) for p in produced),
    }
    manifest_path = out / MANIFEST
    _write(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"), result)
    result.manifest = manifest_path

    for stale in sorted(previous - produced):
        if stale.is_file():
            stale.unlink()
            result.removed.append(stale)
            imported = stale.with_name(stale.name + ".import")  # Godot's sidecar for the removed file
            imported.unlink(missing_ok=True)
    return result


def variant_swap(asset: Asset, v: Variant) -> tuple[dict[str, str], bool]:
    """Base colour -> variant colour ("#rrggbb") for every colour the asset uses that the variant changes,
    and whether that's exact: False when two keys share a base colour but differ in the variant."""
    used = sorted({c for grid in asset.frames.values() for row in grid for c in row if c != TRANSPARENT})
    targets: dict[str, set[str]] = {}
    for key in used:
        base = asset.palette.colors[key].hex
        targets.setdefault(base, set()).add(v.palette.colors[v.keys.get(key, key)].hex)
    swap = {base: next(iter(new)) for base, new in sorted(targets.items()) if len(new) == 1 and new != {base}}
    return swap, all(len(new) == 1 for new in targets.values())


def _tile_names(asset: Asset) -> dict[str, tuple[int, int]]:
    """Tile name -> atlas cell. An animated tile is named after its animation, at its first frame's cell;
    its frames aren't tiles of their own."""
    cells = tile_cells(asset)
    frames_of_animations = {f for a in asset.animations.values() for f in a.frames}
    names = {name: cell for name, cell in cells.items() if name not in frames_of_animations}
    names.update({a.name: cells[a.frames[0]] for a in asset.animations.values()})
    return dict(sorted(names.items(), key=lambda item: (item[1][1], item[1][0])))


def _atlas_tiles(asset: Asset) -> list[AtlasTile]:
    tiles = []
    for name, (column, row) in _tile_names(asset).items():
        anim = asset.animations.get(name)
        if anim is None:
            tiles.append(AtlasTile(column, row))
        else:
            wraps = len(anim.frames) > asset.columns
            tiles.append(AtlasTile(column, row, len(anim.frames), asset.columns if wraps else 0, anim.fps))
    return tiles


def _normal_sheet(asset: Asset, rects: dict[str, tuple[int, int, int, int]]) -> Image.Image:
    """Normal maps laid out like the sprite sheet: RGB = normal * 0.5 + 0.5 (x right, y up, z to viewer)."""
    assert asset.normal_maps is not None
    maps = asset.normal_maps()
    width = max(x + w for x, _, w, _ in rects.values())
    height = max(y + h for _, y, _, h in rects.values())
    sheet = np.zeros((height, width, 4), dtype=np.uint8)
    for name, (x, y, w, h) in rects.items():
        rgb = np.clip(np.rint((maps[name] * 0.5 + 0.5) * 255), 0, 255).astype(np.uint8)
        alpha = np.array([[0 if c == "." else 255 for c in row] for row in asset.frames[name]], dtype=np.uint8)
        sheet[y : y + h, x : x + w, :3] = rgb
        sheet[y : y + h, x : x + w, 3] = alpha
        sheet[y : y + h, x : x + w, :3][alpha == 0] = (128, 128, 255)
    return Image.fromarray(sheet, "RGBA")


def _ref(path: Path, out: Path, godot_root: Path | None) -> str:
    """How the manifest refers to a file: res:// inside Godot, else relative to the output dir."""
    if godot_root is not None:
        return res_path(path, godot_root)
    return path.resolve().relative_to(out.resolve()).as_posix()


def _previous_outputs(out: Path) -> set[Path]:
    """Files the previous build recorded. Only paths inside output_dir count: never delete anything else."""
    manifest = out / MANIFEST
    root = out.resolve()
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        names = data.get("files", []) if isinstance(data, dict) else []
    except (OSError, ValueError):
        return set()
    found: set[Path] = set()
    for name in names:
        if not isinstance(name, str) or Path(name).is_absolute():
            continue
        path = (root / name).resolve()
        if path.is_relative_to(root) and path != root and path.suffix in (".png", ".tres", ".json"):
            found.add(path)
    return found
