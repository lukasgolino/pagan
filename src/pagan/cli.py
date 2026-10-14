"""Command-line interface for PAGAN."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from importlib.resources import files
from pathlib import Path
from string import Template
from typing import Any

from pagan import __version__
from pagan.findings import Finding, PaganError, display_path
from pagan.palette import NAME_RE, PALETTE_SUFFIX, Palette, load_palette_file
from pagan.project import CONFIG_NAME, Project, discover_project, find_project_root, load_project
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
