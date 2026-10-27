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


# --- ring (#35) ---------------------------------------------------------------------------------


def ring_cells(centre: tuple[float, float, float], outer: float, inner: float, height: int, axis: str) -> set[Cell]:
    """Brute force: cells whose centres lie inner..outer from the axis, `height` layers from the centre's layer."""
    along = "xyz".index(axis)
    out: set[Cell] = set()
    for x in range(-20, 21):
        for y in range(-20, 21):
            for z in range(-20, 21):
                c = (x, y, z)
                if not 0 <= c[along] - centre[along] < height:
                    continue
                d2 = sum((c[i] - centre[i]) ** 2 for i in range(3) if i != along)
                if inner * inner - 1e-9 <= d2 <= outer * outer + 1e-9:
                    out.add(c)
    return out


@pytest.mark.parametrize("axis", ["z", "x", "y"])
@pytest.mark.parametrize(("centre", "outer", "inner", "height"), [((0, 0, 0), 4, 3, 1), ((2, -1, 3), 5.5, 2, 3), ((0.5, 0.5, 0.5), 3, 2, 2)])
def test_ring_is_an_open_annulus(mproject: Project, axis: str, centre: tuple[float, ...], outer: float, inner: float, height: int) -> None:
    c = list(centre)
    c["xyz".index(axis)] = int(c["xyz".index(axis)])  # whole voxels along the axis
    spec = f"ring: {{ center: [{c[0]}, {c[1]}, {c[2]}], outer: {outer}, inner: {inner}, height: {height}, axis: {axis}, material: red }}"
    got = cells(mproject, spec)
    assert got == ring_cells((c[0], c[1], c[2]), outer, inner, height, axis) and got
    # Open: the axis itself is empty, and every layer is the same annulus.
    along = "xyz".index(axis)
    layers = [{tuple(v for i, v in enumerate(cell) if i != along) for cell in got if cell[along] == c[along] + k} for k in range(height)]
    assert all(layer == layers[0] for layer in layers)


def test_ring_matches_a_carved_cylinder(mproject: Project) -> None:
    """What generators did before: a cylinder with a carved cylinder inside (centres within inner excluded)."""
    ring = cells(mproject, "ring: { centre: [0, 0, 2], outer: 6, inner: 4.5, height: 2, material: red }")
    solid = cells(mproject, "cylinder: { base: [0, 0, 2], height: 2, radius: 6, material: red }")
    assert ring == {c for c in solid if c[0] ** 2 + c[1] ** 2 >= 4.5**2}


def test_ring_takes_part_fields(mproject: Project) -> None:
    parts = "  - box: { from: [-6, -6, 0], to: [6, 6, 0], material: red }\n"
    parts += "  - ring: { center: [0, 0, 0], outer: 3, inner: 2, material: red }\n    carve: true\n"
    parts += "  - ring: { center: [0, 4, 1], outer: 2, inner: 1, height: 2, material: green, top: red }\n    id: wheel\n    mirror: true\n"
    asset, findings = model(mproject, parts)
    assert asset is not None and not [f for f in findings if f.severity == "error"], [f.format() for f in findings]
    assert isinstance(asset.mesh, MeshSource)
    voxels = asset.mesh.model.voxels
    assert (3, 0, 0) not in voxels and (0, 0, 0) in voxels and (1, 4, 2) in voxels and (1, -4, 2) in voxels
    assert voxels[(1, 4, 1)] == "green" and voxels[(1, 4, 2)] == "red" and "wheel" in asset.mesh.model.part_ids()


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("center: [0, 0, 0], outer: 3, inner: 3", "inner (3) must be less than outer (3)"),
        ("center: [0, 0, 0], outer: 2, inner: 4", "must be less than outer"),
        ("center: [0, 0, 0], outer: 3", "outer > 0 and inner >= 0"),
        ("center: [0, 0, 0], outer: 0, inner: 0", "outer > 0 and inner >= 0"),
        ("center: [0, 0, 0], outer: 3, inner: -1", "outer > 0 and inner >= 0"),
        ("center: [0, 0, 0], outer: 3, inner: 1, height: 0", "height must be a whole number"),
        ("center: [0, 0, 0], outer: 3, inner: 1, height: 1.5", "height must be a whole number"),
        ("center: [0, 0, 0.5], outer: 3, inner: 1", "whole voxels along its axis"),
        ("center: [0, 0], outer: 3, inner: 1", "ring needs center"),
        ("center: [0, 0, 0], outer: 3, inner: 1, axis: w", "axis x|y|z"),
        ("center: [0, 0, 0], centre: [0, 0, 0], outer: 3, inner: 1", "center once"),
        ("center: [0, 0, 0], outer: 1.4, inner: 1.2", "too thin"),
        ("center: [0, 0, 0], outer: 3, inner: 1, shell: true", "unknown field(s) shell"),
    ],
)
def test_ring_errors(mproject: Project, spec: str, message: str) -> None:
    _, findings = model(mproject, f"  - ring: {{ {spec}, material: red }}\n")
    assert any(f.rule == "E013" and message in f.message for f in findings), [f.format() for f in findings]


def test_ring_in_the_api() -> None:
    from pagan.api import shape_cells

    got = shape_cells("ring", {"center": [0, 0, 0], "outer": 2, "inner": 1, "material": "m"})
    assert set(got) == ring_cells((0, 0, 0), 2, 1, 1, "z") and set(got.values()) == {"m"}
