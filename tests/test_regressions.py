"""Regression tests for bugs found in review (each reproduces a confirmed report)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from conftest import make_project
from pagan.asset import Asset, load_asset
from pagan.build import build
from pagan.cli import main
from pagan.exporters.godot import sprite_frames_tres, verify_with_godot
from pagan.asset import Animation
from pagan.findings import Finding
from pagan.importer import import_png
from pagan.manage import apply_palette_hexes, catalogue, mark
from pagan.palette import load_palette_file
from pagan.project import Project, load_project

MODEL = """\
name: m
size: [32, 32]
pivot: [16, 24]
directions: {directions}
heading: {heading}
materials:
  wood: {material}
parts:
  - box: {{ from: [-3, -3, 0], to: [3, 3, 4], material: {use} }}
"""


def model(project: Project, text: str) -> tuple[Asset | None, list[Finding]]:
    (project.root / "models").mkdir(exist_ok=True)
    path = project.root / "models" / "m.model.yaml"
    path.write_text(text)
    return load_asset(path, project)


@pytest.mark.parametrize(
    "fields",
    [
        {"material": "{ ramp: [red] }"},
        {"use": "[wood]"},
        {"directions": "[4]"},
        {"heading": ".nan"},
        {"heading": ".inf"},
    ],
)
def test_bad_model_values_are_findings_not_crashes(project: Project, fields: dict[str, str]) -> None:
    values = {"directions": "1", "heading": "0", "material": "{ ramp: red }", "use": "wood", **fields}
    asset, findings = model(project, MODEL.format(**values))
    assert asset is None and findings and all(f.rule.startswith("E") for f in findings)


@pytest.mark.parametrize(
    "part",
    [
        "  - cylinder: { base: [0, 0, 0], height: 3, radius: .inf, material: wood }\n",
        "  - box: { from: [0, 0, 0], to: [100000, 100000, 100000], material: wood }\n",
        "  - layers: { at: [0, 0, 0], legend: { w: [wood] }, grids: ['w'] }\n",
    ],
)
def test_absurd_parts_are_rejected(project: Project, part: str) -> None:
    text = MODEL.format(directions=1, heading=0, material="{ ramp: red }", use="wood") + part
    asset, findings = model(project, text)
    assert asset is None and "E013" in [f.rule for f in findings]


def test_pose_hide_with_non_string_ids(project: Project) -> None:
    text = MODEL.format(directions=1, heading=0, material="{ ramp: red }", use="wood")
    text += "animations:\n  a: { poses: [{ hide: [[x]] }] }\n"
    assert model(project, text)[0] is None


def test_animation_named_like_a_heading(project: Project) -> None:
    text = MODEL.format(directions=1, heading=0, material="{ ramp: red }", use="wood")
    text += "animations:\n  main: { poses: [{}] }\n"
    asset, findings = model(project, text)
    assert asset is None and "heading name" in findings[0].message


def test_far_origin_still_renders(project: Project) -> None:
    text = """\
name: m
size: [64, 200]
pivot: [32, 190]
origin: [0, 0, 0]
directions: 1
materials:
  wood: { ramp: red }
parts:
  - box: { from: [-3, -3, 60], to: [3, 3, 65], material: wood }
"""
    asset, findings = model(project, text)
    assert asset is not None, findings
    assert any(c != "." for row in asset.frames["main"] for c in row)


def test_malformed_cache_is_ignored(project: Project) -> None:
    text = MODEL.format(directions=1, heading=0, material="{ ramp: red }", use="wood")
    first, _ = model(project, text)
    for cache in (project.root / ".pagan-cache" / "models").glob("m-*.json"):
        cache.write_text("[]")
    second, _ = model(project, text)
    assert first is not None and second is not None and first.frames == second.frames
    for cache in (project.root / ".pagan-cache" / "models").glob("m-*.json"):
        cache.write_text("{}")
    assert model(project, text)[0] is not None


def test_stale_cleanup_never_leaves_output_dir(tmp_path: Path) -> None:
    (tmp_path / "p").mkdir()
    project = make_project(tmp_path / "p", 'default_palette = "test"\noutput_dir = "out"\n')
    (project.root / "sprites" / "a.sprite.yaml").write_text("name: a\nsize: [1, 1]\nframes:\n  x: |\n    1\n")
    build(project)
    victim = tmp_path / "victim.png"
    victim.write_text("keep me")
    manifest_path = project.output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"] += [str(victim), "../../victim.png", "../pagan.toml"]
    manifest_path.write_text(json.dumps(manifest))
    result = build(project)
    assert victim.exists() and (project.root / "pagan.toml").exists() and result.removed == []


def test_palette_adjust_with_several_keys_on_one_line(tmp_path: Path) -> None:
    path = tmp_path / "p.pal.yaml"
    path.write_text('name: p\ncolors: { "0": "#202020", "1": "#202020", "2": { name: "was #202020", hex: "#202020" } }\n')
    text = apply_palette_hexes(path, {"1": "#111111", "2": "#222222"})
    assert text == 'name: p\ncolors: { "0": "#202020", "1": "#111111", "2": { name: "was #202020", hex: "#222222" } }\n'


def test_mark_with_quoted_or_spaced_keys_and_comments(tmp_path: Path) -> None:
    path = tmp_path / "q.sprite.yaml"
    path.write_text('name: q\n"status": draft   # keep\nstyle_version : 1\nsize: [1, 1]\n')
    mark([path], "approved", 2)
    assert path.read_text() == 'name: q\n"status": approved   # keep\nstyle_version : 2\nsize: [1, 1]\n'


def test_status_counts_project_level_errors(project: Project) -> None:
    (project.root / "sprites" / "r.sprite.yaml").write_text("name: r\nsize: [1, 1]\nframes:\n  x: |\n    1\n")
    (project.root / "tiles" / "r.tiles.yaml").write_text("name: r\ntile_size: [1, 1]\ntiles:\n  x: |\n    1\n")
    assert all(e.errors == 1 and "fix errors" in e.needs(1) for e in catalogue(project))


def test_import_ignores_junk_rgb_in_transparent_pixels() -> None:
    small = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    for x in range(2, 6):
        small.putpixel((x, 3), (200, 50, 50, 255))
    big = small.resize((32, 32), Image.Resampling.NEAREST)
    data = bytearray(big.tobytes())
    for i in range(0, len(data), 4):
        if data[i + 3] == 0:
            data[i : i + 3] = bytes(((i * 7) % 256, (i * 13) % 256, (i * 17) % 256))
    junk = Image.frombytes("RGBA", big.size, bytes(data))
    _, _, report = import_png(junk, palette=None)
    assert report.scale == 4 and report.size == (8, 8)


def test_import_16_bit_grey_keeps_levels() -> None:
    image = Image.new("I;16", (4, 1))
    image.putdata([0, 20000, 40000, 65535])
    _, inline, _ = import_png(image, palette=None, scale=1)
    assert inline is not None and len(inline) == 4


def test_import_cli_rejects_zero_colors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(tmp_path / "x.png")
    assert main(["import", "x.png", "--open", "--max-colors", "0"]) == 1


def test_verify_godot_with_missing_binary(tmp_path: Path) -> None:
    check = verify_with_godot("/nonexistent/godot", tmp_path, "res://manifest.json")
    assert not check.ok and "not found" in check.output


def test_tres_speed_keeps_precision() -> None:
    text = sprite_frames_tres("res://a.png", {"x": (0, 0, 1, 1)}, [Animation("a", ("x",), 2.25, True)])
    assert '"speed": 2.25' in text
    assert '"speed": 6.0' in sprite_frames_tres("res://a.png", {"x": (0, 0, 1, 1)}, [Animation("a", ("x",), 6, True)])
