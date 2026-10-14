"""Sprite and tileset parsing: every format rule (E001-E011) has a test that triggers it."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import LoadFn, make_project
from pagan.asset import Asset
from pagan.findings import Finding

BASIC = """\
name: thing
size: [4, 3]
frames:
  a: |
    .12.
    1221
    .12.
"""


def ok(result: tuple[Asset | None, list[Finding]]) -> Asset:
    asset, findings = result
    assert asset is not None, [f.format() for f in findings]
    assert findings == []
    return asset


def rules(result: tuple[Asset | None, list[Finding]]) -> list[str]:
    asset, findings = result
    assert asset is None
    return [f.rule for f in findings]


def test_basic_sprite(load: LoadFn) -> None:
    asset = ok(load(BASIC))
    assert asset.kind == "sprite"
    assert asset.size == (4, 3)
    assert asset.frames["a"] == (".12.", "1221", ".12.")
    assert asset.pivot == (2, 3)  # default: bottom centre
    assert asset.palette.name == "test"  # project default palette
    assert asset.status == "draft" and asset.style_version == 1


def test_size_as_string_and_list_grid(load: LoadFn) -> None:
    asset = ok(load('name: thing\nsize: "2x2"\nframes:\n  a: ["12", "21"]\n'))
    assert asset.frames["a"] == ("12", "21")


def test_metadata(load: LoadFn) -> None:
    asset = ok(
        load(
            BASIC
            + 'description: "a red thing"\ntags: [item, red]\nstatus: approved\nstyle_version: 2\n'
        )
    )
    assert asset.description == "a red thing"
    assert asset.tags == ("item", "red")
    assert asset.status == "approved" and asset.style_version == 2


@pytest.mark.parametrize(
    "width, authored, expected",
    [
        (4, ".1", ".11."),  # even: reflect all authored columns
        (5, ".12", ".121."),  # odd: centre column not duplicated
    ],
)
def test_mirror(load: LoadFn, width: int, authored: str, expected: str) -> None:
    asset = ok(load(f"name: thing\nsize: [{width}, 1]\nmirror: horizontal\nframes:\n  a: |\n    {authored}\n"))
    assert asset.frames["a"] == (expected,)


def test_outline_auto_uses_darkest_color_by_default(load: LoadFn) -> None:
    asset = ok(load("name: thing\nsize: [5, 5]\noutline: auto\nframes:\n  a: |\n    .....\n    .....\n    ..2..\n    .....\n    .....\n"))
    assert asset.outline_color == "0"
    assert asset.frames["a"] == (".....", "..0..", ".020.", "..0..", ".....")
    assert asset.base_frames["a"][2] == "..2.."


def test_outline_color(load: LoadFn) -> None:
    asset = ok(load('name: thing\nsize: [3, 3]\noutline: auto\noutline_color: "5"\nframes:\n  a: |\n    ...\n    .2.\n    ...\n'))
    assert asset.frames["a"] == (".5.", "525", ".5.")


def test_derived_frames(load: LoadFn) -> None:
    asset = ok(
        load(
            "name: thing\nsize: [3, 2]\nframes:\n"
            "  a: |\n    12.\n    ...\n"
            "  flipped: { from: a, flip: horizontal }\n"
            "  down: { from: flipped, shift: [0, 1] }\n"
            "  both: { from: a, flip: both }\n"
        )
    )
    assert asset.frames["flipped"] == (".21", "...")
    assert asset.frames["down"] == ("...", ".21")
    assert asset.frames["both"] == ("...", ".21")
    assert list(asset.frames) == ["a", "flipped", "down", "both"]  # source order kept
    assert asset.derived_from == {"flipped": "a", "down": "flipped", "both": "a"}


def test_derived_frames_can_reference_later_frames(load: LoadFn) -> None:
    asset = ok(load("name: thing\nsize: [2, 1]\nframes:\n  b: { from: a, flip: horizontal }\n  a: |\n    1.\n"))
    assert asset.frames["b"] == (".1",)


def test_animations(load: LoadFn) -> None:
    asset = ok(load(BASIC + "  b: { from: a }\nanimations:\n  idle: { frames: [a, b], fps: 4, loop: false }\n  walk: [b, a]\n"))
    idle = asset.animations["idle"]
    assert idle.frames == ("a", "b") and idle.fps == 4.0 and idle.loop is False
    assert asset.animations["walk"].fps == 8.0 and asset.animations["walk"].loop is True


def test_pivot(load: LoadFn) -> None:
    assert ok(load(BASIC + "pivot: [0, 3]\n")).pivot == (0, 3)


def test_variants(load: LoadFn) -> None:
    asset = ok(
        load(
            BASIC
            + 'variants:\n  green: { ramp_swap: { red: green } }\n  blue: { key_swap: { "1": "5" } }\n'
            "  dim: { palette: other, ramp_swap: { red: dim } }\n"
        )
    )
    assert asset.variants["green"].keys == {"1": "3", "2": "4"}
    assert asset.variants["blue"].keys == {"1": "5"}
    assert asset.variants["dim"].palette.name == "other"


def test_tileset(load: LoadFn) -> None:
    asset = ok(
        load(
            "name: floor\ntile_size: [2, 2]\ncolumns: 2\ntiles:\n  a: |\n    12\n    21\n  b: { from: a, flip: horizontal }\n",
            name="floor",
            kind="tileset",
        )
    )
    assert asset.kind == "tileset" and asset.columns == 2
    assert asset.frames["b"] == ("21", "12")


def test_inline_palette_in_open_mode(tmp_path: Path, load: LoadFn) -> None:
    (tmp_path / "open").mkdir()
    proj = make_project(tmp_path / "open", 'palette_mode = "open"\n')
    asset = ok(
        load(
            'name: thing\npalette:\n  colors:\n    "x": "#123456"\nsize: [1, 1]\nframes:\n  a: |\n    x\n',
            proj=proj,
        )
    )
    assert asset.palette.name is None and asset.palette.colors["x"].hex == "#123456"


# --- errors -----------------------------------------------------------------------------------


def test_e001_missing_fields(load: LoadFn) -> None:
    assert "E001" in rules(load("name: thing\nframes:\n  a: |\n    1\n"))  # no size
    assert "E001" in rules(load("name: thing\nsize: [1, 1]\n"))  # no frames


def test_e001_unknown_field_and_name_mismatch(load: LoadFn) -> None:
    assert rules(load(BASIC + "colour: red\n")) == ["E001"]
    assert rules(load(BASIC.replace("name: thing", "name: other"))) == ["E001"]


def test_e001_yaml_error_has_line(load: LoadFn) -> None:
    _, findings = load("name: thing\nsize: [1, 1\n")
    assert findings[0].rule == "E001" and findings[0].line is not None


def test_e001_missing_palette_without_default(tmp_path: Path, load: LoadFn) -> None:
    (tmp_path / "nodefault").mkdir()
    proj = make_project(tmp_path / "nodefault", "")
    assert rules(load(BASIC, proj=proj)) == ["E001"]


def test_e002_unknown_pixel_with_location(load: LoadFn) -> None:
    _, findings = load("name: thing\nsize: [3, 2]\nframes:\n  a: |\n    1.1\n    1z1\n")
    assert [f.rule for f in findings] == ["E002"]
    assert findings[0].where == "frames.a row 2 col 2"
    assert findings[0].line == 6  # the row's own line in the file


def test_e002_space_hint(load: LoadFn) -> None:
    _, findings = load("name: thing\nsize: [3, 1]\nframes:\n  a: |\n    1 1\n")
    assert "spaces" in findings[0].message


def test_e003_wrong_row_count_and_width(load: LoadFn) -> None:
    assert rules(load("name: thing\nsize: [2, 2]\nframes:\n  a: |\n    11\n")) == ["E003"]
    assert rules(load("name: thing\nsize: [2, 1]\nframes:\n  a: |\n    111\n")) == ["E003"]


def test_e003_mirror_expects_half_width(load: LoadFn) -> None:
    _, findings = load("name: thing\nsize: [4, 1]\nmirror: horizontal\nframes:\n  a: |\n    1111\n")
    assert findings[0].rule == "E003" and "left 2 columns" in findings[0].message


def test_e004_missing_animation_frame(load: LoadFn) -> None:
    assert rules(load(BASIC + "animations:\n  idle: [a, nope]\n")) == ["E004"]


def test_e005_unknown_palette_and_outline_color(load: LoadFn) -> None:
    assert rules(load(BASIC + "palette: nope\n")) == ["E005"]
    assert rules(load(BASIC + 'outline_color: "z"\n')) == ["E005"]


def test_e006_variant_errors(load: LoadFn) -> None:
    assert rules(load(BASIC + "variants:\n  v: { ramp_swap: { red: nope } }\n")) == ["E006"]
    assert rules(load(BASIC + "variants:\n  v: { ramp_swap: { red: blue } }\n")) == ["E006"]  # lengths differ
    assert rules(load(BASIC + 'variants:\n  v: { key_swap: { "1": "z" } }\n')) == ["E006"]
    assert rules(load(BASIC + "variants:\n  v: { palette: nope }\n")) == ["E006"]
    # "other" has keys 0-2 only; "2"... are fine, but a sprite using "5" can't move without a swap.
    assert rules(load(BASIC.replace("1221", "1251") + "variants:\n  v: { palette: other }\n")) == ["E006"]


def test_e007_outline_clipped(load: LoadFn) -> None:
    _, findings = load("name: thing\nsize: [3, 3]\noutline: auto\nframes:\n  a: |\n    .1.\n    ...\n    ...\n")
    assert [f.rule for f in findings] == ["E007"]
    assert findings[0].where == "frames.a row 1 col 2"


def test_e008_pivot_outside(load: LoadFn) -> None:
    assert rules(load(BASIC + "pivot: [5, 0]\n")) == ["E008"]
    assert rules(load(BASIC + "pivot: centre\n")) == ["E008"]


def test_e009_inline_palette_in_strict_mode(load: LoadFn) -> None:
    text = 'name: thing\npalette:\n  colors:\n    "1": "#123456"\nsize: [1, 1]\nframes:\n  a: |\n    1\n'
    assert rules(load(text)) == ["E009"]


@pytest.mark.parametrize(
    "frames",
    [
        "  b: { from: nope }\n",
        "  b: { from: b }\n",
        "  b: { from: c }\n  c: { from: b }\n",
        "  b: { from: a, flip: diagonal }\n",
        "  b: { from: a, shift: [5, 0] }\n",
        "  b: { flip: horizontal }\n",
    ],
)
def test_e010_derived_frame_errors(load: LoadFn, frames: str) -> None:
    assert set(rules(load(BASIC + frames))) == {"E010"}


def test_e011_outline_required(tmp_path: Path, load: LoadFn) -> None:
    (tmp_path / "req").mkdir()
    proj = make_project(tmp_path / "req", 'default_palette = "test"\n[lint]\nrequire_outline = true\n')
    assert rules(load(BASIC, proj=proj)) == ["E011"]


def test_collects_multiple_errors(load: LoadFn) -> None:
    found = rules(load("name: thing\nsize: [2, 1]\npivot: [9, 9]\nframes:\n  a: |\n    1z\nanimations:\n  x: [q]\n"))
    assert {"E002", "E004", "E008"} <= set(found)
