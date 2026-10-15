"""pagan config: the settings registry, safe TOML edits, refreshes; engine lighting (flat + normal maps)."""

from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

import pytest
from PIL import Image

from conftest import make_project
from pagan.asset import load_asset_or_raise
from pagan.build import build
from pagan.cli import main
from pagan.findings import PaganError
from pagan.project import Config, load_project
from pagan.settings import SETTINGS, current_value, describe, set_in_toml, set_setting

GOLDEN = Path(__file__).parent / "fixtures" / "golden"


def test_registry_defaults_match_the_code() -> None:
    config = Config()
    for setting in SETTINGS:
        if setting.key in ("default_palette",):
            continue
        assert current_value(config, setting.key) == setting.default, setting.key


def test_set_in_toml_keeps_comments_and_layout() -> None:
    text = 'palette_mode = "strict"  # mode\n\n[camera]\nelevation = 42      # angle\nscale = 1\n\n[lint]\ndisable = []\n'
    assert set_in_toml(text, "camera.elevation", 30) == text.replace("elevation = 42      # angle", "elevation = 30      # angle")
    assert set_in_toml(text, "palette_mode", "open").startswith('palette_mode = "open"  # mode\n')
    added = set_in_toml(text, "light.ambient", 0.1)
    assert added.endswith("\n[light]\nambient = 0.1\n") and tomllib.loads(added)["light"]["ambient"] == 0.1
    top = set_in_toml(text, "style_version", 3)
    assert tomllib.loads(top)["style_version"] == 3 and top.index("style_version") < top.index("[camera]")
    inside = set_in_toml(text, "lint.require_outline", True)
    assert tomllib.loads(inside)["lint"] == {"disable": [], "require_outline": True}
    assert set_in_toml('x = "a # not a comment"\n', "x", "b") == 'x = "b"\n'


def test_set_setting_validates_and_never_writes_bad_config(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    before = project.config_path.read_text() if project.config_path else ""
    for key, value in [("camera.elevation", "5"), ("light.direction", "[0, 0]"), ("nope", "1"), ("default_palette", "missing")]:
        with pytest.raises(PaganError):
            set_setting(project, key, value)
        assert project.config_path is not None and project.config_path.read_text() == before
    change = set_setting(project, "camera.elevation", "30")
    assert (change.old, change.new, change.refresh) == (42.0, 30.0, "models")
    assert load_project(tmp_path).config.camera.elevation == 30


def test_describe_marks_changes(tmp_path: Path) -> None:
    project = make_project(tmp_path, 'default_palette = "test"\n[light]\nambient = 0.1\n')
    rows = {r["key"]: r for r in describe(project.config)}
    assert rows["light.ambient"]["value"] == 0.1 and not rows["light.ambient"]["is_default"]
    assert rows["camera.elevation"]["is_default"]


def test_camera_change_rerenders_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    shutil.copytree(GOLDEN, tmp_path / "art", ignore=shutil.ignore_patterns("expected", ".pagan-cache"))
    monkeypatch.chdir(tmp_path / "art")
    path = tmp_path / "art" / "models" / "crate.model.yaml"
    before = load_asset_or_raise(path, load_project(tmp_path / "art")).frames
    assert main(["config", "set", "camera.elevation", "70", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["models"] == ["crate"] and set(result["hand_drawn"]) == {"bug", "turf"}
    after = load_asset_or_raise(path, load_project(tmp_path / "art")).frames
    assert after != before
    assert main(["config", "get", "camera.elevation"]) == 0
    assert capsys.readouterr().out.strip() == "70.0"
    assert main(["config", "show"]) == 0


def test_flat_lighting_uses_one_shade_per_material(tmp_path: Path) -> None:
    shutil.copytree(GOLDEN, tmp_path / "art", ignore=shutil.ignore_patterns("expected", ".pagan-cache"))
    (tmp_path / "art" / "pagan.toml").write_text('default_palette = "mini"\n[light]\nbaked = false\n')
    crate = load_asset_or_raise(tmp_path / "art" / "models" / "crate.model.yaml", load_project(tmp_path / "art"))
    used = {c for grid in crate.base_frames.values() for row in grid for c in row if c != "."}
    assert used == {"5", "2", "6"}  # middle step of berry and leaf, plus the flat gem key


def test_normals_export(tmp_path: Path) -> None:
    shutil.copytree(GOLDEN, tmp_path / "art", ignore=shutil.ignore_patterns("expected", ".pagan-cache"))
    game = tmp_path / "game"
    game.mkdir()
    (game / "project.godot").write_text("config_version=5\n")
    (tmp_path / "art" / "pagan.toml").write_text(
        'default_palette = "mini"\noutput_dir = "../game/gen"\nexport = ["png", "godot", "normals"]\n'
    )
    project = load_project(tmp_path / "art")
    result = build(project)
    assert not result.errors
    sheet = Image.open(game / "gen" / "sprites" / "crate.png")
    normals = Image.open(game / "gen" / "sprites" / "crate.normal.png")
    assert normals.size == sheet.size and normals.mode == "RGBA"
    assert sheet.getchannel("A").tobytes() == normals.getchannel("A").tobytes()
    tres = (game / "gen" / "sprites" / "crate.tres").read_text()
    assert 'normal_texture = ExtResource("2_normal")' in tres and 'atlas = SubResource("CanvasTexture_sheet")' in tres
    assert not (game / "gen" / "sprites" / "bug.normal.png").exists()  # 2D sprites have no normals
    manifest = json.loads((game / "gen" / "manifest.json").read_text())
    assert manifest["assets"]["crate"]["normal_sheet"] == "res://gen/sprites/crate.normal.png"
    # Top faces point up the screen and towards the viewer: green and blue above 128 on the lid.
    pixel = normals.getpixel((16, 13))
    assert isinstance(pixel, tuple)
    r, g, b, a = pixel
    assert a == 255 and g > 128 and b > 128
