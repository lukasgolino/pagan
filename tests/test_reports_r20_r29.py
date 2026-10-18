"""Age of Boom PAGAN_LOG friction filed as R20-R29: 9-slice margins, fonts, animation order, build progress and
speed, tile animation rows, tileset variant previews, palette-wide variants, 2D headings, preview 1x frames,
per-asset ramp budgets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import LoadFn, make_project
from pagan import api
from pagan.asset import load_asset
from pagan.build import build
from pagan.cli import main
from pagan.exporters.godot import find_godot_binary, verify_with_godot
from pagan.lint import lint_paths
from pagan.project import Project, load_project
from pagan.render import tile_cells
from test_reports_r15_r17 import _godot_project

GODOT = find_godot_binary()
needs_godot = pytest.mark.skipif(GODOT is None, reason="no Godot binary (set GODOT=/path/to/godot)")


def rules(findings: list) -> set[str]:  # type: ignore[type-arg]
    return {f.rule for f in findings}


def _manifest(project: Project) -> dict:  # type: ignore[type-arg]
    result = build(project)
    assert not result.errors, [f.format() for f in result.errors]
    assert result.manifest is not None
    data: dict = json.loads(result.manifest.read_text())  # type: ignore[type-arg]
    return data


def _built_project(tmp_path: Path, config: str = "") -> Project:
    return make_project(tmp_path, f'default_palette = "test"\noutput_dir = "out"\n{config}')


# --- R20: 9-slice margins in the manifest ------------------------------------------------------------

PANEL = """\
name: panel
size: [6, 6]
nine_slice: {margins}
frames:
  frame: |
    111111
    122221
    12..21
    12..21
    122221
    111111
  tail: |
    ......
    ..11..
    ..11..
    ..11..
    ......
    ......
lint: {{ disable: [W002] }}
"""


def test_nine_slice_margins_reach_the_manifest(tmp_path: Path) -> None:
    project = _built_project(tmp_path)
    (project.root / "sprites" / "panel.sprite.yaml").write_text(PANEL.format(margins="{ frame: [2, 2, 2, 2] }"))
    entry = _manifest(project)["assets"]["panel"]
    assert entry["nine_slice"] == {"frame": [2, 2, 2, 2]}  # only the frame that is a 9-slice
    (project.root / "sprites" / "panel.sprite.yaml").write_text(PANEL.format(margins="[2, 1, 2, 1]"))
    assert _manifest(project)["assets"]["panel"]["nine_slice"] == {"frame": [2, 1, 2, 1], "tail": [2, 1, 2, 1]}


@pytest.mark.parametrize(
    "margins, message",
    [("[3, 1, 3, 1]", "leaves no centre"), ("[1, 1, 1]", "nine_slice must be"), ("{ nope: [1, 1, 1, 1] }", "isn't a frame"), ("[-1, 0, 0, 0]", "nine_slice must be")],
)
def test_nine_slice_errors(load: LoadFn, margins: str, message: str) -> None:
    asset, findings = load(PANEL.format(margins=margins), "panel")
    assert asset is None and any(message in f.message for f in findings), [f.format() for f in findings]


# --- R21: fonts ---------------------------------------------------------------------------------------

FONT = """\
name: font
size: [8, 4]
outline: none
font: {{ glyphs: {glyphs}, cell: [4, 4], baseline: 3, advance: auto, space: 2 }}
frames:
  sheet: |
    1...111.
    1...1...
    1...111.
    ........
"""


def test_font_metrics_and_bmfont_file(tmp_path: Path) -> None:
    project = _built_project(tmp_path)
    (project.root / "sprites" / "font.sprite.yaml").write_text(FONT.format(glyphs='"lE"') + "lint: { disable: [W001] }\n")
    font = _manifest(project)["assets"]["font"]["font"]
    assert font["glyph_order"] == "lE" and font["ascent"] == 3 and font["descent"] == 1 and font["line_height"] == 4
    assert font["glyphs"]["l"] == {"rect": [0, 0, 4, 4], "advance": 2}  # 1 px drawn + 1 spacing
    assert font["glyphs"]["E"] == {"rect": [4, 0, 4, 4], "advance": 4}
    fnt = (tmp_path / "out" / "fonts" / "font.fnt").read_text()
    assert 'page id=0 file="font.png"' in fnt and "common lineHeight=4 base=3 scaleW=8 scaleH=4" in fnt
    assert "char id=69 x=4 y=0 width=4 height=4 xoffset=0 yoffset=0 xadvance=4" in fnt
    assert _manifest(project)["assets"]["font"]["font_file"] == "fonts/font.fnt"
    page = (tmp_path / "out" / "fonts" / "font.png").read_bytes()
    assert page == (tmp_path / "out" / "sprites" / "font.png").read_bytes()


def test_font_one_glyph_per_frame_and_fixed_advance(load: LoadFn) -> None:
    asset, findings = load("name: digits\nsize: [2, 2]\nfont: { glyphs: [\"0\", \"1\"] }\nframes:\n  a: |\n    11\n    11\n  b: |\n    .1\n    .1\n", "digits")
    assert asset is not None and asset.font is not None, [f.format() for f in findings]
    assert asset.font.glyphs == "01" and asset.font.cell == (2, 2) and asset.font.advance == 2


@pytest.mark.parametrize(
    "glyphs, message",
    [('"abc"', "has 3 characters but the frames hold 2"), ('"ll"', "repeats"), ('"l"', "drawn glyph cells past")],
)
def test_font_errors(load: LoadFn, glyphs: str, message: str) -> None:
    asset, findings = load(FONT.format(glyphs=glyphs), "font")
    assert asset is None and any(message in f.message for f in findings), [f.format() for f in findings]


def test_font_cell_must_divide_the_frame(load: LoadFn) -> None:
    asset, findings = load(FONT.format(glyphs='"lE"').replace("cell: [4, 4]", "cell: [3, 4]"), "font")
    assert asset is None and any("whole cells" in f.message for f in findings)


@needs_godot
def test_godot_loads_the_font(tmp_path: Path) -> None:
    project = _godot_project(tmp_path)
    (project.root / "sprites" / "font.sprite.yaml").write_text(FONT.format(glyphs='"lE"') + "lint: { disable: [W001] }\n")
    result = build(load_project(project.root))
    assert not result.errors, [f.format() for f in result.errors]
    assert GODOT is not None
    for _ in range(2):  # Godot's font importer claims its page image on the second import: the sheet must survive
        check = verify_with_godot(GODOT, tmp_path / "game", "res://gen/manifest.json")
        assert check.ok and check.fonts == 1 and check.sprite_frames == 3, check.output


# --- R22: animation order ---------------------------------------------------------------------------


def test_manifest_keeps_the_files_animation_order(tmp_path: Path) -> None:
    project = _built_project(tmp_path)
    (project.root / "sprites" / "hero.sprite.yaml").write_text(
        "name: hero\nsize: [2, 1]\nframes:\n  a: |\n    11\n  b: |\n    22\n"
        "animations:\n  walk: [a, b]\n  idle: [a]\n  attack: [b, a]\n"
    )
    entry = _manifest(project)["assets"]["hero"]
    assert entry["animation_order"] == ["walk", "idle", "attack"] and sorted(entry["animations"]) == sorted(entry["animation_order"])


# --- R23: build progress, parallel model rendering, Godot timeout --------------------------------------

BOAT = """\
name: boat
size: [40, 40]
pivot: [20, 26]
directions: 32
materials:
  wood: { ramp: red }
  cloth: { keys: ["6", "6"], two_sided: true }
parts:
  - hull: { from: [-8, 0, 0], length: 16, beam: 6, height: 3, material: wood }
  - cylinder: { base: [0, 0, 3], height: 9, material: wood }
  - sail: { at: [0, 0, 5], width: 7, height: 5, brace: 20, material: cloth, yard: wood }
"""


def test_parallel_rendering_is_identical(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    (project.root / "models").mkdir()
    path = project.root / "models" / "boat.model.yaml"
    path.write_text(BOAT)
    frames = {}
    for jobs in ("1", "3"):
        monkeypatch.setenv("PAGAN_JOBS", jobs)
        for cached in (project.root / ".pagan-cache").rglob("*.json"):
            cached.unlink()
        asset, findings = load_asset(path, project)
        assert asset is not None, [f.format() for f in findings]
        frames[jobs] = asset.frames
    assert frames["1"] == frames["3"] and len(frames["1"]) == 32


def test_progress_lines_on_stderr_only(project: Project, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAGAN_QUIET", raising=False)
    monkeypatch.setenv("PAGAN_JOBS", "1")
    (project.root / "models").mkdir()
    (project.root / "models" / "boat.model.yaml").write_text(BOAT.replace("directions: 32", "directions: 4"))
    monkeypatch.chdir(project.root)
    assert main(["lint", "--json"]) == 0
    captured = capsys.readouterr()
    json.loads(captured.out)  # stdout is still exactly one JSON document
    assert "pagan: rendering boat: 4 frames" in captured.err and "pagan: rendered boat in" in captured.err
    (project.root / "models" / "boat.model.yaml").write_text(BOAT.replace("directions: 32", "directions: 8"))
    assert main(["lint", "--quiet"]) == 0
    assert capsys.readouterr().err == ""
    assert main(["lint"]) == 0
    assert capsys.readouterr().err == ""  # cached: nothing slow to report


def test_godot_timeout_must_be_positive(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    project = _godot_project(tmp_path)
    monkeypatch.setenv("GODOT", "/nonexistent/godot")
    monkeypatch.chdir(project.root)
    assert main(["build", "--verify-godot", "--godot-timeout", "0"]) == 1
    assert "--godot-timeout must be 1 or more" in capsys.readouterr().out


# --- R24: tile animations on a new row ------------------------------------------------------------------

TILES = """\
name: shore
tile_size: [1, 1]
columns: 4
tiles:
  a: "1"
  b: "2"
  c: "3"
  w0: "4"
  w1: "5"
animations:
  water: {{ frames: [w0, w1]{new_row} }}
"""


def test_new_row_starts_a_tile_animation_at_column_zero(load: LoadFn) -> None:
    packed, _ = load(TILES.format(new_row=""), "shore", "tileset")
    fresh, findings = load(TILES.format(new_row=", new_row: true"), "shore", "tileset")
    assert packed is not None and fresh is not None, [f.format() for f in findings]
    assert tile_cells(packed)["w0"] == (0, 1)  # didn't fit after c: wraps anyway
    assert tile_cells(fresh)["w0"] == (0, 1) and tile_cells(fresh)["w1"] == (1, 1)
    shorter, _ = load(TILES.format(new_row=", new_row: true").replace("  c: \"3\"\n", ""), "shore", "tileset")
    plain, _ = load(TILES.format(new_row="").replace("  c: \"3\"\n", ""), "shore", "tileset")
    assert shorter is not None and plain is not None
    assert tile_cells(plain)["w0"] == (2, 0) and tile_cells(shorter)["w0"] == (0, 1)


def test_new_row_must_be_a_boolean(load: LoadFn) -> None:
    asset, findings = load(TILES.format(new_row=", new_row: 1"), "shore", "tileset")
    assert asset is None and any("new_row must be true" in f.message for f in findings)


# --- R25: tileset variant previews ------------------------------------------------------------------------


def test_variants_preview_skips_empty_tiles_and_takes_frame_and_scene(project: Project, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    text = "name: isle\ntile_size: [2, 2]\ntiles:\n  empty: |\n    ..\n    ..\n  land: |\n    12\n    21\nvariants:\n  arctic: { ramp_swap: { red: green } }\n"
    (project.root / "tiles" / "isle.tiles.yaml").write_text(text)
    (project.root / "scene.txt").write_text("land land\nempty land\n")
    monkeypatch.chdir(project.root)
    assert main(["preview", "tiles/isle.tiles.yaml", "--scene", "scene.txt", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)["outputs"][0]
    assert out["scene_variants"].endswith("scene_variants.png") and (project.root / out["scene_variants"]).is_file()
    from pagan.preview import representative_frame

    asset, _ = load_asset(project.root / "tiles" / "isle.tiles.yaml", project)
    assert asset is not None and representative_frame(asset) == "land"
    assert main(["preview", "tiles/isle.tiles.yaml", "--frame", "empty", "--json"]) == 0
    capsys.readouterr()
    assert main(["preview", "tiles/isle.tiles.yaml", "--frame", "nope", "--json"]) == 1
    assert "has no frame 'nope'" in capsys.readouterr().out


# --- R26: palette-wide variants -------------------------------------------------------------------------

ARCTIC = """\
variants:
  arctic: { ramp_swap: { green: red }, tags: [world] }
  night: { key_swap: { "6": "0" } }
base_variant: temperate
"""


def _palette_project(tmp_path: Path) -> Project:
    project = _built_project(tmp_path)
    palette = project.root / "palettes" / "test.pal.yaml"
    palette.write_text(palette.read_text() + ARCTIC)
    return load_project(project.root)


def test_palette_variants_reach_tagged_assets(tmp_path: Path) -> None:
    project = _palette_project(tmp_path)
    sprites = project.root / "sprites"
    (sprites / "tree.sprite.yaml").write_text("name: tree\ntags: [world]\nsize: [2, 1]\nframes:\n  a: |\n    36\n")
    (sprites / "coin.sprite.yaml").write_text("name: coin\nsize: [2, 1]\nframes:\n  a: |\n    36\n")
    (sprites / "rock.sprite.yaml").write_text(
        "name: rock\ntags: [world]\nsize: [2, 1]\nframes:\n  a: |\n    36\nvariants:\n  night: false\n  arctic: { key_swap: { \"3\": \"5\" } }\n"
    )
    assets = _manifest(project)["assets"]
    assert set(assets["tree"]["variants"]) == {"temperate", "arctic", "night"} and assets["tree"]["base_variant"] == "temperate"
    assert assets["tree"]["variants"]["arctic"]["swap"] == {"#00ff00": "#ff0000"}
    assert set(assets["coin"]["variants"]) == {"temperate", "night"}  # untagged: only the untagged variant
    assert set(assets["rock"]["variants"]) == {"temperate", "arctic"}  # night turned off, arctic its own
    assert assets["rock"]["variants"]["arctic"]["swap"] == {"#00ff00": "#0000ff"}


def test_palette_variants_reach_models(tmp_path: Path) -> None:
    project = _palette_project(tmp_path)
    (project.root / "models").mkdir()
    (project.root / "models" / "boat.model.yaml").write_text(BOAT.replace("directions: 32", "directions: 1"))
    asset, findings = load_asset(project.root / "models" / "boat.model.yaml", project)
    assert asset is not None and set(asset.variants) == {"night"} and asset.base_variant == "temperate", [f.format() for f in findings]


@pytest.mark.parametrize(
    "extra, message",
    [
        ("variants:\n  arctic: { ramp_swap: { green: blue } }\n", "same length"),
        ("variants:\n  arctic: { ramp_swap: { green: nope } }\n", "unknown ramp 'nope'"),
        ("variants:\n  arctic: { key_swap: { \"9\": \"0\" } }\n", "unknown key"),
        ("variants:\n  arctic: { palette: other }\n", "unknown palette variant field 'palette'"),
        ("variants:\n  arctic: { ramp_swap: { green: red } }\nbase_variant: arctic\n", "also a variant's name"),
        ("base_variant: day\n", "add variants or remove it"),
    ],
)
def test_palette_variant_errors(tmp_path: Path, extra: str, message: str) -> None:
    project = _built_project(tmp_path)
    palette = project.root / "palettes" / "test.pal.yaml"
    palette.write_text(palette.read_text() + extra)
    findings = lint_paths(load_project(project.root)).findings
    assert any(message in f.message for f in findings), [f.format() for f in findings]


def test_turning_off_a_variant_the_palette_lacks(tmp_path: Path) -> None:
    project = _palette_project(tmp_path)
    (project.root / "sprites" / "x.sprite.yaml").write_text("name: x\nsize: [1, 1]\nframes:\n  a: \"3\"\nvariants:\n  dusk: false\n")
    findings = lint_paths(project).findings
    assert any("has no variant 'dusk'" in f.message for f in findings)


# --- R27: 2D headings -------------------------------------------------------------------------------------


def test_rotate_points_turns_counter_clockwise_on_screen() -> None:
    assert api.rotate_points([(2.0, 0.0)], 90, (0.0, 0.0)) == [(0.0, -2.0)]  # east -> north (up the screen)
    assert api.rotate_points([(2.0, 1.0)], 180, (1.0, 1.0)) == [(0.0, 1.0)]


def test_directional_frames_match_model_heading_names() -> None:
    arrow = [(1.0, 2.0), (5.0, 3.0), (1.0, 4.0)]  # points east

    def draw(canvas: api.Canvas, angle: float) -> None:
        canvas.polygon(api.rotate_points(arrow, angle, (3.0, 3.0)), "1")

    frames = api.directional_frames(draw, (6, 6), 8)
    assert list(frames) == ["e", "ne", "n", "nw", "w", "sw", "s", "se"]
    assert frames["w"].rows() == api.Canvas.from_rows(frames["e"].rows()).flip("horizontal").rows()
    assert list(api.directional_frames(draw, (6, 6), 32))[:2] == ["h00", "h01"]
    text = api.sprite_yaml("arrow", (6, 6), frames)
    assert "  ne: |" in text
    with pytest.raises(ValueError):
        api.directional_frames(draw, (6, 6), 6)


# --- R28: preview writes 1x frames --------------------------------------------------------------------------


def test_preview_also_writes_native_frames(project: Project, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    (project.root / "sprites" / "dot.sprite.yaml").write_text("name: dot\nsize: [2, 1]\nframes:\n  a: |\n    12\n")
    monkeypatch.chdir(project.root)
    assert main(["preview", "dot", "--json"]) == 0
    native = json.loads(capsys.readouterr().out)["outputs"][0]["native"]
    assert any(p.endswith("native/frames/a.png") for p in native) and any(p.endswith("native/sheet.png") for p in native)
    from PIL import Image

    assert Image.open(project.root / "previews" / "dot" / "native" / "frames" / "a.png").size == (2, 1)


# --- R29: per-asset ramp budget -----------------------------------------------------------------------------


def test_lint_max_ramps_raises_one_assets_budget(tmp_path: Path) -> None:
    project = make_project(tmp_path, 'default_palette = "test"\n[lint]\nmax_ramps_per_sprite = 2\n')
    path = project.root / "sprites" / "kit.sprite.yaml"
    path.write_text("name: kit\nsize: [3, 1]\nframes:\n  a: |\n    135\n")
    w003 = [f for f in lint_paths(project).findings if f.rule == "W003"]
    assert w003 and "lint: { max_ramps: N }" in w003[0].message
    path.write_text(path.read_text() + "lint: { max_ramps: 3 }\n")
    assert "W003" not in rules(lint_paths(project).findings)
    path.write_text(path.read_text().replace("max_ramps: 3", "max_ramps: 1"))
    w003 = [f for f in lint_paths(project).findings if f.rule == "W003"]
    assert w003 and "this asset's lint.max_ramps is 1" in w003[0].message
    path.write_text(path.read_text().replace("max_ramps: 1", "max_ramps: 0"))
    asset, findings = load_asset(path, project)
    assert asset is None and any("lint.max_ramps must be" in f.message for f in findings)


def test_shared_cache_dir_serves_another_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("PAGAN_CACHE_DIR", str(tmp_path / "shared"))
    monkeypatch.delenv("PAGAN_QUIET", raising=False)
    for checkout in ("main", "worktree"):
        (tmp_path / checkout).mkdir()
        project = make_project(tmp_path / checkout)
        (project.root / "models").mkdir()
        (project.root / "models" / "boat.model.yaml").write_text(BOAT.replace("directions: 32", "directions: 4"))
        monkeypatch.chdir(project.root)
        assert main(["lint"]) == 0
    err = capsys.readouterr().err
    assert err.count("rendering boat") == 1  # the second checkout reused the first one's render
    assert not (tmp_path / "worktree" / ".pagan-cache").exists()
    for directions in (8, 16):  # other versions of the model are kept side by side in a shared cache
        (tmp_path / "worktree" / "models" / "boat.model.yaml").write_text(BOAT.replace("directions: 32", f"directions: {directions}"))
        assert main(["lint", "--quiet"]) == 0
    assert len(list((tmp_path / "shared" / "models").glob("boat-*.json"))) == 3


@needs_godot
def test_verify_godot_accepts_a_swap_only_base_variant(tmp_path: Path) -> None:
    # variant_sheets = false + base_variant: the base's entry under variants has no sheet and an empty swap.
    project = _godot_project(tmp_path, extra="", sheets=False)
    path = project.root / "sprites" / "flag.sprite.yaml"
    path.write_text("base_variant: red\n" + path.read_text())
    result = build(load_project(project.root))
    assert not result.errors, [f.format() for f in result.errors]
    assert GODOT is not None
    check = verify_with_godot(GODOT, tmp_path / "game", "res://gen/manifest.json")
    assert check.ok, check.output
