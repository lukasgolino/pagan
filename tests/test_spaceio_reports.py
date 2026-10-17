"""Fixes for the Space IO use report (SPACIO_USEREPORT.MD, S1-S10)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from conftest import LoadFn, make_project
from pagan import api
from pagan.build import build
from pagan.cli import main
from pagan.exporters.godot import import_mipmaps, sprite_frames_tres, texture_filter
from pagan.lint import lint_paths
from pagan.project import Project, load_project
from pagan.render import downsample

# --- S1: perspective at init; camera marked unused without models ------------------------------


def test_init_perspective_and_style(tmp_path: Path) -> None:
    assert main(["init", str(tmp_path / "art"), "--perspective", "top-down", "--style", "flat"]) == 0
    project = load_project(tmp_path / "art")
    assert project.config.camera.elevation == 90
    brief = (tmp_path / "art" / "BRIEF.md").read_text()
    assert "**Perspective:** top-down (straight down" in brief and "**Rendering style:** flat" in brief
    assert "flat / vector arcade" in (tmp_path / "art" / "STYLE.md").read_text()


def test_init_defaults_keep_todo(tmp_path: Path) -> None:
    assert main(["init", str(tmp_path / "art")]) == 0
    assert load_project(tmp_path / "art").config.camera.elevation == 42
    brief = (tmp_path / "art" / "BRIEF.md").read_text()
    assert "**Perspective:** TODO" in brief and "$" not in brief
    assert "pixel-art** defaults" in (tmp_path / "art" / "STYLE.md").read_text()


def test_config_show_marks_camera_unused_without_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    capsys.readouterr()
    assert main(["--json", "config", "show"]) == 0
    rows = {r["key"]: r for r in json.loads(capsys.readouterr().out)["settings"]}
    assert rows["camera.elevation"]["used"] is False and rows["light.ambient"]["used"] is False
    assert rows["output_dir"]["used"] is True
    assert main(["config", "show"]) == 0
    assert "(unused: no 3D models)" in capsys.readouterr().out


# --- S2: polygons, triangles, thick lines, signed distance --------------------------------------


def test_polygon_fill_and_edge_distance() -> None:
    square = [(1.0, 1.0), (7.0, 1.0), (7.0, 7.0), (1.0, 7.0)]
    c = api.Canvas(8, 8).polygon(square, lambda d: "r" if d < 2 else "f")
    assert c.rows()[0] == "." * 8 and c.rows()[1] == ".rrrrrr." and c.rows()[3] == ".rrffrr."
    assert api.polygon_distance(square, 4, 4) == 3 and api.polygon_distance(square, 0, 4) == -1
    # winding doesn't matter; a concave arrowhead keeps its notch
    arrow = [(8.0, 0.0), (15.0, 15.0), (8.0, 10.0), (1.0, 15.0)]
    a = api.Canvas(16, 16).polygon(arrow, "x")
    b = api.Canvas(16, 16).polygon(arrow[::-1], "x")
    assert a.rows() == b.rows() and a.get(8, 12) == "." and a.get(2, 12) == "x"
    t = api.Canvas(16, 16).triangle((8, 1), (15, 15), (1, 15), "t")
    assert t.get(8, 2) == "t" and t.get(1, 2) == "."
    with pytest.raises(ValueError):
        api.Canvas(4, 4).polygon([(0, 0), (1, 1)], "x")


def test_thick_line() -> None:
    thin = api.Canvas(10, 5).line(0.5, 2.5, 9.5, 2.5, "x")
    thick = api.Canvas(10, 5).line(1.5, 2.5, 8.5, 2.5, "x", width=3)
    assert thin.rows()[1] == "." * 10
    assert thick.rows()[1:4] == ["x" * 10] * 3 and thick.rows()[0] == thick.rows()[4] == "." * 10  # round ends


# --- S5: no nubs on half-integer radii ----------------------------------------------------------


def test_ellipse_has_no_nubs() -> None:
    c = api.Canvas(32, 12).ellipse(16, 6, 15.5, 5.5, "b")
    rows = c.rows()
    assert rows[0] == "." * 32 and rows[11] == "." * 32  # the 1px nubs at the extremes are gone
    assert all(r[0] == "." and r[31] == "." for r in rows)
    assert not c.orphans() and api.API_VERSION == 2


# --- S3 / S10: supersampled output -------------------------------------------------------------

SHIP = """\
name: ship
supersample: 2
pivot: [2, 3]
size: [4, 4]
frames:
  a: |
    1122
    1122
    ..22
    ..2.
"""


def test_downsample_premultiplies_alpha() -> None:
    image = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
    image.putpixel((0, 0), (255, 0, 0, 255))
    out = np.asarray(downsample(image, 2))
    assert out.shape == (1, 1, 4) and tuple(out[0, 0]) == (255, 0, 0, 64)  # no darkening towards black
    assert np.array_equal(np.asarray(downsample(Image.new("RGBA", (4, 2)), 2)), np.zeros((1, 2, 4), np.uint8))


def test_build_supersampled_asset(project: Project) -> None:
    (project.root / "sprites" / "ship.sprite.yaml").write_text(SHIP)
    result = build(project)
    assert not result.errors, [f.format() for f in result.errors]
    entry = json.loads((project.output_dir / "manifest.json").read_text())["assets"]["ship"]
    assert entry["size"] == [2, 2] and entry["source_size"] == [4, 4] and entry["supersample"] == 2
    assert entry["frames"]["a"] == [0, 0, 2, 2] and entry["pivot"] == [1, 1.5]
    sheet = np.asarray(Image.open(project.output_dir / "sprites" / "ship.png"))
    assert sheet.shape == (2, 2, 4)
    assert tuple(sheet[0, 0]) == (255, 0, 0, 255) and tuple(sheet[1, 1]) == (255, 128, 128, 191)


def test_project_supersample_and_size_check(tmp_path: Path) -> None:
    project = make_project(tmp_path, 'default_palette = "test"\nsupersample = 3\n')
    (project.root / "sprites" / "ship.sprite.yaml").write_text(SHIP.replace("supersample: 2\n", ""))
    errors = lint_paths(project).errors
    assert [f.rule for f in errors] == ["E003"] and "pagan.toml supersample (3)" in errors[0].message
    (project.root / "sprites" / "ship.sprite.yaml").write_text(SHIP.replace("supersample: 2", "supersample: 1"))
    assert not lint_paths(project).errors  # the asset's own setting wins


def test_preview_shows_built_look(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    (project.root / "sprites" / "ship.sprite.yaml").write_text(SHIP)
    monkeypatch.chdir(project.root)
    assert main(["preview", "ship"]) == 0
    built = Image.open(project.preview_dir / "ship" / "built_1x.png")
    assert built.size == (2, 2)


# --- S4: Godot import settings ------------------------------------------------------------------


def test_import_sidecar(tmp_path: Path) -> None:
    png = tmp_path / "a.png"
    assert import_mipmaps(png, False) is None and not (tmp_path / "a.png.import").exists()
    sidecar = import_mipmaps(png, True)
    assert sidecar is not None and "mipmaps/generate=true" in sidecar.read_text()
    godot_written = '[remap]\n\nimporter="texture"\nuid="uid://x"\n\n[params]\n\ncompress/mode=0\nmipmaps/generate=true\n'
    sidecar.write_text(godot_written)
    assert import_mipmaps(png, True) is None  # unchanged: no churn
    assert import_mipmaps(png, False) == sidecar
    assert sidecar.read_text() == godot_written.replace("generate=true", "generate=false")
    sidecar.write_text('[remap]\n\nimporter="texture"\n\n[params]\n\ncompress/mode=0\n')
    import_mipmaps(png, True)
    assert sidecar.read_text() == '[remap]\n\nimporter="texture"\n\n[params]\n\nmipmaps/generate=true\ncompress/mode=0\n'


def test_texture_filter_in_sprite_frames() -> None:
    assert texture_filter("inherit", True) is None and texture_filter("linear", True) == 4 and texture_filter("nearest", False) == 1
    text = sprite_frames_tres("res://a.png", {"a": (0, 0, 2, 2)}, [], None, 2)
    assert 'type="CanvasTexture"' in text and "texture_filter = 2" in text and 'atlas = SubResource("CanvasTexture_sheet")' in text
    assert "CanvasTexture" not in sprite_frames_tres("res://a.png", {"a": (0, 0, 2, 2)}, [])


def test_godot_settings_validate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["config", "set", "godot.filter", "linear"]) == 0
    assert main(["config", "set", "godot.mipmaps", "true"]) == 0
    assert main(["config", "set", "godot.filter", "blurry"]) == 1
    config = load_project(tmp_path).config
    assert config.godot.filter == "linear" and config.godot.mipmaps is True


def test_build_writes_import_sidecars(tmp_path: Path) -> None:
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "project.godot").write_text("config_version=5\n")
    config = 'default_palette = "test"\noutput_dir = "../game/gen"\nexport = ["png", "godot"]\n[godot]\nmipmaps = true\nfilter = "linear"\n'
    (tmp_path / "art").mkdir()
    project = make_project(tmp_path / "art", config)
    (project.root / "sprites" / "ship.sprite.yaml").write_text(SHIP)
    result = build(project)
    assert not result.errors
    sidecar = tmp_path / "game" / "gen" / "sprites" / "ship.png.import"
    assert "mipmaps/generate=true" in sidecar.read_text()
    assert "texture_filter = 4" in (tmp_path / "game" / "gen" / "sprites" / "ship.tres").read_text()
    again = build(load_project(project.root))
    assert sidecar not in again.written


# --- S6: base variant name ----------------------------------------------------------------------

TEAM = """\
name: ship
size: [2, 1]
base_variant: red
variants:
  green: { ramp_swap: { red: green } }
frames:
  a: "12"
"""


def test_base_variant_in_manifest(project: Project) -> None:
    (project.root / "sprites" / "ship.sprite.yaml").write_text(TEAM)
    assert not build(project).errors
    entry = json.loads((project.output_dir / "manifest.json").read_text())["assets"]["ship"]
    assert entry["base_variant"] == "red"
    assert entry["variants"]["red"] == {"sheet": entry["sheet"], "swap": {}, "swap_exact": True}
    assert set(entry["variants"]) == {"red", "green"}


def test_base_variant_clash(load: LoadFn) -> None:
    asset, findings = load(TEAM.replace("base_variant: red", "base_variant: green"), name="ship")
    assert asset is None and any(f.rule == "E006" and f.where == "base_variant" for f in findings)
    asset, findings = load(TEAM.replace("base_variant: red", "base_variant: Red!"), name="ship")
    assert asset is None and any(f.where == "base_variant" for f in findings)


def test_base_variant_labels_previews(project: Project) -> None:
    from pagan.preview import base_label

    (project.root / "sprites" / "ship.sprite.yaml").write_text(TEAM)
    asset = api.load(project.root / "sprites" / "ship.sprite.yaml", project)
    assert base_label(asset) == "red"
