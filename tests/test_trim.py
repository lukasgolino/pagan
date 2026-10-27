"""#1 (R30a): `trim: true` crops sprite frames to their content and packs the crops into the sheet."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from conftest import make_project
from pagan.build import build
from pagan.lint import lint_paths
from pagan.project import Project, load_project
from pagan.render import content_box, downsample, frame_image
from pagan.settings import BY_KEY, set_setting

SPARK = """\
name: spark
size: [6, 4]
{extra}frames:
  a: |
    ......
    ..11..
    ..12..
    ......
  b: |
    1.....
    ......
    ......
    .....2
  empty: |
    ......
    ......
    ......
    ......
animations:
  burst: {{ frames: [a, b, empty], fps: 8 }}
"""


def _project(root: Path, config: str = "") -> Project:
    root.mkdir(parents=True, exist_ok=True)
    return make_project(root, f'default_palette = "test"\noutput_dir = "out"\n{config}')


def _build(project: Project) -> dict[str, Any]:
    result = build(project)
    assert not result.errors and result.manifest is not None, [f.format() for f in result.errors]
    manifest: dict[str, Any] = json.loads(result.manifest.read_text())
    return manifest


def _outputs(project: Project) -> dict[str, bytes]:
    out = project.root / "out"
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}


def _pixels(path: Path) -> Any:
    return np.array(Image.open(path).convert("RGBA"))


def test_untrimmed_output_is_unchanged(tmp_path: Path) -> None:
    """No `trim`, `trim: false` and `[build] trim = false` all build exactly what an untrimmed sprite builds."""
    builds = []
    for i, (extra, config) in enumerate((("", ""), ("trim: false\n", ""), ("", "[build]\ntrim = false\n"), ("trim: false\n", "[build]\ntrim = true\n"))):
        project = _project(tmp_path / str(i), config)
        (project.root / "sprites" / "spark.sprite.yaml").write_text(SPARK.format(extra=extra))
        manifest = _build(project)
        assert "trim" not in manifest["assets"]["spark"]
        assert manifest["assets"]["spark"]["frames"]["b"] == [6, 0, 6, 4]
        builds.append(_outputs(project))
    assert all(b == builds[0] for b in builds)


def test_trimmed_frames_are_packed_with_full_logical_size(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project.root / "sprites" / "spark.sprite.yaml").write_text(SPARK.format(extra="trim: true\n"))
    manifest = _build(project)
    entry = manifest["assets"]["spark"]
    assert entry["trim"] is True and entry["size"] == [6, 4]
    assert entry["frames"] == {
        "a": {"size": [6, 4], "trim_rect": [0, 0, 2, 2], "offset": [2, 1]},
        "b": {"size": [6, 4], "trim_rect": [3, 0, 6, 4], "offset": [0, 0]},  # 1 px gap after a
        "empty": {"size": [6, 4], "trim_rect": [10, 0, 1, 1], "offset": [0, 0]},  # transparent: its top-left pixel
    }
    sheet = _pixels(project.root / "out" / "sprites" / "spark.png")
    assert sheet.shape == (4, 11, 4)
    asset = lint_paths(project).assets[0]
    for name, frame in entry["frames"].items():
        x, y, w, h = frame["trim_rect"]
        ox, oy = frame["offset"]
        full = np.array(frame_image(asset, name))
        assert (sheet[y : y + h, x : x + w] == full[oy : oy + h, ox : ox + w]).all()
        rest = full.copy()
        rest[oy : oy + h, ox : ox + w] = 0
        assert not rest[..., 3].any()  # nothing outside the crop was lost
    assert not sheet[:, 2, 3].any() and not sheet[:, 9, 3].any()  # the gaps stay transparent
    before = _outputs(project)
    assert not build(project).written and _outputs(project) == before  # deterministic: a rebuild changes nothing


def test_godot_atlas_textures_get_margins(tmp_path: Path) -> None:
    from pagan.exporters.godot import sprite_frames_tres
    from pagan.asset import Animation

    text = sprite_frames_tres("res://s.png", {"a": (3, 0, 2, 2)}, [Animation("a", ("a",), 8.0, True)], margins={"a": (2, 1, 4, 2)})
    # Godot 4.7.2's ResourceSaver writes margin right after region; size = region size + margin size
    assert 'region = Rect2(3, 0, 2, 2)\nmargin = Rect2(2, 1, 4, 2)\n\n' in text
    assert "margin" not in sprite_frames_tres("res://s.png", {"a": (3, 0, 2, 2)}, [Animation("a", ("a",), 8.0, True)])


def test_sheet_columns_sets_crops_per_row(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project.root / "sprites" / "spark.sprite.yaml").write_text(SPARK.format(extra="trim: true\nsheet_columns: 2\n"))
    frames = _build(project)["assets"]["spark"]["frames"]
    assert frames["a"]["trim_rect"] == [0, 0, 2, 2]
    assert frames["b"]["trim_rect"] == [3, 0, 6, 4]
    assert frames["empty"]["trim_rect"] == [0, 5, 1, 1]  # below the tallest crop of row 1, plus the gap


def test_project_default_trims_sprites_except_fonts_and_nine_slice(tmp_path: Path) -> None:
    project = _project(tmp_path, "[build]\ntrim = true\n")
    sprites = project.root / "sprites"
    (sprites / "spark.sprite.yaml").write_text(SPARK.format(extra=""))
    (sprites / "panel.sprite.yaml").write_text("name: panel\nsize: [3, 3]\nnine_slice: [1, 1, 1, 1]\nframes:\n  main: |\n    ...\n    .1.\n    ...\n")
    (sprites / "glyphs.sprite.yaml").write_text("name: glyphs\nsize: [3, 3]\nfont: { glyphs: A }\nframes:\n  A: |\n    ...\n    .1.\n    ...\n")
    (project.root / "tiles" / "ground.tiles.yaml").write_text("name: ground\ntile_size: [2, 2]\ntiles:\n  g: |\n    1.\n    ..\n")
    assets = _build(project)["assets"]
    assert assets["spark"]["trim"] is True
    for name in ("panel", "glyphs", "ground"):
        assert "trim" not in assets[name] and isinstance(assets[name]["frames"]["main" if name == "panel" else ("A" if name == "glyphs" else "g")], list)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("trim: yes please\n", "true or false"),
        ("trim: true\nfont: { glyphs: A }\n", "font"),
        ("trim: true\nnine_slice: [1, 1, 1, 1]\n", "nine_slice"),
    ],
)
def test_trim_errors(tmp_path: Path, body: str, message: str) -> None:
    project = _project(tmp_path)
    (project.root / "sprites" / "x.sprite.yaml").write_text(f"name: x\nsize: [3, 3]\n{body}frames:\n  A: |\n    ...\n    .1.\n    ...\n")
    errors = lint_paths(project).errors
    assert [f.rule for f in errors] == ["E001"] and message in errors[0].message and errors[0].where == "trim"


def test_trim_isnt_a_tileset_field_and_build_table_is_checked(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project.root / "tiles" / "ground.tiles.yaml").write_text("name: ground\ntile_size: [2, 2]\ntrim: true\ntiles:\n  g: |\n    1.\n    ..\n")
    assert [f.rule for f in lint_paths(project).errors] == ["E001"]
    from pagan.findings import PaganError

    (tmp_path / "pagan.toml").write_text('default_palette = "test"\n[build]\ntrim = 1\ncrop = true\n')
    with pytest.raises(PaganError) as raised:
        load_project(tmp_path)
    assert {f.where for f in raised.value.findings} == {"build.trim", "build.crop"}


def test_supersample_crops_on_output_pixels(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project.root / "sprites" / "dot.sprite.yaml").write_text(
        "name: dot\nsize: [8, 4]\nsupersample: 2\ntrim: true\nframes:\n  a: |\n    ........\n    ...1....\n    ....2...\n    ........\n"
    )
    entry = _build(project)["assets"]["dot"]
    # source pixels x 3-4, y 1-2 -> output pixels x 1-2, y 0-1 (rounded outwards)
    assert entry["frames"]["a"] == {"size": [4, 2], "trim_rect": [0, 0, 2, 2], "offset": [1, 0]}
    asset = lint_paths(project).assets[0]
    full = np.array(downsample(frame_image(asset, "a"), 2))
    assert (_pixels(project.root / "out" / "sprites" / "dot.png") == full[0:2, 1:3]).all()


def test_content_box() -> None:
    assert content_box(("....", ".1..", "..1.", "....")) == (1, 1, 2, 2)
    assert content_box(("....", ".1..", "..1.", "...."), 2) == (0, 0, 2, 2)
    assert content_box(("...", "...")) == (0, 0, 1, 1)


def test_variants_share_the_layout_and_points_stay_logical(tmp_path: Path) -> None:
    project = _project(tmp_path)
    extra = 'trim: true\npoints:\n  tip: { a: [3, 1] }\nvariants:\n  green: { key_swap: { "1": "3", "2": "4" } }\n'
    (project.root / "sprites" / "spark.sprite.yaml").write_text(SPARK.format(extra=extra))
    entry = _build(project)["assets"]["spark"]
    assert entry["points"] == {"tip": {"a": [3, 1]}}
    base = _pixels(project.root / "out" / "sprites" / "spark.png")
    green = _pixels(project.root / "out" / "sprites" / "spark.green.png")
    assert base.shape == green.shape and (base[..., 3] == green[..., 3]).all()
    assert tuple(green[0, 0, :3]) == (0, 255, 0)


def test_w014_measures_the_packed_sheet(tmp_path: Path) -> None:
    project = _project(tmp_path)
    row = "1" + "." * 4095
    body = "".join(f"  f{i}: |\n    {row}\n" for i in range(5))
    path = project.root / "sprites" / "wide.sprite.yaml"
    path.write_text(f"name: wide\nsize: [4096, 1]\nlint: {{ disable: [W001] }}\nframes:\n{body}")
    assert [f.rule for f in lint_paths(project).warnings] == ["W014"]
    path.write_text(f"name: wide\nsize: [4096, 1]\ntrim: true\nlint: {{ disable: [W001] }}\nframes:\n{body}")
    assert not lint_paths(project).findings


def test_build_trim_setting_is_registered(tmp_path: Path) -> None:
    assert BY_KEY["build.trim"].default is False and BY_KEY["build.trim"].refresh == "build"
    project = _project(tmp_path)
    set_setting(project, "build.trim", "true")
    assert load_project(project.root).config.build.trim is True
