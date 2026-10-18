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
from pagan.asset import Animation, Asset, Variant, glyph_cells
from pagan.exporters.godot import (
    AtlasTile,
    centered_offset,
    find_godot_project,
    import_mipmaps,
    res_path,
    sprite_frames_tres,
    texture_filter,
    tileset_tres,
)
from pagan.findings import Finding
from pagan.lint import LintResult, lint_paths
from pagan.palette import TRANSPARENT
from pagan.project import Project
from pagan.render import downsample, frame_rects, save_png, sheet_image, supersample_factor, tile_cells

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

    godot = project.config.godot
    filter_mode = texture_filter(godot.filter, godot.mipmaps)

    def write_png(path: Path, image: Image.Image) -> None:
        _write(path, _png_bytes(image, scratch), result)
        produced.add(path.resolve())
        if godot_root is not None:
            imported = import_mipmaps(path, godot.mipmaps)
            if imported is not None:
                result.written.append(imported)

    for asset in sorted((a for a in lint.assets if not a.template), key=lambda a: a.name):
        folder = out / ("tiles" if asset.kind == "tileset" else "sprites")
        factor = supersample_factor(asset, project)
        size = (asset.size[0] // factor, asset.size[1] // factor)
        rects = {name: (x // factor, y // factor, w // factor, h // factor) for name, (x, y, w, h) in frame_rects(asset).items()}
        animations = _animations_for(asset) if asset.kind != "tileset" else []
        font = font_metrics(asset, factor) if asset.font is not None else None
        sheet_size = (max(x + w for x, _, w, _ in rects.values()), max(y + h for _, y, _, h in rects.values()))
        normal_sheet: Path | None = None
        if "normals" in exporters and asset.normal_maps is not None:
            normal_sheet = folder / f"{asset.name}.normal.png"
            write_png(normal_sheet, downsample(_normal_sheet(asset, frame_rects(asset)), factor))

        def emit(variant: str | None) -> dict[str, Any]:
            stem = asset.name if variant is None else f"{asset.name}.{variant}"
            sheet = folder / f"{stem}.png"
            write_png(sheet, downsample(sheet_image(asset, variant), factor))
            info: dict[str, Any] = {"sheet": _ref(sheet, out, godot_root)}
            if font is not None:
                # The font gets its own copy of the sheet: an engine's font importer may claim its page image
                # (Godot marks it importer="skip"), and the sprite's sheet must stay a plain texture.
                page = out / "fonts" / f"{stem}.png"
                _write(page, sheet.read_bytes(), result)
                fnt = page.with_suffix(".fnt")
                _write(fnt, bmfont_text(asset.name, font, page.name, sheet_size).encode("utf-8"), result)
                produced.update((page.resolve(), fnt.resolve()))
                info["font_file"] = _ref(fnt, out, godot_root)
            if godot_root is not None:
                tres = folder / f"{stem}.tres"
                if asset.kind == "tileset":
                    text = tileset_tres(res_path(sheet, godot_root), size, _atlas_tiles(asset))
                    info["godot_tileset"] = res_path(tres, godot_root)
                else:
                    normal_res = res_path(normal_sheet, godot_root) if normal_sheet is not None else None
                    text = sprite_frames_tres(res_path(sheet, godot_root), rects, animations, normal_res, filter_mode)
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
            "size": list(size),
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
            pivot = (_shrink(asset.pivot[0], factor), _shrink(asset.pivot[1], factor))
            entry["pivot"] = list(pivot)
            entry["godot_offset"] = list(centered_offset(size, pivot))
            entry["animations"] = {
                a.name: {"frames": list(a.frames), "fps": a.fps, "loop": a.loop} for a in animations
            }
        if "animations" in entry:  # JSON objects are unordered (and the manifest sorts keys): the file's order
            entry["animation_order"] = [a.name for a in (animations if asset.kind != "tileset" else asset.animations.values())]
        if asset.kind == "model":
            entry["headings"] = [a.name for a in asset.animations.values() if a.frames == (a.name,)]
        if asset.nine_slice:
            entry["nine_slice"] = {name: [m // factor for m in margins] for name, margins in asset.nine_slice.items()}
        if font is not None:
            entry["font"] = font
        if normal_sheet is not None:
            entry["normal_sheet"] = _ref(normal_sheet, out, godot_root)
        if factor > 1:
            entry["supersample"] = factor
            entry["source_size"] = list(asset.size)
        variants: dict[str, Any] = {}
        if asset.base_variant is not None:  # the base under its own name, so the game sees one uniform set
            entry["base_variant"] = asset.base_variant
            base_files = {k: entry[k] for k in ("sheet", "godot_sprite_frames", "godot_tileset") if k in entry}
            variants[asset.base_variant] = {**(base_files if project.config.variant_sheets else {}), "swap": {}, "swap_exact": True}
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


def font_metrics(asset: Asset, factor: int = 1) -> dict[str, Any]:
    """A font sprite's glyphs for the manifest: each character's rect in the sheet and its advance, in output
    pixels, plus line metrics. Auto advance = the glyph's drawn width (to its rightmost pixel) + spacing."""
    font = asset.font
    assert font is not None
    rects = frame_rects(asset)
    cell_w, cell_h = font.cell
    per_row = asset.size[0] // cell_w
    glyphs: dict[str, Any] = {}
    counters: dict[str, int] = {}
    for char, (frame, grid) in zip(font.glyphs, glyph_cells(font, asset.frames, asset.size), strict=False):
        index = counters.get(frame, 0)
        counters[frame] = index + 1
        x, y, _, _ = rects[frame]
        left, top = x + (index % per_row) * cell_w, y + (index // per_row) * cell_h
        drawn = max((i + 1 for row in grid for i, c in enumerate(row) if c != TRANSPARENT), default=0)
        advance = font.advance if font.advance is not None else (drawn + font.spacing if drawn else font.space)
        glyphs[char] = {
            "rect": [left // factor, top // factor, cell_w // factor, cell_h // factor],
            "advance": -(-advance // factor),
        }
    return {
        "glyph_order": font.glyphs,
        "glyphs": glyphs,
        "cell": [cell_w // factor, cell_h // factor],
        "ascent": font.baseline // factor,
        "descent": (cell_h - font.baseline) // factor,
        "line_height": font.line_height // factor,
    }


def bmfont_text(name: str, font: dict[str, Any], page: str, sheet_size: tuple[int, int]) -> str:
    """The font as an AngelCode BMFont text file (.fnt): Godot imports it as a FontFile, and most engines read it."""
    lines = [
        f'info face="{name}" size={font["line_height"]} bold=0 italic=0 charset="" unicode=1 stretchH=100 smooth=0 aa=1 '
        "padding=0,0,0,0 spacing=0,0 outline=0",
        f'common lineHeight={font["line_height"]} base={font["ascent"]} scaleW={sheet_size[0]} scaleH={sheet_size[1]} '
        "pages=1 packed=0 alphaChnl=0 redChnl=0 greenChnl=0 blueChnl=0",
        f'page id=0 file="{page}"',
        f"chars count={len(font['glyphs'])}",
    ]
    for char, glyph in sorted(font["glyphs"].items(), key=lambda item: ord(item[0])):
        x, y, w, h = glyph["rect"]
        lines.append(f"char id={ord(char)} x={x} y={y} width={w} height={h} xoffset=0 yoffset=0 xadvance={glyph['advance']} page=0 chnl=15")
    return "\n".join(lines) + "\n"


def _shrink(value: int, factor: int) -> int | float:
    """A source pixel coordinate in output pixels: an int when it lands on a pixel edge."""
    return value // factor if value % factor == 0 else value / factor


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
        if path.is_relative_to(root) and path != root and path.suffix in (".png", ".tres", ".json", ".fnt"):
            found.add(path)
    return found
