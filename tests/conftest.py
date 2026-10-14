from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from pagan.asset import Asset, load_asset
from pagan.findings import Finding
from pagan.project import Project, load_project

PALETTE = """\
name: test
colors:
  "0": { hex: "#000000", name: ink }
  "1": { hex: "#ff0000", name: red_dark }
  "2": { hex: "#ff8080", name: red }
  "3": { hex: "#00ff00", name: green_dark }
  "4": { hex: "#80ff80", name: green }
  "5": { hex: "#0000ff", name: blue }
  "6": { hex: "#ffffff", name: white }
ramps:
  red: ["1", "2"]
  green: ["3", "4"]
  blue: ["5"]
  mono: ["0", "6"]
"""

OTHER_PALETTE = """\
name: other
colors:
  "0": { hex: "#101010" }
  "1": { hex: "#202020" }
  "2": { hex: "#303030" }
ramps:
  dim: ["1", "2"]
"""


def make_project(root: Path, config: str = 'default_palette = "test"\n') -> Project:
    (root / "pagan.toml").write_text(config)
    for name in ("palettes", "sprites", "tiles"):
        (root / name).mkdir(exist_ok=True)
    (root / "palettes" / "test.pal.yaml").write_text(PALETTE)
    (root / "palettes" / "other.pal.yaml").write_text(OTHER_PALETTE)
    return load_project(root)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return make_project(tmp_path)


LoadFn = Callable[..., tuple[Asset | None, list[Finding]]]


@pytest.fixture
def load(project: Project) -> LoadFn:
    """Write a sprite (or tileset) file into the project and load it."""

    def _load(text: str, name: str = "thing", kind: str = "sprite", proj: Project | None = None) -> tuple[Asset | None, list[Finding]]:
        p = proj or project
        folder, suffix = ("sprites", ".sprite.yaml") if kind == "sprite" else ("tiles", ".tiles.yaml")
        path = p.root / folder / f"{name}{suffix}"
        path.write_text(text)
        return load_asset(path, p)

    return _load


def ascii_grid(rows: tuple[str, ...]) -> str:
    return "\n".join(rows)
