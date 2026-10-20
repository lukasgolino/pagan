"""End-to-end Godot checks. Skipped unless a Godot 4 binary is available (GODOT env var or `godot` on PATH).

CI downloads Godot, so these run there on every push.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pagan.build import build
from pagan.exporters.godot import find_godot_binary, render_views, verify_with_godot
from pagan.project import load_project

ROOT = Path(__file__).parent.parent
GODOT = find_godot_binary()
pytestmark = pytest.mark.skipif(GODOT is None, reason="no Godot binary (set GODOT=/path/to/godot)")


@pytest.fixture
def copies(tmp_path: Path) -> tuple[Path, Path]:
    """The demo project and Godot project, copied so the test can build without touching the repo."""
    shutil.copytree(ROOT / "examples" / "demo", tmp_path / "demo", ignore=shutil.ignore_patterns("previews", ".pagan-cache"))
    shutil.copytree(ROOT / "examples" / "godot", tmp_path / "godot", ignore=shutil.ignore_patterns(".godot", "*.import"))
    return tmp_path / "demo", tmp_path / "godot"


def test_generated_resources_load_in_godot(copies: tuple[Path, Path]) -> None:
    demo, godot_root = copies
    result = build(load_project(demo))
    assert not result.errors and result.godot_root == godot_root.resolve()
    assert GODOT is not None
    check = verify_with_godot(GODOT, godot_root, "res://assets/generated/manifest.json")
    assert check.ok, check.output


def test_demo_scene_shows_every_asset(copies: tuple[Path, Path]) -> None:
    demo, godot_root = copies
    build(load_project(demo))
    assert GODOT is not None
    subprocess.run([GODOT, "--headless", "--path", str(godot_root), "--import"], capture_output=True, timeout=300)
    run = subprocess.run(
        [GODOT, "--headless", "--path", str(godot_root), "-s", "res://tests/check_scene.gd"],
        capture_output=True, text=True, timeout=300,
    )  # fmt: skip
    output = run.stdout + run.stderr
    assert run.returncode == 0 and "CHECK_OK" in output, output
    assert "SCRIPT ERROR" not in output and "ERROR:" not in output, output


CHECK_FILTER = """\
extends SceneTree
func _init():
	var frames: SpriteFrames = load("res://assets/generated/sprites/barrel.tres")
	var texture = frames.get_frame_texture(frames.get_animation_names()[0], 0)
	var canvas: CanvasTexture = texture.atlas
	var sheet: Texture2D = canvas.diffuse_texture
	print("FILTER ", canvas.texture_filter, " MIPMAPS ", sheet.get_image().has_mipmaps())
	quit()
"""


def test_godot_mipmaps_and_filter(copies: tuple[Path, Path], tmp_path: Path) -> None:
    """[godot] mipmaps/filter (Space IO S4): Godot imports with mipmaps and SpriteFrames carry the filter."""
    demo, godot_root = copies
    with (demo / "pagan.toml").open("a") as config:
        config.write('\n[godot]\nmipmaps = true\nfilter = "linear"\n')
    assert not build(load_project(demo)).errors
    assert GODOT is not None
    subprocess.run([GODOT, "--headless", "--path", str(godot_root), "--import"], capture_output=True, timeout=300)
    script = tmp_path / "check_filter.gd"
    script.write_text(CHECK_FILTER)
    run = subprocess.run(
        [GODOT, "--headless", "--path", str(godot_root), "-s", str(script)], capture_output=True, text=True, timeout=300
    )
    assert "FILTER 4 MIPMAPS true" in run.stdout, run.stdout + run.stderr


def test_meshes_load_in_godot(copies: tuple[Path, Path]) -> None:
    """With "mesh" exported: every .glb and .tscn loads, with the manifest's nodes, metadata, visibility,
    animations (loop flags) and PAGAN materials on every surface."""
    demo, godot_root = copies
    assert '"mesh"' in (demo / "pagan.toml").read_text()  # the demo exports meshes
    result = build(load_project(demo))
    assert not result.errors
    assert GODOT is not None
    check = verify_with_godot(GODOT, godot_root, "res://assets/generated/manifest.json")
    assert check.ok and check.meshes == 2, check.output


def test_verify_accepts_mesh_only_models(copies: tuple[Path, Path]) -> None:
    """D10: a mesh-only model (directions: 0) has no sheet; --verify-godot checks its mesh only."""
    demo, godot_root = copies
    text = (demo / "models" / "sailor.model.yaml").read_text().replace("name: sailor", "name: statue").replace("directions: 8", "directions: 0")
    (demo / "models" / "statue.model.yaml").write_text(text)
    result = build(load_project(demo))
    assert not result.errors
    assert GODOT is not None
    check = verify_with_godot(GODOT, godot_root, "res://assets/generated/manifest.json")
    assert check.ok and check.meshes == 3, check.output


def test_mesh_scene_shows_every_mesh(copies: tuple[Path, Path]) -> None:
    demo, godot_root = copies
    build(load_project(demo))
    assert GODOT is not None
    subprocess.run([GODOT, "--headless", "--path", str(godot_root), "--import"], capture_output=True, timeout=300)
    run = subprocess.run(
        [GODOT, "--headless", "--path", str(godot_root), "-s", "res://tests/check_mesh_scene.gd"],
        capture_output=True, text=True, timeout=300,
    )  # fmt: skip
    output = run.stdout + run.stderr
    assert run.returncode == 0 and "CHECK_OK 2 meshes" in output, output


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="rendering needs a display")
@pytest.mark.parametrize(("method", "tolerance"), [("forward_plus", 0), ("gl_compatibility", 0), ("mobile", 4)])
def test_ramp_shader_keeps_palette_colours(copies: tuple[Path, Path], method: str, tolerance: int) -> None:
    """Every lit pixel is a colour of the model's ramp in every renderer (D5: Compatibility works in sRGB space).
    Mobile keeps light in a 10-bit buffer, so dark colours may be a few levels off there."""
    demo, godot_root = copies
    build(load_project(demo))
    assert GODOT is not None
    for model in ("ship", "sailor"):
        ramp = np.asarray(Image.open(godot_root / "assets" / "generated" / "models" / f"{model}.ramp.png").convert("RGB"))
        palette = np.unique(ramp.reshape(-1, 3), axis=0).astype(int)
        scene = f"res://assets/generated/models/{model}.tscn"
        images, output = render_views(GODOT, godot_root, scene, 2.0, 0.5, [(30, 20), (210, -20)], rendering_method=method)
        assert images and f"PAGAN_VIEWS_OK 2 {method}" in output, output  # Godot falls back to another renderer silently
        for path in images:
            pixels = np.asarray(Image.open(path).convert("RGBA")).reshape(-1, 4).astype(int)
            lit = pixels[pixels[:, 3] > 0, :3]
            distance = np.abs(lit[:, None, :] - palette[None, :, :]).max(axis=2).min(axis=1)
            assert len(lit) > 100 and distance.max() <= tolerance, f"{model} {method}: off by up to {distance.max()}"
