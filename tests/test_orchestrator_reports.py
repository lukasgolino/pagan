"""Fixes for reports filed by game orchestrators in ORCHESTRATOR_PLAN.md (R1-R6) and the game's PAGAN log."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import LoadFn, make_project
from pagan.buildinfo import version_string
from pagan.cli import main
from pagan.findings import PaganError
from pagan.project import load_project
from pagan.settings import set_setting


def test_version_string_names_the_build() -> None:
    text = version_string()
    assert text.startswith("pagan ") and "(" in text  # this test suite runs from an editable checkout


def test_init_godot_sets_output_and_gdignore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "project.godot").write_text("config_version=5\n")
    monkeypatch.chdir(tmp_path / "game")
    assert main(["init", "art", "--godot", ".", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    config = load_project(tmp_path / "game" / "art").config
    assert config.output_dir == "../assets/generated" and config.export == ("png", "godot")
    assert (tmp_path / "game" / "art" / ".gdignore").exists() and result["godot_project"] == "."
    assert main(["init", "elsewhere", "--godot", "nope"]) == 1


def test_init_outside_godot_has_no_gdignore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init", "art"]) == 0
    assert not (tmp_path / "art" / ".gdignore").exists()


def test_config_lists_accept_commas_and_errors_show_syntax(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    change = set_setting(project, "export", "png,normals")
    assert change.new == ["png", "normals"]
    with pytest.raises(PaganError) as exc:
        set_setting(load_project(tmp_path), "export", "png,unity")
    assert "TOML" in exc.value.findings[0].message and '["png"]' in exc.value.findings[0].message


def test_mirrored_animation(load: LoadFn) -> None:
    asset, findings = load(
        "name: thing\nsize: [3, 1]\nframes:\n  a: |\n    12.\n  b: |\n    .12\n"
        "animations:\n  walk_left: { frames: [a, b], fps: 6, loop: false }\n"
        "  walk_right: { from: walk_left, flip: horizontal }\n"
    )
    assert asset is not None, [f.format() for f in findings]
    right = asset.animations["walk_right"]
    assert right.frames == ("walk_right_0", "walk_right_1") and right.fps == 6 and right.loop is False
    assert asset.frames["walk_right_0"] == (".21",) and asset.derived_from["walk_right_1"] == "b"


def test_mirrored_animation_errors(load: LoadFn) -> None:
    base = "name: thing\nsize: [3, 1]\nframes:\n  a: |\n    12.\nanimations:\n  l: [a]\n"
    assert {f.rule for f in load(base + "  r: { from: nope, flip: horizontal }\n")[1]} == {"E004"}
    assert {f.rule for f in load(base + "  r: { from: l, flip: sideways }\n")[1]} == {"E010"}
    clash = base.replace("  a: |\n    12.\n", "  a: |\n    12.\n  r_0: |\n    1..\n")
    assert "E001" in {f.rule for f in load(clash + "  r: { from: l, flip: horizontal }\n")[1]}


def test_e007_reported_once_for_derived_frames(load: LoadFn) -> None:
    text = (
        "name: thing\nsize: [4, 3]\nmirror: horizontal\noutline: auto\nframes:\n  a: |\n    ..\n    1.\n    ..\n"
        "  b: { from: a, flip: horizontal }\nanimations:\n  l: [a]\n  r: { from: l, flip: horizontal }\n"
    )
    _, findings = load(text)
    e007 = [f for f in findings if f.rule == "E007"]
    assert len(e007) == 1 and e007[0].where == "frames.a row 2 col 1"


def test_scaffold_outline_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["new", "sprite", "hero", "--outline"]) == 0
    assert "keep the outermost rows and columns empty" in (tmp_path / "sprites" / "hero.sprite.yaml").read_text()


# --- Age of Boom G1 log ---


def test_palette_files_accept_description(tmp_path: Path) -> None:
    from pagan.palette import load_palette_file

    path = tmp_path / "naval.pal.yaml"
    path.write_text('name: naval\ndescription: "sea, wood and team colours"\ncolors:\n  "a": "#123456"\n')
    assert load_palette_file(path).name == "naval"


def test_new_model_in_open_mode_without_palette(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init", "--open"]) == 0
    assert main(["new", "model", "boat", "--directions", "32"]) == 0
    assert main(["lint"]) == 0
    from pagan.asset import load_asset_or_raise

    boat = load_asset_or_raise(tmp_path / "models" / "boat.model.yaml", load_project(tmp_path))
    assert list(boat.frames)[:3] == ["h00", "h01", "h02"] and len(boat.frames) == 32


def test_new_model_strict_without_palette_suggests_fix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(tmp_path)
    main(["init"])
    capsys.readouterr()
    assert main(["new", "model", "boat"]) == 1
    assert "pagan new palette" in capsys.readouterr().out


def test_default_palette_change_counts_only_followers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_project(tmp_path)
    (tmp_path / "sprites" / "a.sprite.yaml").write_text("name: a\nsize: [1, 1]\nframes:\n  x: |\n    1\n")
    (tmp_path / "sprites" / "b.sprite.yaml").write_text("name: b\npalette: test\nsize: [1, 1]\nframes:\n  x: |\n    1\n")
    monkeypatch.chdir(tmp_path)
    capsys.readouterr()
    assert main(["config", "set", "default_palette", "other"]) == 0
    assert "1 assets don't name a palette and follow the default: a." in capsys.readouterr().out


def test_fore_aft_sail_and_triangle(tmp_path: Path) -> None:
    from pagan.model import _Builder
    from pagan.voxel import Material, VoxelModel

    model = VoxelModel()
    errors: list[str] = []
    builder = _Builder(model, lambda *a: errors.append(str(a)), {"m": Material("m", ("1", "2"), two_sided=True)})
    builder.build(
        [
            {"sail": {"at": [0, 0, 0], "width": 10, "height": 4, "bulge": 0, "rig": "fore-aft", "material": "m"}},
            {"triangle": {"points": [[20, 0, 0], [26, 0, 0], [20, 0, 6]], "material": "m"}},
        ],
        None,
    )
    assert not errors
    sail = [c for c in model.voxels if c[0] <= 0]
    assert min(c[0] for c in sail) <= -9 and max(c[0] for c in sail) == 0  # luff at the mast, reaching aft
    assert len({c[1] for c in sail}) <= 2  # lies along the hull (2 voxels thick), not across it
    tri = [c for c in model.voxels if c[0] >= 20]
    assert (20, 0, 6) in tri and (26, 0, 0) in tri and all(c[1] == 0 for c in tri)
    assert all(model.normals[c] in ((0.0, -1.0, 0.0), (0.0, 1.0, 0.0)) for c in tri)


def test_models_get_their_own_ramp_limit() -> None:
    from pagan.project import Config

    assert Config().lint.max_ramps_per_model == 6 and Config().lint.max_ramps_per_sprite == 3
