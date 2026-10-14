"""pagan import: scale detection, palette snapping (with report), open-mode extraction, round trips."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from conftest import make_project
from pagan.asset import load_asset_or_raise
from pagan.cli import main
from pagan.color import oklab_to_rgb, rgb_to_oklab
from pagan.importer import detect_scale, import_png
from pagan.project import load_project
from pagan.render import frame_image

GOLDEN = Path(__file__).parent / "fixtures" / "golden"


def bug_image() -> Image.Image:
    asset = load_asset_or_raise(GOLDEN / "sprites" / "bug.sprite.yaml", load_project(GOLDEN))
    return frame_image(asset, "walk_0")


@pytest.mark.parametrize("scale", [1, 2, 3, 5])
def test_detect_scale(scale: int) -> None:
    image = bug_image()
    big = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
    assert detect_scale(big) == scale


def test_color_round_trip() -> None:
    for rgb in [(0, 0, 0), (255, 255, 255), (20, 16, 28), (200, 80, 74)]:
        assert oklab_to_rgb(rgb_to_oklab(rgb)) == rgb


def test_snap_to_palette_recovers_exact_grid() -> None:
    project = load_project(GOLDEN)
    palette = project.load_palette("mini")
    source = bug_image()
    # Nudge every color slightly off-palette and upscale 4x.
    data = source.tobytes()
    nudged = bytes(min(255, v + 6) if i % 4 != 3 else v for i, v in enumerate(data))
    off = Image.frombytes("RGBA", source.size, nudged).resize((source.width * 4, source.height * 4), Image.Resampling.NEAREST)
    rows, inline, report = import_png(off, palette=palette)
    assert inline is None
    assert report.scale == 4 and report.size == source.size
    assert report.changed_pixels == report.opaque_pixels  # every opaque pixel was off-palette
    assert 0 < report.max_distance < 0.05
    asset = load_asset_or_raise(GOLDEN / "sprites" / "bug.sprite.yaml", project)
    assert tuple(rows) == asset.frames["walk_0"]


def test_open_mode_extracts_colors_darkest_first() -> None:
    rows, inline, report = import_png(bug_image(), palette=None)
    assert inline is not None and report.reduced_from is None
    assert len(inline) == report.source_colors == 4
    assert inline["0"] == "#14101c"  # the outline color is darkest
    assert rows[1] == "...0.0..."


def test_open_mode_reduces_colors() -> None:
    gradient = Image.new("RGBA", (64, 1))
    gradient.putdata([(i * 4, 255 - i * 4, 128, 255) for i in range(64)])
    rows, inline, report = import_png(gradient, palette=None, max_colors=8)
    assert inline is not None and len(inline) <= 8
    assert report.reduced_from == 64 and report.changed_pixels > 0
    assert len(rows[0]) == 64


def test_alpha_threshold() -> None:
    image = Image.new("RGBA", (2, 1))
    image.putdata([(255, 0, 0, 100), (255, 0, 0, 200)])
    rows, _, _ = import_png(image, palette=None, alpha_threshold=128, scale=1)
    assert rows == [".0"]


def test_cli_import_creates_lint_clean_sprite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    for x in range(2, 6):
        for y in range(2, 6):
            image.putpixel((x, y), (250, 5, 5, 255))  # near the palette's "#ff0000"
    image.putpixel((6, 2), (250, 5, 5, 255))  # a 1px detail, so the native size is unambiguous
    image.resize((32, 32), Image.Resampling.NEAREST).save(tmp_path / "Red Block.png")
    assert main(["import", "Red Block.png"]) == 0
    out = capsys.readouterr().out
    assert "scale 4 -> 8x8" in out and "-> '1'" in out
    sprite = tmp_path / "sprites" / "red_block.sprite.yaml"
    assert "palette: test" in sprite.read_text()
    assert main(["lint"]) == 0
    assert main(["import", "Red Block.png"]) == 1  # refuses to overwrite
    assert main(["import", "Red Block.png", "--force", "--open", "--name", "red2", "--out", "x.sprite.yaml"]) == 0
