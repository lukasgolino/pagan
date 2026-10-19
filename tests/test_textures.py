"""`export_textures` on tilesets (MESH_PLAN M7): tiles and tile groups as repeatable PNGs for 3D surfaces."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from conftest import LoadFn, make_project
from pagan.build import build
from pagan.exporters.godot import texture_material_tres
from pagan.preview import PreviewOptions, contact_sheet
from pagan.project import load_project

TILES = """\
name: ground
tile_size: [2, 2]
tiles:
  a: |
    11
    12
  b: |
    33
    34
  hole: |
    1.
    .1
{extra}"""


def test_export_textures_parses(load: LoadFn) -> None:
    asset, _ = load(TILES.format(extra="export_textures: true\n"), "ground", "tileset")
    assert asset is not None and asset.textures is not None and asset.textures.tiles == ("a", "b", "hole")
    asset, _ = load(TILES.format(extra="export_textures:\n  groups:\n    mix: |\n      a b\n      b a\n  triplanar: true\n"), "ground", "tileset")
    assert asset is not None and asset.textures is not None
    assert asset.textures.tiles == () and asset.textures.groups == {"mix": (("a", "b"), ("b", "a"))} and asset.textures.triplanar


def test_export_textures_errors(load: LoadFn) -> None:
    for extra, message in (
        ("export_textures: 3\n", "export_textures is true"),
        ("export_textures: { tiles: [nope] }\n", "no tile(s) nope"),
        ("export_textures: { groups: { mix: \"a b\\nb\" } }\n", "every row the same length"),
        ("export_textures: { groups: { mix: \"a .\" } }\n", "no '.'"),
        ("export_textures: { groups: { a: \"a\" } }\n", "not a tile's name"),
        ("export_textures: { size: 3 }\n", "unknown export_textures field"),
    ):
        asset, findings = load(TILES.format(extra=extra), "ground", "tileset")
        assert asset is None and any(message in f.message for f in findings), (extra, [f.message for f in findings])


def test_build_writes_textures_and_godot_materials(tmp_path: Path) -> None:
    godot = tmp_path / "game"
    godot.mkdir()
    (godot / "project.godot").write_text("config_version=5\n")
    (tmp_path / "art").mkdir()
    project = make_project(tmp_path / "art", 'default_palette = "test"\noutput_dir = "../game/art"\nexport = ["png", "godot"]\n')
    extra = "export_textures:\n  tiles: [a, hole]\n  groups:\n    mix: |\n      a b\n      b a\n  triplanar: true\nvariants:\n  green: { ramp_swap: { red: green } }\n"
    (project.tiles_dir / "ground.tiles.yaml").write_text(TILES.format(extra=extra))
    result = build(load_project(project.root))
    assert not result.errors, [f.format() for f in result.errors]
    manifest = json.loads((godot / "art" / "manifest.json").read_text())
    textures = manifest["assets"]["ground"]["textures"]
    assert set(textures) == {"a", "hole", "mix"}
    mix = textures["mix"]
    assert mix["png"] == "res://art/textures/ground.mix.png" and mix["size"] == [4, 4] and mix["metres"] == [0.25, 0.25]
    assert mix["tiles"] == [["a", "b"], ["b", "a"]] and mix["godot_material"] == "res://art/textures/ground.mix.material.tres"
    assert mix["variants"]["green"]["png"] == "res://art/textures/ground.mix.green.png"
    pixels = np.array(Image.open(godot / "art" / "textures" / "ground.mix.png").convert("RGBA"))
    assert pixels.shape == (4, 4, 4) and tuple(pixels[0, 0]) == (255, 0, 0, 255) and tuple(pixels[0, 2]) == (0, 255, 0, 255)
    material = (godot / "art" / "textures" / "ground.mix.material.tres").read_text()
    assert "uv1_world_triplanar = true" in material and "uv1_scale = Vector3(4.0, 4.0, 4.0)" in material
    assert "transparency = 2" in (godot / "art" / "textures" / "ground.hole.material.tres").read_text()
    assert "transparency" not in (godot / "art" / "textures" / "ground.a.material.tres").read_text()


def test_texture_material_without_triplanar() -> None:
    text = texture_material_tres("res://t.png", (1.0, 2.0), False, False)
    assert "uv1" not in text and "texture_filter = 0" in text and 'albedo_texture = ExtResource("1_texture")' in text


def test_preview_tiles_texture_groups(load: LoadFn) -> None:
    asset, _ = load(TILES.format(extra="export_textures:\n  groups:\n    mix: |\n      a b\n"), "ground", "tileset")
    assert asset is not None
    plain, _ = load(TILES.format(extra=""), "ground", "tileset")
    assert plain is not None
    options = PreviewOptions(scale=4)
    assert contact_sheet(asset, options).height > contact_sheet(plain, options).height  # the groups' seam check row
