"""Command-line interface for PAGAN."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable, Sequence
from importlib.resources import files
from pathlib import Path
from string import Template
from typing import Any

from pagan import __version__
from pagan.asset import MODEL_SUFFIX, SPRITE_SUFFIX, TILESET_SUFFIX, Asset, load_asset_or_raise
from pagan.findings import Finding, PaganError, display_path
from pagan.build import build
from pagan.exporters.godot import find_godot_binary, res_path, verify_with_godot
from pagan.importer import import_png, sprite_yaml
from pagan.lint import lint_paths
from pagan.manage import Adjustment, adjust_colors, apply_palette_hexes, bump_style, catalogue, mark, outdated
from pagan.palette import NAME_RE, PALETTE_SUFFIX, Palette, load_palette_file
from pagan.project import CONFIG_NAME, Project, discover_project, find_project_root, load_project
from pagan.preview import PreviewOptions, gallery, write_previews
from pagan.render import frame_image, save_png, sheet_image
from pagan.settings import BY_KEY, describe, set_setting
from pagan.swatch import render_swatch


class Output:
    """Human-readable output by default; one JSON object on stdout with --json."""

    def __init__(self, as_json: bool) -> None:
        self.as_json = as_json

    def say(self, text: str) -> None:
        if not self.as_json:
            print(text)

    def result(self, data: dict[str, Any]) -> None:
        if self.as_json:
            print(json.dumps({"ok": True, **data}, indent=2))

    def failure(self, findings: list[Finding], data: dict[str, Any] | None = None) -> None:
        if self.as_json:
            print(json.dumps({"ok": False, **(data or {}), "findings": [f.to_dict() for f in findings]}, indent=2))
        else:
            for finding in findings:
                print(finding.format())


def _usage_error(message: str, path: Path | None = None) -> PaganError:
    return PaganError([Finding("E000", message, path)])


def _template(name: str) -> str:
    return files("pagan").joinpath("templates", name).read_text(encoding="utf-8")


def _require_project() -> Project:
    root = find_project_root(Path.cwd())
    if root is None:
        raise _usage_error(f"no {CONFIG_NAME} found here or in any parent directory; run `pagan init` first")
    return load_project(root)


# --- pagan init -------------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace, out: Output) -> int:
    root = Path(args.dir)
    config_path = root / CONFIG_NAME
    if config_path.exists():
        raise _usage_error("a PAGAN project already exists here", config_path)

    root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    skipped: list[Path] = []

    mode = "open" if args.open else "strict"
    config_path.write_text(Template(_template("pagan.toml")).substitute(palette_mode=mode), encoding="utf-8")
    created.append(config_path)

    for name, content in (
        ("STYLE.md", _template("STYLE.md")),
        ("BRIEF.md", _template("BRIEF.md")),
        (".gitignore", "previews/\n.pagan-cache/\n"),
    ):
        path = root / name
        if path.exists():
            skipped.append(path)
        else:
            path.write_text(content, encoding="utf-8")
            created.append(path)

    for name in ("palettes", "sprites", "tiles", "models"):
        path = root / name
        if path.is_dir():
            skipped.append(path)
        else:
            path.mkdir()
            created.append(path)

    out.say(f"Initialized PAGAN project in {display_path(root)} ({mode} palette mode)")
    for path in created:
        out.say(f"  created {display_path(path)}")
    for path in skipped:
        out.say(f"  kept existing {display_path(path)}")
    if mode == "strict":
        out.say("Next: `pagan new palette <name>`, then set default_palette in pagan.toml.")
    out.result(
        {
            "project": display_path(root),
            "palette_mode": mode,
            "created": [display_path(p) for p in created],
            "skipped": [display_path(p) for p in skipped],
        }
    )
    return 0


# --- pagan new palette ------------------------------------------------------------------------

_PALETTE_STARTER = """\
name: $name
# Each key is ONE character used in pixel grids: 0-9, a-z, A-Z. "." is reserved for transparent.
# Quote keys and hex values: YAML treats an unquoted # as the start of a comment.
colors:
  "0": { hex: "#1a1c2c", name: ink }
  "1": { hex: "#5d5d72", name: gray }
  "2": { hex: "#a0a0b4", name: silver }
  "3": { hex: "#f4f4f4", name: white }
ramps:
  # shadow -> mid -> highlight
  gray: ["0", "1", "2", "3"]
"""


def cmd_new_palette(args: argparse.Namespace, out: Output) -> int:
    name: str = args.name
    if not NAME_RE.match(name):
        raise _usage_error(f"invalid palette name {name!r}: use lowercase letters, digits, '_' or '-'")
    project = _require_project()
    path = project.palette_path(name)
    if path.exists():
        raise _usage_error("palette already exists", path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(Template(_PALETTE_STARTER).substitute(name=name), encoding="utf-8")

    out.say(f"created {display_path(path)}")
    if project.config.default_palette is None:
        out.say(f'Set default_palette = "{name}" in {CONFIG_NAME} to use it for sprites by default.')
    out.result({"created": display_path(path), "palette": name})
    return 0


# --- pagan new sprite / tiles ----------------------------------------------------------------

_INLINE_PALETTE_STARTER = """\
palette:                  # inline palette (open mode); or name a palette file instead
  colors:
    "0": { hex: "#1a1c2c", name: ink }
    "1": { hex: "#5d5d72", name: shadow }
    "2": { hex: "#a0a0b4", name: mid }
    "3": { hex: "#f4f4f4", name: light }
  ramps:
    main: ["0", "1", "2", "3"]
"""


def _parse_size_arg(text: str) -> tuple[int, int]:
    parts = text.lower().split("x")
    if len(parts) != 2 or not all(p.isdigit() and 0 < int(p) <= 1024 for p in parts):
        raise _usage_error(f"invalid size {text!r}: use WIDTHxHEIGHT, e.g. 16x16")
    return int(parts[0]), int(parts[1])


def _palette_lines(project: Project, palette: str | None) -> str:
    if palette is not None:
        project.load_palette(palette)  # fail early on a typo
        return f"palette: {palette}\n"
    if project.config.default_palette is not None:
        return f"# palette: {project.config.default_palette}   (project default)\n"
    if project.config.palette_mode == "open":
        return _INLINE_PALETTE_STARTER
    raise _usage_error("no --palette given and pagan.toml has no default_palette")


def _blank(width: int, height: int, indent: str) -> str:
    return "".join(f"{indent}{'.' * width}\n" for _ in range(height))


def cmd_new_asset(args: argparse.Namespace, out: Output) -> int:
    kind: str = args.kind
    name: str = args.name
    if not NAME_RE.match(name):
        raise _usage_error(f"invalid name {name!r}: use lowercase letters, digits, '_' or '-'")
    project = _require_project()
    width, height = _parse_size_arg(args.size)
    count: int = args.frames
    if count < 1:
        raise _usage_error("--frames must be at least 1")
    description = args.description or "TODO: what this is and what it should look like"

    lines = [f"name: {name}", f"description: {json.dumps(description)}", _palette_lines(project, args.palette).rstrip("\n")]
    if kind == "sprite":
        authored = -(-width // 2) if args.mirror else width
        lines += [
            f"size: [{width}, {height}]",
            f"pivot: [{width // 2}, {height}]      # anchor point (feet): x, y from the top-left corner",
            f"mirror: {'horizontal' if args.mirror else 'none'}" + (f"       # author only the left {authored} columns" if args.mirror else ""),
            f"outline: {'auto' if args.outline else 'none'}",
            "status: draft",
            f"style_version: {project.config.style_version}",
            "tags: []",
            "frames:",
        ]
        frame_names = [f"idle_{i}" for i in range(count)] if count > 1 else ["main"]
        body = "\n".join(lines) + "\n" + "".join(f"  {f}: |\n{_blank(authored, height, '    ')}" for f in frame_names)
        if count > 1:
            body += f"animations:\n  idle: {{ frames: [{', '.join(frame_names)}], fps: 4, loop: true }}\n"
        path = project.sprites_dir / f"{name}{SPRITE_SUFFIX}"
    else:
        lines += [
            f"tile_size: [{width}, {height}]",
            "columns: 8",
            "status: draft",
            f"style_version: {project.config.style_version}",
            "tags: []",
            "tiles:",
        ]
        body = "\n".join(lines) + "\n" + "".join(f"  tile_{i}: |\n{_blank(width, height, '    ')}" for i in range(count))
        path = project.tiles_dir / f"{name}{TILESET_SUFFIX}"

    if path.exists():
        raise _usage_error("file already exists", path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    out.say(f"created {display_path(path)}")
    out.result({"created": display_path(path), "kind": kind, "name": name})
    return 0


# --- pagan new model / pagan bake -------------------------------------------------------------


def cmd_new_model(args: argparse.Namespace, out: Output) -> int:
    name: str = args.name
    if not NAME_RE.match(name):
        raise _usage_error(f"invalid name {name!r}: use lowercase letters, digits, '_' or '-'")
    project = _require_project()
    width, height = _parse_size_arg(args.size)
    palette_name = args.palette or project.config.default_palette
    if palette_name is None:
        raise _usage_error("no --palette given and pagan.toml has no default_palette")
    palette = project.load_palette(palette_name)
    if not palette.ramps:
        raise _usage_error(f"palette {palette_name!r} has no ramps; models shade with ramps")
    ramps = list(palette.ramps)
    main_ramp, accent_ramp = ramps[0], ramps[min(1, len(ramps) - 1)]
    if args.directions not in (1, 4, 8, 16):
        raise _usage_error("--directions must be 1, 4, 8 or 16")
    description = args.description or "TODO: what this is and what it should look like"
    text = f"""name: {name}
description: {json.dumps(description)}
palette: {palette_name}
size: [{width}, {height}]
pivot: [{width // 2}, {round(height * 0.62)}]     # where `origin` lands in each frame
origin: [0, 0, 0]                 # model point (x forward, y left, z up) placed on the pivot
directions: {args.directions}                     # 1, 4, 8 or 16 headings -> frames e, ne, n, ...
outline: auto
status: draft
style_version: {project.config.style_version}
tags: []

# Materials shade with a palette ramp (dark -> light) under the project's light ([light] in pagan.toml).
materials:
  body:   {{ ramp: {main_ramp} }}
  accent: {{ ramp: {accent_ramp} }}

# Shapes: box, hull, cylinder, ellipsoid, line, sail, layers. Whole voxels; x forward, y left, z up.
# Per part: `mirror: true` reflects across y = 0, `carve: true` removes voxels, `id:` names it for poses.
parts:
  - box: {{ from: [-4, -3, 0], to: [4, 3, 5], material: body, top: accent }}

# animations:
#   bob:
#     fps: 6
#     poses:                # one pose per frame; parts with an id move by whole voxels
#       - {{}}
#       - {{ lid: {{ offset: [0, 0, 1] }} }}
"""
    path = project.models_dir / f"{name}{MODEL_SUFFIX}"
    if path.exists():
        raise _usage_error("file already exists", path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    out.say(f"created {display_path(path)}")
    out.result({"created": display_path(path), "kind": "model", "name": name})
    return 0


def cmd_bake(args: argparse.Namespace, out: Output) -> int:
    project = project_for([args.model])
    asset = load_asset_or_raise(resolve_asset_path(args.model, project), project)
    if asset.kind != "model":
        raise _usage_error(f"{asset.name} is a {asset.kind}, not a model")
    name = args.name or asset.name
    if not NAME_RE.match(name):
        raise _usage_error(f"invalid name {name!r}")
    path = Path(args.out) if args.out else project.sprites_dir / f"{name}{SPRITE_SUFFIX}"
    if path.exists() and not args.force:
        raise _usage_error("file already exists (pass --force to overwrite)", path)
    lines = [
        f"name: {name}",
        f"description: {json.dumps(asset.description or '')}",
        f"palette: {asset.palette.name}" if asset.palette.name else "# palette: (inline palettes aren't baked)",
        f"size: [{asset.size[0]}, {asset.size[1]}]",
        f"pivot: [{asset.pivot[0]}, {asset.pivot[1]}]",
        "outline: none                  # the outline is already baked into the pixels",
        f"status: {asset.status}",
        f"style_version: {asset.style_version}",
        f"tags: [{', '.join([*asset.tags, 'baked'])}]",
        "frames:",
    ]
    for frame, grid in asset.frames.items():
        lines.append(f"  {frame}: |")
        lines.extend(f"    {row}" for row in grid)
    trivial = all(a.frames == (a.name,) for a in asset.animations.values()) and len(asset.frames) == 1
    if not trivial:
        lines.append("animations:")
    for anim in asset.animations.values() if not trivial else []:
        lines.append(
            f"  {anim.name}: {{ frames: [{', '.join(anim.frames)}], fps: {anim.fps:g}, loop: {'true' if anim.loop else 'false'} }}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out.say(f"baked {asset.name} ({len(asset.frames)} frames) -> {display_path(path)}")
    if name == asset.name:
        out.say(f"Asset names must be unique: rename or remove {display_path(asset.path) if asset.path else 'the model'} if you keep the bake.")
    out.result({"created": display_path(path), "frames": len(asset.frames)})
    return 0


# --- pagan render -----------------------------------------------------------------------------


def resolve_asset_path(target: str, project: Project) -> Path:
    """A path to an asset file, or a bare asset name looked up in sprites/ and tiles/."""
    path = Path(target)
    if path.is_file():
        return path
    if NAME_RE.match(target):
        for candidate in (
            project.sprites_dir / f"{target}{SPRITE_SUFFIX}",
            project.tiles_dir / f"{target}{TILESET_SUFFIX}",
            project.models_dir / f"{target}{MODEL_SUFFIX}",
        ):
            if candidate.is_file():
                return candidate
    raise _usage_error(f"no such asset: {target} (give a path, or the name of a file in sprites/, tiles/ or models/)")


def project_for(targets: list[str]) -> Project:
    """The project containing the first target that is an existing path; else the one at the cwd."""
    for target in targets:
        path = Path(target)
        if path.exists():
            return discover_project(path if path.is_dir() else path.parent)
    return discover_project()


def _load_targets(targets: list[str], project: Project) -> tuple[list[Asset], list[Finding]]:
    assets: list[Asset] = []
    findings: list[Finding] = []
    for target in targets:
        try:
            assets.append(load_asset_or_raise(resolve_asset_path(target, project), project))
        except PaganError as exc:
            findings.extend(exc.findings)
    return assets, findings


def cmd_render(args: argparse.Namespace, out: Output) -> int:
    project = project_for(args.assets)
    assets, findings = _load_targets(args.assets, project)
    outputs: list[dict[str, Any]] = []
    for asset in assets:
        base = project.preview_dir / asset.name / "native"
        written: list[str] = []
        for variant in (None, *asset.variants):
            folder = base if variant is None else base / variant
            for frame in asset.frames:
                path = folder / "frames" / f"{frame}.png"
                save_png(frame_image(asset, frame, variant), path)
                written.append(display_path(path))
            sheet = folder / "sheet.png"
            save_png(sheet_image(asset, variant), sheet)
            written.append(display_path(sheet))
        out.say(f"{asset.name}: wrote {len(written)} PNGs to {display_path(base)}")
        outputs.append({"asset": asset.name, "files": written})
    if findings:
        out.failure(findings, {"outputs": outputs})
        return 1
    out.result({"outputs": outputs})
    return 0


# --- pagan preview / gallery -----------------------------------------------------------------


def _preview_options(args: argparse.Namespace) -> PreviewOptions:
    background: str = args.bg
    if background not in ("checker", "none") and not re.fullmatch(r"#[0-9a-fA-F]{6}", background):
        raise _usage_error("--bg must be checker, none or #rrggbb")
    if args.scale is not None and not 1 <= args.scale <= 64:
        raise _usage_error("--scale must be between 1 and 64")
    return PreviewOptions(scale=args.scale, grid=args.grid, background=background)


def cmd_preview(args: argparse.Namespace, out: Output) -> int:
    project = project_for(args.assets)
    options = _preview_options(args)
    assets, findings = _load_targets(args.assets, project)
    outputs: list[dict[str, Any]] = []
    for asset in assets:
        result = write_previews(asset, project.preview_dir, options)
        out.say(f"{asset.name}: {display_path(result.sheet)}")
        for gif in result.gifs:
            out.say(f"  animation: {display_path(gif)}")
        out.say(f"  frames: {display_path(result.sheet.parent / 'frames')}/ ({len(result.frames)} PNGs)")
        outputs.append(
            {
                "asset": asset.name,
                "sheet": display_path(result.sheet),
                "gifs": [display_path(g) for g in result.gifs],
                "frames": [display_path(f) for f in result.frames],
            }
        )
    if findings:
        out.failure(findings, {"outputs": outputs})
        return 1
    out.result({"outputs": outputs})
    return 0


def cmd_gallery(args: argparse.Namespace, out: Output) -> int:
    project = discover_project()
    options = _preview_options(args)
    result = lint_paths(project)
    path = Path(args.out) if args.out else project.preview_dir / "gallery.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    gallery(result.assets, options, f"{project.root.name} gallery").save(path)
    out.say(f"wrote {display_path(path)} ({len(result.assets)} assets)")
    if result.errors:
        out.say(f"{len(result.errors)} errors: assets with errors are missing; run `pagan lint`")
    out.result({"gallery": display_path(path), "assets": len(result.assets), "errors": len(result.errors)})
    return 0


# --- pagan lint -------------------------------------------------------------------------------


def cmd_lint(args: argparse.Namespace, out: Output) -> int:
    project = project_for(args.paths)
    paths = [Path(p) for p in args.paths] or None
    missing = [p for p in paths or [] if not p.exists()]
    if missing:
        raise _usage_error(f"no such file or directory: {', '.join(map(str, missing))}")
    result = lint_paths(project, paths)
    failed = bool(result.errors) or (args.warnings_as_errors and bool(result.warnings))
    summary = f"{len(result.files)} files: {len(result.errors)} errors, {len(result.warnings)} warnings"
    if out.as_json:
        print(
            json.dumps(
                {
                    "ok": not failed,
                    "files": [display_path(f) for f in result.files],
                    "errors": len(result.errors),
                    "warnings": len(result.warnings),
                    "findings": [f.to_dict() for f in result.findings],
                },
                indent=2,
            )
        )
    else:
        for finding in result.findings:
            print(finding.format())
        print(summary)
    return 1 if failed else 0


# --- pagan build ------------------------------------------------------------------------------


def cmd_build(args: argparse.Namespace, out: Output) -> int:
    project = project_for([args.project] if args.project else [])
    if project.config_path is None:
        raise _usage_error(f"no {CONFIG_NAME} found; `pagan build` needs a project (run `pagan init`)")
    result = build(project)
    if result.errors:
        out.failure(result.errors)
        if not out.as_json:
            print("build failed: fix the errors above (`pagan lint` shows warnings too)")
        return 1
    warnings = result.lint.warnings
    out.say(f"built {len(result.lint.assets)} assets into {display_path(project.output_dir)}")
    out.say(f"  {len(result.written)} files written, {len(result.unchanged)} unchanged, {len(result.removed)} stale removed")
    if warnings:
        out.say(f"  {len(warnings)} lint warnings (run `pagan lint` to see them)")
    verified: bool | None = None
    if args.verify_godot:
        godot = find_godot_binary()
        if result.godot_root is None or result.manifest is None:
            raise _usage_error('--verify-godot needs export = ["godot"] in pagan.toml')
        if godot is None:
            raise _usage_error("--verify-godot: no Godot binary found; set GODOT=/path/to/godot or put godot on PATH")
        check = verify_with_godot(godot, result.godot_root, res_path(result.manifest, result.godot_root))
        verified = check.ok
        if check.ok:
            out.say("  Godot: every generated resource loads")
        else:
            if out.as_json:
                out.failure([Finding("E000", "Godot failed to load generated resources:\n" + check.output[-3000:])])
            else:
                print(check.output[-3000:])
                print("Godot verification FAILED")
            return 1
    out.result(
        {
            "output_dir": display_path(project.output_dir),
            "assets": len(result.lint.assets),
            "written": [display_path(p) for p in result.written],
            "unchanged": len(result.unchanged),
            "removed": [display_path(p) for p in result.removed],
            "warnings": len(warnings),
            "godot_verified": verified,
        }
    )
    return 0


# --- pagan import -----------------------------------------------------------------------------


def cmd_import(args: argparse.Namespace, out: Output) -> int:
    from PIL import Image, UnidentifiedImageError

    source = Path(args.png)
    project = discover_project()
    try:
        image = Image.open(source)
        image.load()
    except (OSError, UnidentifiedImageError) as exc:
        raise _usage_error(f"can't read image: {exc}", source) from None

    palette: Palette | None = None
    palette_name: str | None = args.palette
    if not args.open:
        palette_name = palette_name or project.config.default_palette
        if palette_name is None and project.config.palette_mode == "strict" and project.config_path is not None:
            raise _usage_error("no --palette given and pagan.toml has no default_palette (or pass --open)")
        if palette_name is not None:
            palette = project.load_palette(palette_name)

    name = args.name or re.sub(r"[^a-z0-9_-]+", "_", source.stem.lower()).strip("_") or "imported"
    if not NAME_RE.match(name):
        raise _usage_error(f"invalid name {name!r}: pass --name")
    if args.scale is not None and args.scale < 1:
        raise _usage_error("--scale must be at least 1")
    if not 1 <= args.max_colors <= 62:
        raise _usage_error("--max-colors must be 1-62 (palette keys are single characters)")
    if not 0 <= args.alpha_threshold <= 255:
        raise _usage_error("--alpha-threshold must be 0-255")
    rows, inline, report = import_png(
        image, palette=palette, scale=args.scale, alpha_threshold=args.alpha_threshold, max_colors=args.max_colors
    )
    if not rows or not rows[0]:
        raise _usage_error("image is empty after downscaling")

    path = Path(args.out) if args.out else project.sprites_dir / f"{name}{SPRITE_SUFFIX}"
    if path.exists() and not args.force:
        raise _usage_error("file already exists (pass --force to overwrite)", path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sprite_yaml(name, rows, palette_name if palette else None, inline, source), encoding="utf-8")

    w, h = report.size
    out.say(f"imported {display_path(source)} -> {display_path(path)}")
    out.say(f"  size: {report.source_size[0]}x{report.source_size[1]}, scale {report.scale} -> {w}x{h}, {report.opaque_pixels} opaque pixels")
    if palette is not None:
        out.say(
            f"  snapped {report.source_colors} colors to palette {palette_name!r}: {report.changed_pixels} pixels changed, "
            f"worst color distance {report.max_distance:.3f} (OKLab; <0.02 is invisible, >0.1 is obvious)"
        )
        for src, (key, d) in sorted(report.mapping.items(), key=lambda item: -item[1][1]):
            if d > 0:
                out.say(f"    {src} -> {key!r} ({palette.colors[key].hex}, distance {d:.3f})")
    else:
        reduced = f", reduced from {report.reduced_from} ({report.changed_pixels} pixels changed)" if report.reduced_from else ""
        out.say(f"  inline palette with {len(inline or {})} colors{reduced}")
    out.result(
        {
            "created": display_path(path),
            "name": name,
            "scale": report.scale,
            "size": [w, h],
            "source_colors": report.source_colors,
            "changed_pixels": report.changed_pixels,
            "max_distance": round(report.max_distance, 4),
            "mapping": {k: {"key": v[0], "distance": v[1]} for k, v in report.mapping.items()},
            "palette": palette_name if palette else None,
        }
    )
    return 0


# --- pagan status / mark / style bump ---------------------------------------------------------


def cmd_status(args: argparse.Namespace, out: Output) -> int:
    project = project_for([args.project] if args.project else [])
    if project.config_path is None:
        raise _usage_error(
            f"no {CONFIG_NAME} found here or in any parent directory: this isn't a PAGAN project yet "
            "(run `pagan init <dir>`, or cd into the art folder)"
        )
    entries = catalogue(project)
    current = project.config.style_version
    if out.as_json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "project": display_path(project.root),
                    "style_version": current,
                    "default_palette": project.config.default_palette,
                    "assets": [
                        {
                            "name": e.name, "kind": e.kind, "path": display_path(e.path), "description": e.description,
                            "status": e.status, "style_version": e.style_version,
                            "size": list(e.size) if e.size else None, "frames": e.frames, "animations": e.animations,
                            "errors": e.errors, "warnings": e.warnings, "tags": list(e.tags), "needs": e.needs(current),
                        }  # fmt: skip
                        for e in entries
                    ],
                },
                indent=2,
            )
        )
        return 0
    palette = project.config.default_palette or ("open mode" if project.config.palette_mode == "open" else "none")
    print(f"{display_path(project.root)}: {len(entries)} assets, palette {palette}, style v{current}")
    for e in entries:
        size = f"{e.size[0]}x{e.size[1]}" if e.size else "?"
        flags = ", ".join(e.needs(current)) or "ok"
        description = (e.description or "").replace("\n", " ")
        print(f"  {e.name:<20} {e.kind:<8} {size:>7}  {e.status:<8} v{e.style_version}  [{flags}]")
        if description:
            print(f"      {description[:100]}{'…' if len(description) > 100 else ''}")
    stale = [e for e in entries if e.style_version < current]
    if stale:
        print(f"{len(stale)} assets predate style v{current}: see the STYLE.md changelog, update them, then `pagan mark --current <asset>`")
    return 0


def cmd_mark(args: argparse.Namespace, out: Output) -> int:
    project = project_for(args.assets if not args.outdated else [])
    if args.outdated:
        paths = outdated(project)
    else:
        if not args.assets:
            raise _usage_error("name the assets to mark (or pass --outdated)")
        paths = [resolve_asset_path(a, project) for a in args.assets]
    if args.status is None and not args.current:
        raise _usage_error("nothing to do: pass --status approved|draft and/or --current")
    mark(paths, args.status, project.config.style_version if args.current else None)
    for path in paths:
        out.say(f"marked {display_path(path)}")
    out.result({"marked": [display_path(p) for p in paths]})
    return 0


def cmd_style_bump(args: argparse.Namespace, out: Output) -> int:
    project = _require_project()
    version = bump_style(project, args.note)
    stale = len(outdated(load_project(project.root)))
    out.say(f"style is now v{version}; logged in STYLE.md. {stale} assets are flagged for review (lint W006, `pagan status`).")
    out.result({"style_version": version, "outdated": stale})
    return 0


# --- pagan palette adjust ---------------------------------------------------------------------


def cmd_palette_adjust(args: argparse.Namespace, out: Output) -> int:
    from PIL import Image

    project = _require_project()
    palette = project.load_palette(args.palette)
    if palette.path is None:
        raise _usage_error("palette has no file")
    keys = list(palette.colors)
    if args.ramp:
        unknown = [r for r in args.ramp if r not in palette.ramps]
        if unknown:
            raise _usage_error(f"unknown ramp(s) {', '.join(unknown)}; palette ramps: {', '.join(palette.ramps)}")
        keys = [k for k in keys if any(k in palette.ramps[r] for r in args.ramp)]
    if args.keys:
        unknown = [k for k in args.keys if k not in palette.colors]
        if unknown:
            raise _usage_error(f"unknown key(s) {', '.join(unknown)}")
        keys = [k for k in keys if k in args.keys]
    adjustment = Adjustment(
        lightness=args.lightness, contrast=args.contrast, saturation=args.saturation, hue=args.hue, warmth=args.warmth
    )
    if adjustment.is_identity():
        raise _usage_error("nothing to change: pass --lightness, --contrast, --saturation, --hue and/or --warmth")
    new_hexes = adjust_colors(palette, keys, adjustment)
    target_name = args.out or palette.name or args.palette
    if not NAME_RE.match(target_name):
        raise _usage_error(f"invalid palette name {target_name!r}")
    text = apply_palette_hexes(palette.path, new_hexes, new_name=args.out)
    target = project.palette_path(target_name)

    changes = {k: (palette.colors[k].hex, h) for k, h in new_hexes.items() if palette.colors[k].hex != h}
    for key, (old, new) in changes.items():
        out.say(f"  {key}: {old} -> {new}")
    compare = project.preview_dir / "palettes" / f"{target_name}-adjust.png"
    if not args.dry_run:
        if args.out and target.exists() and not args.force:
            raise _usage_error("palette already exists (pass --force to overwrite)", target)
        target.write_text(text, encoding="utf-8")
        adjusted = load_palette_file(target)
        before, after = render_swatch(palette, f"{args.palette} (before)"), render_swatch(adjusted, f"{target_name} (after)")
        both = Image.new("RGB", (max(before.width, after.width), before.height + after.height))
        both.paste(before, (0, 0))
        both.paste(after, (0, before.height))
        compare.parent.mkdir(parents=True, exist_ok=True)
        both.save(compare)
        out.say(f"{'wrote' if args.out else 'updated'} {display_path(target)} ({len(changes)} colors changed); before/after: {display_path(compare)}")
        if not args.out:
            out.say("Every asset using this palette now uses the new colors; check with `pagan gallery`.")
    else:
        out.say(f"dry run: {len(changes)} colors would change")
    out.result(
        {
            "palette": target_name,
            "changes": {k: {"from": a, "to": b} for k, (a, b) in changes.items()},
            "written": not args.dry_run,
            "compare": None if args.dry_run else display_path(compare),
        }
    )
    return 0


# --- pagan config ---------------------------------------------------------------------------


def cmd_config_show(args: argparse.Namespace, out: Output) -> int:
    project = _require_project()
    rows = describe(project.config)
    if out.as_json:
        print(json.dumps({"ok": True, "config": display_path(project.config_path or project.root), "settings": rows}, indent=2))
        return 0
    print(f"{display_path(project.config_path or project.root)}  (change with `pagan config set <key> <value>`)")
    for row in rows:
        marker = " " if row["is_default"] else "*"
        print(f"{marker} {row['key']:<26} = {json.dumps(row['value']):<22} {row['meaning']}")
    print("* = changed from the default. 'models' settings re-render every 3D model on the next build/preview.")
    return 0


def cmd_config_get(args: argparse.Namespace, out: Output) -> int:
    project = _require_project()
    if args.key not in BY_KEY:
        raise _usage_error(f"unknown setting {args.key!r}; see `pagan config show`")
    row = next(r for r in describe(project.config) if r["key"] == args.key)
    out.say(json.dumps(row["value"]))
    out.result(row)
    return 0


def cmd_config_set(args: argparse.Namespace, out: Output) -> int:
    from pagan.manage import catalogue

    project = _require_project()
    change = set_setting(project, args.key, args.value)
    updated = load_project(project.root)
    entries = catalogue(updated)
    models = [e.name for e in entries if e.kind == "model"]
    hand_drawn = [e.name for e in entries if e.kind != "model"]
    errors = sum(e.errors for e in entries)
    out.say(f"{change.key}: {json.dumps(change.old)} -> {json.dumps(change.new)}  (saved in {CONFIG_NAME})")
    if change.refresh == "models":
        out.say(f"  {len(models)} 3D models will re-render with this on the next `pagan build` / `pagan preview`.")
        if hand_drawn:
            out.say(
                f"  {len(hand_drawn)} 2D sprites/tiles are hand-drawn and won't change; if they must match "
                "(e.g. a new camera angle or light direction), `pagan style bump \"...\"` and redraw them."
            )
    elif change.refresh == "all":
        out.say(f"  every asset using the default palette recolors on the next build ({len(entries)} assets).")
    elif change.refresh == "build":
        out.say("  takes effect on the next `pagan build`.")
    if errors:
        out.say(f"  {errors} lint errors now (e.g. palette keys missing from the new palette): run `pagan lint`.")
    out.result(
        {
            "key": change.key,
            "old": change.old,
            "new": change.new,
            "refreshes": change.refresh,
            "models": models,
            "hand_drawn": hand_drawn,
            "errors": errors,
        }
    )
    return 0


# --- pagan skill install ----------------------------------------------------------------------

SKILL_FILES = ("SKILL.md", "reference.md")


def _git_root(start: Path) -> Path | None:
    for directory in (start.resolve(), *start.resolve().parents):
        if (directory / ".git").exists():
            return directory
    return None


def cmd_skill_install(args: argparse.Namespace, out: Output) -> int:
    base = Path(args.dir) if args.dir else (_git_root(Path.cwd()) or Path.cwd())
    target = base / ".claude" / "skills" / "pagan"
    target.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name in SKILL_FILES:
        text = files("pagan").joinpath("skill", name).read_text(encoding="utf-8")
        path = target / name
        if path.exists() and path.read_text(encoding="utf-8") == text:
            continue
        path.write_text(text, encoding="utf-8")
        written.append(display_path(path))
    out.say(f"PAGAN skill {'installed' if written else 'already up to date'} in {display_path(target)}")
    out.result({"skill_dir": display_path(target), "written": written})
    return 0


# --- pagan palette show -----------------------------------------------------------------------


def _resolve_palette(target: str, project: Project) -> Palette:
    path = Path(target)
    if path.is_file():
        return load_palette_file(path)
    if target.endswith(PALETTE_SUFFIX) or "/" in target:
        raise _usage_error(f"no such file: {target}")
    if project.config_path is None:
        raise _usage_error(f"{target!r} isn't a file, and there's no {CONFIG_NAME} to look up palette names in")
    return project.load_palette(target)


def cmd_palette_show(args: argparse.Namespace, out: Output) -> int:
    project = discover_project()
    targets: list[str] = args.palettes or project.palette_names()
    if not targets:
        raise _usage_error(f"no palettes found in {display_path(project.palettes_dir)}")
    if args.out is not None and len(targets) != 1:
        raise _usage_error("--out works with exactly one palette")

    outputs: list[dict[str, Any]] = []
    findings: list[Finding] = []
    for target in targets:
        try:
            palette = _resolve_palette(target, project)
        except PaganError as exc:
            findings.extend(exc.findings)
            continue
        stem = palette.name or Path(target).stem
        path = Path(args.out) if args.out else project.preview_dir / "palettes" / f"{stem}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        render_swatch(palette).save(path, format="PNG")
        outputs.append(
            {"palette": palette.name, "path": display_path(path), "colors": len(palette.colors), "ramps": len(palette.ramps)}
        )
        out.say(f"wrote {display_path(path)} ({len(palette.colors)} colors, {len(palette.ramps)} ramps)")

    if findings:
        out.failure(findings, {"outputs": outputs})
        return 1
    out.result({"outputs": outputs})
    return 0


# --- parser -----------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable JSON output")

    parser = argparse.ArgumentParser(
        prog="pagan",
        description="PAGAN (Pixel Art Grammar And Notation): turn text pixel art into PNGs.",
    )
    parser.add_argument("--version", action="version", version=f"pagan {__version__}")
    commands = parser.add_subparsers(title="commands", metavar="<command>")

    init = commands.add_parser("init", parents=[common], help="create a PAGAN project")
    init.add_argument("dir", nargs="?", default=".", help="project directory (default: current)")
    init.add_argument("--open", action="store_true", help="open palette mode: sprites may define inline palettes")
    init.set_defaults(handler=cmd_init)

    new = commands.add_parser("new", help="scaffold a new source file")
    new_kinds = new.add_subparsers(title="kinds", metavar="<kind>", required=True)
    new_palette = new_kinds.add_parser("palette", parents=[common], help="scaffold a palette file")
    new_palette.add_argument("name", help="palette name, e.g. dusk")
    new_palette.set_defaults(handler=cmd_new_palette)

    for kind, help_text in (("sprite", "scaffold a sprite"), ("tiles", "scaffold a tileset")):
        sub = new_kinds.add_parser(kind, parents=[common], help=help_text)
        sub.add_argument("name", help="asset name, e.g. slime")
        sub.add_argument("--size", default="16x16", help="WIDTHxHEIGHT of one frame/tile (default 16x16)")
        sub.add_argument("--palette", help="palette name (default: the project's default_palette)")
        sub.add_argument("--frames", type=int, default=1, help="number of blank frames/tiles (default 1)")
        sub.add_argument("--description", help="what the asset is; kept in the file for future reference")
        if kind == "sprite":
            sub.add_argument("--mirror", action="store_true", help="symmetric: author only the left half")
            sub.add_argument("--outline", action="store_true", help="outline: auto (1px outline added by PAGAN)")
        else:
            sub.set_defaults(mirror=False, outline=False)
        sub.set_defaults(handler=cmd_new_asset, kind="sprite" if kind == "sprite" else "tileset")

    new_model = new_kinds.add_parser("model", parents=[common], help="scaffold a 3D voxel model")
    new_model.add_argument("name", help="model name, e.g. ship")
    new_model.add_argument("--size", default="64x64", help="frame size WIDTHxHEIGHT (default 64x64)")
    new_model.add_argument("--palette", help="palette name (default: the project's default_palette)")
    new_model.add_argument("--directions", type=int, default=8, help="headings to render: 1, 4, 8 or 16 (default 8)")
    new_model.add_argument("--description", help="what the asset is; kept in the file for future reference")
    new_model.set_defaults(handler=cmd_new_model)

    bake = commands.add_parser("bake", parents=[common], help="write a model's rendered frames as an editable sprite")
    bake.add_argument("model", help="model file or name")
    bake.add_argument("--name", help="sprite name (default: the model's name)")
    bake.add_argument("--out", help="output path (default: sprites/<name>.sprite.yaml)")
    bake.add_argument("--force", action="store_true", help="overwrite an existing file")
    bake.set_defaults(handler=cmd_bake)

    render = commands.add_parser("render", parents=[common], help="render assets to native-size PNGs")
    render.add_argument("assets", nargs="+", help="asset files or names")
    render.set_defaults(handler=cmd_render)

    build_cmd = commands.add_parser("build", parents=[common], help="lint, then write final assets to output_dir")
    build_cmd.add_argument("project", nargs="?", help="project directory (default: the one containing the cwd)")
    build_cmd.add_argument("--verify-godot", action="store_true", help="load every generated resource in headless Godot")
    build_cmd.set_defaults(handler=cmd_build)

    imp = commands.add_parser("import", parents=[common], help="convert a PNG into a sprite source file")
    imp.add_argument("png", help="image to import")
    imp.add_argument("--palette", help="snap colors to this palette (default: the project's default_palette)")
    imp.add_argument("--open", action="store_true", help="keep the image's own colors as an inline palette")
    imp.add_argument("--scale", type=int, help="upscale factor to undo (default: detect)")
    imp.add_argument("--alpha-threshold", type=int, default=128, help="alpha below this is transparent (default 128)")
    imp.add_argument("--max-colors", type=int, default=32, help="open mode: reduce to at most this many colors (max 62)")
    imp.add_argument("--name", help="asset name (default: from the file name)")
    imp.add_argument("--out", help="output path (default: sprites/<name>.sprite.yaml)")
    imp.add_argument("--force", action="store_true", help="overwrite an existing file")
    imp.set_defaults(handler=cmd_import)

    view = argparse.ArgumentParser(add_help=False)
    view.add_argument("--scale", type=int, help="pixel scale (default: automatic, about 256px per frame)")
    view.add_argument("--grid", action="store_true", help="draw pixel grid lines")
    view.add_argument("--bg", default="checker", help="background: checker (default), none, or #rrggbb")

    preview = commands.add_parser(
        "preview", parents=[common, view], help="upscaled previews: contact sheet, frames, animated GIFs"
    )
    preview.add_argument("assets", nargs="+", help="asset files or names")
    preview.set_defaults(handler=cmd_preview)

    gallery_cmd = commands.add_parser(
        "gallery", parents=[common, view], help="every asset side by side at one common scale (default: largest ~192px)"
    )
    gallery_cmd.add_argument("--out", help="output PNG path (default: <previews>/gallery.png)")
    gallery_cmd.set_defaults(handler=cmd_gallery)

    lint = commands.add_parser("lint", parents=[common], help="check source files for errors and style warnings")
    lint.add_argument("paths", nargs="*", help="files or directories (default: the whole project)")
    lint.add_argument("--warnings-as-errors", action="store_true", help="exit non-zero on warnings too")
    lint.set_defaults(handler=cmd_lint)

    status = commands.add_parser("status", parents=[common], help="catalogue of every asset and what needs attention")
    status.add_argument("project", nargs="?", help="project directory (default: the one containing the cwd)")
    status.set_defaults(handler=cmd_status)

    mark_cmd = commands.add_parser("mark", parents=[common], help="set assets' status and/or stamp the current style version")
    mark_cmd.add_argument("assets", nargs="*", help="asset files or names")
    mark_cmd.add_argument("--status", choices=["draft", "approved"], help="set status")
    mark_cmd.add_argument("--current", action="store_true", help="set style_version to the project's current one")
    mark_cmd.add_argument("--outdated", action="store_true", help="apply to every asset made under an older style")
    mark_cmd.set_defaults(handler=cmd_mark)

    style = commands.add_parser("style", help="style versioning")
    style_cmds = style.add_subparsers(title="style commands", metavar="<subcommand>", required=True)
    bump_cmd = style_cmds.add_parser("bump", parents=[common], help="record a style change; flags older assets for review")
    bump_cmd.add_argument("note", help='what changed, e.g. "more shadows: ambient 0.2 -> 0.1"')
    bump_cmd.set_defaults(handler=cmd_style_bump)

    config = commands.add_parser("config", help="project settings (camera, light, palette, ...): show, get, set")
    config_cmds = config.add_subparsers(title="config commands", metavar="<subcommand>", required=True)
    config_show = config_cmds.add_parser("show", parents=[common], help="every setting: value, default, meaning")
    config_show.set_defaults(handler=cmd_config_show)
    config_get = config_cmds.add_parser("get", parents=[common], help="one setting's value")
    config_get.add_argument("key", help="e.g. camera.elevation")
    config_get.set_defaults(handler=cmd_config_get)
    config_set = config_cmds.add_parser("set", parents=[common], help="change a setting (validated, saved in pagan.toml)")
    config_set.add_argument("key", help="e.g. camera.elevation")
    config_set.add_argument("value", help='TOML value, e.g. 30, true, "tide", [-0.5, 0.45, 0.75]')
    config_set.set_defaults(handler=cmd_config_set)

    skill = commands.add_parser("skill", help="the Claude skill that teaches agents to use PAGAN")
    skill_cmds = skill.add_subparsers(title="skill commands", metavar="<subcommand>", required=True)
    skill_install = skill_cmds.add_parser("install", parents=[common], help="install into <repo>/.claude/skills/pagan/")
    skill_install.add_argument("dir", nargs="?", help="repo root (default: the git root containing the cwd)")
    skill_install.set_defaults(handler=cmd_skill_install)

    palette = commands.add_parser("palette", help="palette tools")
    palette_cmds = palette.add_subparsers(title="palette commands", metavar="<subcommand>", required=True)
    show = palette_cmds.add_parser("show", parents=[common], help="render palettes as swatch images")
    show.add_argument("palettes", nargs="*", help="palette names or .pal.yaml paths (default: all in the project)")
    show.add_argument("--out", help="output PNG path (single palette only)")
    show.set_defaults(handler=cmd_palette_show)

    adjust = palette_cmds.add_parser(
        "adjust", parents=[common], help="shift a palette's look (darker, more contrast, pastel, warmer...)"
    )
    adjust.add_argument("palette", help="palette name")
    adjust.add_argument("--lightness", type=float, default=0.0, help="add to lightness, e.g. -0.05 (darker) or 0.05")
    adjust.add_argument("--contrast", type=float, default=1.0, help="spread lightness, e.g. 1.2 (more) or 0.8 (less)")
    adjust.add_argument("--saturation", type=float, default=1.0, help="scale colorfulness, e.g. 0.6 (pastel/muted) or 1.2")
    adjust.add_argument("--hue", type=float, default=0.0, help="rotate hue by degrees")
    adjust.add_argument("--warmth", type=float, default=0.0, help="push towards warm (+) or cool (-), e.g. 0.02")
    adjust.add_argument("--ramp", action="append", help="only colors in this ramp (repeatable)")
    adjust.add_argument("--keys", nargs="+", help="only these color keys")
    adjust.add_argument("--out", help="write a new palette with this name instead of editing in place")
    adjust.add_argument("--force", action="store_true", help="overwrite --out if it exists")
    adjust.add_argument("--dry-run", action="store_true", help="show the changes without writing")
    adjust.set_defaults(handler=cmd_palette_adjust)

    return parser


Handler = Callable[[argparse.Namespace, Output], int]


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: Handler | None = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    out = Output(as_json=getattr(args, "json", False))
    try:
        return handler(args, out)
    except PaganError as exc:
        out.failure(exc.findings)
        return 1
