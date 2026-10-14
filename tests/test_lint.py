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
    assert lint_one(project, text) == ["W005"]


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
