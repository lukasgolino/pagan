"""`pagan build`: lint, then write final assets (sheets, manifest, engine resources) to the output dir.

Output is deterministic: same sources -> byte-identical files, so projects can commit it. Files that
PAGAN generated before but no longer produces (recorded in the previous manifest) are removed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pagan import __version__
from pagan.asset import Animation, Asset
from pagan.exporters.godot import centered_offset, find_godot_project, res_path, sprite_frames_tres
from pagan.findings import Finding
from pagan.lint import LintResult, lint_paths
from pagan.project import Project
from pagan.render import frame_rects, save_png, sheet_image

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

    for asset in sorted(lint.assets, key=lambda a: a.name):
        folder = out / ("tiles" if asset.kind == "tileset" else "sprites")
        rects = frame_rects(asset)
        animations = _animations_for(asset) if asset.kind != "tileset" else []

        def emit(variant: str | None) -> dict[str, Any]:
            stem = asset.name if variant is None else f"{asset.name}.{variant}"
            sheet = folder / f"{stem}.png"
            _write(sheet, _png_bytes(sheet_image(asset, variant), scratch), result)
            produced.add(sheet.resolve())
            info: dict[str, Any] = {"sheet": _ref(sheet, out, godot_root)}
            if godot_root is not None and asset.kind != "tileset":
                tres = folder / f"{stem}.tres"
                text = sprite_frames_tres(res_path(sheet, godot_root), rects, animations)
                _write(tres, text.encode("utf-8"), result)
                produced.add(tres.resolve())
                info["godot_sprite_frames"] = res_path(tres, godot_root)
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
        else:
            entry["pivot"] = list(asset.pivot)
            entry["godot_offset"] = list(centered_offset(asset.size, asset.pivot))
            entry["animations"] = {
                a.name: {"frames": list(a.frames), "fps": a.fps, "loop": a.loop} for a in animations
            }
        if asset.kind == "model":
            entry["headings"] = [a.name for a in asset.animations.values() if a.frames == (a.name,)]
        entry["variants"] = {v: emit(v) for v in asset.variants}
        entries[asset.name] = entry

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


def _ref(path: Path, out: Path, godot_root: Path | None) -> str:
    """How the manifest refers to a file: res:// inside Godot, else relative to the output dir."""
    if godot_root is not None:
        return res_path(path, godot_root)
    return path.resolve().relative_to(out.resolve()).as_posix()


def _previous_outputs(out: Path) -> set[Path]:
    manifest = out / MANIFEST
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return {(out / f).resolve() for f in data.get("files", []) if ".." not in Path(f).parts}
    except (OSError, ValueError, AttributeError):
        return set()
