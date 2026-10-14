"""Lint warnings W001-W006, rule disabling, and whole-project linting."""

from __future__ import annotations

from pathlib import Path

from conftest import make_project
from pagan.lint import lint_paths
from pagan.project import Project


def lint_one(project: Project, text: str, name: str = "thing") -> list[str]:
    path = project.root / "sprites" / f"{name}.sprite.yaml"
    path.write_text(text)
    return [f.rule for f in lint_paths(project, [path]).findings]


SOLID = "name: thing\nsize: [3, 3]\nframes:\n  a: |\n    111\n    111\n    111\n"


def test_clean_sprite_has_no_findings(project: Project) -> None:
    assert lint_one(project, SOLID) == []


def test_w001_orphan_pixel_with_row_line(project: Project) -> None:
    path = project.root / "sprites" / "thing.sprite.yaml"
    path.write_text("name: thing\nsize: [3, 3]\nframes:\n  a: |\n    1..\n    ...\n    ..1\n")
    findings = lint_paths(project, [path]).findings
    assert [f.rule for f in findings] == ["W001", "W001"]
    assert findings[1].where == "frames.a row 3 col 3" and findings[1].line == 7


def test_w001_mirrored_sprite_reports_authored_half_once(project: Project) -> None:
    text = "name: thing\nsize: [5, 3]\nmirror: horizontal\nframes:\n  a: |\n    ...\n    .1.\n    ...\n"
    assert lint_one(project, text) == ["W001"]


def test_w002_unused_frame(project: Project) -> None:
    text = SOLID + "  b: { from: a }\n  c: |\n    111\n    111\n    111\nanimations:\n  idle: [b]\n"
    assert lint_one(project, text) == ["W002"]  # c is unused; a is used as b's source


def test_w003_too_many_ramps(project: Project) -> None:
    text = "name: thing\nsize: [4, 1]\nframes:\n  a: |\n    1350\n"
    assert lint_one(project, text) == ["W003"]  # red, green, blue, mono > 3


def test_w004_empty_frame(project: Project) -> None:
    assert lint_one(project, "name: thing\nsize: [2, 2]\nframes:\n  a: |\n    ..\n    ..\n") == ["W004"]


def test_w005_jitter(project: Project) -> None:
    text = "name: thing\nsize: [4, 4]\nframes:\n  a: |\n    1111\n    1111\n    1111\n    1111\n  b: |\n    ....\n    .11.\n    .11.\n    ....\nanimations:\n  idle: [a, b]\n"
    assert "W005" in lint_one(project, text)


def test_w006_old_style_version(tmp_path: Path) -> None:
    (tmp_path / "p").mkdir()
    project = make_project(tmp_path / "p", 'default_palette = "test"\nstyle_version = 2\n')
    assert lint_one(project, SOLID) == ["W006"]
    assert lint_one(project, SOLID + "style_version: 2\n") == []


def test_disable_rules(tmp_path: Path) -> None:
    (tmp_path / "p").mkdir()
    project = make_project(tmp_path / "p", 'default_palette = "test"\n[lint]\ndisable = ["W004"]\n')
    assert lint_one(project, "name: thing\nsize: [1, 1]\nframes:\n  a: |\n    .\n") == []


def test_lint_whole_project_reports_broken_palette_once(project: Project) -> None:
    (project.root / "palettes" / "test.pal.yaml").write_text('name: test\ncolors:\n  "1": "#nothex"\n')
    (project.root / "sprites" / "a.sprite.yaml").write_text(SOLID.replace("thing", "a"))
    (project.root / "sprites" / "b.sprite.yaml").write_text(SOLID.replace("thing", "b"))
    result = lint_paths(project)
    palette_findings = [f for f in result.findings if f.path is not None and f.path.name == "test.pal.yaml"]
    assert len(palette_findings) == 1 and palette_findings[0].rule == "E005"
    assert len(result.files) == 4  # 2 palettes + 2 sprites


def test_e012_duplicate_asset_names(project: Project) -> None:
    (project.root / "sprites" / "dup.sprite.yaml").write_text(SOLID.replace("thing", "dup"))
    (project.root / "tiles" / "dup.tiles.yaml").write_text("name: dup\ntile_size: [1, 1]\ntiles:\n  a: |\n    1\n")
    assert [f.rule for f in lint_paths(project).errors] == ["E012", "E012"]  # both files flagged


def test_sprite_with_broken_palette_fails_when_linted_alone(project: Project) -> None:
    (project.root / "palettes" / "test.pal.yaml").write_text('name: wrongname\ncolors:\n  "1": "#ffffff"\n')
    path = project.root / "sprites" / "thing.sprite.yaml"
    path.write_text(SOLID)
    result = lint_paths(project, [path])
    assert result.errors, "a sprite whose palette is broken must not lint clean"


def test_unhashable_ramp_swap_is_an_error_not_a_crash(project: Project) -> None:
    assert lint_one(project, SOLID + "variants:\n  v: { ramp_swap: { red: [green] } }\n") == ["E006"]


def test_derived_frame_error_reported_once(project: Project) -> None:
    text = SOLID + "  b: { from: a, flip: sideways }\n  c: { from: b }\n  d: { from: b }\n"
    path = project.root / "sprites" / "thing.sprite.yaml"
    path.write_text(text)
    from pagan.asset import load_asset

    _, findings = load_asset(path, project)
    assert [f.rule for f in findings] == ["E010"]


def test_w007_big_frame_change(project: Project) -> None:
    text = (
        "name: thing\nsize: [4, 4]\nframes:\n"
        "  a: |\n    1111\n    1111\n    1111\n    1111\n"
        "  b: |\n    2222\n    2222\n    2222\n    2222\n"
        "  c: { from: a, shift: [0, 0] }\n"
        "animations:\n  bad: [a, b]\n  fine: [a, c]\n"
    )
    path = project.root / "sprites" / "thing.sprite.yaml"
    path.write_text(text)
    findings = [f for f in lint_paths(project, [path]).findings if f.rule == "W007"]
    assert [f.where for f in findings] == ["animations.bad"]


def test_w008_too_many_shades_from_one_ramp(tmp_path: Path) -> None:
    (tmp_path / "p").mkdir()
    project = make_project(tmp_path / "p", 'default_palette = "test"\n[lint]\nmax_ramp_steps = 1\n')
    assert lint_one(project, "name: thing\nsize: [2, 1]\nframes:\n  a: |\n    12\n") == ["W008"]
    assert lint_one(project, "name: thing\nsize: [2, 1]\nframes:\n  a: |\n    11\n") == []
