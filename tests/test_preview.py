"""Previews: upscaling, contact sheets, GIFs, change views, gallery, and the W007 frame-change metric."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from pagan.asset import Asset, load_asset_or_raise
from pagan.lint import frame_change
from pagan.preview import CHANGED, REMOVED, PreviewOptions, auto_scale, change_image, gallery, upscale, write_previews
from pagan.project import load_project
from pagan.render import frame_image

GOLDEN = Path(__file__).parent / "fixtures" / "golden"


def bug() -> Asset:
    return load_asset_or_raise(GOLDEN / "sprites" / "bug.sprite.yaml", load_project(GOLDEN))


def test_auto_scale() -> None:
    assert auto_scale((16, 16)) == 16
    assert auto_scale((32, 24)) == 8
    assert auto_scale((96, 96)) == 2
    assert auto_scale((1000, 10)) == 1


def test_upscale_is_nearest_neighbour_on_background() -> None:
    image = frame_image(bug(), "walk_0")
    big = upscale(image, 4, PreviewOptions(background="#ff0000"))
    assert big.size == (36, 36)
    assert big.getpixel((0, 0)) == (255, 0, 0, 255)  # transparent corner shows the background
    x, y = 4 * 4 + 1, 4 * 4 + 1  # inside native pixel (4, 4), an opaque body pixel
    assert big.getpixel((x, y)) == image.getpixel((4, 4))


def test_change_image_marks_changed_and_removed() -> None:
    asset = bug()
    diff = change_image(asset, "walk_0", "walk_1")  # walk_1 is walk_0 moved up 1px
    colors = {c for _, c in diff.getcolors(maxcolors=4096) or []}
    assert CHANGED in colors and REMOVED in colors
    assert change_image(asset, "walk_0", "walk_0").getcolors(maxcolors=4096) is not None
    same = {c for _, c in change_image(asset, "walk_0", "walk_0").getcolors(maxcolors=4096) or []}
    assert CHANGED not in same and REMOVED not in same


def test_frame_change_ignores_pure_movement() -> None:
    asset = bug()
    change, shift = frame_change(asset.frames["walk_0"], asset.frames["walk_1"])
    assert change == 0.0 and shift == (0, -1)
    change, shift = frame_change(asset.frames["walk_0"], asset.frames["walk_0"])
    assert change == 0.0 and shift == (0, 0)
    change, _ = frame_change(("11", ".."), ("..", "22"))
    assert change > 0.9  # different colors even after moving


def test_write_previews(tmp_path: Path) -> None:
    result = write_previews(bug(), tmp_path, PreviewOptions(scale=4, grid=True))
    assert result.sheet == tmp_path / "bug" / "sheet.png" and result.sheet.exists()
    names = sorted(p.name for p in result.frames)
    assert names == sorted(
        ["walk_0.png", "walk_1.png", "walk_flip.png", "walk_0@ripe.png", "walk_1@ripe.png", "walk_flip@ripe.png"]
    )
    gifs = {p.name: p for p in result.gifs}
    assert set(gifs) == {"walk.gif", "flip.gif"}
    with Image.open(gifs["walk.gif"]) as gif:
        assert getattr(gif, "n_frames") == 2
        assert gif.info["duration"] == 170  # 6 fps, rounded to GIF's 10ms steps
        assert gif.size == (36, 36)


def test_gallery_includes_every_kind() -> None:
    project = load_project(GOLDEN)
    crate = load_asset_or_raise(GOLDEN / "models" / "crate.model.yaml", project)
    turf = load_asset_or_raise(GOLDEN / "tiles" / "turf.tiles.yaml", project)
    with_model = gallery([bug(), crate, turf], PreviewOptions(), "test")
    without = gallery([bug(), turf], PreviewOptions(scale=4), "test")
    assert with_model.height > without.height  # the model gets its own row
    assert gallery([bug()], PreviewOptions(), "test").width > 0
