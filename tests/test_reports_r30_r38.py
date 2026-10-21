"""LOOSE! title-logo reports R30-R38 (GitHub issues #1-#9): translucent palette colours (#2), wide/stacked
outlines and drop shadows (#3), rotated/scaled derived frames (#4),
per-frame attachment points (#5)."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from conftest import LoadFn, make_project
from pagan.asset import load_asset
from pagan.build import build
from pagan.importer import import_png
from pagan.manage import Adjustment, adjust_colors
from pagan.palette import parse_palette
from pagan.project import Project, load_project
from pagan.render import frame_image, sheet_image
from pagan.swatch import render_swatch

ALPHA_PALETTE = """\
name: glow
colors:
  "0": "#101010"
  "1": "#f0d040"
  "s": { hex: "#00000080", name: shadow }
  "g": "#FFE08040"
  "o": "#203040ff"
ramps:
  gold: ["0", "1"]
"""


def _alpha_project(root: Path, config: str = "") -> Project:
    root.mkdir(parents=True, exist_ok=True)
    project = make_project(root, f'default_palette = "glow"\n{config}')
    (root / "palettes" / "glow.pal.yaml").write_text(ALPHA_PALETTE)
    return load_project(root)


def _sprite(project: Project, body: str, name: str = "spark") -> Path:
    path = project.root / "sprites" / f"{name}.sprite.yaml"
    path.write_text(f"name: {name}\nsize: [3, 3]\n{body}")
    return path


def rules(findings: list) -> set[str]:  # type: ignore[type-arg]
    return {f.rule for f in findings}


# --- R31 (#2): translucent palette colours ----------------------------------------------------


def test_palette_accepts_rrggbbaa_and_normalises_opaque() -> None:
    palette, findings = parse_palette(
        {"name": "p", "colors": {"0": "#00000080", "1": "#AABBCCFF", "2": {"hex": "#ff000000"}}}
    )
    assert palette is not None, findings
    assert palette.colors["0"].hex == "#00000080" and palette.colors["0"].rgba == (0, 0, 0, 128)
    assert palette.colors["1"].hex == "#aabbcc" and palette.colors["1"].alpha == 255  # "ff" = opaque, one spelling
    assert palette.colors["2"].alpha == 0
    _, bad = parse_palette({"name": "p", "colors": {"0": "#0000008"}})
    assert rules(bad) == {"E005"} and "#rrggbbaa" in bad[0].message


def test_translucent_pixels_render_with_their_alpha(tmp_path: Path) -> None:
    project = _alpha_project(tmp_path)
    asset, findings = load_asset(_sprite(project, 'frames:\n  a: |\n    s1g\n    ...\n    ...\n'), project)
    assert asset is not None, [f.format() for f in findings]
    image = frame_image(asset, "a")
    assert image.getpixel((0, 0)) == (0, 0, 0, 128)
    assert image.getpixel((1, 0)) == (240, 208, 64, 255)
    assert image.getpixel((2, 0)) == (255, 224, 128, 64)
    assert sheet_image(asset).getpixel((0, 0)) == (0, 0, 0, 128)


def test_default_outline_colour_is_the_darkest_opaque_one(tmp_path: Path) -> None:
    project = _alpha_project(tmp_path)
    asset, findings = load_asset(_sprite(project, "outline: auto\nframes:\n  a: |\n    ...\n    .1.\n    ...\n"), project)
    assert asset is not None, [f.format() for f in findings]
    assert asset.outline_color == "0"  # not the translucent black "s"


def test_require_opaque_is_opt_in(tmp_path: Path) -> None:
    body = 'frames:\n  a: |\n    s1.\n    ...\n    ...\n'
    project = _alpha_project(tmp_path / "free")
    asset, _ = load_asset(_sprite(project, body), project)
    assert asset is not None
    strict = _alpha_project(tmp_path / "strict", "[lint]\nrequire_opaque = true\n")
    asset, findings = load_asset(_sprite(strict, body), strict)
    assert asset is None and rules(findings) == {"E015"} and "s" in findings[0].message
    opaque_only, findings = load_asset(_sprite(strict, 'frames:\n  a: |\n    01.\n    ...\n    ...\n', "plain"), strict)
    assert opaque_only is not None, [f.format() for f in findings]


def test_models_reject_translucent_materials(tmp_path: Path) -> None:
    project = _alpha_project(tmp_path)
    (project.root / "models").mkdir()
    path = project.root / "models" / "crate.model.yaml"
    path.write_text(
        "name: crate\nsize: [16, 16]\ndirections: 1\nmaterials:\n  wood: { keys: [\"0\", \"s\"] }\n"
        "parts:\n  - { box: [0, 0, 0, 3, 3, 3], material: wood }\n"
    )
    asset, findings = load_asset(path, project)
    assert asset is None
    assert any(f.rule == "E013" and "translucent" in f.message for f in findings), [f.format() for f in findings]


def test_palette_adjust_keeps_alpha(tmp_path: Path) -> None:
    project = _alpha_project(tmp_path)
    palette = project.load_palette("glow")
    out = adjust_colors(palette, ["s", "1"], Adjustment(lightness=0.1))
    assert out["s"].endswith("80") and len(out["s"]) == 9
    assert len(out["1"]) == 7


def test_import_snaps_to_opaque_colours_only(tmp_path: Path) -> None:
    project = _alpha_project(tmp_path)
    image = Image.new("RGBA", (2, 1), (0, 0, 0, 255))  # pure black: "s" is closer by RGB, but translucent
    rows, _, _ = import_png(image, palette=project.load_palette("glow"), scale=1)
    assert rows == ["00"]


def test_swatch_draws_translucent_colours(tmp_path: Path) -> None:
    project = _alpha_project(tmp_path)
    image = render_swatch(project.load_palette("glow"))
    assert image.width > 0 and image.height > 0


# --- R32 (#3): wide and stacked outlines, drop shadows -----------------------------------------

DOT = "name: dot\nsize: [9, 9]\n{extra}frames:\n  a: |\n" + "".join(f"    {row}\n" for row in [
    ".........", ".........", ".........", ".........", "....1....", ".........", ".........", ".........", ".........",
])


def test_outline_auto_is_unchanged_by_the_ring_code(load: LoadFn) -> None:
    from pagan.asset import _outline, _outline_ring

    auto, findings = load(DOT.format(extra="outline: auto\n"), name="dot")
    ring, _ = load(DOT.format(extra="outline: { width: 1 }\n"), name="dot")
    assert auto is not None and ring is not None, [f.format() for f in findings]
    assert auto.frames == ring.frames and auto.outlines == ((1, "0"),)
    grid = ("....", ".12.", "..2.", "....")
    assert _outline_ring(grid, "0", 1) == _outline(grid, "0")


def test_wide_outline_is_a_round_ring(load: LoadFn) -> None:
    asset, findings = load(DOT.format(extra='outline: { width: 2, color: "5" }\n'), name="dot")
    assert asset is not None, [f.format() for f in findings]
    assert asset.frames["a"][2:7] == ("....5....", "...555...", "..55155..", "...555...", "....5....")
    assert asset.outline and asset.outline_color == "5"


def test_stacked_outlines_and_shadow(load: LoadFn) -> None:
    extra = 'outline: [{ width: 1, color: "0" }, { width: 1, color: "6" }]\nshadow: { offset: [1, 2], color: "5" }\n'
    asset, findings = load(DOT.format(extra=extra), name="dot")
    assert asset is not None, [f.format() for f in findings]
    assert asset.frames["a"] == (
        ".........",
        ".........",
        "....6....",
        "...606...",
        "..60106..",
        "...6065..",
        "...56555.",
        "....555..",
        ".....5...",
    )
    assert asset.shadow == (1, 2, "5") and asset.base_frames["a"][4] == "....1...."


def test_wide_outline_and_shadow_clipping_is_e007(load: LoadFn) -> None:
    near = DOT.replace("....1....\n", "..1......\n")
    _, findings = load(near.format(extra="outline: { width: 3 }\n"), name="dot")
    assert rules(findings) == {"E007"} and "3px" in findings[0].message and findings[0].where == "frames.a row 5 col 3"
    assert load(near.format(extra="outline: { width: 2 }\n"), name="dot")[0] is not None
    _, findings = load(DOT.format(extra='shadow: { offset: [5, 0], color: "5" }\n'), name="dot")
    assert rules(findings) == {"E007"} and "shadow" in findings[0].message


def test_outline_and_shadow_field_errors(load: LoadFn) -> None:
    def found(extra: str) -> set[str]:
        return rules(load(DOT.format(extra=extra), name="dot")[1])

    assert found("outline: thick\n") == {"E001"}
    assert found("outline: { width: 0 }\n") == {"E001"}
    assert found("outline: { width: 9 }\n") == {"E001"}
    assert found('outline: { width: 2, colour: "0" }\n') == {"E001"}
    assert found('outline: { width: 2, color: "z" }\n') == {"E005"}
    assert found('shadow: { offset: [1, 1] }\n') == {"E001"}
    assert found('shadow: { offset: [0, 0], color: "5" }\n') == {"E001"}
    assert found('shadow: { offset: [1, 1], color: "z" }\n') == {"E005"}


# --- R33 (#4): derived frames that rotate and scale ---------------------------------------------

BAR = "name: bar\nsize: [5, 5]\npivot: [{px}, {py}]\nframes:\n  a: |\n    .....\n    ..1..\n    ..1..\n    ..2..\n    .....\n"


def test_derived_rotate_about_centre(load: LoadFn) -> None:
    asset, findings = load(BAR.format(px=2, py=5) + "  r: { from: a, rotate: 90, about: center }\n", name="bar")
    assert asset is not None, [f.format() for f in findings]
    assert asset.frames["r"] == (".....", ".....", ".211.", ".....", ".....")  # clockwise: the top swings right
    assert asset.derived_from["r"] == "a"
    back, _ = load(BAR.format(px=2, py=5) + "  r: { from: a, rotate: 360, about: center }\n", name="bar")
    assert back is not None and back.frames["r"] == back.frames["a"]


def test_derived_scale_about_pivot(load: LoadFn) -> None:
    text = BAR.format(px=2, py=4) + "  squash: { from: a, scale: [1, 0.5] }\n  tall: { from: a, scale: [1, 1.25] }\n"
    asset, findings = load(text, name="bar")
    assert asset is not None, [f.format() for f in findings]
    assert asset.frames["squash"] == (".....", ".....", "..1..", "..2..", ".....")  # half height, foot stays put
    assert asset.frames["tall"] == ("..1..", "..1..", "..1..", "..2..", ".....")


def test_derived_transform_combines_with_flip_and_shift(load: LoadFn) -> None:
    text = BAR.format(px=2, py=4) + "  s: { from: a, flip: vertical, scale: 1, rotate: 0, shift: [1, 0] }\n"
    asset, findings = load(text, name="bar")
    assert asset is not None, [f.format() for f in findings]
    assert asset.frames["s"] == (".....", "...2.", "...1.", "...1.", ".....")


def test_derived_transform_errors(load: LoadFn) -> None:
    def found(spec: str) -> set[str]:
        return rules(load(BAR.format(px=2, py=4) + f"  r: {{ from: a, {spec} }}\n", name="bar")[1])

    assert found("scale: 3") == {"E010"}  # off the canvas
    assert found("scale: 0") == {"E010"}
    assert found("scale: [-1, 1]") == {"E010"}
    assert found("rotate: 400") == {"E010"}
    assert found("rotate: 10, about: middle") == {"E010"}
    assert found("about: center") == {"E010"}  # nothing to rotate/scale about
    assert found("spin: 3") == {"E001"}


# --- R34 (#5): per-frame attachment points ---------------------------------------------------------

WOBBLE = (
    "name: sign\nsize: [4, 4]\nframes:\n  a: |\n    ....\n    .11.\n    .11.\n    ....\n"
    "  b: {{ from: a, shift: [1, 0] }}\n{points}"
)


def test_points_per_frame_and_every_frame(load: LoadFn) -> None:
    asset, findings = load(WOBBLE.format(points="points:\n  muzzle: [4, 2]\n  fire: { b: [3, 1], a: [2, 1] }\n"), name="sign")
    assert asset is not None, [f.format() for f in findings]
    assert asset.points == {"muzzle": {"a": (4, 2), "b": (4, 2)}, "fire": {"a": (2, 1), "b": (3, 1)}}
    assert list(asset.points["fire"]) == ["a", "b"]  # sheet order, not file order


def test_points_errors(load: LoadFn) -> None:
    def found(points: str) -> set[str]:
        return rules(load(WOBBLE.format(points=f"points:\n  {points}\n"), name="sign")[1])

    assert found("p: [5, 0]") == {"E008"}
    assert found("p: [1.5, 0]") == {"E008"}
    assert found("p: { c: [1, 1] }") == {"E001"}
    assert found("p: 3") == {"E001"}
    assert found("p q: [1, 1]") == {"E001"}


def test_points_in_the_manifest(tmp_path: Path) -> None:
    project = make_project(tmp_path, 'default_palette = "test"\noutput_dir = "out"\n')
    (project.root / "sprites" / "sign.sprite.yaml").write_text(WOBBLE.format(points="points:\n  fire: { a: [2, 1] }\n"))
    (project.root / "sprites" / "big.sprite.yaml").write_text(
        "name: big\nsize: [4, 4]\nsupersample: 2\npoints:\n  tip: [3, 2]\nframes:\n  a: |\n    ....\n    .11.\n    .11.\n    ....\n"
    )
    result = build(project)
    assert not result.errors and result.manifest is not None, [f.format() for f in result.errors]
    assets = json.loads(result.manifest.read_text())["assets"]
    assert assets["sign"]["points"] == {"fire": {"a": [2, 1]}}
    assert assets["big"]["points"] == {"tip": {"a": [1.5, 1]}}  # output pixels
