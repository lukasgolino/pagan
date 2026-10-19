"""Mesh export (MESH_PLAN M1-M4): geometry, glTF validity, coordinates, ramp shading, rig, animations, build."""

from __future__ import annotations

import json
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from conftest import make_project
from pagan.asset import Asset, load_asset
from pagan.build import build
from pagan.findings import Finding
from pagan.gltf import read_accessor, read_glb, validate
from pagan.mesh import MeshExport, Surface, _labels, export_mesh, greedy_quads, polygons, ramp_image, ramp_rows, ramp_width, triangulate
from pagan.model import MeshSource
from pagan.project import Project, load_project
from pagan.voxel import Camera, Light, render_heading

ROOT = Path(__file__).parent.parent
MESH_CONFIG = 'default_palette = "test"\nexport = ["png", "mesh"]\n'


def model(project: Project, text: str, name: str = "thing") -> tuple[Asset | None, list[Finding]]:
    (project.root / "models").mkdir(exist_ok=True)
    path = project.root / "models" / f"{name}.model.yaml"
    path.write_text(text)
    return load_asset(path, project)


def ok(result: tuple[Asset | None, list[Finding]]) -> Asset:
    asset, findings = result
    assert asset is not None, [f.format() for f in findings]
    return asset


def export(asset: Asset, shading: str = "ramp", voxel_size: float = 1.0) -> MeshExport:
    source = asset.mesh
    assert isinstance(source, MeshSource)
    return export_mesh(source, asset.palette, voxel_size, shading, "pagan test")


def decoded(result: MeshExport) -> tuple[dict[str, Any], bytes]:
    doc, binary = read_glb(result.glb)
    assert validate(doc, binary) == []
    return doc, binary


def triangles(doc: dict[str, Any], binary: bytes, mesh: int = 0) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """(positions, normals, uvs) per triangle of every primitive of a mesh."""
    out = []
    for prim in doc["meshes"][mesh]["primitives"]:
        pos = read_accessor(doc, binary, prim["attributes"]["POSITION"])
        nor = read_accessor(doc, binary, prim["attributes"]["NORMAL"])
        uv = read_accessor(doc, binary, prim["attributes"]["TEXCOORD_0"])
        idx = read_accessor(doc, binary, prim["indices"]).reshape(-1, 3)
        out += [(pos[t], nor[t[0]], uv[t[0]]) for t in idx]
    return out


def box(a: tuple[int, int, int], b: tuple[int, int, int], material: str = "red", extra: str = "") -> str:
    return f"  - box: {{ from: {list(a)}, to: {list(b)}, material: {material} }}\n{extra}"


def mesh_model(parts: str, more: str = "", materials: str = "  red: { ramp: red }\n  green: { ramp: green }\n  blue: { ramp: blue }\n") -> str:
    return f"name: thing\ndirections: 0\norigin: [0, 0, 0]\nmaterials:\n{materials}parts:\n{parts}{more}"


@pytest.fixture
def mproject(tmp_path: Path) -> Project:
    return make_project(tmp_path, MESH_CONFIG)


# --- geometry ---------------------------------------------------------------------------------------


def test_a_cube_is_twelve_triangles(mproject: Project) -> None:
    doc, binary = decoded(export(ok(model(mproject, mesh_model(box((0, 0, 0), (2, 2, 2)))))))
    assert len(triangles(doc, binary)) == 12


def test_touching_boxes_share_no_inner_faces(mproject: Project) -> None:
    asset = ok(model(mproject, mesh_model(box((0, 0, 0), (1, 1, 1)) + box((2, 0, 0), (3, 1, 1)))))
    doc, binary = decoded(export(asset))
    assert len(triangles(doc, binary)) == 12  # one 4x2x2 block: 6 rectangles


def test_greedy_merges_per_material(mproject: Project) -> None:
    asset = ok(model(mproject, mesh_model(box((0, 0, 0), (1, 1, 1)) + box((2, 0, 0), (3, 1, 1), "green"))))
    doc, binary = decoded(export(asset))
    # 2 end faces + 4 sides split by material = 10 rectangles
    assert len(triangles(doc, binary)) == 20


def test_greedy_quads_on_known_shapes() -> None:
    labels = np.full((3, 3, 1), -1, dtype=np.int32)
    labels[:, 0, 0] = 0
    labels[0, :, 0] = 0  # an L of 5 voxels in one layer
    quads = greedy_quads(labels)
    assert len([q for q in quads if q.axis == 2]) == 4  # top and bottom: 2 rectangles each
    assert sum((q.u1 - q.u0) * (q.v1 - q.v0) for q in quads) == 5 * 2 + 12  # every face covered exactly once


def _directed_edges(prim_positions: list[tuple[float, float, float]], indices: list[int]) -> Counter[tuple[Any, Any]]:
    edges: Counter[tuple[Any, Any]] = Counter()
    for t in range(0, len(indices), 3):
        tri = [prim_positions[i] for i in indices[t : t + 3]]
        for i in range(3):
            edges[(tri[i], tri[(i + 1) % 3])] += 1
    return edges


@pytest.mark.parametrize("seed", range(6))
def test_meshes_are_watertight_no_t_junctions(seed: int) -> None:
    """Every edge is used once in each direction: no T-junctions, so no cracks at any resolution."""
    rng = np.random.default_rng(seed)
    labels = np.where(rng.random((6, 5, 4)) < 0.55, rng.integers(0, 3, (6, 5, 4)), -1).astype(np.int32)
    quads = greedy_quads(labels, (2, -3, 1))
    prim = triangulate(quads, {i: (0.0, 0.0) for i in range(3)})
    edges = _directed_edges(prim.positions, prim.indices)
    # Edges may be split into collinear pieces differently on either side only if T-junctions remain.
    assert all(edges[(b, a)] == count for (a, b), count in edges.items())


def test_polygons_insert_vertices_on_edges() -> None:
    labels = np.full((2, 2, 2), -1, dtype=np.int32)
    labels[:, :, 0] = 0
    labels[0, 0, 1] = 0  # a 1-voxel bump on a 2x2 slab
    quads = greedy_quads(labels)
    assert any(len(p) > 4 for p in polygons(quads))


def test_two_sided_materials_get_their_own_material(mproject: Project) -> None:
    text = mesh_model(box((0, 0, 0), (1, 1, 1)) + box((0, 0, 2), (1, 1, 2), "cloth"), materials="  red: { ramp: red }\n  cloth: { ramp: green, two_sided: true }\n")
    doc, _ = decoded(export(ok(model(mproject, text))))
    assert [m["name"] for m in doc["materials"]] == ["thing", "thing_two_sided"]
    assert len(doc["meshes"][0]["primitives"]) == 2


# --- coordinates ----------------------------------------------------------------------------------


def test_front_left_top_map_to_plus_z_plus_x_plus_y(mproject: Project) -> None:
    """Asymmetric fixture: red plate on the front (+x), green on the left (+y), blue on top (+z)."""
    parts = box((-2, -2, 0), (1, 1, 3), "white") + box((2, -2, 0), (2, 1, 3)) + box((-2, 2, 0), (1, 2, 3), "green") + box((-2, -2, 4), (1, 1, 4), "blue")
    asset = ok(model(mproject, mesh_model(parts, materials="  white: { ramp: mono }\n  red: { ramp: red }\n  green: { ramp: green }\n  blue: { ramp: blue }\n")))
    result = export(asset)
    doc, binary = decoded(result)
    rows = result.rows
    for normal, ramp in (((0, 0, 1), "red"), ((1, 0, 0), "green"), ((0, 1, 0), "blue")):
        axis = normal.index(1)
        facing = [t for t in triangles(doc, binary) if tuple(t[1]) == normal]
        outermost = max(t[0][:, axis].max() for t in facing)
        colours = {rows[int(t[2][1] * len(rows))] for t in facing if t[0][:, axis].max() == outermost}
        assert colours == {asset.palette.ramps[ramp]}, (normal, colours)


def test_origin_is_the_mesh_origin_and_voxel_size_scales(mproject: Project) -> None:
    asset = ok(model(mproject, mesh_model(box((0, 0, 0), (1, 1, 1))).replace("origin: [0, 0, 0]", "origin: [1, 1, 0]")))
    doc, binary = decoded(export(asset, voxel_size=0.5))
    accessor = doc["accessors"][doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
    assert accessor["min"] == [-0.5, 0.0, -0.5] and accessor["max"] == [0.5, 1.0, 0.5]


# --- ramp texture and shading -----------------------------------------------------------------


def test_ramp_texture_layout(mproject: Project) -> None:
    text = mesh_model(box((0, 0, 0), (1, 1, 1)) + box((0, 0, 2), (1, 1, 2), "blue") + box((0, 0, 3), (1, 1, 3), "trio"),
                      materials="  red: { ramp: red }\n  blue: { ramp: blue }\n  trio: { keys: ['0', '1', '2'] }\n")  # fmt: skip
    asset = ok(model(mproject, text))
    rows = ramp_rows(asset.mesh)
    assert rows == [("1", "2"), ("5",), ("0", "1", "2")]
    assert ramp_width(rows) == 6
    pixels = np.array(ramp_image(rows, asset.palette))
    hexes = [["#%02x%02x%02x" % tuple(p) for p in row] for row in pixels]
    assert hexes[0] == ["#ff0000"] * 3 + ["#ff8080"] * 3
    assert hexes[1] == ["#0000ff"] * 6
    assert hexes[2] == ["#000000"] * 2 + ["#ff0000"] * 2 + ["#ff8080"] * 2


def test_brightness_as_u_picks_the_renderers_step() -> None:
    """Sampling the ramp at u = brightness (what the shader does) gives floor(brightness * steps)."""
    rows = [("a", "b"), ("a", "b", "c"), ("a", "b", "c", "d", "e")]
    width = ramp_width(rows)
    for keys in rows:
        for brightness in np.linspace(0, 0.9999, 997):
            column = int(brightness * width)
            assert column * len(keys) // width == min(int(brightness * len(keys)), len(keys) - 1)


def test_uv_x_points_at_the_middle_step(mproject: Project) -> None:
    result = export(ok(model(mproject, mesh_model(box((0, 0, 0), (1, 1, 1)), materials="  red: { keys: ['0', '1', '2'] }\n"))))
    doc, binary = decoded(result)
    uvs = {tuple(t[2]) for t in triangles(doc, binary)}
    assert uvs == {(np.float32(0.5), np.float32(0.5))}


def test_baked_steps_match_the_sprite_renderer(mproject: Project) -> None:
    """Straight down (elevation 90), each pixel shows its column's top voxel: the baked mesh must pick the
    same ramp step for it as the sprite renderer (both use voxel.cell_intensity / ramp_steps)."""
    text = mesh_model("  - ellipsoid: { center: [0, 0, 3], radii: [5, 4, 3], material: red }\n  - box: { from: [-1, -1, 6], to: [0, 0, 8], material: green }\n",
                      materials="  red: { keys: ['0', '1', '2', '6'] }\n  green: { ramp: green }\n")  # fmt: skip
    asset = ok(model(mproject, text))
    source = asset.mesh
    rows = ramp_rows(source)
    cells = np.array(list(source.model.voxels), dtype=np.int64)
    labels, surfaces = _labels(source, rows, "baked", cells, list(source.model.voxels.values()), source.model)
    baked = {tuple(c): surfaces[label] for c, label in zip(cells.tolist(), labels.tolist(), strict=True)}
    frame = render_heading(source.model, source.materials, heading=0, size=(16, 16), origin=(0, 0, 0), pivot=(8, 8),
                           camera=Camera(90.0, 1.0), light=source.light)  # fmt: skip
    checked = 0
    for py, row in enumerate(frame):
        for px, key in enumerate(row):
            if key == ".":
                continue
            x, y = px - 8, 8 - py - 1
            z = max(c[2] for c in source.model.voxels if c[0] == x and c[1] == y)
            surface = baked[(x, y, z)]
            assert rows[surface.row][surface.step if surface.step is not None else 0] == key, (x, y, z)
            checked += 1
    assert checked > 50


def test_baked_shading_marks_materials_unlit(mproject: Project) -> None:
    doc, _ = decoded(export(ok(model(mproject, mesh_model(box((0, 0, 0), (1, 1, 1))))), shading="baked"))
    assert doc["materials"][0]["extensions"] == {"KHR_materials_unlit": {}}
    assert "KHR_materials_unlit" in doc["extensionsUsed"]


def test_mesh_export_is_deterministic(mproject: Project) -> None:
    demo = load_project(ROOT / "examples" / "demo")
    asset, _ = load_asset(ROOT / "examples" / "demo" / "models" / "ship.model.yaml", demo)
    assert asset is not None
    assert export(asset, "baked").glb == export(asset, "baked").glb
    assert export(asset).glb == export(asset).glb


def test_demo_models_are_valid_gltf() -> None:
    demo = load_project(ROOT / "examples" / "demo")
    for name in ("ship", "sailor"):
        asset, _ = load_asset(ROOT / "examples" / "demo" / "models" / f"{name}.model.yaml", demo)
        assert asset is not None
        for shading in ("ramp", "baked", "flat"):
            doc, binary = decoded(export(asset, shading, 0.0625))
            assert doc["asset"] == {"version": "2.0", "generator": "pagan test"}
            assert doc["images"] == [{"uri": f"{name}.ramp.png", "name": f"{name}.ramp"}]
            assert doc["samplers"][0] == {"magFilter": 9728, "minFilter": 9728, "wrapS": 33071, "wrapT": 33071}


# --- rig ----------------------------------------------------------------------------------------------

RIGGED = mesh_model(
    box((-1, -1, 0), (1, 1, 5), extra="    id: torso\n")
    + box((-1, -1, 6), (1, 1, 8), "green", "    id: head\n")
    + box((-1, -1, 9), (1, 1, 9), "blue", "    id: helmet\n")
    + box((2, 0, 7), (2, 0, 7), "blue", "    id: eye\n"),
    """rig:
  torso: { pivot: [0, 0, 3] }
  head: { pivot: [0, 0, 6], parent: torso }
  helmet: { parent: head, meta: { hitzone: armour, detachable: true, hp: 3 }, collision: box }
  eye: { parent: head, meta: { hitzone: eye } }
animations:
  nod:
    fps: 4
    interpolation: linear
    poses:
      - {}
      - { head: { pitch: 20 } }
""",
)


def test_rig_builds_the_node_hierarchy_with_metadata(mproject: Project) -> None:
    result = export(ok(model(mproject, RIGGED)))
    doc, _ = decoded(result)
    nodes = {n["name"]: n for n in doc["nodes"]}
    names = [n["name"] for n in doc["nodes"]]
    assert names[0] == "body" and doc["scenes"][0]["nodes"] == [0]
    assert [names[i] for i in nodes["body"]["children"]] == ["torso"]
    assert [names[i] for i in nodes["torso"]["children"]] == ["head"]
    assert sorted(names[i] for i in nodes["head"]["children"]) == ["eye", "helmet"]
    assert nodes["head"]["translation"] == [0.0, 3.0, 0.0]  # pivot (0,0,6) relative to torso's (0,0,3)
    assert nodes["helmet"]["extras"] == {"hitzone": "armour", "detachable": True, "hp": 3, "pagan_part": "helmet", "pagan_collision": "box"}
    parts = result.info["parts"]
    assert parts["helmet"]["node"] == "body/torso/head/helmet"
    assert parts["helmet"]["aabb"] == {"min": [-1.0, 9.0, -1.0], "max": [2.0, 10.0, 2.0]}
    assert parts["eye"]["meta"] == {"hitzone": "eye"} and parts["eye"]["voxels"] == 1


@pytest.mark.parametrize(
    ("rig", "message"),
    [
        ("rig:\n  nope: {}\n", "no part has id"),
        ("rig:\n  head: { parent: nope }\n", "parent must be"),
        ("rig:\n  head: { parent: torso }\n  torso: { parent: head }\n", "cycle"),
        ("rig:\n  head: { pivot: [1, 2] }\n", "pivot must be"),
        ("rig:\n  head: { meta: { hitzone: [1] } }\n", "meta maps"),
        ("rig:\n  head: { collision: sphere }\n", "collision must be"),
        ("rig:\n  body: { parent: head }\n", "root node"),
    ],
)
def test_rig_errors(mproject: Project, rig: str, message: str) -> None:
    text = mesh_model(box((0, 0, 0), (1, 1, 1), extra="    id: torso\n") + box((0, 0, 2), (1, 1, 2), extra="    id: head\n"), rig)
    asset, findings = model(mproject, text)
    assert asset is None
    assert any(f.rule == "E014" and message in f.message for f in findings), [f.format() for f in findings]


def test_rig_children_follow_their_parents_in_sprites_too(project: Project) -> None:
    text = """name: arm
size: [24, 24]
pivot: [12, 20]
origin: [0, 0, 0]
directions: 1
outline: none
materials:
  red: { ramp: red }
parts:
  - box: { from: [0, 0, 0], to: [0, 0, 3], material: red }
    id: upper
  - box: { from: [0, 0, 4], to: [0, 0, 5], material: red }
    id: hand
rig:
  hand: { parent: upper }
animations:
  lift:
    poses:
      - { upper: { offset: [0, 0, 2] } }
"""
    asset = ok(model(project, text, "arm"))
    rest = {(x, y) for y, r in enumerate(asset.frames["main"]) for x, c in enumerate(r) if c != "."}
    lifted = {(x, y) for y, r in enumerate(asset.frames["lift_0"]) for x, c in enumerate(r) if c != "."}
    assert len(lifted) == len(rest) and min(y for _, y in lifted) < min(y for _, y in rest)  # the hand went up too


# --- animations -------------------------------------------------------------------------------------


def _channels(doc: dict[str, Any], binary: bytes, animation: str) -> dict[tuple[str, str], tuple[np.ndarray, np.ndarray, str]]:
    names = [n["name"] for n in doc["nodes"]]
    anim = next(a for a in doc["animations"] if a["name"] == animation)
    out = {}
    for channel in anim["channels"]:
        sampler = anim["samplers"][channel["sampler"]]
        target = channel["target"]
        if target["path"] == "pointer":
            pointer = target["extensions"]["KHR_animation_pointer"]["pointer"]
            key = (names[int(pointer.split("/")[2])], "visible")
        else:
            key = (names[target["node"]], target["path"])
        out[key] = (read_accessor(doc, binary, sampler["input"]), read_accessor(doc, binary, sampler["output"]), sampler["interpolation"])
    return out


def test_demo_sailor_walk_and_swing_keys() -> None:
    demo = load_project(ROOT / "examples" / "demo")
    asset, _ = load_asset(ROOT / "examples" / "demo" / "models" / "sailor.model.yaml", demo)
    assert asset is not None
    result = export(asset, voxel_size=0.0625)
    doc, binary = decoded(result)
    assert [a["name"] for a in doc["animations"]] == ["walk-loop", "swing"]
    walk = _channels(doc, binary, "walk-loop")
    times, values, mode = walk[("left_leg", "translation")]
    assert mode == "STEP" and list(times) == pytest.approx([0, 0.125, 0.25, 0.375, 0.5])
    rest = np.array(doc["nodes"][[n["name"] for n in doc["nodes"]].index("left_leg")]["translation"])
    assert values[0] - rest == pytest.approx([0, 0, 0.0625])  # offset [1, 0, 0]: one voxel forward = +Z
    assert values[2] - rest == pytest.approx([0, 0, -0.0625])
    assert values[4] == pytest.approx(values[3])  # the last frame holds until the loop
    swing = _channels(doc, binary, "swing")
    assert list(swing[("sword_up", "visible")][1]) == [1, 0, 0, 0, 0]
    assert list(swing[("sword_down", "visible")][1]) == [0, 0, 1, 1, 1]
    assert ("sword_up", "visible") in walk  # every animation keys every animated node
    hidden = [n for n in doc["nodes"] if n["name"].startswith("sword")]
    assert all(n["extensions"]["KHR_node_visibility"] == {"visible": False} for n in hidden)
    assert result.info["animations"]["walk"] == {"gltf_name": "walk-loop", "fps": 8.0, "loop": True, "frames": 4, "interpolation": "step", "duration": 0.5}


def test_linear_rotation_about_the_pivot(mproject: Project) -> None:
    doc, binary = decoded(export(ok(model(mproject, RIGGED))))
    channels = _channels(doc, binary, "nod-loop")
    times, rotations, mode = channels[("head", "rotation")]
    assert mode == "LINEAR" and len(times) == 3
    assert rotations[0] == pytest.approx([0, 0, 0, 1]) and rotations[2] == pytest.approx([0, 0, 0, 1])  # loops back
    # pitch +20 tips the front (+x -> glTF +Z) down: a rotation about the model's y axis = glTF +X
    angle = 2 * np.degrees(np.arctan2(rotations[1][0], rotations[1][3]))
    assert angle == pytest.approx(20, abs=1e-4) and rotations[1][1:3] == pytest.approx([0, 0])
    assert ("torso", "rotation") not in channels  # parts that never move aren't keyed


def test_whole_model_tilt_rotates_the_root(mproject: Project) -> None:
    text = mesh_model(box((0, 0, 0), (1, 1, 1)), "animations:\n  rock:\n    poses:\n      - { roll: 10 }\n      - {}\n")
    channels = _channels(*decoded(export(ok(model(mproject, text)))), "rock-loop")
    assert ("body", "rotation") in channels


# --- notation, lint, build ----------------------------------------------------------------------


def test_mesh_lint_only_with_mesh_export(project: Project, mproject: Project) -> None:
    text = mesh_model(
        box((0, 0, 0), (1, 1, 1), extra="    id: arm\n") + box((5, 5, 5), (5, 5, 5), extra="    id: arm\n")
        + "  - box: { from: [0, 0, 3], to: [0, 0, 3], material: red }\n    id: hole\n    hidden: true\n    carve: true\n",
        "voxel_size: 0.5\nrig:\n  arm: { pivot: [40, 0, 0] }\n",
    ).replace("directions: 0", "directions: 1\nsize: [24, 24]")  # fmt: skip
    _, findings = model(mproject, text)
    assert {"E014", "W009", "W010", "W011"} <= {f.rule for f in findings}
    asset, findings = model(project, text)
    assert asset is not None and not {"E014", "W009", "W010", "W011"} & {f.rule for f in findings}


def test_mesh_only_model_without_mesh_export_warns(project: Project) -> None:
    asset, findings = model(project, mesh_model(box((0, 0, 0), (1, 1, 1))))
    assert asset is not None and asset.mesh_only and not asset.frames
    assert [f.rule for f in findings] == ["W012"]


def test_build_writes_mesh_files_and_manifest(mproject: Project) -> None:
    model(mproject, RIGGED)
    model(mproject, mesh_model(box((0, 0, 0), (3, 3, 3))).replace("name: thing\ndirections: 0", "name: crate\ndirections: 4\nsize: [24, 24]").replace("parts:", "variants:\n  green: { ramp_swap: { red: green } }\nparts:"), "crate")
    result = build(load_project(mproject.root))
    assert not result.errors, [f.format() for f in result.errors]
    out = mproject.output_dir
    manifest = json.loads((out / "manifest.json").read_text())
    thing, crate = manifest["assets"]["thing"], manifest["assets"]["crate"]
    assert thing["mesh_only"] is True and "sheet" not in thing
    assert thing["mesh"]["glb"] == "models/thing.glb" and (out / "models" / "thing.glb").is_file()
    assert thing["mesh"]["parts"]["helmet"]["collision"] == "box"
    assert crate["sheet"] == "sprites/crate.png" and crate["mesh"]["variants"]["green"] == {"ramp": "models/crate.green.ramp.png"}
    assert {"models/crate.glb", "models/crate.ramp.png", "models/crate.green.ramp.png", "models/thing.glb"} <= set(manifest["files"])
    first = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
    build(load_project(mproject.root))
    assert first == {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}  # byte-identical rebuild
    (mproject.root / "models" / "thing.model.yaml").unlink()
    result = build(load_project(mproject.root))
    assert out / "models" / "thing.glb" in result.removed  # stale meshes are cleaned up


def test_model_voxel_size_overrides_the_project(mproject: Project) -> None:
    model(mproject, mesh_model(box((0, 0, 0), (1, 1, 1)), "voxel_size: 0.5\n"))
    build(load_project(mproject.root))
    manifest = json.loads((mproject.output_dir / "manifest.json").read_text())
    assert manifest["assets"]["thing"]["mesh"]["voxel_size"] == 0.5
    assert manifest["assets"]["thing"]["mesh"]["bounds"] == {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]}


def test_demo_2d_output_is_unchanged_with_mesh_export(tmp_path: Path) -> None:
    """Turning meshes on adds files and `mesh` keys; every sprite, tileset and Godot resource stays byte-identical."""
    demo = tmp_path / "demo"
    shutil.copytree(ROOT / "examples" / "demo", demo, ignore=shutil.ignore_patterns("previews", ".pagan-cache"))
    shutil.copytree(ROOT / "examples" / "godot", tmp_path / "godot", ignore=shutil.ignore_patterns(".godot", "*.import"))
    committed = ROOT / "examples" / "godot" / "assets" / "generated"
    config = demo / "pagan.toml"
    config.write_text(config.read_text().replace('export = ["png", "godot"]', 'export = ["png", "godot", "mesh"]'))
    result = build(load_project(demo))
    assert not result.errors
    generated = tmp_path / "godot" / "assets" / "generated"
    for path in committed.rglob("*"):
        if path.is_file() and path.name != "manifest.json" and path.suffix != ".import":
            assert (generated / path.relative_to(committed)).read_bytes() == path.read_bytes(), path
    old = json.loads((committed / "manifest.json").read_text())
    new = json.loads((generated / "manifest.json").read_text())
    for name, entry in old["assets"].items():
        assert {k: v for k, v in new["assets"][name].items() if k != "mesh"} == entry
    assert set(new["assets"]["ship"]["mesh"]) >= {"glb", "ramp", "parts", "animations", "godot_scene", "godot_materials"}


@pytest.mark.slow
def test_castle_wall_meshes_in_seconds() -> None:
    """400 x 40 x 300 voxels (castle scale) with windows and two materials, meshed in a few seconds."""
    labels = np.zeros((400, 40, 300), dtype=np.int32)
    labels[:, :, 280:] = 1
    labels[::20, :, 100:140] = -1  # arrow slits
    labels[:, 15:25, 200:] = -1  # a walkway trench
    started = time.monotonic()
    quads = greedy_quads(labels)
    prim = triangulate(quads, {0: (0.0, 0.0), 1: (0.5, 0.5)})
    elapsed = time.monotonic() - started
    assert elapsed < 8, elapsed
    assert len(prim.indices) // 3 < 20_000


def test_surface_is_hashable() -> None:
    assert len({Surface(0, None, False), Surface(0, None, False)}) == 1


def test_validator_catches_problems() -> None:
    doc: dict[str, Any] = {
        "asset": {"version": "2.0"},
        "bufferViews": [{"buffer": 0, "byteOffset": 2, "byteLength": 4}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
    }
    problems = validate(doc, b"\0" * 8)
    assert any("aligned" in p for p in problems) and any("min and max" in p for p in problems)


def test_light_is_part_of_the_mesh_source(mproject: Project) -> None:
    asset = ok(model(mproject, mesh_model(box((0, 0, 0), (1, 1, 1)), "light: { ambient: 0.5 }\n")))
    assert isinstance(asset.mesh.light, Light) and asset.mesh.light.ambient == 0.5
