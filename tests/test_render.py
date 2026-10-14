"""Rendering: golden images (exact pixels) and byte-for-byte determinism."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from PIL import Image

from pagan.asset import Asset, load_asset_or_raise
from pagan.project import load_project
from pagan.render import frame_rects, save_png, sheet_image

GOLDEN = Path(__file__).parent / "fixtures" / "golden"
EXPECTED = GOLDEN / "expected"
UPDATE = os.environ.get("PAGAN_UPDATE_GOLDEN") == "1"


def load(name: str) -> Asset:
    project = load_project(GOLDEN)
    kind_dir = "sprites" if (GOLDEN / "sprites" / f"{name}.sprite.yaml").exists() else "tiles"
    suffix = ".sprite.yaml" if kind_dir == "sprites" else ".tiles.yaml"
    return load_asset_or_raise(GOLDEN / kind_dir / f"{name}{suffix}", project)


def test_bug_frame_is_mirrored_and_outlined() -> None:
    # Hand-checked expectation: mirror reflects the left 5 columns (centre not doubled),
    # outline adds "0" on the 4-neighbourhood of every opaque pixel.
    assert load("bug").frames["walk_0"] == (
        ".........",
        "...0.0...",
        "..01010..",
        ".0120210.",
        "012323210",
        "012222210",
        ".0122210.",
        "..01010..",
        "...0.0...",
    )


def test_sheet_layout() -> None:
    bug = load("bug")
    assert frame_rects(bug) == {"walk_0": (0, 0, 9, 9), "walk_1": (9, 0, 9, 9), "walk_flip": (18, 0, 9, 9)}
    turf = load("turf")  # tileset: columns: 2
    assert frame_rects(turf) == {"plain": (0, 0, 4, 4), "flower": (4, 0, 4, 4), "plain_flip": (0, 4, 4, 4)}


CASES = [("bug", None), ("bug", "ripe"), ("turf", None)]


@pytest.mark.parametrize("name, variant", CASES)
def test_golden_sheet(name: str, variant: str | None) -> None:
    image = sheet_image(load(name), variant)
    expected_path = EXPECTED / f"{name}{'_' + variant if variant else ''}.png"
    if UPDATE:
        save_png(image, expected_path)
    expected = Image.open(expected_path)
    assert expected.mode == "RGBA" and image.size == expected.size
    assert image.tobytes() == expected.tobytes(), f"{expected_path.name} differs; inspect it, then rerun with PAGAN_UPDATE_GOLDEN=1"


def colors(image: Image.Image) -> set[object]:
    found = image.getcolors(maxcolors=1 << 16)
    assert found is not None
    return {c for _, c in found}


def test_variant_recolors_only() -> None:
    bug = load("bug")
    base, ripe = sheet_image(bug), sheet_image(bug, "ripe")
    assert base.getchannel("A").tobytes() == ripe.getchannel("A").tobytes()  # same geometry
    assert (0x6E, 0x9A, 0x3C, 255) in colors(base)  # leaf
    assert (0x6E, 0x9A, 0x3C, 255) not in colors(ripe)
    assert (0xC8, 0x50, 0x4A, 255) in colors(ripe)  # leaf -> berry


def test_png_bytes_are_deterministic(tmp_path: Path) -> None:
    # Fresh copies of the project and two separate renders must give identical bytes.
    outputs = []
    for run in ("a", "b"):
        root = tmp_path / run
        shutil.copytree(GOLDEN, root)
        asset = load_asset_or_raise(root / "sprites" / "bug.sprite.yaml", load_project(root))
        path = tmp_path / f"{run}.png"
        save_png(sheet_image(asset), path)
        outputs.append(path.read_bytes())
    assert outputs[0] == outputs[1]
