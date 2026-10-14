"""3D voxel models: primitives, rendering, poses (frame consistency), caching, errors, CLI."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from PIL import Image

from conftest import LoadFn, make_project
from pagan.asset import Asset, load_asset_or_raise
from pagan.cli import main
from pagan.findings import Finding
from pagan.lint import frame_change, lint_paths
from pagan.model import _Builder
from pagan.project import Project, load_project
from pagan.render import save_png, sheet_image
from pagan.voxel import Material, VoxelModel

GOLDEN = Path(__file__).parent / "fixtures" / "golden"
UPDATE = os.environ.get("PAGAN_UPDATE_GOLDEN") == "1"

CUBE = """\
name: cube
size: [24, 24]
pivot: [12, 16]
directions: {directions}
materials:
  red: {{ ramp: red }}
parts:
  - box: {{ from: [-3, -3, 0], to: [3, 3, 6], material: red }}
"""


def load_model(project: Project, text: str, name: str = "cube") -> tuple[Asset | None, list[Finding]]:
    from pagan.asset import load_asset

    (project.root / "models").mkdir(exist_ok=True)
    path = project.root / "models" / f"{name}.model.yaml"
    path.write_text(text)
    return load_asset(path, project)


def ok(result: tuple[Asset | None, list[Finding]]) -> Asset:
    asset, findings = result
    assert asset is not None, [f.format() for f in findings]
    return asset


def rules(result: tuple[Asset | None, list[Finding]]) -> list[str]:
    asset, findings = result
    assert asset is None
    return [f.rule for f in findings]


def silhouette(grid: tuple[str, ...]) -> set[tuple[int, int]]:
    return {(x, y) for y, row in enumerate(grid) for x, c in enumerate(row) if c != "."}


def test_directions_and_frame_names(project: Project) -> None:
    asset = ok(load_model(project, CUBE.format(directions=8)))
    assert asset.kind == "model"
    assert list(asset.frames) == ["e", "ne", "n", "nw", "w", "sw", "s", "se"]
    assert list(asset.animations) == ["e", "ne", "n", "nw", "w", "sw", "s", "se"]
    assert ok(load_model(project, CUBE.format(directions=1))).frames.keys() == {"main"}


def test_square_box_has_the_same_silhouette_every_quarter_turn(project: Project) -> None:
    asset = ok(load_model(project, CUBE.format(directions=4)))
    shapes = [silhouette(asset.frames[d]) for d in ("e", "n", "w", "s")]
    assert all(shape == shapes[0] for shape in shapes)
    assert shapes[0]


def test_lighting_uses_the_ramp_and_outline(project: Project) -> None:
    asset = ok(load_model(project, CUBE.format(directions=1)))
    used = {c for row in asset.base_frames["main"] for c in row if c != "."}
    assert used <= {"1", "2"} and len(used) == 2  # top lit, sides darker
    assert asset.outline and asset.outline_color == "0"
    assert any("0" in row for row in asset.frames["main"])


def test_render_is_deterministic_and_cached(project: Project) -> None:
    first = ok(load_model(project, CUBE.format(directions=8)))
    cache = list((project.root / ".pagan-cache" / "models").glob("cube-*.json"))
    assert len(cache) == 1
    second = ok(load_model(project, CUBE.format(directions=8)))
    assert first.frames == second.frames
    shutil.rmtree(project.root / ".pagan-cache")
    third = ok(load_model(project, CUBE.format(directions=8)))
    assert first.frames == third.frames
    # A change to the file invalidates the cache and replaces the stale entry.
    ok(load_model(project, CUBE.format(directions=4)))
    assert len(list((project.root / ".pagan-cache" / "models").glob("cube-*.json"))) == 1


def test_poses_move_only_their_part(project: Project) -> None:
    asset = load_asset_or_raise(GOLDEN / "models" / "crate.model.yaml", load_project(GOLDEN))
    assert list(asset.animations["bob_e"].frames) == ["bob_e_0", "bob_e_1"]
    a, b = asset.frames["bob_e_0"], asset.frames["bob_e_1"]
    assert a == asset.frames["e"]  # the empty pose is the static frame
    changed = {(x, y) for y, (ra, rb) in enumerate(zip(a, b)) for x, (pa, pb) in enumerate(zip(ra, rb)) if pa != pb}
    # Only the knob and the shadow it casts on the lid change; the crate's body stays pixel-identical.
    assert changed
    knob = silhouette(a) ^ silhouette(b) | {p for p in changed if a[p[1]][p[0]] != "." and b[p[1]][p[0]] != "."}
    xs, ys = [x for x, _ in knob], [y for _, y in knob]
    assert max(xs) - min(xs) <= 8 and max(ys) <= 18
    change, _ = frame_change(a, b)
    assert change < 0.2


def test_mirror_and_layers_orientation() -> None:
    model = VoxelModel()
    errors: list[str] = []
    builder = _Builder(model, lambda *a: errors.append(str(a)), {"m": Material("m", ("1",))})
    builder.build(
        [
            {"box": {"from": [0, 2, 0], "to": [0, 2, 0], "material": "m"}, "mirror": True},
            {"layers": {"at": [10, 5, 0], "legend": {"x": "m"}, "grids": ["x.\n.x", "x"]}},
        ],
        None,
    )
    assert not errors
    assert {(0, 2, 0), (0, -2, 0)} <= model.voxels.keys()
    # Layer grids are seen from above with the front (+x) to the right: rows step towards -y.
    assert {(10, 5, 0), (11, 4, 0), (10, 5, 1)} <= model.voxels.keys()
    assert (11, 5, 0) not in model.voxels


def test_carve(project: Project) -> None:
    text = CUBE.format(directions=1) + "  - box: { from: [-3, -3, 4], to: [3, 3, 6], material: red }\n    carve: true\n"
    carved = ok(load_model(project, text))
    full = ok(load_model(project, CUBE.format(directions=1)))
    assert len(silhouette(carved.base_frames["main"])) < len(silhouette(full.base_frames["main"]))


def test_sail_and_hull_and_line_build(project: Project) -> None:
    text = """\
name: boat
size: [64, 64]
pivot: [32, 40]
directions: 4
materials:
  wood: { ramp: red }
  cloth: { keys: ["6", "6"], two_sided: true }
parts:
  - hull: { from: [-10, 0, 0], length: 20, beam: 8, height: 3, material: wood }
  - cylinder: { base: [0, 0, 3], height: 12, material: wood }
  - sail: { at: [0, 0, 5], width: 8, height: 6, brace: 20, material: cloth, yard: wood }
  - line: { from: [10, 0, 3], to: [14, 0, 5], material: wood }
  - ellipsoid: { center: [-8, 0, 4], radii: [1.5, 1.5, 1.5], material: wood }
"""
    asset = ok(load_model(project, text, "boat"))
    assert all(silhouette(grid) for grid in asset.frames.values())


@pytest.mark.parametrize(
    "parts, rule",
    [
        ("  - box: { from: [0, 0, 0], to: [1, 1, 1], material: nope }\n", "E013"),
        ("  - pyramid: { size: 3 }\n", "E013"),
        ("  - box: { from: [0, 0], to: [1, 1, 1], material: red }\n", "E013"),
        ("  - box: { from: [0, 0, 0], to: [1, 1, 1], material: red, colour: x }\n", "E013"),
        ("  - box: { from: [0, 0, 0], to: [1, 1, 1], material: red }\n    carve: true\n", "E013"),
    ],
)
def test_part_errors(project: Project, parts: str, rule: str) -> None:
    text = "name: cube\nsize: [24, 24]\nmaterials:\n  red: { ramp: red }\nparts:\n" + parts
    assert rule in rules(load_model(project, text))


def test_material_errors(project: Project) -> None:
    base = "name: cube\nsize: [24, 24]\nparts:\n  - box: { from: [0, 0, 0], to: [1, 1, 1], material: red }\n"
    assert "E013" in rules(load_model(project, base + "materials:\n  red: { ramp: nope }\n"))
    assert "E005" in rules(load_model(project, base + 'materials:\n  red: { keys: ["z"] }\n'))


def test_other_model_errors(project: Project) -> None:
    assert "E013" in rules(load_model(project, CUBE.format(directions=3)))
    assert "E013" in rules(load_model(project, CUBE.format(directions=1) + "animations:\n  x: { poses: [{ nope: { offset: [0, 0, 1] } }] }\n"))
    # A model too big for its frame would have its outline clipped.
    assert "E007" in rules(load_model(project, CUBE.format(directions=1).replace("size: [24, 24]", "size: [8, 8]").replace("pivot: [12, 16]", "pivot: [4, 4]")))


def test_project_camera_and_light(tmp_path: Path) -> None:
    (tmp_path / "flat").mkdir()
    project = make_project(
        tmp_path / "flat",
        'default_palette = "test"\n[camera]\nelevation = 90\nscale = 2\n[light]\nambient = 0.9\nshadows = false\n',
    )
    asset = ok(load_model(project, CUBE.format(directions=1)))
    # Straight down at 2px per voxel: a 7x7 box top becomes a 14x14 square, all one shade.
    pixels = silhouette(asset.base_frames["main"])
    assert len(pixels) == 14 * 14
    assert {c for row in asset.base_frames["main"] for c in row if c != "."} == {"2"}


def test_bad_camera_config(tmp_path: Path) -> None:
    from pagan.findings import PaganError

    (tmp_path / "bad").mkdir()
    with pytest.raises(PaganError):
        make_project(tmp_path / "bad", "[camera]\nelevation = 5\n")


def test_golden_model_sheet() -> None:
    asset = load_asset_or_raise(GOLDEN / "models" / "crate.model.yaml", load_project(GOLDEN))
    image = sheet_image(asset)
    expected_path = GOLDEN / "expected" / "crate.png"
    if UPDATE:
        save_png(image, expected_path)
    expected = Image.open(expected_path)
    assert image.size == expected.size and image.tobytes() == expected.tobytes()


def test_model_lints_with_project(project: Project) -> None:
    load_model(project, CUBE.format(directions=4))
    assert not lint_paths(project).errors


def test_cli_new_model_and_bake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, load: LoadFn) -> None:
    make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["new", "model", "barrel", "--size", "32x32", "--directions", "4"]) == 0
    assert main(["lint"]) == 0
    assert main(["bake", "barrel", "--name", "barrel_flat"]) == 0
    baked = load_asset_or_raise(tmp_path / "sprites" / "barrel_flat.sprite.yaml", load_project(tmp_path))
    model = load_asset_or_raise(tmp_path / "models" / "barrel.model.yaml", load_project(tmp_path))
    assert baked.frames == model.frames
    assert list(baked.animations) == list(model.animations)
    assert main(["bake", "barrel", "--name", "barrel_flat"]) == 1  # exists
    assert main(["preview", "barrel"]) == 0
