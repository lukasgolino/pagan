"""3D review previews (MESH_PLAN M6): orbit sheets (from below to straight down), part closeups, the Godot
engine render, and mesh-only models in previews and the gallery."""

from __future__ import annotations

import io
import json
import os
import shutil
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from conftest import make_project
from pagan.asset import Asset, load_asset
from pagan.cli import main
from pagan.exporters.godot import find_godot_binary
from pagan.project import Project
from pagan.views import closeup_views, orbit_views

ROOT = Path(__file__).parent.parent

TOWER = """\
name: tower
directions: {directions}
{size}origin: [0, 0, 0]
outline: none
materials:
  stone: {{ ramp: mono }}
  base: {{ keys: ["5"] }}
  flag: {{ ramp: red }}
parts:
  - box: {{ from: [0, 0, 0], to: [0, 0, 0], material: base }}  # deep under the overhang: seen only from below
  - box: {{ from: [-2, -2, 1], to: [2, 2, 9], material: stone }}
  - box: {{ from: [0, 0, 10], to: [0, 0, 13], material: flag }}
    id: flag
"""


def cli(root: Path, *argv: str) -> dict[str, Any]:
    previous = os.getcwd()
    os.chdir(root)
    try:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            main(["--json", *argv])
    finally:
        os.chdir(previous)
    result: dict[str, Any] = json.loads(buffer.getvalue())
    return result


def tower(project: Project, directions: int = 4, size: str = "size: [32, 40]\n") -> Asset:
    (project.root / "models").mkdir(exist_ok=True)
    path = project.root / "models" / "tower.model.yaml"
    path.write_text(TOWER.format(directions=directions, size=size))
    asset, findings = load_asset(path, project)
    assert asset is not None, [f.format() for f in findings]
    return asset


def colours(image: Image.Image) -> set[tuple[int, ...]]:
    pixels = np.array(image.convert("RGBA")).reshape(-1, 4)
    return {tuple(int(v) for v in p) for p in pixels[pixels[:, 3] > 0]}


def test_orbit_shows_the_underside_only_from_below(project: Project) -> None:
    rows = orbit_views(tower(project), 1.0)
    assert [label.split(" (")[0] for label, _ in rows] == ["elevation -30°", "elevation +0°", "elevation +30°", "elevation +60°", "elevation +90°"]
    assert [v.label for v in rows[0][1]] == ["e", "ne", "n", "nw", "w", "sw", "s", "se"]
    blue = (0, 0, 255, 255)  # the base plate's colour: only its bottom face is visible, and only from below
    assert blue in colours(rows[0][1][0].image)
    assert blue not in colours(rows[2][1][0].image) and blue not in colours(rows[4][1][0].image)


def test_closeup_fills_the_view_with_one_part(project: Project) -> None:
    rows = closeup_views(tower(project), "flag")
    alone = rows[-1][1][0].image
    box = alone.getbbox()
    assert box is not None and (box[3] - box[1]) > alone.height * 0.6  # the 4-voxel flag fills the view
    assert colours(alone) <= {(255, 0, 0, 255), (255, 128, 128, 255)}  # nothing but the flag
    with pytest.raises(KeyError):
        closeup_views(tower(project), "nope")


def test_preview_cli_orbit_and_closeup(project: Project) -> None:
    tower(project)
    result = cli(project.root, "preview", "tower", "--orbit", "--closeup", "flag", "--closeup", "nope")
    assert not result["ok"] and "has no part 'nope' (parts: body, flag)" in result["findings"][0]["message"]
    output = result["outputs"][0]
    assert output["orbit"] == "previews/tower/orbit.png" and output["closeup"] == {"flag": "previews/tower/closeup_flag.png"}
    assert "sheet" not in output  # only the 3D views were asked for
    assert Image.open(project.root / output["orbit"]).width > 400
    both = cli(project.root, "preview", "tower", "--orbit", "--all-previews")["outputs"][0]
    assert {"orbit", "sheet", "montage"} <= set(both)
    sprite = cli(project.root, "preview", "tower", "--engine")
    assert not sprite["ok"] and "export" in sprite["findings"][0]["message"]  # nothing built yet


def test_orbit_needs_a_model(project: Project) -> None:
    (project.root / "sprites" / "dot.sprite.yaml").write_text("name: dot\nsize: [1, 1]\nframes:\n  a: |\n    1\n")
    result = cli(project.root, "preview", "dot", "--orbit")
    assert not result["ok"] and "need a 3D model" in result["findings"][0]["message"]


def test_mesh_only_models_preview_as_orbit_and_join_the_gallery(tmp_path: Path) -> None:
    project = make_project(tmp_path, 'default_palette = "test"\nexport = ["png", "mesh"]\n')
    tower(project, directions=0, size="")
    (project.root / "sprites" / "dot.sprite.yaml").write_text("name: dot\nsize: [2, 2]\nframes:\n  a: |\n    11\n    11\n")
    output = cli(project.root, "preview", "tower")["outputs"][0]
    assert output["sheet"] == "previews/tower/orbit.png" and output["frames"] == []
    assert Image.open(project.root / output["montage"]).getbbox() is not None
    gallery = cli(project.root, "gallery")
    assert gallery["ok"] and gallery["assets"] == 2


@pytest.mark.skipif(find_godot_binary() is None or not os.environ.get("DISPLAY"), reason="needs Godot and a display")
def test_engine_preview_renders_through_godot(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "examples" / "demo", tmp_path / "demo", ignore=shutil.ignore_patterns("previews", ".pagan-cache"))
    shutil.copytree(ROOT / "examples" / "godot", tmp_path / "godot", ignore=shutil.ignore_patterns(".godot", "*.import"))
    assert cli(tmp_path / "demo", "build")["ok"]
    result = cli(tmp_path / "demo", "preview", "sailor", "--engine")
    assert result["ok"], result
    sheet = Image.open(tmp_path / "demo" / result["outputs"][0]["engine"])
    assert sheet.width > 1000 and len(colours(sheet)) > 10


def test_mesh_only_models_in_other_commands(tmp_path: Path) -> None:
    project = make_project(tmp_path, 'default_palette = "test"\nexport = ["png", "mesh"]\n')
    tower(project, directions=0, size="")
    render = cli(project.root, "render", "tower")
    assert not render["ok"] and "mesh-only" in render["findings"][0]["message"]
    bake = cli(project.root, "bake", "tower")
    assert not bake["ok"] and "mesh-only" in bake["findings"][0]["message"]
    assert not (project.sprites_dir / "tower_baked.sprite.yaml").exists()
    status = cli(project.root, "status")
    assert status["ok"]
    assert cli(project.root, "build")["ok"]
