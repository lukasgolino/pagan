"""pagan build: outputs, manifest, determinism, stale-file removal, Godot .tres text."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pagan.build import build
from pagan.cli import main
from pagan.exporters.godot import centered_offset, sprite_frames_tres
from pagan.asset import Animation
from pagan.project import Project, load_project

GOLDEN = Path(__file__).parent / "fixtures" / "golden"


@pytest.fixture
def proj(tmp_path: Path) -> Project:
    shutil.copytree(GOLDEN, tmp_path / "art", ignore=shutil.ignore_patterns("expected", ".pagan-cache"))
    (tmp_path / "art" / "pagan.toml").write_text('default_palette = "mini"\noutput_dir = "out"\n')
    return load_project(tmp_path / "art")


def godot_project(proj: Project) -> Project:
    game = proj.root.parent / "game"
    game.mkdir()
    (game / "project.godot").write_text("config_version=5\n")
    (proj.root / "pagan.toml").write_text(
        'default_palette = "mini"\noutput_dir = "../game/assets/generated"\nexport = ["png", "godot"]\n'
    )
    return load_project(proj.root)


def test_build_outputs_and_manifest(proj: Project) -> None:
    result = build(proj)
    assert not result.errors
    out = proj.output_dir
    for name in ("sprites/bug.png", "sprites/bug.ripe.png", "sprites/crate.png", "tiles/turf.png", "manifest.json"):
        assert (out / name).is_file(), name
    manifest = json.loads((out / "manifest.json").read_text())
    bug = manifest["assets"]["bug"]
    assert bug["sheet"] == "sprites/bug.png" and bug["size"] == [9, 9] and bug["pivot"] == [4, 8]
    assert bug["frames"]["walk_1"] == [9, 0, 9, 9]
    assert bug["animations"]["walk"] == {"frames": ["walk_0", "walk_1"], "fps": 6.0, "loop": True}
    assert bug["variants"]["ripe"]["sheet"] == "sprites/bug.ripe.png"
    assert bug["godot_offset"] == [0.5, -3.5]
    assert manifest["assets"]["crate"]["headings"] == ["e", "n", "w", "s"]
    assert "sprites/bug.png" in manifest["files"]


def test_tileset_atlas_coordinates(proj: Project) -> None:
    (proj.root / "tiles" / "four.tiles.yaml").write_text(
        "name: four\ntile_size: [2, 2]\ncolumns: 3\ntiles:\n"
        + "".join(f"  t{i}: |\n    {k}{k}\n    {k}{k}\n" for i, k in enumerate("1234"))
    )
    build(proj)
    entry = json.loads((proj.output_dir / "manifest.json").read_text())["assets"]["four"]
    assert entry["frames"] == {"t0": [0, 0, 2, 2], "t1": [2, 0, 2, 2], "t2": [4, 0, 2, 2], "t3": [0, 2, 2, 2]}
    assert entry["columns"] == 3


def test_build_is_deterministic_and_incremental(proj: Project) -> None:
    first = build(proj)
    snapshot = {p.relative_to(proj.output_dir): p.read_bytes() for p in proj.output_dir.rglob("*") if p.is_file()}
    second = build(proj)
    assert second.written == [] and len(second.unchanged) == len(first.written)
    shutil.rmtree(proj.output_dir)
    shutil.rmtree(proj.root / ".pagan-cache", ignore_errors=True)
    build(proj)
    again = {p.relative_to(proj.output_dir): p.read_bytes() for p in proj.output_dir.rglob("*") if p.is_file()}
    assert again == snapshot


def test_build_removes_stale_outputs(proj: Project) -> None:
    build(proj)
    (proj.root / "sprites" / "bug.sprite.yaml").unlink()
    result = build(proj)
    assert {p.name for p in result.removed} == {"bug.png", "bug.ripe.png"}
    assert not (proj.output_dir / "sprites" / "bug.png").exists()
    assert (proj.output_dir / "tiles" / "turf.png").exists()


def test_build_fails_on_lint_errors(proj: Project) -> None:
    (proj.root / "sprites" / "bad.sprite.yaml").write_text("name: bad\nsize: [1, 1]\nframes:\n  a: |\n    z\n")
    result = build(proj)
    assert [f.rule for f in result.errors] == ["E002"]
    assert not proj.output_dir.exists()


def test_godot_export_needs_a_godot_project(proj: Project) -> None:
    (proj.root / "pagan.toml").write_text('default_palette = "mini"\noutput_dir = "out"\nexport = ["png", "godot"]\n')
    result = build(load_project(proj.root))
    assert result.errors and "project.godot" in result.errors[0].message


def test_godot_export_writes_sprite_frames(proj: Project) -> None:
    project = godot_project(proj)
    result = build(project)
    assert not result.errors
    tres = (project.output_dir / "sprites" / "bug.tres").read_text()
    assert tres.startswith('[gd_resource type="SpriteFrames" format=3]')
    assert 'path="res://assets/generated/sprites/bug.png"' in tres
    assert "region = Rect2(9, 0, 9, 9)" in tres
    assert '"name": &"walk"' in tres and '"speed": 6.0' in tres
    manifest = json.loads((project.output_dir / "manifest.json").read_text())
    assert manifest["assets"]["bug"]["godot_sprite_frames"] == "res://assets/generated/sprites/bug.tres"
    assert manifest["assets"]["bug"]["variants"]["ripe"]["godot_sprite_frames"] == "res://assets/generated/sprites/bug.ripe.tres"
    tileset = (project.output_dir / "tiles" / "turf.tres").read_text()
    assert tileset.startswith('[gd_resource type="TileSet" format=3]')
    assert "tile_size = Vector2i(4, 4)" in tileset and "texture_region_size = Vector2i(4, 4)" in tileset
    assert "0:0/0 = 0\n1:0/0 = 0\n0:1/0 = 0" in tileset  # columns: 2
    turf = manifest["assets"]["turf"]
    assert turf["godot_tileset"] == "res://assets/generated/tiles/turf.tres"
    assert turf["tiles"] == {"plain": [0, 0], "flower": [1, 0], "plain_flip": [0, 1]}


def test_sprite_frames_text() -> None:
    text = sprite_frames_tres(
        "res://a.png",
        {"x": (0, 0, 2, 2), "y": (2, 0, 2, 2)},
        [Animation("run", ("x", "y", "x"), 12.0, False)],
    )
    assert text.count("[sub_resource") == 2  # frames are shared, not duplicated
    assert text.count('SubResource("AtlasTexture_0")') == 2
    assert '"loop": false' in text


def test_centered_offset() -> None:
    assert centered_offset((16, 16), (8, 16)) == (0.0, -8.0)
    assert centered_offset((9, 9), (4, 8)) == (0.5, -3.5)


def test_cli_build(proj: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(proj.root)
    assert main(["build", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] and result["assets"] == 3 and result["godot_verified"] is None
    assert main(["build", "--verify-godot"]) == 1  # png-only export can't be verified in Godot
