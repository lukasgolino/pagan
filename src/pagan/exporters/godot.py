"""Godot 4 exporter: a SpriteFrames `.tres` per sprite/model sheet, plus helpers to verify headlessly.

The text format mirrors what Godot 4.7's ResourceSaver writes (format=3, AtlasTexture sub-resources,
`animations` as a list of dicts). IDs are derived from names, never random, so output is byte-stable.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from pagan.asset import Animation


def find_godot_project(start: Path) -> Path | None:
    """The nearest directory at or above `start` that contains project.godot."""
    start = start.resolve()
    for directory in (start, *start.parents):
        if (directory / "project.godot").is_file():
            return directory
    return None


def res_path(path: Path, godot_root: Path) -> str:
    return "res://" + path.resolve().relative_to(godot_root.resolve()).as_posix()


def _string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# CanvasItem.TextureFilter values
_FILTERS = {("nearest", False): 1, ("linear", False): 2, ("nearest", True): 3, ("linear", True): 4}


def texture_filter(name: str, mipmaps: bool) -> int | None:
    """The CanvasItem.TextureFilter for a `[godot] filter` setting; None = inherit from the node/project."""
    return _FILTERS.get((name, mipmaps))


def import_mipmaps(png: Path, mipmaps: bool) -> Path | None:
    """Make Godot import `png` with or without mipmaps, by setting `mipmaps/generate` in its `.import`
    sidecar (Godot reimports when the sidecar changes and keeps the other settings). Without a sidecar
    and with mipmaps off, nothing is written: that's Godot's default. Returns the file if it changed."""
    sidecar = png.with_name(png.name + ".import")
    value = f"mipmaps/generate={'true' if mipmaps else 'false'}"
    if not sidecar.is_file():
        if not mipmaps:
            return None
        sidecar.write_text(f'[remap]\n\nimporter="texture"\ntype="CompressedTexture2D"\n\n[params]\n\n{value}\n', encoding="utf-8")
        return sidecar
    text = sidecar.read_text(encoding="utf-8")
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("mipmaps/generate="):
            if line == value:
                return None
            lines[i] = value
            break
    else:
        if "[params]" in lines:
            at = lines.index("[params]") + 1
            if at < len(lines) and lines[at] == "":
                at += 1  # after the blank line Godot writes under the header
            lines.insert(at, value)
        else:
            lines += ["[params]", "", value, ""]
    sidecar.write_text("\n".join(lines), encoding="utf-8")
    return sidecar


def sprite_frames_tres(
    sheet_res: str,
    rects: dict[str, tuple[int, int, int, int]],
    animations: list[Animation],
    normal_res: str | None = None,
    filter_mode: int | None = None,
) -> str:
    """SpriteFrames resource text: one AtlasTexture per frame, shared by every animation using it.

    With `normal_res` (and/or a `filter_mode`), frames come from a CanvasTexture wrapping the sheet:
    the normal map lets Godot's 2D lights shade the sprite, the filter overrides the node's.
    """
    frame_ids = {name: f"AtlasTexture_{i}" for i, name in enumerate(rects)}
    lines = ['[gd_resource type="SpriteFrames" format=3]', "", f'[ext_resource type="Texture2D" path={_string(sheet_res)} id="1_sheet"]']
    atlas = 'ExtResource("1_sheet")'
    if normal_res is not None or filter_mode is not None:
        if normal_res is not None:
            lines.append(f'[ext_resource type="Texture2D" path={_string(normal_res)} id="2_normal"]')
        lines += ["", '[sub_resource type="CanvasTexture" id="CanvasTexture_sheet"]', 'diffuse_texture = ExtResource("1_sheet")']
        if normal_res is not None:
            lines.append('normal_texture = ExtResource("2_normal")')
        if filter_mode is not None:
            lines.append(f"texture_filter = {filter_mode}")
        atlas = 'SubResource("CanvasTexture_sheet")'
    lines.append("")
    for name, (x, y, w, h) in rects.items():
        lines += [
            f'[sub_resource type="AtlasTexture" id="{frame_ids[name]}"]',
            f"atlas = {atlas}",
            f"region = Rect2({x}, {y}, {w}, {h})",
            "",
        ]
    entries = []
    for anim in animations:
        frames = ", ".join(
            "{\n" + '"duration": 1.0,\n' + f'"texture": SubResource("{frame_ids[f]}")\n' + "}" for f in anim.frames
        )
        entries.append(
            "{\n"
            f'"frames": [{frames}],\n'
            f'"loop": {"true" if anim.loop else "false"},\n'
            f'"name": &{_string(anim.name)},\n'
            f'"speed": {float(anim.fps)!r}\n'
            "}"
        )
    lines += ["[resource]", f"animations = [{', '.join(entries)}]", ""]
    return "\n".join(lines)


@dataclass(frozen=True)
class AtlasTile:
    """One tile of a TileSet atlas. An animated tile's frames follow it to the right (wrapping every
    `columns` cells when columns > 0), each shown for 1/fps seconds."""

    column: int
    row: int
    frames: int = 1
    columns: int = 0
    fps: float = 1.0


def tileset_tres(atlas_res: str, tile_size: tuple[int, int], tiles: list[AtlasTile]) -> str:
    """TileSet resource text: one TileSetAtlasSource over the atlas, a tile at every (column, row)."""
    width, height = tile_size
    tile_lines: list[str] = []
    for tile in tiles:
        cell = f"{tile.column}:{tile.row}"
        if tile.frames > 1:
            if tile.columns:
                tile_lines.append(f"{cell}/animation_columns = {tile.columns}")
            tile_lines.append(f"{cell}/animation_speed = {float(tile.fps)!r}")
            tile_lines += [f"{cell}/animation_frame_{i}/duration = 1.0" for i in range(tile.frames)]
        tile_lines.append(f"{cell}/0 = 0")
    lines = [
        '[gd_resource type="TileSet" format=3]',
        "",
        f'[ext_resource type="Texture2D" path={_string(atlas_res)} id="1_atlas"]',
        "",
        '[sub_resource type="TileSetAtlasSource" id="TileSetAtlasSource_0"]',
        'texture = ExtResource("1_atlas")',
        f"texture_region_size = Vector2i({width}, {height})",
        *tile_lines,
        "",
        "[resource]",
        f"tile_size = Vector2i({width}, {height})",
        'sources/0 = SubResource("TileSetAtlasSource_0")',
        "",
    ]
    return "\n".join(lines)


def centered_offset(size: tuple[int, int], pivot: tuple[float, float]) -> tuple[float, float]:
    """`offset` for an AnimatedSprite2D/Sprite2D with centered = true, putting the pivot on the node origin."""
    return (size[0] / 2 - pivot[0], size[1] / 2 - pivot[1])


# --- headless verification --------------------------------------------------------------------


@dataclass
class GodotCheck:
    ok: bool
    output: str
    sprite_frames: int = 0
    tilesets: int = 0


def find_godot_binary() -> str | None:
    candidate = os.environ.get("GODOT")
    if candidate:
        return candidate
    for name in ("godot", "godot4"):
        found = shutil.which(name)
        if found:
            return found
    return None


def verify_with_godot(godot: str, godot_root: Path, manifest_res: str, timeout: int = 300) -> GodotCheck:
    """Import the project, then load every generated resource in a headless Godot. Needs a Godot 4 binary.

    The check script runs from a temp folder (by absolute path), so nothing is written into the game.
    """
    script = files("pagan").joinpath("templates", "godot_verify.gd").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="pagan-verify-") as scratch:
        script_path = Path(scratch) / "pagan_verify.gd"
        script_path.write_text(script, encoding="utf-8")
        try:
            imported = subprocess.run(
                [godot, "--headless", "--path", str(godot_root), "--import"],
                capture_output=True, text=True, timeout=timeout,
            )  # fmt: skip
            import_output = (imported.stdout + imported.stderr).strip()
            import_errors = [line for line in import_output.splitlines() if "ERROR" in line]
            if imported.returncode != 0 or import_errors:
                detail = "\n".join(import_errors[-20:]) or import_output[-2000:]
                return GodotCheck(ok=False, output=f"Godot's import step failed (exit {imported.returncode}):\n{detail}")
            result = subprocess.run(
                [godot, "--headless", "--path", str(godot_root), "-s", str(script_path), "--", manifest_res],
                capture_output=True, text=True, timeout=timeout,
            )  # fmt: skip
        except FileNotFoundError:
            return GodotCheck(ok=False, output=f"Godot binary not found: {godot} (set GODOT=/path/to/godot)")
        except PermissionError:
            return GodotCheck(ok=False, output=f"can't run {godot}: not executable")
        except subprocess.TimeoutExpired:
            return GodotCheck(ok=False, output=f"Godot didn't finish within {timeout}s")
    output = (result.stdout + result.stderr).strip()
    ok = result.returncode == 0 and "PAGAN_VERIFY_OK" in result.stdout
    match = re.search(r"PAGAN_VERIFY_OK (\d+) SpriteFrames, (\d+) TileSets", result.stdout)
    counts = (int(match.group(1)), int(match.group(2))) if match else (0, 0)
    return GodotCheck(ok=ok, output=output, sprite_frames=counts[0], tilesets=counts[1])
