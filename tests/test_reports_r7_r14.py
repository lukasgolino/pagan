"""Fixes for orchestrator reports R7-R14 (ORCHESTRATOR_PLAN.md, Age of Boom G2-G3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import LoadFn, make_project
from pagan.asset import Asset, load_asset
from pagan.build import build
from pagan.cli import main
from pagan.findings import Finding
from pagan.lint import lint_paths
from pagan.project import Project, load_project
from pagan.voxel import Cell, PartMove, VoxelData, move_cells

MODEL_HEAD = """\
name: {name}
size: [24, 24]
pivot: [12, 15]
directions: 4
outline: none
materials:
  wood: {{ ramp: red }}
  sail: {{ ramp: green }}
parts:
  - box: {{ from: [-4, -1, 0], to: [4, 1, 1], material: wood }}
"""


def _mkdir(path: Path) -> Path:
    path.mkdir()
    return path


def write_model(project: Project, body: str, name: str = "boat") -> Path:
    (project.root / "models").mkdir(exist_ok=True)
    path = project.root / "models" / f"{name}.model.yaml"
    path.write_text(MODEL_HEAD.format(name=name) + body)
    return path


def load_model(project: Project, body: str, name: str = "boat") -> tuple[Asset | None, list[Finding]]:
    return load_asset(write_model(project, body, name), project)


# --- R14: W001 on models -------------------------------------------------------------------------


def test_models_skip_w001_and_label_frames(project: Project) -> None:
    # A lone voxel far from the hull renders as an orphan pixel.
    write_model(project, "  - box: { from: [0, 0, 6], to: [0, 0, 6], material: wood }\n")
    findings = lint_paths(project).findings
    assert not [f for f in findings if f.rule == "W001"]
    assert all(not (f.where or "").startswith("tiles.") for f in findings)


# --- R7: per-asset lint suppression ----------------------------------------------------------------

BURST = """\
name: burst
size: [5, 5]
frames:
  a: |
    .....
    .....
    ..1..
    .....
    .....
  b: |
    .111.
    11111
    11111
    11111
    .111.
animations:
  pop: { frames: [a, b], fps: 8 }
"""


def test_asset_lint_disable(project: Project, load: LoadFn) -> None:
    load(BURST, "burst")
    rules = {f.rule for f in lint_paths(project).findings}
    assert {"W001", "W005", "W007"} <= rules
    load(BURST + "lint: { disable: [W005, W007] }\n", "burst")
    rules = {f.rule for f in lint_paths(project).findings}
    assert "W005" not in rules and "W007" not in rules and "W001" in rules


def test_lint_for_one_frame_or_animation(project: Project, load: LoadFn) -> None:
    load(BURST + "lint:\n  for: { a: [W001], pop: [W005, W007] }\n", "burst")
    assert not lint_paths(project).warnings


def test_lint_section_errors(load: LoadFn) -> None:
    _, findings = load(BURST + "lint: { disable: [E002], for: { nope: [W001] }, extra: 1 }\n", "burst")
    messages = " ".join(f.message for f in findings)
    assert "errors can't be disabled" in messages and "isn't a frame" in messages and "unknown lint field" in messages


def test_tile_lint_for(project: Project, load: LoadFn) -> None:
    load("name: shore\ntile_size: [2, 2]\ntiles:\n  empty: |\n    ..\n    ..\n  full: |\n    11\n    11\n", "shore", kind="tileset")
    assert [f.rule for f in lint_paths(project).warnings] == ["W004"]
    load(
        "name: shore\ntile_size: [2, 2]\nlint: { for: { empty: [W004] } }\n"
        "tiles:\n  empty: |\n    ..\n    ..\n  full: |\n    11\n    11\n",
        "shore",
        kind="tileset",
    )
    assert not lint_paths(project).warnings


def test_model_lint_for_pose_animation(project: Project) -> None:
    body = """\
  - box: { from: [-1, -1, 2], to: [1, 1, 8], material: sail }
    id: mast
animations:
  gone: { poses: [ { hide: [mast] } ] }
lint: { for: { gone: [W005] } }
"""
    asset, findings = load_model(project, body)
    assert asset is not None, [f.format() for f in findings]
    assert {"gone_e", "gone_e_0"} <= set(asset.lint_disable_for)


def test_build_and_lint_count_warnings_by_rule(project: Project, load: LoadFn, capsys: pytest.CaptureFixture[str]) -> None:
    load(BURST, "burst")
    assert main(["lint", str(project.root)]) == 0
    assert "W001×1" in capsys.readouterr().out


# --- R10: hidden parts are overlays ----------------------------------------------------------------

DECAL = """\
  - box: {{ from: [-1, -1, 1], to: [1, 1, 1], material: sail }}
    id: scorch
    hidden: true{carve}
animations:
  damaged: {{ poses: [ {{ show: [scorch] }} ] }}
"""


def test_hidden_part_never_changes_normal_frames(tmp_path: Path) -> None:
    plain, decal = (make_project(_mkdir(tmp_path / n)) for n in "ab")
    base, _ = load_model(plain, "")
    with_decal, findings = load_model(decal, DECAL.format(carve=""))
    assert base is not None and with_decal is not None, [f.format() for f in findings]
    for heading in ("e", "n", "w", "s"):
        assert with_decal.frames[heading] == base.frames[heading]
        assert with_decal.frames[f"damaged_{heading}_0"] != base.frames[heading]  # shown: drawn over the hull


def test_hidden_carve_cuts_only_when_shown(tmp_path: Path) -> None:
    plain, holed = (make_project(_mkdir(tmp_path / n)) for n in "ab")
    base, _ = load_model(plain, "")
    asset, findings = load_model(holed, DECAL.format(carve="\n    carve: true"))
    assert base is not None and asset is not None, [f.format() for f in findings]
    assert asset.frames["n"] == base.frames["n"]
    assert asset.frames["damaged_n_0"] != base.frames["n"]  # the hole shows


def test_visible_carve_still_cuts_hidden_layers(project: Project) -> None:
    body = """\
  - box: { from: [-2, -3, 3], to: [2, 3, 3], material: sail }
    id: deck_cloth
    hidden: true
  - box: { from: [-2, -3, 3], to: [2, 3, 3], material: sail }
    carve: true
animations:
  shown: { poses: [ { show: [deck_cloth] } ] }
"""
    asset, findings = load_model(project, body)
    assert asset is not None, [f.format() for f in findings]
    assert asset.frames["shown_e_0"] == asset.frames["e"]


def test_id_shared_by_hidden_and_visible_parts_is_an_error(project: Project) -> None:
    body = """\
  - box: { from: [0, 0, 2], to: [0, 0, 2], material: sail }
    id: mixed
  - box: { from: [1, 0, 2], to: [1, 0, 2], material: sail }
    id: mixed
    hidden: true
"""
    _, findings = load_model(project, body)
    assert any("hidden and visible" in f.message for f in findings)


# --- R9: roll and pitch --------------------------------------------------------------------------

MAST = """\
  - box: {{ from: [0, 0, 2], to: [0, 0, 9], material: sail }}
    id: mast
animations:
  sink: {{ poses: [ {pose} ] }}
"""


def test_whole_model_roll_and_pitch(project: Project) -> None:
    asset, findings = load_model(project, MAST.format(pose="{ roll: 20 }") )
    assert asset is not None, [f.format() for f in findings]
    assert asset.frames["sink_e_0"] != asset.frames["e"]
    asset, _ = load_model(project, MAST.format(pose="{ roll: 0, pitch: 0 }"))
    assert asset is not None and asset.frames["sink_e_0"] == asset.frames["e"]


def test_part_rotation_keeps_thin_parts_solid() -> None:
    mast: dict[Cell, VoxelData] = {(0, 0, z): ("wood", "mast", 0, None) for z in range(10)}
    fallen = move_cells(mast, PartMove(pitch=90))
    assert len(fallen) >= 10
    assert {z for _, _, z in fallen} == {0}  # lying flat on its hinge
    leaning = move_cells(mast, PartMove(roll=45))
    zs = sorted({z for _, _, z in leaning})
    assert zs == list(range(zs[0], zs[-1] + 1))  # no gaps along its length
    shifted = move_cells(mast, PartMove(offset=(1, 2, 3)))
    assert (1, 2, 3) in shifted and len(shifted) == 10


def test_part_rotation_in_a_pose(project: Project) -> None:
    asset, findings = load_model(project, MAST.format(pose="{ mast: { pitch: -80, about: [0.5, 0.5, 2] } }"))
    assert asset is not None, [f.format() for f in findings]
    assert asset.frames["sink_n_0"] != asset.frames["n"]


def test_bad_pose_fields(project: Project) -> None:
    _, findings = load_model(project, MAST.format(pose="{ roll: 999, mast: { spin: 3 } }"))
    messages = " ".join(f.message for f in findings)
    assert "tilts the whole model" in messages and "a part's pose is" in messages


# --- R13: pagan fit --------------------------------------------------------------------------------


def test_fit_suggests_a_frame_for_every_pose(project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_model(project, MAST.format(pose="{ mast: { pitch: -90 } }").replace("to: [0, 0, 9]", "to: [0, 0, 20]"))
    assert main(["fit", str(path), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["clipped"]  # the 21-voxel mast doesn't fit 24x24
    text = path.read_text()
    text = text.replace("size: [24, 24]", f"size: {result['size']}").replace("pivot: [12, 15]", f"pivot: {result['pivot']}")
    text = text.replace("outline: none", "outline: auto")
    path.write_text(text)
    assert main(["fit", str(path), "--json"]) == 0
    refit = json.loads(capsys.readouterr().out)
    assert refit["size"][0] == result["size"][0] + 2  # outline: one free pixel each side
    text = text.replace(f"size: {result['size']}", f"size: {refit['size']}").replace(f"pivot: {result['pivot']}", f"pivot: {refit['pivot']}")
    path.write_text(text)
    asset, findings = load_asset(path, load_project(project.root))
    assert asset is not None, [f.format() for f in findings]  # no E007
    assert main(["fit", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["clipped"] == []


def test_fit_write_sets_size_and_pivot(project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    # #35: --write edits the file (keeping comments) so the model passes lint without a manual patch.
    path = write_model(project, MAST.format(pose="{ mast: { pitch: -90 } }").replace("to: [0, 0, 9]", "to: [0, 0, 20]"))
    path.write_text(path.read_text().replace("outline: none", "outline: auto  # keep me"))
    _, findings = load_asset(path, load_project(project.root))
    assert any(f.rule == "E007" for f in findings)
    assert main(["fit", str(path), "--write", "--even", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["written"] is True
    text = path.read_text()
    assert f"size: [{result['size'][0]}, {result['size'][1]}]" in text and f"pivot: [{result['pivot'][0]}, {result['pivot'][1]}]" in text
    assert "outline: auto  # keep me" in text
    asset, findings = load_asset(path, load_project(project.root))
    assert asset is not None and not [f for f in findings if f.severity == "error"], [f.format() for f in findings]
    assert main(["fit", str(path), "--write", "--even", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["written"] is False  # already fits: nothing to change
    assert path.read_text() == text


def test_fit_rejects_sprites(project: Project, load: LoadFn) -> None:
    load(BURST, "burst")
    assert main(["fit", str(project.root / "sprites" / "burst.sprite.yaml")]) == 1


# --- R8: animated tiles ----------------------------------------------------------------------------

WATER = """\
name: sea
tile_size: [2, 2]
columns: 3
tiles:
  rock: |
    11
    11
  water_0: |
    55
    5.
  water_1: |
    55
    .5
  water_2: |
    .5
    55
  sand: |
    44
    44
animations:
  water: { frames: [water_0, water_1, water_2], fps: 4 }
"""


def test_tile_animation_layout(load: LoadFn) -> None:
    from pagan.render import tile_cells

    asset, findings = load(WATER, "sea", kind="tileset")
    assert asset is not None, [f.format() for f in findings]
    # rock at (0,0); the 3 water frames don't fit after it in a 3-wide row, so they take row 1; sand goes after them
    assert tile_cells(asset) == {"rock": (0, 0), "water_0": (0, 1), "water_1": (1, 1), "water_2": (2, 1), "sand": (0, 2)}


def test_tile_animation_errors(load: LoadFn) -> None:
    bad = WATER.replace("{ frames: [water_0, water_1, water_2], fps: 4 }", "{ frames: [water_0, water_0, nope], loop: false }")
    _, findings = load(bad, "sea", kind="tileset")
    messages = " ".join(f.message for f in findings)
    assert "always loop" in messages
    bad = WATER.replace("[water_0, water_1, water_2], fps: 4", "[water_0, water_0, nope]")
    _, findings = load(bad, "sea", kind="tileset")
    messages = " ".join(f.message for f in findings)
    assert "missing tile 'nope'" in messages and "repeats water_0" in messages
    bad = WATER.replace("  water: {", "  rock: {")
    _, findings = load(bad, "sea", kind="tileset")
    assert any("also a tile name" in f.message for f in findings)


def test_tile_animation_godot_export(tmp_path: Path) -> None:
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "project.godot").write_text("config_version=5\n")
    (tmp_path / "game" / "art").mkdir()
    project = make_project(tmp_path / "game" / "art", 'default_palette = "test"\noutput_dir = "../gen"\nexport = ["png", "godot"]\n')
    (project.root / "tiles" / "sea.tiles.yaml").write_text(WATER)
    result = build(load_project(project.root))
    assert not result.errors, [f.format() for f in result.errors]
    tres = (tmp_path / "game" / "gen" / "tiles" / "sea.tres").read_text()
    assert "0:1/animation_speed = 4.0\n0:1/animation_frame_0/duration = 1.0" in tres
    assert "0:1/0 = 0" in tres and "1:1/0 = 0" not in tres and "animation_columns" not in tres
    manifest = json.loads((tmp_path / "game" / "gen" / "manifest.json").read_text())
    entry = manifest["assets"]["sea"]
    assert entry["tiles"] == {"rock": [0, 0], "sand": [0, 2], "water": [0, 1]}
    assert entry["animations"]["water"] == {"frames": ["water_0", "water_1", "water_2"], "fps": 4.0, "loop": True}


def test_long_tile_animation_wraps_into_a_block(load: LoadFn) -> None:
    from pagan.build import _atlas_tiles
    from pagan.render import tile_cells

    asset, findings = load(WATER.replace("columns: 3", "columns: 2"), "sea", kind="tileset")
    assert asset is not None, [f.format() for f in findings]
    cells = tile_cells(asset)
    assert cells["water_0"] == (0, 1) and cells["water_2"] == (0, 2) and cells["sand"] == (0, 3)
    water = next(t for t in _atlas_tiles(asset) if (t.column, t.row) == (0, 1))
    assert water.frames == 3 and water.columns == 2
