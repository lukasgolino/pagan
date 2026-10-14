"""The example project shipped in examples/demo must always be valid."""

from pathlib import Path

import pytest

from pagan.project import load_project

DEMO = Path(__file__).parent.parent / "examples" / "demo"
PALETTES = sorted((DEMO / "palettes").glob("*.pal.yaml"))


def test_demo_project_loads() -> None:
    project = load_project(DEMO)
    assert project.config.default_palette in project.palette_names()


@pytest.mark.parametrize("path", PALETTES, ids=lambda p: p.name)
def test_demo_palettes_are_valid(path: Path) -> None:
    palette = load_project(DEMO).load_palette(path.name.removesuffix(".pal.yaml"))
    assert 16 <= len(palette.colors) <= 32
    # Every color belongs to at least one ramp.
    in_ramps = {key for ramp in palette.ramps.values() for key in ramp}
    assert in_ramps == set(palette.colors)
