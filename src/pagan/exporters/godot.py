"""Godot 4 exporter: a SpriteFrames `.tres` per sprite/model sheet, plus helpers to verify headlessly.

The text format mirrors what Godot 4.7's ResourceSaver writes (format=3, AtlasTexture sub-resources,
`animations` as a list of dicts). IDs are derived from names, never random, so output is byte-stable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
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


def sprite_frames_tres(
    sheet_res: str,
    rects: dict[str, tuple[int, int, int, int]],
    animations: list[Animation],
    normal_res: str | None = None,
) -> str:
    """SpriteFrames resource text: one AtlasTexture per frame, shared by every animation using it.

    With `normal_res`, frames come from a CanvasTexture pairing the sheet with its normal map, so
    Godot's 2D lights shade the sprite.
    """
    frame_ids = {name: f"AtlasTexture_{i}" for i, name in enumerate(rects)}
    lines = ['[gd_resource type="SpriteFrames" format=3]', "", f'[ext_resource type="Texture2D" path={_string(sheet_res)} id="1_sheet"]']
    atlas = 'ExtResource("1_sheet")'
    if normal_res is not None:
        lines += [
            f'[ext_resource type="Texture2D" path={_string(normal_res)} id="2_normal"]',
            "",
            '[sub_resource type="CanvasTexture" id="CanvasTexture_sheet"]',
            'diffuse_texture = ExtResource("1_sheet")',
            'normal_texture = ExtResource("2_normal")',
        ]
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


def centered_offset(size: tuple[int, int], pivot: tuple[int, int]) -> tuple[float, float]:
    """`offset` for an AnimatedSprite2D/Sprite2D with centered = true, putting the pivot on the node origin."""
    return (size[0] / 2 - pivot[0], size[1] / 2 - pivot[1])


# --- headless verification --------------------------------------------------------------------


@dataclass
class GodotCheck:
    ok: bool
    output: str


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
    """Import the project, then load every generated resource in a headless Godot. Needs a Godot 4 binary."""
    script = files("pagan").joinpath("templates", "godot_verify.gd")
    with open(godot_root / ".pagan_verify.gd", "w", encoding="utf-8") as handle:
        handle.write(script.read_text(encoding="utf-8"))
    try:
        imported = subprocess.run(
            [godot, "--headless", "--path", str(godot_root), "--import"],
            capture_output=True, text=True, timeout=timeout,
        )  # fmt: skip
        result = subprocess.run(
            [godot, "--headless", "--path", str(godot_root), "-s", "res://.pagan_verify.gd", "--", manifest_res],
            capture_output=True, text=True, timeout=timeout,
        )  # fmt: skip
    except FileNotFoundError:
        return GodotCheck(ok=False, output=f"Godot binary not found: {godot} (set GODOT=/path/to/godot)")
    except PermissionError:
        return GodotCheck(ok=False, output=f"can't run {godot}: not executable")
    except subprocess.TimeoutExpired:
        return GodotCheck(ok=False, output=f"Godot didn't finish within {timeout}s")
    finally:
        for leftover in (godot_root / ".pagan_verify.gd", godot_root / ".pagan_verify.gd.uid"):
            leftover.unlink(missing_ok=True)
    output = (imported.stdout + imported.stderr + result.stdout + result.stderr).strip()
    return GodotCheck(ok=result.returncode == 0 and "PAGAN_VERIFY_OK" in result.stdout, output=output)
