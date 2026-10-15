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
from pagan.findings import Finding, PaganError
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


# --- review round 3 ---


def test_model_light_override_keys_are_checked_and_all_supported(project: Project) -> None:
    base = MODEL.format(directions=1, heading=0, material="{ ramp: red }", use="wood")
    asset, findings = model(project, base + "light: { typo: 1 }\n")
    assert asset is None and findings[0].rule == "E013"
    asset, findings = model(project, base + "camera: { elevaton: 80 }\n")
    assert asset is None
    flat, findings = model(project, base + "light: { baked: false, shadow_strength: 0 }\n")
    assert flat is not None, findings
    assert {c for row in flat.base_frames["main"] for c in row if c != "."} == {"2"}  # middle of red [1, 2]


def test_config_set_multiline_array_and_odd_values(tmp_path: Path) -> None:
    from pagan.settings import set_setting, unset_setting

    project = make_project(tmp_path, 'default_palette = "test"\n[lint]\ndisable = [\n  "W001",\n]\n')
    set_setting(project, "lint.disable", "W002")
    assert load_project(tmp_path).config.lint.disable == ("W002",)
    for odd in ("2026-10-15", "{a=1}"):
        with pytest.raises(PaganError):
            set_setting(load_project(tmp_path), "palette_mode", odd)
    change = unset_setting(load_project(tmp_path), "lint.disable")
    assert change.new == [] and load_project(tmp_path).config.lint.disable == ()


def test_default_palette_replaces_the_template_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    assert main(["new", "palette", "pal"]) == 0
    assert main(["config", "set", "default_palette", "pal"]) == 0
    text = (tmp_path / "pagan.toml").read_text()
    assert 'default_palette = "pal"' in text and "# default_palette" not in text
    lines = text.split("\n")
    at = lines.index('default_palette = "pal"')
    assert "Palette for sprites" in lines[at - 1]  # where the template put it, under its own comment
    assert main(["config", "unset", "default_palette"]) == 0
    assert load_project(tmp_path).config.default_palette is None


def test_mark_refuses_unsafe_edits(tmp_path: Path) -> None:
    empty = tmp_path / "e.sprite.yaml"
    empty.write_text("name: e\nstatus:\nsize: [1, 1]\n")
    mark([empty], "approved", None)
    assert "status: approved" in empty.read_text()
    flow = tmp_path / "f.sprite.yaml"
    original = '{name: f, size: [1, 1], frames: {a: "1"}}\n'
    flow.write_text(original)
    with pytest.raises(PaganError):
        mark([flow], "approved", None)
    assert flow.read_text() == original


def test_json_flag_before_the_subcommand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    capsys.readouterr()
    assert main(["--json", "config", "get", "palette_mode"]) == 0
    assert json.loads(capsys.readouterr().out)["value"] == "strict"


def test_bake_defaults_to_a_unique_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["new", "model", "barrel", "--size", "32x32", "--directions", "4"]) == 0
    assert main(["bake", "barrel"]) == 0
    assert (tmp_path / "sprites" / "barrel_baked.sprite.yaml").exists()
    assert main(["lint"]) == 0


def test_heading_names_follow_the_angle(project: Project) -> None:
    asset, findings = model(project, MODEL.format(directions=4, heading=45, material="{ ramp: red }", use="wood"))
    assert asset is not None, findings
    assert list(asset.frames) == ["ne", "nw", "sw", "se"]


@pytest.mark.parametrize("directions, animations", [(4, 4), (8, 8)])
def test_new_sprite_directions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, directions: int, animations: int) -> None:
    from pagan.asset import load_asset_or_raise

    make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["new", "sprite", "hero", "--size", "8x8", "--directions", str(directions), "--frames", "2"]) == 0
    hero = load_asset_or_raise(tmp_path / "sprites" / "hero.sprite.yaml", load_project(tmp_path))
    assert len(hero.animations) == animations and "idle_right" in hero.animations
    assert main(["new", "sprite", "bad", "--directions", "3"]) == 1


def test_preview_writes_a_montage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import shutil

    shutil.copytree(Path(__file__).parent / "fixtures" / "golden", tmp_path / "art", ignore=shutil.ignore_patterns("expected"))
    monkeypatch.chdir(tmp_path / "art")
    capsys.readouterr()
    assert main(["preview", "crate", "--bg", "#1d3b53", "--scale", "2", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)["outputs"][0]
    assert result["scale"] == 2
    montage = Image.open(tmp_path / "art" / result["montage"])
    assert montage.size == (4 * 64, 64)  # 4 headings in one row
    assert montage.getpixel((0, 0)) == (0x1D, 0x3B, 0x53, 255)
