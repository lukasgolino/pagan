"""Age of Boom reports R18 (--verify-godot on swap-only variants) and R19 (fit must hold the pivot)."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from pagan.asset import load_asset
from pagan.build import build
from pagan.cli import main
from pagan.exporters.godot import find_godot_binary, verify_with_godot
from pagan.project import Project, load_project
from test_reports_r15_r17 import _godot_project

GODOT = find_godot_binary()
needs_godot = pytest.mark.skipif(GODOT is None, reason="no Godot binary (set GODOT=/path/to/godot)")

# --- R18: verify swap-only variants, fail fast on script errors ---------------------------------


@needs_godot
def test_verify_godot_with_swap_only_variants(tmp_path: Path) -> None:
    result = build(_godot_project(tmp_path, sheets=False))
    assert not result.errors, [f.format() for f in result.errors]
    assert GODOT is not None
    check = verify_with_godot(GODOT, tmp_path / "game", "res://gen/manifest.json")
    assert check.ok, check.output
    assert check.sprite_frames == 1


@needs_godot
def test_verify_godot_script_error_fails_fast(tmp_path: Path) -> None:
    build(_godot_project(tmp_path))
    manifest_path = tmp_path / "game" / "gen" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    del manifest["assets"]["flag"]["size"]  # the script indexes entry["size"]: a runtime error
    manifest_path.write_text(json.dumps(manifest))
    assert GODOT is not None
    start = time.monotonic()
    check = verify_with_godot(GODOT, tmp_path / "game", "res://gen/manifest.json", timeout=60)
    assert not check.ok and "the check script hit an error" in check.output, check.output
    assert time.monotonic() - start < 50


# --- R19: fit holds the pivot; --even --------------------------------------------------------------

FLAGS = """\
name: flags
size: [6, 6]
pivot: [3, 3]
directions: 4
outline: none
origin: [0, 0, 0]
materials:
  cloth: { ramp: red }
parts:
  - box: { from: [-1, 0, 14], to: [1, 0, 15], material: cloth }
"""


def _fit(project: Project, *extra: str, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    assert main(["fit", str(project.root / "models" / "flags.model.yaml"), "--json", *extra]) == 0
    result: dict[str, object] = json.loads(capsys.readouterr().out)
    return result


def _apply(path: Path, size: object, pivot: object) -> None:
    text = re.sub(r"size: \[.*\]", f"size: {size}", path.read_text())
    path.write_text(re.sub(r"pivot: \[.*\]", f"pivot: {pivot}", text))


def test_fit_grows_the_frame_to_hold_an_overlays_pivot(project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    path = project.root / "models" / "flags.model.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(FLAGS)
    result = _fit(project, capsys=capsys)
    assert result["grown_for_pivot"] is True
    size, pivot = result["size"], result["pivot"]
    assert isinstance(size, list) and isinstance(pivot, list)
    assert 0 <= pivot[0] <= size[0] and 0 <= pivot[1] <= size[1]
    _apply(path, size, pivot)
    asset, findings = load_asset(path, load_project(project.root))
    assert asset is not None and not [f for f in findings if f.rule in ("E007", "E008")], [f.format() for f in findings]


def test_fit_even(project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    path = project.root / "models" / "flags.model.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(FLAGS.replace("from: [-1, 0, 14]", "from: [-2, 0, 14]"))
    plain, even = _fit(project, capsys=capsys), _fit(project, "--even", capsys=capsys)
    assert isinstance(plain["size"], list) and isinstance(even["size"], list)
    assert all(n % 2 == 0 for n in even["size"])
    assert [n + n % 2 for n in plain["size"]] == even["size"] and even["pivot"] == plain["pivot"]
