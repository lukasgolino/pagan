"""#29/#36: the exact pixel dimetric camera (`[camera] projection = "dimetric"`, `tile`, `cell`, `z_step`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_project
from pagan.asset import Asset, load_asset
from pagan.findings import Finding, PaganError
from pagan.lint import lint_paths
from pagan.project import Project
from pagan.settings import set_setting
from pagan.voxel import Camera

DIMETRIC = 'default_palette = "test"\n[camera]\nprojection = "dimetric"\n'
DIAMOND = [*range(2, 63, 4), *range(62, 1, -4)]  # the hand-drawn 64x32 tile: 32 rows, widest row doubled

FLOOR = """\
name: floor
size: [{w}, {h}]
pivot: [{px}, {py}]
directions: 4
heading: 45
outline: none
materials:
  a: {{ keys: ["3"] }}
  b: {{ keys: ["5"] }}
parts:
{parts}
"""


def load(project: Project, text: str, name: str) -> tuple[Asset | None, list[Finding]]:
    (project.root / "models").mkdir(exist_ok=True)
    path = project.root / "models" / f"{name}.model.yaml"
    path.write_text(text.replace("name: floor\n", f"name: {name}\n"))
    return load_asset(path, project)


def ok(result: tuple[Asset | None, list[Finding]]) -> Asset:
    asset, findings = result
    assert asset is not None, [f.format() for f in findings]
    return asset


def mask(grid: tuple[str, ...], key: str | None = None) -> set[tuple[int, int]]:
    return {(x, y) for y, row in enumerate(grid) for x, c in enumerate(row) if (c != "." if key is None else c == key)}


@pytest.fixture
def dimetric(tmp_path: Path) -> Project:
    return make_project(tmp_path, DIMETRIC)


def test_one_floor_cell_is_the_hand_drawn_diamond(dimetric: Project) -> None:
    # A 3x3-cell floor whose middle cell has its own colour: that cell shows only its top face.
    parts = "  - box: { from: [0, 0, 0], to: [47, 47, 0], material: a }\n  - box: { from: [16, 16, 0], to: [31, 31, 0], material: b }"
    asset = ok(load(dimetric, FLOOR.format(w=200, h=110, px=100, py=60, parts=parts), "floor"))
    assert list(asset.frames) == ["ne", "nw", "sw", "se"]
    for frame in asset.frames.values():
        cell = mask(frame, "5")
        rows = sorted({y for _, y in cell})
        assert [sum(1 for _, y in cell if y == r) for r in rows] == DIAMOND
        assert rows == list(range(rows[0], rows[0] + 32))
        for r in rows:  # each row is one run, centred on the tile's middle column
            xs = sorted(x for x, y in cell if y == r)
            assert xs == list(range(xs[0], xs[-1] + 1)) and xs[0] + xs[-1] + 1 == 2 * 100
        # Copies at the tile pitch (32 px across, 16 down) never overlap and leave no holes.
        seen: set[tuple[int, int]] = set()
        for i in range(-2, 3):
            for j in range(-2, 3):
                moved = {(x + (i - j) * 32, y + (i + j) * 16) for x, y in cell}
                assert not moved & seen
                seen |= moved
        top = rows[0]
        assert {(x, y) for x in range(100 - 32, 100 + 32) for y in range(top, top + 32)} <= seen


def test_one_cell_tiles_at_the_tile_pitch_with_no_gaps_or_overlap(dimetric: Project) -> None:
    """One-cell slabs placed at the 32/16 px pitch cover exactly what one 4x4-cell floor covers."""
    one = ok(load(dimetric, FLOOR.format(w=80, h=48, px=40, py=24, parts="  - box: { from: [0, 0, 0], to: [15, 15, 0], material: a }"), "one"))
    big = ok(load(dimetric, FLOOR.format(w=270, h=150, px=135, py=75, parts="  - box: { from: [0, 0, 0], to: [63, 63, 0], material: a }"), "big"))
    tile = mask(one.frames["ne"])
    covered: set[tuple[int, int]] = set()
    # Cell (i, j)'s centre is (16 i - 24, 16 j - 24) voxels from the big floor's: x/y step (2, -1) and (-2, -1) px.
    for i in range(4):
        for j in range(4):
            dx, dy = 135 - 40 + (i - j) * 32, 75 - 24 + 48 - (i + j) * 16
            covered |= {(x + dx, y + dy) for x, y in tile}
    assert covered == mask(big.frames["ne"])


def walker(name: str, cam: str = "") -> str:
    return f"""\
name: {name}
size: [64, 96]
pivot: [32, 80]
directions: 4
heading: 45
{cam}light: {{ shadows: false }}
materials:
  body: {{ ramp: red }}
  gem: {{ ramp: green }}
parts:
  - box: {{ from: [-2, -3, 0], to: [1, 2, 7], material: body }}
  - box: {{ from: [-2, -2, 12], to: [1, 1, 15], material: gem }}
    id: head
animations:
  bob:
    fps: 6
    poses:
      - {{}}
      - {{ head: {{ offset: [0, 0, 1] }} }}
"""


def head_pixels(grid: tuple[str, ...]) -> dict[tuple[int, int], str]:
    return {(x, y): c for y, row in enumerate(grid) for x, c in enumerate(row) if c in "34"}


@pytest.mark.parametrize("z_step", [0, 3])
def test_one_voxel_bob_moves_whole_pixels(tmp_path: Path, z_step: int) -> None:
    """#36: a 1-voxel z offset moves the part exactly z_step px (default 2 for a 64x32 tile, cell 16)."""
    project = make_project(tmp_path, DIMETRIC + f"z_step = {z_step}\n")
    asset = ok(load(project, walker("w"), "w"))
    step = z_step or 2
    for d in ("ne", "nw", "sw", "se"):
        a, b = asset.base_frames[f"bob_{d}_0"], asset.base_frames[f"bob_{d}_1"]
        assert head_pixels(b) == {(x, y - step): c for (x, y), c in head_pixels(a).items()}
        assert mask(a, "1") | mask(a, "2") == mask(b, "1") | mask(b, "2")  # the body stays put
    findings = lint_paths(project, [project.root / "models" / "w.model.yaml"]).findings
    assert not [f for f in findings if f.rule == "W007"]


def test_orthographic_one_voxel_bob_is_a_fraction_of_a_pixel(tmp_path: Path) -> None:
    """The #36 report: at elevation 30 a voxel of height is cos(30) px x scale, so the moved part re-rasterises."""
    project = make_project(tmp_path, 'default_palette = "test"\n[camera]\nelevation = 30\nscale = 2.83\n')
    asset = ok(load(project, walker("w"), "w"))
    a, b = asset.base_frames["bob_ne_0"], asset.base_frames["bob_ne_1"]
    assert all(head_pixels(b) != {(x, y - s): c for (x, y), c in head_pixels(a).items()} for s in range(4))


def test_dimetric_allows_only_the_diagonal_headings(dimetric: Project) -> None:
    parts = "  - box: { from: [0, 0, 0], to: [3, 3, 3], material: a }"
    base = FLOOR.format(w=40, h=40, px=20, py=24, parts=parts)
    for bad in (base.replace("heading: 45\n", ""), base.replace("directions: 4", "directions: 8"), base.replace("heading: 45", "heading: 30")):
        asset, findings = load(dimetric, bad, "floor")
        assert asset is None and any(f.rule == "E013" and "diagonal headings" in f.message for f in findings)
    assert list(ok(load(dimetric, base.replace("directions: 4", "directions: 1").replace("heading: 45", "heading: 225"), "floor")).frames) == ["main"]
    assert ok(load(dimetric, base.replace("directions: 4", "directions: 0").replace("heading: 45", "heading: 10"), "floor")).frames == {}


def test_model_may_switch_to_dimetric(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    cam = "camera: { projection: dimetric, tile: [32, 16], cell: 8 }\n"
    asset = ok(load(project, FLOOR.format(w=48, h=32, px=24, py=16, parts="  - box: { from: [0, 0, 0], to: [7, 7, 0], material: a }").replace("parts:", cam + "parts:"), "floor"))
    rows = [r.count("3") for r in asset.frames["ne"] if "3" in r]
    assert rows[:8] == list(range(2, 31, 4))  # the upper half of a 32x16 diamond (the slab's sides start below)


@pytest.mark.parametrize(
    ("toml", "where"),
    [
        ('projection = "iso"', "camera.projection"),
        ("tile = [64, 30]", "camera.tile"),
        ("tile = [64, 32, 1]", "camera.tile"),
        ("tile = [6, 3]", "camera.tile"),
        ("cell = 32", "camera.cell"),
        ("cell = 3", "camera.cell"),
        ("cell = 0", "camera.cell"),
        ("z_step = -1", "camera.z_step"),
        ("z_step = 1.5", "camera.z_step"),
    ],
)
def test_bad_dimetric_settings(tmp_path: Path, toml: str, where: str) -> None:
    with pytest.raises(PaganError) as raised:
        make_project(tmp_path, f"[camera]\n{toml}\n")
    assert [f.where for f in raised.value.findings] == [where]


def test_config_set_dimetric(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    assert set_setting(project, "camera.projection", "dimetric").refresh == "models"
    assert set_setting(project, "camera.tile", "[128, 64]").new == [128, 64]
    with pytest.raises(PaganError):
        set_setting(project, "camera.cell", "64")  # 64 / 2 / 64 isn't a whole pixel step


def test_cache_key_keeps_orthographic_and_tracks_dimetric() -> None:
    # Orthographic keys are what they were before dimetric existed, so existing caches stay valid.
    assert Camera(30.0, 2.0).cache_key() == {"elevation": 30.0, "scale": 2.0}
    keys = [Camera(projection="dimetric", **kw).cache_key() for kw in ({}, {"tile": (128, 64)}, {"cell": 8}, {"z_step": 3})]
    assert len({str(k) for k in keys}) == 4
    assert Camera(projection="dimetric").cache_key() == Camera(projection="dimetric", z_step=2).cache_key()  # 0 = auto = 2


def test_fit_sizes_dimetric_frames(dimetric: Project) -> None:
    from pagan.model import fit_model

    ok(load(dimetric, walker("w"), "w"))
    fit, findings = fit_model(dimetric.root / "models" / "w.model.yaml", dimetric)
    assert fit is not None and not fit.clipped, [f.format() for f in findings]
    # 8 x 6 voxels across the diagonal (2 px each way) and 16 tall (2 px each), + the outline
    assert fit.size[0] <= 32 and fit.size[1] <= 52
