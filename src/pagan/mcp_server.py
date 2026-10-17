"""`pagan mcp`: PAGAN as an MCP server, for agents without the Claude skill or a shell.

One server serves one PAGAN project. Tools return the same JSON as the matching CLI command with `--json`
(they run the CLI handlers with stdout captured), so the CLI, the skill and MCP share one contract.
Errors are results (`ok: false` + `findings`), not exceptions: agents fix them like lint output.
Nothing reads or writes outside the project, its output dir and its preview dir.

Needs the optional extra: `pip install "pagan[mcp]"`.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import os
import threading
from collections.abc import Callable
from contextlib import redirect_stdout
from datetime import date
from functools import wraps
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal, ParamSpec, TypeVar

from mcp.server.mcpserver import Image, MCPServer
from mcp.types import ToolAnnotations
from PIL import Image as PILImage

from pagan import __version__
from pagan.asset import MODEL_SUFFIX, SPRITE_SUFFIX, TILESET_SUFFIX
from pagan.findings import Finding, PaganError
from pagan.lint import lint_paths
from pagan.palette import NAME_RE, PALETTE_SUFFIX
from pagan.project import CONFIG_NAME, Project, find_project_root, load_project
from pagan.preview import PreviewOptions, auto_scale, montage

MAX_SOURCE_BYTES = 2_000_000
MAX_IMAGE_SIDE = 1568  # what vision models take without downscaling further
MAX_IMAGE_BYTES = 1_000_000
Kind = Literal["sprite", "tiles", "model"]
KINDS: dict[Kind, tuple[str, str]] = {"sprite": ("sprites", SPRITE_SUFFIX), "tiles": ("tiles", TILESET_SUFFIX), "model": ("models", MODEL_SUFFIX)}

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
OVERWRITE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)

INSTRUCTIONS = """\
PAGAN turns text into game art: palettes, sprites, tilesets and 3D voxel models written as YAML, linted,
previewed and built into engine-ready sheets. Read the workflow first (resource pagan://workflow, notation:
pagan://reference). Call `status` first and read BRIEF.md/STYLE.md (`read_docs`) before making anything.
Loop: `scaffold` -> `write_asset` (lints it) -> fix findings -> `preview` and LOOK at the image -> report.
Never invent colours: everything comes from the palette. `build` writes the game's files; only after approval.
"""

P = ParamSpec("P")
R = TypeVar("R")


def _failure(findings: list[Finding]) -> dict[str, Any]:
    return {"ok": False, "findings": [f.to_dict() for f in findings]}


def _error(message: str, path: Path | None = None) -> PaganError:
    return PaganError([Finding("E000", message, path)])


def _results(fn: Callable[P, R]) -> Callable[P, R | dict[str, Any]]:
    """Turn a PaganError into an `ok: false` result with findings."""

    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | dict[str, Any]:
        try:
            return fn(*args, **kwargs)
        except PaganError as exc:
            return _failure(exc.findings)

    return wrapper


class Pagan:
    """The project a server is bound to, and safe access to it."""

    def __init__(self, root: Path, allow_godot: bool = False) -> None:
        self.root = root.resolve()
        self.allow_godot = allow_godot
        self._lock = threading.Lock()  # the CLI uses the cwd and stdout, which are per process

    def project(self) -> Project:
        return load_project(self.root)  # fresh: files change between calls

    def cli(self, *argv: str) -> dict[str, Any]:
        """Run `pagan --json <argv>` in the project and return its JSON result."""
        from pagan.cli import main

        buffer = io.StringIO()
        with self._lock:
            previous = os.getcwd()
            os.chdir(self.root)
            try:
                with redirect_stdout(buffer):
                    code = main(["--json", *argv])
            except SystemExit as exc:  # argparse rejected the arguments
                return _failure([Finding("E000", f"invalid arguments for `pagan {' '.join(argv)}` (exit {exc.code})")])
            finally:
                os.chdir(previous)
        text = buffer.getvalue().strip()
        try:
            data = json.loads(text) if text else {"ok": code == 0}
        except ValueError:
            data = {"ok": code == 0, "output": text}
        if not isinstance(data, dict):
            data = {"ok": code == 0, "result": data}
        return data

    def allowed_roots(self) -> list[Path]:
        project = self.project()
        return [self.root, project.output_dir.resolve(), project.preview_dir.resolve()]

    def inside(self, path: str | Path) -> Path:
        """`path` (relative to the project root) resolved, if it's inside the project, output or preview dir."""
        resolved = (self.root / path).resolve()
        if not any(resolved == r or resolved.is_relative_to(r) for r in self.allowed_roots()):
            raise _error(f"{path} is outside the PAGAN project")
        return resolved

    def source_path(self, kind: Kind, name: str) -> Path:
        _check_name(name)
        folder, suffix = KINDS[kind]
        return self.root / folder / f"{name}{suffix}"

    def find_asset(self, name: str) -> Path:
        _check_name(name)
        for folder, suffix in KINDS.values():
            path = self.root / folder / f"{name}{suffix}"
            if path.is_file():
                return path
        raise _error(f"no asset {name!r} (sprites/, tiles/ or models/); `status` lists them")

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix() if path.resolve().is_relative_to(self.root) else str(path)


def _check_name(name: str) -> None:
    if not NAME_RE.match(name):
        raise _error(f"invalid name {name!r}: lowercase letters, digits, '_' or '-'")


def _check_text(text: str) -> None:
    if len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise _error(f"source text is over {MAX_SOURCE_BYTES // 1_000_000} MB")


def _image(path: Path | None = None, image: PILImage.Image | None = None) -> Image | None:
    """A PNG for the model to look at, scaled down to MAX_IMAGE_SIDE; None if it's still too big."""
    if image is None:
        if path is None or not path.is_file():
            return None
        image = PILImage.open(path)
        image.load()
    longest = max(image.size)
    if longest > MAX_IMAGE_SIDE:
        factor = MAX_IMAGE_SIDE / longest
        image = image.resize((max(1, round(image.width * factor)), max(1, round(image.height * factor))), PILImage.Resampling.NEAREST)
    data = io.BytesIO()
    image.save(data, format="PNG")
    if data.tell() > MAX_IMAGE_BYTES:
        return None
    return Image(data=data.getvalue(), format="png")


def _with_image(result: dict[str, Any], picture: Image | None, path: str | None = None) -> list[Any]:
    if picture is None and path is not None:
        result = {**result, "image_note": f"image too large to inline; open {path}"}
    return [result, picture] if picture is not None else [result]


def create_server(root: Path, allow_godot: bool = False) -> MCPServer:
    """The MCP server for the PAGAN project at `root`."""
    pagan = Pagan(root, allow_godot)
    server = MCPServer(name="pagan", title="PAGAN", version=__version__, instructions=INSTRUCTIONS)

    # --- project ---------------------------------------------------------------------------

    @server.tool(annotations=READ)
    def status() -> dict[str, Any]:
        """Every asset (kind, size, status, style version, errors/warnings, what needs attention), the
        style version and default palette. Call this first."""
        return pagan.cli("status")

    @server.tool(annotations=READ)
    def read_docs() -> dict[str, Any]:
        """BRIEF.md (what the game needs, decisions log) and STYLE.md (how the art must look). Read both
        before making or changing anything: they are the project's memory between sessions."""
        return {
            "ok": True,
            **{name: (pagan.root / name).read_text(encoding="utf-8") if (pagan.root / name).is_file() else None for name in ("BRIEF.md", "STYLE.md")},
        }

    @server.tool(annotations=OVERWRITE)
    @_results
    def write_doc(doc: Literal["BRIEF.md", "STYLE.md"], text: str) -> dict[str, Any]:
        """Replace BRIEF.md or STYLE.md with `text` (read it first and keep what's there)."""
        _check_text(text)
        (pagan.root / doc).write_text(text, encoding="utf-8")
        return {"ok": True, "written": doc}

    @server.tool(annotations=WRITE)
    @_results
    def log_feedback(note: str) -> dict[str, Any]:
        """Add a dated line to BRIEF.md's "Decisions and feedback log" (what the owner asked or decided)."""
        brief = pagan.root / "BRIEF.md"
        if not brief.is_file():
            raise _error("no BRIEF.md in the project")
        line = f"- {date.today().isoformat()}: {' '.join(note.split())}"
        text = brief.read_text(encoding="utf-8").rstrip("\n")
        if "## Decisions and feedback log" not in text:
            text += "\n\n## Decisions and feedback log\n"
        brief.write_text(f"{text}\n{line}\n", encoding="utf-8")
        return {"ok": True, "logged": line}

    @server.tool(annotations=READ)
    def config_show() -> dict[str, Any]:
        """Every pagan.toml setting (camera, light, palette, supersample, godot...): value, default, meaning."""
        return pagan.cli("config", "show")

    @server.tool(annotations=WRITE)
    def config_set(key: str, value: str) -> dict[str, Any]:
        """Change a setting (validated; nothing is written if invalid). `value` is TOML: 30, true, "tide",
        [-0.5, 0.45, 0.75]. The result says what refreshes (3D models re-render; hand-drawn 2D doesn't)."""
        return pagan.cli("config", "set", key, value)

    @server.tool(annotations=WRITE)
    def config_unset(key: str) -> dict[str, Any]:
        """Return a setting to its default."""
        return pagan.cli("config", "unset", key)

    # --- palettes ----------------------------------------------------------------------------

    @server.tool(annotations=READ)
    @_results
    def palette_list() -> dict[str, Any]:
        """Every palette: colours (key -> hex, name) and ramps (keys dark -> light)."""
        project = pagan.project()
        palettes: dict[str, Any] = {}
        findings: list[Finding] = []
        for name in project.palette_names():
            try:
                palette = project.load_palette(name)
            except PaganError as exc:
                findings.extend(exc.findings)
                continue
            palettes[name] = {
                "colors": {k: {"hex": c.hex, "name": c.name} for k, c in palette.colors.items()},
                "ramps": {r: list(keys) for r, keys in palette.ramps.items()},
            }
        return {"ok": not findings, "default_palette": project.config.default_palette, "palettes": palettes,
                **({"findings": [f.to_dict() for f in findings]} if findings else {})}  # fmt: skip

    @server.tool(annotations=READ, structured_output=False)
    @_results
    def palette_show(name: str) -> list[Any]:
        """A palette's swatch image (keys, colours, ramps) to look at."""
        _check_name(name)
        result = pagan.cli("palette", "show", name)
        swatch = (result.get("outputs") or [{}])[0].get("path") if result.get("ok") else None
        return _with_image(result, _image(pagan.root / swatch) if swatch else None, swatch)

    @server.tool(annotations=OVERWRITE)
    @_results
    def palette_write(name: str, text: str) -> dict[str, Any]:
        """Write palettes/<name>.pal.yaml (creates or replaces) and validate it. See pagan://reference."""
        from pagan.palette import load_palette_file

        _check_name(name)
        _check_text(text)
        path = pagan.root / "palettes" / f"{name}{PALETTE_SUFFIX}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        try:
            load_palette_file(path)
        except PaganError as exc:
            return {"ok": False, "written": pagan.rel(path), "findings": [f.to_dict() for f in exc.findings]}
        return {"ok": True, "written": pagan.rel(path)}

    @server.tool(annotations=WRITE, structured_output=False)
    @_results
    def palette_adjust(
        palette: str,
        lightness: float = 0.0,
        contrast: float = 1.0,
        saturation: float = 1.0,
        hue: float = 0.0,
        warmth: float = 0.0,
        ramps: list[str] | None = None,
        keys: list[str] | None = None,
        out: str | None = None,
        dry_run: bool = True,
    ) -> list[Any]:
        """Change a palette's colours in OKLab, which changes every asset that uses it ("darker": lightness
        -0.05; "more contrast": contrast 1.15; "pastel": saturation 0.6, lightness 0.04; "warmer": warmth
        0.02). Dry run by default: check the changes, then call again with dry_run false. `out` writes a
        new palette instead of editing this one."""
        _check_name(palette)
        argv = ["palette", "adjust", palette, f"--lightness={lightness}", f"--contrast={contrast}",
                f"--saturation={saturation}", f"--hue={hue}", f"--warmth={warmth}"]  # fmt: skip
        for ramp in ramps or []:
            argv.append(f"--ramp={ramp}")
        if keys:
            argv += ["--keys", *keys]
        if out is not None:
            _check_name(out)
            argv += ["--out", out, "--force"]
        if dry_run:
            argv.append("--dry-run")
        result = pagan.cli(*argv)
        compare = result.get("compare")
        return _with_image(result, _image(pagan.root / compare) if compare else None, compare)

    # --- assets ------------------------------------------------------------------------------

    @server.tool(annotations=WRITE)
    @_results
    def scaffold(
        kind: Kind,
        name: str,
        size: str = "16x16",
        description: str | None = None,
        palette: str | None = None,
        frames: int = 1,
        directions: int | None = None,
        mirror: bool = False,
        outline: bool = False,
    ) -> dict[str, Any]:
        """Create a blank asset file and return its text: sprite (2D), tiles (tileset) or model (3D voxels,
        rendered in 1/4/8/16/32 headings). Always give a `description` (what it is, how it should look).
        size is WIDTHxHEIGHT (models: the frame size, default 64x64 is typical)."""
        _check_name(name)
        argv = ["new", kind, name, f"--size={size}"]
        if description:
            argv.append(f"--description={description}")
        if palette:
            argv.append(f"--palette={palette}")
        if kind != "model":
            argv.append(f"--frames={frames}")
        if directions is not None:
            if kind == "tiles":
                raise _error("directions only applies to sprites and models")
            argv.append(f"--directions={directions}")
        if kind == "sprite":
            argv += [*(["--mirror"] if mirror else []), *(["--outline"] if outline else [])]
        result = pagan.cli(*argv)
        path = pagan.source_path(kind, name)
        if result.get("ok") and path.is_file():
            result["text"] = path.read_text(encoding="utf-8")
        return result

    @server.tool(annotations=READ)
    @_results
    def read_asset(name: str) -> dict[str, Any]:
        """An asset's source text (sprite, tileset or model) by name."""
        path = pagan.find_asset(name)
        return {"ok": True, "path": pagan.rel(path), "text": path.read_text(encoding="utf-8")}

    @server.tool(annotations=OVERWRITE, structured_output=False)
    @_results
    def write_asset(kind: Kind, name: str, text: str, preview: bool = True) -> list[Any]:
        """Write an asset's source (creates or replaces sprites/<name>.sprite.yaml, tiles/<name>.tiles.yaml
        or models/<name>.model.yaml) and lint it in the same call. Fix every error in `findings`; read the
        warnings. When it parses, a small preview image of its frames comes back: look at it."""
        _check_name(name)
        _check_text(text)
        path = pagan.source_path(kind, name)
        others = [p for k in KINDS if k != kind and (p := pagan.source_path(k, name)).is_file()]
        if others:
            raise _error(f"{pagan.rel(others[0])} already uses the name {name!r}: asset names are unique across kinds")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        project = pagan.project()
        linted = lint_paths(project, [path])
        result: dict[str, Any] = {
            "ok": not linted.errors,
            "written": pagan.rel(path),
            "errors": len(linted.errors),
            "warnings": len(linted.warnings),
            "findings": [f.to_dict() for f in linted.findings],
        }
        picture = None
        if preview and linted.assets:
            asset = linted.assets[0]
            scale = auto_scale(asset.size)
            picture = _image(image=montage(asset, PreviewOptions(scale=scale)))
            result["preview_scale"] = scale
        return _with_image(result, picture)

    @server.tool(annotations=READ)
    def lint(assets: list[str] | None = None) -> dict[str, Any]:
        """Errors and style warnings for named assets (default: the whole project). Rule ids are explained
        in pagan://reference; a warning that's wrong by design goes in the asset's `lint: { disable: [...] }`."""
        paths: list[str] = []
        for name in assets or []:
            try:
                paths.append(pagan.rel(pagan.find_asset(name)))
            except PaganError as exc:
                return _failure(exc.findings)
        return pagan.cli("lint", *paths)

    @server.tool(annotations=READ, structured_output=False)
    @_results
    def preview(
        asset: str,
        which: Literal["sheet", "montage", "variants", "built"] = "sheet",
        scale: int | None = None,
        background: str = "checker",
        inline: bool = True,
    ) -> list[Any]:
        """Render previews (labelled contact sheet with every frame, heading and animation "changes" row;
        montage; variants side by side; built = supersampled output at 1x) and return the chosen one as an
        image. LOOK at it before reporting. Paths to the GIFs and every file are in the result.
        background: checker, none or #rrggbb."""
        _check_name(asset)
        argv = ["preview", asset, f"--bg={background}"]
        if scale is not None:
            argv.append(f"--scale={scale}")
        result = pagan.cli(*argv)
        outputs = result.get("outputs") or [{}]
        key = {"sheet": "sheet", "montage": "montage", "variants": "variants", "built": "built_1x"}[which]
        chosen = outputs[0].get(key)
        if result.get("ok") and chosen is None:
            result["image_note"] = f"no {which} preview for {asset} (variants: needs variants; built: needs supersample)"
        if not inline or chosen is None:
            return [result]
        return _with_image(result, _image(pagan.root / chosen), chosen)

    @server.tool(annotations=READ, structured_output=False)
    @_results
    def gallery() -> list[Any]:
        """Every asset side by side at one scale: check the set looks like one game."""
        result = pagan.cli("gallery")
        path = result.get("gallery")
        return _with_image(result, _image(pagan.root / path) if path else None, path)

    @server.tool(annotations=READ)
    def fit(model: str, margin: int = 0) -> dict[str, Any]:
        """The smallest frame size and pivot that fit every heading and pose of a 3D model."""
        try:
            path = pagan.rel(pagan.find_asset(model))
        except PaganError as exc:
            return _failure(exc.findings)
        return pagan.cli("fit", path, f"--margin={margin}")

    @server.tool(annotations=WRITE)
    def mark(
        assets: list[str] | None = None,
        status: Literal["draft", "approved"] | None = None,
        current: bool = False,
        outdated: bool = False,
    ) -> dict[str, Any]:
        """Record reviews: status approved/draft, and/or `current` = made under the current style version.
        `outdated` applies to every asset made under an older style."""
        argv = ["mark"]
        for name in assets or []:
            try:
                argv.append(pagan.rel(pagan.find_asset(name)))
            except PaganError as exc:
                return _failure(exc.findings)
        if status is not None:
            argv.append(f"--status={status}")
        argv += [*(["--current"] if current else []), *(["--outdated"] if outdated else [])]
        return pagan.cli(*argv)

    @server.tool(annotations=WRITE)
    def style_bump(note: str) -> dict[str, Any]:
        """Record a style change that means existing 2D art must be redrawn: bumps style_version, logs the
        note in STYLE.md, flags older assets (W006) until they're updated and marked current."""
        return pagan.cli("style", "bump", note)

    @server.tool(annotations=WRITE)
    @_results
    def import_png(
        path: str | None = None,
        png_base64: str | None = None,
        name: str | None = None,
        palette: str | None = None,
        open_palette: bool = False,
        scale: int | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Convert a PNG into a sprite source (detects upscaling, snaps colours to the palette). Give a
        `path` inside the project, or the image as `png_base64` (with a `name`)."""
        if (path is None) == (png_base64 is None):
            raise _error("give exactly one of path or png_base64")
        if png_base64 is not None:
            if name is None:
                raise _error("png_base64 needs a name")
            _check_name(name)
            try:
                data = base64.b64decode(png_base64, validate=True)
            except (binascii.Error, ValueError):
                raise _error("png_base64 isn't valid base64") from None
            source = pagan.project().preview_dir / "imports" / f"{name}.png"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(data)
        else:
            assert path is not None
            source = pagan.inside(path)
        argv = ["import", str(source)]
        if name is not None:
            _check_name(name)
            argv.append(f"--name={name}")
        if palette is not None:
            argv.append(f"--palette={palette}")
        if open_palette:
            argv.append("--open")
        if scale is not None:
            argv.append(f"--scale={scale}")
        if force:
            argv.append("--force")
        return pagan.cli(*argv)

    # --- output ------------------------------------------------------------------------------

    @server.tool(annotations=WRITE)
    def build(verify_godot: bool = False) -> dict[str, Any]:
        """Lint, then write final sheets, manifest.json and engine resources into the project's output dir
        (usually the game). Do this after the owner approves. `verify_godot` loads every resource in a
        headless Godot (only if the server was started with --allow-godot)."""
        if verify_godot and not pagan.allow_godot:
            return _failure([Finding("E000", "verify_godot runs a Godot binary; start the server with `pagan mcp --allow-godot`")])
        return pagan.cli("build", *(["--verify-godot"] if verify_godot else []))

    @server.tool(annotations=READ)
    @_results
    def manifest(asset: str | None = None) -> dict[str, Any]:
        """The build's manifest.json (the contract with the game): per asset its sheet, frame rects,
        animations, pivot, headings, tiles, variants and swap tables. Optionally one asset."""
        path = pagan.project().output_dir / "manifest.json"
        if not path.is_file():
            raise _error("no manifest.json yet: run `build`")
        data = json.loads(path.read_text(encoding="utf-8"))
        if asset is not None:
            entry = data.get("assets", {}).get(asset)
            if entry is None:
                raise _error(f"{asset!r} isn't in the manifest (built assets: {', '.join(data.get('assets', {}))})")
            return {"ok": True, "generator": data.get("generator"), "asset": asset, "entry": entry}
        return {"ok": True, **data}

    # --- resources and prompts ---------------------------------------------------------------

    def skill_text(name: str) -> str:
        text = files("pagan").joinpath("skill", name).read_text(encoding="utf-8")
        if text.startswith("---"):
            text = text.split("---", 2)[2].lstrip("\n")  # drop the skill frontmatter
        return text

    @server.resource("pagan://workflow", mime_type="text/markdown", description="How to make and maintain art with PAGAN")
    def workflow() -> str:
        return skill_text("SKILL.md")

    @server.resource("pagan://reference", mime_type="text/markdown", description="The PAGAN notation, settings and lint rules")
    def reference() -> str:
        return skill_text("reference.md")

    @server.resource("pagan://brief", mime_type="text/markdown", description="BRIEF.md: what the game needs, decisions log")
    def brief() -> str:
        path = pagan.root / "BRIEF.md"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    @server.resource("pagan://style", mime_type="text/markdown", description="STYLE.md: how the art must look")
    def style() -> str:
        path = pagan.root / "STYLE.md"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    @server.resource("pagan://manifest", mime_type="application/json", description="The last build's manifest.json")
    def manifest_resource() -> str:
        path = pagan.project().output_dir / "manifest.json"
        return path.read_text(encoding="utf-8") if path.is_file() else "{}"

    @server.resource("pagan://palette/{name}", mime_type="text/yaml", description="A palette's source")
    def palette_resource(name: str) -> str:
        _check_name(name)
        return (pagan.root / "palettes" / f"{name}{PALETTE_SUFFIX}").read_text(encoding="utf-8")

    @server.resource("pagan://asset/{name}", mime_type="text/yaml", description="An asset's source")
    def asset_resource(name: str) -> str:
        return pagan.find_asset(name).read_text(encoding="utf-8")

    @server.prompt(description="Set up the art for a new game (asks the owner a few questions first)")
    def setup_new_game(game: str = "") -> str:
        return (
            f"Set up PAGAN art for this game: {game or '(ask me about it)'}.\n"
            "Follow section 1 of pagan://workflow: ask ONE message of questions with defaults (rendering style, "
            "perspective, mood, sizes, look rules, engine), write 2-3 palettes with `palette_write`, look at them "
            "with `palette_show`, then fill in BRIEF.md and STYLE.md (`read_docs` / `write_doc`)."
        )

    @server.prompt(description="Make one asset: scaffold, write, lint, preview, look, report")
    def make_asset(request: str) -> str:
        return (
            f"Make this asset with PAGAN: {request}\n"
            "1. `status` and `read_docs` (BRIEF.md, STYLE.md). 2. Decide 2D sprite, tileset or 3D model (pagan://workflow "
            "section 2). 3. `scaffold` with a description. 4. `write_asset` until there are no errors. 5. `preview` and "
            "look at the image critically against STYLE.md; fix and repeat (at most ~4 rounds). 6. Report the preview, "
            "a one-line summary and any choices you made; leave it draft until approved."
        )

    @server.prompt(description="Change the look of the whole game (darker, warmer, new light, new angle...)")
    def change_the_look(request: str) -> str:
        return (
            f"Change the look: {request}\n"
            "Use pagan://workflow section 4: prefer `palette_adjust` (dry run first) and `config_set`, which update every "
            "asset at once. If 2D art must be redrawn, `style_bump` and go through the flagged assets. Check with "
            "`gallery`, then `log_feedback`."
        )

    @server.prompt(description="Review an asset against the style guide")
    def review_asset(name: str) -> str:
        return (
            f"Review the asset {name}: `read_asset`, `lint`, `preview` (sheet), and compare it with STYLE.md and the "
            "approved assets in `gallery`. List concrete problems (silhouette, light direction, ramps, jitter in the "
            "changes rows, size versus the others) and fix them with `write_asset` if asked."
        )

    return server


def serve(project: str | None = None, allow_godot: bool = False) -> int:
    """Run the stdio server (`pagan mcp`)."""
    start = Path(project) if project else Path.cwd()
    root = find_project_root(start)
    if root is None:
        raise _error(f"no {CONFIG_NAME} found at or above {start}; run `pagan init` first or pass --project")
    create_server(root, allow_godot).run("stdio")
    return 0
