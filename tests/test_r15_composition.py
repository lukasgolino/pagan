"""R15: models that extend a shared base, and variant axes that combine (ORCHESTRATOR_PLAN.md)."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import LoadFn, make_project
from pagan.asset import load_asset
from pagan.build import build
from pagan.lint import lint_paths
from pagan.project import Project, load_project

BASE = """\
name: body
template: true
size: [24, 24]
pivot: [12, 15]
directions: 4
outline: none
materials:
  main: { ramp: red }
  trim: { ramp: green }
parts:
  - box: { from: [-3, -1, 0], to: [3, 1, 2], material: main }
  - box: { from: [0, 0, 3], to: [0, 0, 6], material: trim }
    id: antenna
animations:
  wave: { poses: [ {}, { antenna: { offset: [0, 1, 0] } } ] }
"""


def _models(project: Project, **files: str) -> None:
    (project.root / "models").mkdir(exist_ok=True)
    for name, text in files.items():
        (project.root / "models" / f"{name}.model.yaml").write_text(text)


def test_extends_inherits_and_overrides(project: Project) -> None:
    _models(
        project,
        body=BASE,
        scout="name: scout\nextends: body\ndescription: light variant\nremove: [antenna]\n"
        "materials:\n  main: { ramp: blue }\nparts:\n  - box: { from: [3, 0, 3], to: [4, 0, 3], material: trim }\n"
        "animations:\n  wave: { poses: [ {} ] }\n",
    )
    base, findings = load_asset(project.root / "models" / "body.model.yaml", project)
    scout, more = load_asset(project.root / "models" / "scout.model.yaml", project)
    assert base is not None and scout is not None, [f.format() for f in findings + more]
    assert base.template and not scout.template and scout.description == "light variant"
    assert scout.size == base.size and set(scout.animations) == set(base.animations)
    assert scout.frames["e"] != base.frames["e"]  # recoloured, antenna removed, a new part added
    assert "5" in "".join(scout.frames["e"]) and "1" not in "".join(scout.frames["e"])


def test_extends_errors(project: Project) -> None:
    _models(project, body=BASE, a="name: a\nextends: b\n", b="name: b\nextends: a\n",
            c="name: c\nextends: nope\n", d="name: d\nextends: body\nremove: [mast]\n")  # fmt: skip
    messages: dict[str, str] = {}
    for f in lint_paths(project).errors:
        name = f.path.name if f.path else ""
        messages[name] = messages.get(name, "") + f.message + "\n"
    assert "cycle" in messages["a.model.yaml"] and "can't read base model 'nope'" in messages["c.model.yaml"]
    assert "no part id 'mast'" in messages["d.model.yaml"]


def test_template_is_linted_not_built(tmp_path: Path) -> None:
    project = make_project(tmp_path, 'default_palette = "test"\n')
    _models(project, body=BASE, scout="name: scout\nextends: body\n")
    result = build(load_project(project.root))
    assert not result.errors, [f.format() for f in result.errors]
    manifest = json.loads((project.output_dir / "manifest.json").read_text())
    assert set(manifest["assets"]) == {"scout"}


def test_editing_the_base_invalidates_the_cache(project: Project) -> None:
    _models(project, body=BASE, scout="name: scout\nextends: body\n")
    first, _ = load_asset(project.root / "models" / "scout.model.yaml", project)
    _models(project, body=BASE.replace("to: [3, 1, 2]", "to: [5, 1, 2]"))
    second, _ = load_asset(project.root / "models" / "scout.model.yaml", project)
    assert first is not None and second is not None and first.frames["e"] != second.frames["e"]


AXES = """\
name: flag
size: [3, 1]
frames:
  a: |
    135
variant_axes:
  team: {{ green: {{ ramp_swap: {{ red: green }} }}, plain: {{}} }}
  stripe: {{ white: {{ key_swap: {{ "5": "6" }} }}, blue: {{}} }}
{extra}"""


def test_variant_axes_combine(load: LoadFn) -> None:
    asset, findings = load(AXES.format(extra=""), "flag")
    assert asset is not None, [f.format() for f in findings]
    assert set(asset.variants) == {"green+white", "green+blue", "plain+white", "plain+blue"}
    assert asset.variants["green+white"].keys == {"1": "3", "2": "4", "5": "6"}
    assert asset.variants["plain+blue"].keys == {}
    assert set(asset.variant_axes) == {"team", "stripe"}


def test_overlapping_axes_are_an_error(load: LoadFn) -> None:
    text = AXES.format(extra="").replace('{ "5": "6" }', '{ "1": "6" }')
    _, findings = load(text, "flag")
    assert any("both recolour key '1'" in f.message for f in findings)
    _, findings = load(AXES.format(extra="").replace("plain: {}", "plain: { palette: other }"), "flag")
    assert any("ramp_swap/key_swap only" in f.message for f in findings)


def test_axes_in_the_manifest(tmp_path: Path) -> None:
    for sheets in (True, False):
        root = tmp_path / str(sheets)
        root.mkdir()
        project = make_project(root, f'default_palette = "test"\nvariant_sheets = {str(sheets).lower()}\n')
        (project.root / "sprites" / "flag.sprite.yaml").write_text(AXES.format(extra=""))
        result = build(load_project(project.root))
        assert not result.errors, [f.format() for f in result.errors]
        entry = json.loads((project.output_dir / "manifest.json").read_text())["assets"]["flag"]
        assert entry["variant_axes"]["stripe"]["white"] == {"swap": {"#0000ff": "#ffffff"}, "swap_exact": True}
        assert entry["variant_axes"]["team"]["plain"]["swap"] == {}
        assert (set(entry["variants"]) == {"green+white", "green+blue", "plain+white", "plain+blue"}) is sheets
        assert (project.output_dir / "sprites" / "flag.green+white.png").exists() is sheets
