"""Model parts (LOOSE! report D7): hollow shapes (`shell`), and ids that later parts cover completely (W013)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from conftest import make_project
from pagan.asset import Asset, load_asset
from pagan.findings import Finding
from pagan.model import MeshSource
from pagan.project import Project
from pagan.voxel import Cell

CONFIG = 'default_palette = "test"\nexport = ["png", "mesh"]\n'


@pytest.fixture
def mproject(tmp_path: Path) -> Project:
    return make_project(tmp_path, CONFIG)


def model(project: Project, parts: str, more: str = "") -> tuple[Asset | None, list[Finding]]:
    (project.root / "models").mkdir(exist_ok=True)
    path = project.root / "models" / "thing.model.yaml"
    path.write_text(f"name: thing\ndirections: 0\norigin: [0, 0, 0]\nmaterials:\n  red: {{ ramp: red }}\n  green: {{ ramp: green }}\nparts:\n{parts}{more}")
    return load_asset(path, project)


def cells(project: Project, shape: str) -> set[Cell]:
    asset, findings = model(project, f"  - {shape}\n")
    assert asset is not None, [f.format() for f in findings]
    assert isinstance(asset.mesh, MeshSource)
    return set(asset.mesh.model.voxels)


def surface(solid: set[Cell], thickness: int) -> set[Cell]:
    """The cells within `thickness` face steps of the outside, by brute force."""
    out: set[Cell] = set()
    layer = {c for c in solid if any(n not in solid for n in neighbours(c))}
    for _ in range(thickness):
        out |= layer
        layer = {c for c in solid - out if any(n in out for n in neighbours(c))}
    return out


def neighbours(c: Cell) -> list[Cell]:
    x, y, z = c
    return [(x + 1, y, z), (x - 1, y, z), (x, y + 1, z), (x, y - 1, z), (x, y, z + 1), (x, y, z - 1)]


@pytest.mark.parametrize(
    "shape",
    [
        "box: { from: [0, 0, 0], to: [6, 4, 9], material: red",
        "cylinder: { base: [2, -1, 3], height: 7, radius: 4.5, material: red",
        "cylinder: { base: [2, -1, 3], height: 7, radius: 4.5, axis: x, material: red",
        "cylinder: { base: [2, -1, 3], height: 7, radius: 3, axis: y, material: red",
        "ellipsoid: { center: [0.5, 0, 4], radii: [5, 3.5, 6], material: red",
    ],
)
@pytest.mark.parametrize("thickness", [1, 2])
def test_shell_is_the_outer_layer_of_the_solid_shape(mproject: Project, shape: str, thickness: int) -> None:
    solid = cells(mproject, shape + " }")
    hollow = cells(mproject, shape + f", shell: {'true' if thickness == 1 else thickness} }}")
    assert hollow == surface(solid, thickness) and len(hollow) < len(solid)


def test_shell_errors(mproject: Project) -> None:
    for bad in ("0", "-1", "1.5", "thick"):
        _, findings = model(mproject, f"  - box: {{ from: [0, 0, 0], to: [3, 3, 3], material: red, shell: {bad} }}\n")
        assert any(f.rule == "E013" and "shell must be" in f.message for f in findings), bad


def test_big_hollow_tower_stays_under_the_voxel_cap(mproject: Project) -> None:
    """A 12 m round tower at 0.0625 m per voxel: 7.5M voxels solid (over the cap), ~0.4M as a 2-voxel shell."""
    start = time.perf_counter()
    hollow = cells(mproject, "cylinder: { base: [0, 0, 0], height: 260, radius: 96, material: red, shell: 2 }")
    assert 300_000 < len(hollow) < 600_000 and time.perf_counter() - start < 20
    _, findings = model(mproject, "  - cylinder: { base: [0, 0, 0], height: 260, radius: 96, material: red }\n")
    assert any(f.rule == "E013" and "limit" in f.message for f in findings)


HELM = """\
  - ellipsoid: { center: [0, 0, 4], radii: [2, 2, 2], material: red }
    id: head
  - box: { from: [-3, -3, 1], to: [3, 3, 7], material: green }
    id: helmet
"""


def test_a_part_covered_completely_warns(mproject: Project) -> None:
    asset, findings = model(mproject, HELM)
    assert asset is not None
    warning = next(f for f in findings if f.rule == "W013")
    assert "'head' has no voxels left" in warning.message and "'helmet'" in warning.message and (warning.line, warning.where) == (8, "parts[0]")


def test_a_shell_keeps_the_part_inside(mproject: Project) -> None:
    asset, findings = model(mproject, HELM.replace("material: green }", "material: green, shell: 1 }"))
    assert asset is not None and not [f for f in findings if f.rule == "W013"]
    assert isinstance(asset.mesh, MeshSource) and "head" in asset.mesh.model.part_ids()


def test_rig_and_poses_on_a_covered_part_explain_why(mproject: Project) -> None:
    _, findings = model(mproject, HELM, "rig:\n  head: { pivot: [0, 0, 2] }\n")
    rig = next(f for f in findings if f.rule == "E014")
    assert "no part has id 'head'" in rig.message and "later parts cover all of it" in rig.message
    _, findings = model(mproject, HELM, "animations:\n  nod: { poses: [ { head: { offset: [0, 0, 1] } } ] }\n")
    pose = next(f for f in findings if f.rule == "E013")
    assert "unknown part id 'head'" in pose.message and "later parts cover all of it" in pose.message


def test_a_carved_away_part_warns(mproject: Project) -> None:
    parts = "  - box: { from: [0, 0, 0], to: [3, 3, 3], material: red }\n  - box: { from: [0, 0, 4], to: [1, 1, 4], material: red }\n    id: knob\n"
    parts += "  - box: { from: [0, 0, 4], to: [1, 1, 4], material: red }\n    carve: true\n"
    _, findings = model(mproject, parts)
    assert any(f.rule == "W013" and "carve parts removed all of it" in f.message for f in findings)
