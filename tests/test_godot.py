"""End-to-end Godot checks. Skipped unless a Godot 4 binary is available (GODOT env var or `godot` on PATH).

CI downloads Godot, so these run there on every push.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from pagan.build import build
from pagan.exporters.godot import find_godot_binary, verify_with_godot
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
