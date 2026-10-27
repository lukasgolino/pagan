"""`pagan.api`, the stable API for generator scripts (R11/R12)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import ImageFont

from pagan import api
from pagan.asset import load_asset
from pagan.cli import main
from pagan.lint import lint_paths
from pagan.project import Project


def test_canvas_shapes() -> None:
    c = api.Canvas(9, 9).circle(4.5, 4.5, 3, "1")
    # a pixel centre exactly on the edge (x = 1.5, 3 from the centre) is outside: no 1px nubs (Space IO S5)
    assert c.get(4, 4) == "1" and c.get(0, 0) == "." and c.rows()[4] == ".." + "1" * 5 + ".."
    ring = api.Canvas(9, 9).ring(4.5, 4.5, 4, 4, 1, "2")
    assert ring.get(4, 4) == "." and ring.get(4, 1) == "2" and ring.get(4, 0) == "."
    line = api.Canvas(4, 4).line(0.5, 0.5, 3.5, 3.5, "3")
    assert [line.get(i, i) for i in range(4)] == ["3"] * 4
    shaded = api.Canvas(9, 9).ellipse(4.5, 4.5, 4, 4, lambda dx, dy: api.ramp_pick("12", api.sphere_light(dx, dy)))
    assert shaded.get(2, 2) == "2" and shaded.get(6, 7) == "1"  # lit from the top-left
    assert api.Canvas.from_rows(["12", ".3"]).flip().rows() == ["21", "3."]


def test_fade_and_scatter_are_repeatable() -> None:
    a = api.Canvas(16, 16).circle(8, 8, 7, "1").fade(0.4, seed=3)
    b = api.Canvas(16, 16).circle(8, 8, 7, "1").fade(0.4, seed=3)
    full = len(api.Canvas(16, 16).circle(8, 8, 7, "1").opaque())
    assert a.rows() == b.rows() and len(a.opaque()) == full - int(full * 0.4)
    assert a.get(8, 8) == "1"  # the middle survives longest
    s = api.Canvas(16, 16).scatter(10, "2", seed=1)
    assert s.rows() == api.Canvas(16, 16).scatter(10, "2", seed=1).rows() and s.opaque()


def test_orphans_match_lint() -> None:
    c = api.Canvas(5, 5)
    c.put(0, 0, "1")
    c.put(3, 3, "1")
    c.put(4, 3, "1")
    assert c.orphans() == [(0, 0)]
    assert api.Canvas.from_rows(c.rows()).pair_orphans().orphans() == []
    assert c.copy().remove_orphans().opaque() == [(3, 3), (4, 3)]


def test_sprite_yaml_round_trip(project: Project) -> None:
    frame = api.Canvas(4, 4).circle(2, 2, 1.6, "1")
    text = api.sprite_yaml(
        "dot",
        (4, 4),
        {"a": frame, "on": frame.copy().flip()},
        {"blink": {"frames": ["a", "on"], "fps": 4, "loop": False}},
        description="a dot: tests quoting",
        tags=["effect"],
        lint={"disable": ["W007"]},
    )
    path = api.write(project.root / "sprites" / "dot.sprite.yaml", text)
    asset, findings = load_asset(path, project)
    assert asset is not None, [f.format() for f in findings]
    assert asset.frames["on"] == tuple(frame.copy().flip().rows())
    assert asset.description == "a dot: tests quoting" and asset.lint_disable == {"W007"}
    assert asset.animations["blink"].loop is False
    with pytest.raises(ValueError):
        api.sprite_yaml("bad", (3, 3), {"a": frame})


def test_corner_tiles_and_compose(project: Project) -> None:
    def paint(field: object, x: int, y: int, corners: tuple[int, int, int, int]) -> str:
        assert callable(field)
        return "4" if field(x, y) >= 0.5 else "5"

    tiles = api.corner_tiles("shore", 8, paint, seed=1)
    assert len(tiles) == 16
    assert all(k == "5" for row in tiles["shore_0000"].rows() for k in row)
    assert all(k == "4" for row in tiles["shore_1111"].rows() for k in row)
    assert tiles["shore_1000"].get(0, 0) == "4" and tiles["shore_1000"].get(7, 7) == "5"  # NW corner only
    path = api.write(project.root / "tiles" / "shore.tiles.yaml", api.tileset_yaml("shore", (8, 8), tiles, columns=4))
    asset = api.load(path, project)
    scene = api.compose(asset, "shore_1111 shore_1010\nshore_0101 .")
    assert scene.size == (16, 16) and scene.getpixel((12, 12)) == (0, 0, 0, 0)
    with pytest.raises(ValueError):
        api.compose(asset, "nope")
    assert not lint_paths(project).errors


def test_preview_scene(project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    tiles = {"a": ["11", "11"], "b": ["22", "22"]}
    api.write(project.root / "tiles" / "t.tiles.yaml", api.tileset_yaml("t", (2, 2), tiles))
    layout = project.root / "scene.txt"
    layout.write_text("a b a\nb a b\n")
    assert main(["preview", str(project.root / "tiles" / "t.tiles.yaml"), "--scene", str(layout), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert Path(result["outputs"][0]["scene"]).name == "scene.png"


def test_geometry_matches_the_primitives() -> None:
    hull = api.shape_cells("hull", {"from": [0, 0, 0], "length": 27, "beam": 9, "height": 3, "bow": 0.45, "stern": 0.08, "material": "wood"})
    for x in range(27):
        for z, keel in ((0, True), (2, False)):
            reach = api.hull_reach(x, 27, 9, 0.45, 0.08, keel=keel)
            assert {y for (cx, y, cz) in hull if cx == x and cz == z} == set(range(-reach, reach + 1))
    sail = api.shape_cells("sail", {"at": [0, 0, 5], "width": 8, "height": 6, "brace": 20, "material": "cloth", "yard": "spar"})
    cells = api.sail_cells((0, 0, 5), 8, 6, brace=20, yard=True)
    assert {c.cell for c in cells} == set(sail)
    assert {sail[c.cell] for c in cells if c.normal is None} == {"spar"}
    assert {c.row for c in cells if c.normal is not None} == set(range(6))
    with pytest.raises(ValueError):
        api.shape_cells("box", {"from": [0, 0], "to": [1, 1, 1], "material": "x"})


def test_light_follows_the_project(project: Project) -> None:
    lx, ly, lz = api.light_2d(project)
    assert lx < 0 and ly < 0 and lz > 0  # default: from the top-left, towards the viewer
    assert api.hash01(3, 4, 5) == api.hash01(3, 4, 5) != api.hash01(3, 4, 6)
    assert abs(api.periodic_noise(0, 3, 16) - api.periodic_noise(16, 3, 16)) < 1e-9


# --- text from a real typeface (#15) -----------------------------------------------------------


def _font() -> ImageFont.FreeTypeFont:
    font = ImageFont.load_default(10)  # Pillow's bundled TrueType font (needs FreeType, as Pillow wheels have)
    assert isinstance(font, ImageFont.FreeTypeFont)
    return font


def test_text_mask_cap_height_and_metrics() -> None:
    mask = api.text_mask("H", _font(), cap_height=12)
    ink = mask.mask()
    x0, y0, x1, y1 = mask.bbox
    assert mask.origin[1] == y1 and y1 - y0 == 12  # baseline under the ink, "H" exactly 12 px tall
    assert ink[y0:y1, x0:x1].any(axis=1).all() and not ink[:y0].any() and not ink[y1:].any()
    assert mask.coverage.min() >= 0 and mask.coverage.max() <= 1
    pair = api.text_mask("HH", _font(), cap_height=12)
    assert pair.advance == pytest.approx(2 * mask.advance, abs=0.5)
    by_size = api.text_mask("H", _font(), size=20)
    assert by_size.coverage.shape != mask.coverage.shape
    assert api.text_mask("H", _font(), cap_height=12).coverage.tobytes() == mask.coverage.tobytes()  # repeatable


def test_text_mask_rotate_and_scale_about_the_anchor() -> None:
    rest = api.text_mask("I", _font(), cap_height=20, anchor="baseline_centre")
    tilt = api.text_mask("I", _font(), cap_height=20, anchor="baseline_centre", rotate=15)
    wide = api.text_mask("I", _font(), cap_height=20, anchor="baseline_centre", scale=(2, 1))
    for m in (rest, tilt, wide):  # the anchor stays where the letter stands
        ox, oy = m.origin
        assert m.mask()[oy - 2, ox - 3 : ox + 3].any()
    def top_x(m: api.TextMask) -> int:  # first inked pixel (row-major), relative to the anchor
        return int(np.argwhere(m.mask())[0][1]) - m.origin[0]

    assert top_x(tilt) > top_x(rest)  # clockwise: the top swings right
    assert (wide.bbox[2] - wide.bbox[0]) > (rest.bbox[2] - rest.bbox[0])


def test_text_mask_errors() -> None:
    with pytest.raises(ValueError):
        api.text_mask("H", _font())
    with pytest.raises(ValueError):
        api.text_mask("H", _font(), size=10, cap_height=10)
    with pytest.raises(ValueError):
        api.text_mask("H", _font(), size=10, variation={"wght": 900})  # not a variable font


def test_reference_api_calls_exist() -> None:
    # #33: every call the skill's reference shows for `pagan.api` must exist where it says: `api.x` / bare `x(` on
    # the module, `canvas.x(` / `Canvas.x(` on Canvas (bare calls may also be Canvas/TextMask methods, which the
    # Canvas bullet lists without a prefix). Callbacks the reader writes are not API.
    import re

    reference = (Path(api.__file__).parent / "skill" / "reference.md").read_text(encoding="utf-8")
    section = reference.split("## Generator scripts: `pagan.api`")[1].split("\n## ")[0]
    callbacks = {"draw", "field", "paint"}
    missing = []
    for code in re.findall(r"`([^`]+)`", section):
        for match in re.finditer(r"(?<![\w.])(api\.|canvas\.|Canvas\.)?([A-Za-z_]\w*)\(", code):
            prefix, name = match.groups()
            if prefix == "api.":
                ok = name in api.__all__
            elif prefix in ("canvas.", "Canvas."):
                ok = hasattr(api.Canvas, name)
            else:
                ok = name in callbacks or name in api.__all__ or hasattr(api.Canvas, name) or hasattr(api.TextMask, name)
            if not ok:
                missing.append(match.group(0))
        missing += [f"api.{name}" for name in re.findall(r"api\.(\w+)", code) if name not in api.__all__]
    assert not missing
    assert "canvas.text(" in section and not re.search(r"(?<![\w.])text\(", section)  # a Canvas method, not api.text


def test_pixel_font_has_every_printable_ascii_glyph_at_its_size() -> None:
    printable = "".join(chr(c) for c in range(0x20, 0x7F))
    for size, cell in (("3x5", (3, 5)), ("5x7", (5, 7))):
        font = api.pixel_font(size)
        assert font.font is not None and font.font.glyphs == printable and font.font.cell == cell
        assert len(font.frames) == len(printable)
        for grid in font.frames.values():
            assert len(grid) == cell[1] and all(len(row) == cell[0] for row in grid)
    upper = api.pixel_font("3x5")
    assert all(upper.frames[f"u{ord(c):02x}"] == upper.frames[f"u{ord(c.upper()):02x}"] for c in "abcxyz")
    lower = api.pixel_font("5x7")
    assert lower.frames[f"u{ord('a'):02x}"] != lower.frames[f"u{ord('A'):02x}"]
    with pytest.raises(ValueError, match="sizes: 3x5, 5x7"):
        api.pixel_font("4x6")


def test_pixel_font_glyphs_render_non_empty_except_space() -> None:
    for size in ("3x5", "5x7"):
        font = api.pixel_font(size)
        assert font.font is not None
        for char in font.font.glyphs:
            canvas = api.Canvas(*font.font.cell).text(font, char, 0, 0, key="k")
            inked = sum(row.count("k") for row in canvas.rows())
            assert (inked == 0) == (char == " "), (size, char)


def test_pixel_font_letters_exit() -> None:
    canvas = api.Canvas(16, 5).text(api.pixel_font("3x5"), "Exit", 0, 0, key="k")
    assert canvas.rows() == [
        "kkk.k.k.kkk.kkk.",
        "k...k.k..k...k..",
        "kk...k...k...k..",
        "k...k.k..k...k..",
        "kkk.k.k.kkk..k..",
    ]
    again = api.Canvas(16, 5).text(api.pixel_font("3x5"), "EXIT", 0, 0, key="k")
    assert again.rows() == canvas.rows()
    big = api.Canvas(48, 14).text(api.pixel_font("5x7"), "EXIT", 0, 0, scale=2, key="k")
    assert big.rows()[0] == "kkkkkkkkkk..kk......kk....kkkkkk....kkkkkkkkkk.."
    with pytest.raises(ValueError, match="pass key="):
        api.Canvas(16, 5).text(api.pixel_font("3x5"), "EXIT", 0, 0)
