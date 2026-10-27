"""LOOSE! title-logo reports R30-R38 (GitHub issues #1-#9): translucent palette colours (#2), wide/stacked
outlines and drop shadows (#3), rotated/scaled derived frames (#4),
per-frame attachment points (#5), numpy-friendly `pagan.api` (#6), faster lint of big
sprites (#7), per-frame durations, `loop_from` and tile durations (#8), bigger canvases,
`sheet_columns` and the sheet-size warning (#9, R30c)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from conftest import LoadFn, make_project
from pagan import api
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
    assert auto.frames == ring.frames and auto.outlines == ((1, "0", False),)
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


# --- R35 (#6): numpy canvases, dithering, distance fields, bevels, text, numpy ints in YAML --------


def test_canvas_numpy_round_trip() -> None:
    canvas = api.Canvas.from_rows(["12.", ".3."])
    array = canvas.to_array()
    assert array.shape == (2, 3) and array[0, 1] == "2"
    assert api.Canvas.from_array(array).rows() == canvas.rows()
    assert canvas.mask().tolist() == [[True, True, False], [False, True, False]]
    indexed = api.Canvas.from_array(np.array([[0, 1, -1], [2, 2, 0]]), "abc")
    assert indexed.rows() == ["ab.", "cca"]
    with pytest.raises(ValueError):
        api.Canvas.from_array(np.array([[3]]), "abc")
    with pytest.raises(ValueError):
        api.Canvas.from_array(np.zeros((2, 2, 2)))


def test_dither_scalar_and_arrays() -> None:
    assert api.dither("abc", 0.0, 3, 5) == "a" and api.dither("abc", 1.0, 3, 5) == "c"
    ys, xs = np.mgrid[0:8, 0:8]
    half = api.dither("ab", np.full((8, 8), 0.5), xs, ys)
    assert (half == "b").sum() == 32  # half the pixels take the lighter step
    assert (api.dither("ab", np.full((8, 8), 0.25), xs, ys, matrix=8) == "b").sum() == 16
    assert api.Canvas.from_array(half).rows()[0] in ("abababab", "babababa")
    with pytest.raises(ValueError):
        api.dither("ab", 0.5, 0, 0, matrix=3)


def test_distance_field_is_exact() -> None:
    mask = np.zeros((7, 9), dtype=bool)
    mask[1:6, 2:8] = True
    field = api.distance_field(mask)
    assert field[3, 4] == 3.0 and field[1, 4] == 1.0  # inside: to the nearest outside pixel centre
    assert field[0, 0] == pytest.approx(-(5**0.5))  # outside: minus the distance to (row 1, col 2)
    assert field[0, 4] == -1.0
    assert (api.distance_field(np.zeros((2, 2), dtype=bool)) < 0).all()


def test_bevel_lights_the_top_left_edge() -> None:
    mask = np.zeros((20, 20), dtype=bool)
    mask[3:17, 3:17] = True
    shade = api.bevel(mask, 4)
    assert shade[0, 0] == 0.0
    assert shade[4, 10] > shade[10, 10] > shade[15, 10]  # lit edge, flat top, shadowed edge
    assert 0.0 <= shade.min() and shade.max() <= 1.0


def test_canvas_text_with_a_font_sprite(load: LoadFn) -> None:
    text = (
        'name: font\nsize: [8, 4]\nfont: { glyphs: "lE", cell: [4, 4], baseline: 3, advance: auto, space: 2 }\n'
        "lint: { disable: [W001] }\nframes:\n  sheet: |\n    1...111.\n    1...1...\n    1...111.\n    ........\n"
    )
    font, findings = load(text, name="font")
    assert font is not None, [f.format() for f in findings]
    canvas = api.Canvas(8, 4).text(font, "lE", 0, 0)
    assert canvas.rows() == ["1.111...", "1.1.....", "1.111...", "........"]  # l advances 1 + spacing 1
    assert api.Canvas(4, 6).text(font, "l", 0, 0, scale=2, key="5").rows()[:2] == ["55..", "55.."]
    with pytest.raises(ValueError):
        api.Canvas(8, 4).text(font, "x", 0, 0)


def test_sprite_yaml_accepts_numpy_numbers() -> None:
    size: Any = (np.int64(2), np.int64(1))  # what numpy maths hands a generator
    text = api.sprite_yaml(
        "dot", size, {"a": ["1."]}, {"pulse": {"frames": ["a"], "fps": np.float64(4.0)}},
        pivot=[np.int64(1), np.int64(1)],
    )
    assert "pivot: [1, 1]" in text and "size: [2, 1]" in text and "fps: 4.0" in text


# --- R36 (#7): big sprites lint faster ----------------------------------------------------------


def test_orphans_match_the_pixel_by_pixel_rule() -> None:
    from pagan.asset import opaque
    from pagan.lint import _orphans

    rng = np.random.default_rng(7)
    for _ in range(20):
        grid = tuple("".join("1" if v else "." for v in row) for row in rng.random((9, 11)) < 0.2)
        expected = [
            (x, y)
            for y, row in enumerate(grid)
            for x, c in enumerate(row)
            if c != "." and not any(opaque(grid, x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy)
        ]
        assert _orphans(grid) == expected
    assert _orphans(()) == []


# --- R37 (#8): per-frame durations ----------------------------------------------------------------

HOLD = "name: hit\nsize: [2, 1]\nframes:\n  a: |\n    1.\n  b: |\n    .1\nanimations:\n{anims}"


def test_durations_parse_and_mirror(load: LoadFn) -> None:
    asset, findings = load(HOLD.format(anims="  hit: { frames: [a, b, a], fps: 10, durations: [1, 3, 0.5] }\n  back: { from: hit, flip: horizontal }\n"), name="hit")
    assert asset is not None, [f.format() for f in findings]
    assert asset.animations["hit"].durations == (1.0, 3.0, 0.5)
    assert asset.animations["back"].durations == (1.0, 3.0, 0.5)  # copied from the source animation
    plain, _ = load(HOLD.format(anims="  hit: [a, b]\n"), name="hit")
    assert plain is not None and plain.animations["hit"].durations is None


def test_durations_errors(load: LoadFn) -> None:
    for bad in ("[1, 2]", "[1, 0, 1]", "[1, true, 1]", "3"):
        _, findings = load(HOLD.format(anims=f"  hit: {{ frames: [a, b, a], durations: {bad} }}\n"), name="hit")
        assert rules(findings) == {"E001"}, bad


def test_durations_in_manifest_godot_and_gif(tmp_path: Path) -> None:
    from pagan.exporters.godot import sprite_frames_tres
    from pagan.preview import PreviewOptions, animation_gif

    project = make_project(tmp_path, 'default_palette = "test"\noutput_dir = "out"\n')
    (project.root / "sprites" / "hit.sprite.yaml").write_text(
        HOLD.format(anims="  hit: { frames: [a, b], fps: 10, durations: [1, 3] }\n  idle: [a]\n") + "lint: { disable: [W001] }\n"
    )
    result = build(project)
    assert not result.errors and result.manifest is not None, [f.format() for f in result.errors]
    animations = json.loads(result.manifest.read_text())["assets"]["hit"]["animations"]
    assert animations["hit"]["durations"] == [1.0, 3.0] and "durations" not in animations["idle"]
    asset = load_asset(project.root / "sprites" / "hit.sprite.yaml", project)[0]
    assert asset is not None
    tres = sprite_frames_tres("res://hit.png", {"a": (0, 0, 2, 1), "b": (2, 0, 2, 1)}, list(asset.animations.values()))
    assert '"duration": 3.0' in tres and '"duration": 1.0' in tres
    gif = tmp_path / "hit.gif"
    animation_gif(asset, "hit", PreviewOptions(scale=1), gif)
    with Image.open(gif) as image:
        shown = []
        for i in range(getattr(image, "n_frames", 1)):
            image.seek(i)
            shown.append(image.info["duration"])
    assert shown == [100, 300]


# --- R38 (#9) + R30c (#1): canvases up to 4096, sheet_columns, W014 ------------------------------


def _wide(width: int, frames: int, extra: str = "") -> str:
    row = "1" + "." * (width - 1)
    body = "".join(f"  f{i}: |\n    {row}\n" for i in range(frames))
    return f"name: wide\nsize: [{width}, 1]\nlint: {{ disable: [W001] }}\n{extra}frames:\n{body}"


def test_sprites_can_be_4096_wide_models_stay_1024(load: LoadFn, tmp_path: Path) -> None:
    asset, findings = load(_wide(4096, 1), name="wide")
    assert asset is not None, [f.format() for f in findings]
    _, findings = load(_wide(4097, 1), name="wide")
    assert rules(findings) == {"E001"} and "1-4096" in findings[0].message
    (tmp_path / "m").mkdir()
    project = make_project(tmp_path / "m")
    (project.root / "models").mkdir()
    path = project.root / "models" / "box.model.yaml"
    path.write_text('name: box\nsize: [2048, 16]\nmaterials:\n  m: { keys: ["1"] }\nparts:\n  - { box: [0, 0, 0, 1, 1, 1], material: m }\n')
    assert any("1-1024" in f.message for f in load_asset(path, project)[1])


def test_sheet_columns_and_w014(tmp_path: Path) -> None:
    from pagan.lint import lint_paths
    from pagan.render import frame_rects

    project = make_project(tmp_path)
    path = project.root / "sprites" / "wide.sprite.yaml"
    path.write_text(_wide(4096, 5))  # 5 in a row: 20480 px wide
    result = lint_paths(project)
    assert [f.rule for f in result.warnings] == ["W014"] and "20480x1" in result.warnings[0].message
    path.write_text(_wide(4096, 5, "sheet_columns: 2\n"))
    result = lint_paths(project)
    assert not result.findings, [f.format() for f in result.findings]
    asset = result.assets[0]
    assert frame_rects(asset)["f2"] == (0, 1, 4096, 1)
    path.write_text(_wide(16, 2, "sheet_columns: 0\n"))
    assert rules(lint_paths(project).findings) == {"E001"}


# --- #37: outlines that skip translucent glows -------------------------------------------------


def test_outline_skip_translucent_leaves_glows_unringed(tmp_path: Path) -> None:
    project = _alpha_project(tmp_path)
    rows = [".......", ".......", "..ggg..", "..g1g..", "..ggg..", "...1...", "......."]
    frames = "frames:\n  a: |\n" + "".join(f"    {row}\n" for row in rows)

    def outlined(outline: str) -> tuple[str, ...]:
        path = project.root / "sprites" / "icon.sprite.yaml"
        path.write_text(f"name: icon\nsize: [7, 7]\noutline: {outline}\n{frames}")
        asset, findings = load_asset(path, project)
        assert asset is not None and not findings, [f.format() for f in findings]
        return asset.frames["a"]

    assert outlined("auto") == (".......", "..000..", ".0ggg0.", ".0g1g0.", ".0ggg0.", "..010..", "...0...")
    # Only the opaque pixel below the glow is ringed; the glow keeps its soft edge and isn't painted over.
    assert outlined("{ width: 1, skip_translucent: true }") == (
        ".......", ".......", "..ggg..", "..g1g..", "..ggg..", "..010..", "...0...",
    )
    from pagan.asset import _outline_ring

    wide = _outline_ring(tuple(rows), "0", 2, frozenset("g"))  # the numpy path for wider rings
    # Distances still run through the glow (the ring is `width` from the opaque pixels), but no glow pixel is ringed.
    assert wide == (".......", "...0...", "..ggg..", ".0g1g0.", "..ggg..", ".00100.", "..000..")


def test_outline_skip_translucent_ignores_glows_at_the_canvas_edge(tmp_path: Path) -> None:
    project = _alpha_project(tmp_path)
    body = "frames:\n  a: |\n    ggg\n    g1g\n    ggg\n"
    _, findings = load_asset(_sprite(project, "outline: auto\n" + body), project)
    assert rules(findings) == {"E007"}  # the glow touches the edge
    asset, findings = load_asset(_sprite(project, "outline: { width: 1, skip_translucent: true }\n" + body), project)
    assert asset is not None and not findings, [f.format() for f in findings]
    assert asset.frames["a"] == ("ggg", "g1g", "ggg")  # the only opaque pixel is fully surrounded by glow
    _, findings = load_asset(_sprite(project, "outline: { width: 1, skip_translucent: 1 }\n" + body), project)
    assert rules(findings) == {"E001"}


# --- R37 (#8): loop_from (intro, then a loop) and tile animation durations -------------------------

INTRO = "name: hit\nsize: [2, 1]\nframes:\n  a: |\n    1.\n  b: |\n    .1\n  c: |\n    11\nanimations:\n{anims}lint: {{ disable: [W001] }}\n"


def test_loop_from_parses_and_mirrors(load: LoadFn) -> None:
    asset, findings = load(INTRO.format(anims="  rise: { frames: [a, b, c, b], loop_from: 2 }\n  back: { from: rise, flip: horizontal }\n"), name="hit")
    assert asset is not None, [f.format() for f in findings]
    assert asset.animations["rise"].loop_from == 2 and asset.animations["back"].loop_from == 2
    plain, _ = load(INTRO.format(anims="  rise: [a, b]\n"), name="hit")
    assert plain is not None and plain.animations["rise"].loop_from is None


@pytest.mark.parametrize(
    ("anims", "hint"),
    [
        ("  rise: { frames: [a, b, c], loop_from: 0 }\n", "from 1 to 2"),
        ("  rise: { frames: [a, b, c], loop_from: 3 }\n", "from 1 to 2"),
        ("  rise: { frames: [a, b, c], loop_from: true }\n", "from 1 to 2"),
        ("  rise: { frames: [a, b, c], loop_from: 1.5 }\n", "from 1 to 2"),
        ("  rise: { frames: [a, b, c], loop_from: 1, loop: false }\n", "remove loop: false"),
        ("  rise: { frames: [a, b, c], loop_from: 1 }\n  rise_loop: [c]\n", "'rise_loop', which is already an animation"),
    ],
)
def test_loop_from_errors(load: LoadFn, anims: str, hint: str) -> None:
    _, findings = load(INTRO.format(anims=anims), name="hit")
    assert rules(findings) == {"E001"} and hint in findings[0].message, [f.format() for f in findings]
    assert findings[0].where == "animations.rise"


def test_loop_from_in_manifest_godot_and_gif(tmp_path: Path) -> None:
    from pagan.preview import LOOP_FROM_REPEATS, PreviewOptions, animation_gif

    (tmp_path / "game" / "art").mkdir(parents=True)
    (tmp_path / "game" / "project.godot").write_text("config_version=5\n")
    project = make_project(tmp_path / "game" / "art", 'default_palette = "test"\noutput_dir = "../gen"\nexport = ["png", "godot"]\n')
    anims = "  idle: [a]\n  rise: { frames: [a, b, c, b], fps: 10, durations: [2, 1, 1, 3], loop_from: 2 }\n"
    (project.root / "sprites" / "hit.sprite.yaml").write_text(INTRO.format(anims=anims))
    result = build(load_project(project.root))
    assert not result.errors and result.manifest is not None, [f.format() for f in result.errors]
    entry = json.loads(result.manifest.read_text())["assets"]["hit"]
    assert entry["animation_order"] == ["idle", "rise", "rise_loop"]
    assert entry["animations"]["idle"] == {"frames": ["a"], "fps": 8.0, "loop": True}
    assert entry["animations"]["rise"] == {"frames": ["a", "b"], "fps": 10.0, "loop": False, "durations": [2.0, 1.0], "loop_from": 2, "next": "rise_loop"}
    assert entry["animations"]["rise_loop"] == {"frames": ["c", "b"], "fps": 10.0, "loop": True, "durations": [1.0, 3.0]}
    tres = (tmp_path / "game" / "gen" / "sprites" / "hit.tres").read_text()
    assert '"loop": false,\n"name": &"rise"' in tres and '"loop": true,\n"name": &"rise_loop"' in tres
    asset = load_asset(project.root / "sprites" / "hit.sprite.yaml", load_project(project.root))[0]
    assert asset is not None
    gif = tmp_path / "rise.gif"
    animation_gif(asset, "rise", PreviewOptions(scale=1), gif)
    with Image.open(gif) as image:
        shown = []
        for i in range(getattr(image, "n_frames", 1)):
            image.seek(i)
            shown.append(image.info["duration"])
    assert shown == [200, 100] + [100, 300] * LOOP_FROM_REPEATS  # the intro once, then the loop


def test_loop_from_seam_lint_skips_the_intro(tmp_path: Path) -> None:
    from pagan.lint import lint_paths

    project = make_project(tmp_path, 'default_palette = "test"\n[lint]\nmax_frame_change = 0.01\n')
    path = project.root / "sprites" / "hit.sprite.yaml"
    path.write_text(INTRO.format(anims="  rise: { frames: [a, c, c, c, c], loop_from: 1 }\n"))
    pairs = [f.message.split(":")[0] for f in lint_paths(load_project(project.root)).findings if f.rule == "W007"]
    assert pairs == ["a -> c"]  # the loop's seam is c -> c, not c -> a


TILE_HOLD = """\
name: sea
tile_size: [2, 2]
columns: 4
tiles:
  rock: |
    00
    00
  w0: |
    11
    11
  w1: |
    22
    22
animations:
  water: {spec}
"""


def test_tile_animation_durations(tmp_path: Path, load: LoadFn) -> None:
    asset, findings = load(TILE_HOLD.format(spec="{ frames: [w0, w1], fps: 4, durations: [3, 0.5] }"), "sea", kind="tileset")
    assert asset is not None, [f.format() for f in findings]
    assert asset.animations["water"].durations == (3.0, 0.5)
    for bad in ("[1]", "[1, 0]", "[true, 1]"):
        _, findings = load(TILE_HOLD.format(spec=f"{{ frames: [w0, w1], durations: {bad} }}"), "sea", kind="tileset")
        assert rules(findings) == {"E001"} and "durations" in findings[0].message, bad
    _, findings = load(TILE_HOLD.format(spec="{ frames: [w0, w1], loop_from: 1 }"), "sea", kind="tileset")
    assert rules(findings) == {"E001"} and "always loop" in findings[0].message

    (tmp_path / "game" / "art").mkdir(parents=True)
    (tmp_path / "game" / "project.godot").write_text("config_version=5\n")
    project = make_project(tmp_path / "game" / "art", 'default_palette = "test"\noutput_dir = "../gen"\nexport = ["png", "godot"]\n')
    (project.root / "tiles" / "sea.tiles.yaml").write_text(TILE_HOLD.format(spec="{ frames: [w0, w1], fps: 4, durations: [3, 0.5] }"))
    result = build(load_project(project.root))
    assert not result.errors and result.manifest is not None, [f.format() for f in result.errors]
    tres = (tmp_path / "game" / "gen" / "tiles" / "sea.tres").read_text()
    assert "1:0/animation_speed = 4.0\n1:0/animation_frame_0/duration = 3.0\n1:0/animation_frame_1/duration = 0.5\n" in tres
    water = json.loads(result.manifest.read_text())["assets"]["sea"]["animations"]["water"]
    assert water == {"frames": ["w0", "w1"], "fps": 4.0, "loop": True, "durations": [3.0, 0.5]}
