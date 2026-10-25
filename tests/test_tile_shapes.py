"""#30: isometric (and other) tile shapes for tilesets: Godot TileSet export, manifest, scene previews."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import LoadFn
from pagan import api
from pagan.asset import TileShape
from pagan.build import build
from pagan.cli import main
from pagan.exporters.godot import find_godot_binary, tileset_tres, verify_with_godot
from pagan.project import load_project
from pagan.render import tile_origin
from test_reports_r15_r17 import _godot_project

GODOT = find_godot_binary()

DIAMOND = """\
name: floor
tile_size: [8, 4]
{extra}tiles:
  a: |
    ...11...
    .111111.
    .111111.
    ...11...
  b: |
    ...33...
    .333333.
    .333333.
    ...33...
"""

# Tile centres from Godot 4.7.2's TileMapLayer.map_to_local, isometric 64x32, for these map cells.
CELLS = [(0, 0), (1, 0), (0, 1), (1, 1), (2, 1), (0, 2), (1, 2)]
GODOT_CENTRES = {
    ("stacked", "horizontal"): [(32, 16), (96, 16), (64, 32), (128, 32), (192, 32), (32, 48), (96, 48)],
    ("stacked_offset", "horizontal"): [(64, 16), (128, 16), (32, 32), (96, 32), (160, 32), (64, 48), (128, 48)],
    ("stairs_right", "horizontal"): [(32, 16), (96, 16), (64, 32), (128, 32), (192, 32), (96, 48), (160, 48)],
    ("stairs_down", "horizontal"): [(32, 16), (64, 32), (32, 48), (64, 64), (96, 80), (32, 80), (64, 96)],
    ("diamond_right", "horizontal"): [(32, 16), (64, 0), (64, 32), (96, 16), (128, 0), (96, 48), (128, 32)],
    ("diamond_down", "horizontal"): [(32, 16), (64, 32), (0, 32), (32, 48), (64, 64), (-32, 48), (0, 64)],
    ("stacked", "vertical"): [(32, 16), (64, 32), (32, 48), (64, 64), (96, 48), (32, 80), (64, 96)],
    ("stacked_offset", "vertical"): [(32, 32), (64, 16), (32, 64), (64, 48), (96, 64), (32, 96), (64, 80)],
    ("diamond_down", "vertical"): [(32, 16), (64, 32), (0, 32), (32, 48), (64, 64), (-32, 48), (0, 64)],
}


@pytest.mark.parametrize("layout, axis", list(GODOT_CENTRES))
def test_isometric_positions_match_godot(layout: str, axis: str) -> None:
    shape = TileShape("isometric", layout, axis)
    got = [tile_origin(shape, c, r, (64, 32)) for c, r in CELLS]
    assert got == [(x - 32, y - 16) for x, y in GODOT_CENTRES[layout, axis]]


def test_tileset_tres_writes_the_shape_like_godot() -> None:
    square = tileset_tres("res://floor.png", (64, 32), [])
    assert "tile_shape" not in square and "tile_layout" not in square  # unchanged for square tilesets
    iso = tileset_tres("res://floor.png", (64, 32), [], TileShape("isometric", "diamond_down"))
    assert "[resource]\ntile_shape = 1\ntile_layout = 5\ntile_size = Vector2i(64, 32)\n" in iso  # as Godot saves it
    half = tileset_tres("res://floor.png", (64, 32), [], TileShape("half_offset_square", "stacked_offset", "vertical"))
    assert "[resource]\ntile_shape = 2\ntile_layout = 1\ntile_offset_axis = 1\ntile_size" in half


def test_tile_shape_fields(load: LoadFn) -> None:
    asset, findings = load(DIAMOND.format(extra="tile_shape: isometric\ntile_layout: diamond_down\n"), "floor", kind="tileset")
    assert asset is not None, [f.format() for f in findings]
    assert asset.tile_shape == TileShape("isometric", "diamond_down", "horizontal")
    asset, findings = load(DIAMOND.format(extra="tile_shape: iso\ntile_layout: diamond\n"), "floor", kind="tileset")
    assert asset is None and {f.where for f in findings} == {"tile_shape", "tile_layout"}
    _, findings = load("name: s\nsize: [2, 2]\ntile_shape: isometric\nframes:\n  a: |\n    11\n    11\n", "s")
    assert any(f.rule == "E001" and "tile_shape" in f.message for f in findings)  # tilesets only


def test_isometric_scene_tiles_without_gaps_or_overlap(load: LoadFn) -> None:
    asset, _ = load(DIAMOND.format(extra="tile_shape: isometric\ntile_layout: diamond_down\n"), "floor", kind="tileset")
    assert asset is not None
    image = api.compose(asset, "a b\nb a")
    assert image.size == (16, 8)  # cells (0,0) (1,0) (0,1) (1,1): x from -4 to 12, y from 0 to 8
    alpha = image.getchannel("A")
    assert sum(1 for y in range(8) for x in range(16) if alpha.getpixel((x, y))) == 4 * 16  # four 16-pixel diamonds, none on top of another
    assert [alpha.getpixel((x, 3)) for x in range(1, 15)] == [255] * 14  # the seam row between them is closed
    square = api.compose(asset, "a b\nb a", square=True)
    assert square.size == (16, 8) and square.getchannel("A").getpixel((3, 0)) == 255  # a plain grid when asked


def test_tile_shape_in_manifest_godot_and_previews(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _godot_project(tmp_path)
    (project.root / "tiles" / "floor.tiles.yaml").write_text(DIAMOND.format(extra="tile_shape: isometric\ntile_layout: diamond_down\n"))
    result = build(load_project(project.root))
    assert not result.errors, [f.format() for f in result.errors]
    gen = tmp_path / "game" / "gen"
    entry = json.loads((gen / "manifest.json").read_text())["assets"]["floor"]
    assert entry["tile_shape"] == {"shape": "isometric", "layout": "diamond_down", "offset_axis": "horizontal"}
    assert "tile_shape = 1\ntile_layout = 5\n" in (gen / "tiles" / "floor.tres").read_text()
    assert "tile_shape" not in json.loads((gen / "manifest.json").read_text())["assets"]["flag"]
    (project.root / "layout.txt").write_text("a b a\nb a b\n")
    monkeypatch.chdir(project.root)
    assert main(["preview", "floor", "--scene", "layout.txt", "--quiet", "--scale", "1"]) == 0
    from PIL import Image

    scene = Image.open(project.preview_dir / "floor" / "scene.png")
    assert scene.size == (20, 10)  # 3 x 2 cells of an 8x4 diamond map: x -4..16, y 0..10
    if GODOT is not None:  # Godot loads the isometric TileSet
        check = verify_with_godot(GODOT, tmp_path / "game", "res://gen/manifest.json")
        assert check.ok, check.output
