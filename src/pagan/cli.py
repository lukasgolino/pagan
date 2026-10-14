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
from pagan.asset import SPRITE_SUFFIX, TILESET_SUFFIX, Asset, load_asset_or_raise
from pagan.findings import Finding, PaganError, display_path
from pagan.importer import import_png, sprite_yaml
from pagan.lint import lint_paths
from pagan.palette import NAME_RE, PALETTE_SUFFIX, Palette, load_palette_file
from pagan.project import CONFIG_NAME, Project, discover_project, find_project_root, load_project
from pagan.preview import PreviewOptions, gallery, write_previews
from pagan.render import frame_image, save_png, sheet_image
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

    for name, content in (("STYLE.md", _template("STYLE.md")), (".gitignore", "previews/\n")):
        path = root / name
        if path.exists():
            skipped.append(path)
        else:
            path.write_text(content, encoding="utf-8")
            created.append(path)

    for name in ("palettes", "sprites", "tiles"):
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


# --- pagan render -----------------------------------------------------------------------------


def resolve_asset_path(target: str, project: Project) -> Path:
    """A path to an asset file, or a bare asset name looked up in sprites/ and tiles/."""
    path = Path(target)
    if path.is_file():
        return path
    if NAME_RE.match(target):
        for candidate in (project.sprites_dir / f"{target}{SPRITE_SUFFIX}", project.tiles_dir / f"{target}{TILESET_SUFFIX}"):
            if candidate.is_file():
                return candidate
    raise _usage_error(f"no such asset: {target} (give a path, or the name of a file in sprites/ or tiles/)")


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

    render = commands.add_parser("render", parents=[common], help="render assets to native-size PNGs")
    render.add_argument("assets", nargs="+", help="asset files or names")
    render.set_defaults(handler=cmd_render)

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

    gallery_cmd = commands.add_parser("gallery", parents=[common, view], help="every asset side by side in one image")
    gallery_cmd.add_argument("--out", help="output PNG path (default: <previews>/gallery.png)")
    gallery_cmd.set_defaults(handler=cmd_gallery)

    lint = commands.add_parser("lint", parents=[common], help="check source files for errors and style warnings")
    lint.add_argument("paths", nargs="*", help="files or directories (default: the whole project)")
    lint.add_argument("--warnings-as-errors", action="store_true", help="exit non-zero on warnings too")
    lint.set_defaults(handler=cmd_lint)

    palette = commands.add_parser("palette", help="palette tools")
    palette_cmds = palette.add_subparsers(title="palette commands", metavar="<subcommand>", required=True)
    show = palette_cmds.add_parser("show", parents=[common], help="render palettes as swatch images")
    show.add_argument("palettes", nargs="*", help="palette names or .pal.yaml paths (default: all in the project)")
    show.add_argument("--out", help="output PNG path (single palette only)")
    show.set_defaults(handler=cmd_palette_show)

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
