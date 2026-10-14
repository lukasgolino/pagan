"""Long-term management: catalogue, palette adjust, mark, style bump."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from conftest import make_project
from pagan.asset import load_asset_or_raise
from pagan.cli import main
from pagan.color import rgb_to_oklab
from pagan.lint import lint_paths
from pagan.manage import Adjustment, adjust_colors, apply_palette_hexes, bump_style, catalogue, mark
from pagan.palette import load_palette_file
from pagan.project import Project, load_project

SPRITE = "name: {name}\nsize: [2, 1]\nframes:\n  a: |\n    12\n"


@pytest.fixture
def proj(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    project = make_project(tmp_path)
    (tmp_path / "STYLE.md").write_text("# Style bible\n\n## Changelog\n\nIntro line.\n\n- v1: initial style\n")
    for name in ("alpha", "beta"):
        (tmp_path / "sprites" / f"{name}.sprite.yaml").write_text(SPRITE.format(name=name))
    monkeypatch.chdir(tmp_path)
    return project


def test_catalogue_includes_broken_assets(proj: Project) -> None:
    (proj.root / "sprites" / "broken.sprite.yaml").write_text("name: broken\nsize: [1, 1]\nframes:\n  a: |\n    z\n")
    entries = {e.name: e for e in catalogue(proj)}
    assert set(entries) == {"alpha", "beta", "broken"}
    assert entries["broken"].errors == 1 and "fix errors" in entries["broken"].needs(1)
    assert entries["alpha"].needs(1) == ["approve", "describe"]
    assert entries["alpha"].needs(2)[0] == "review for style v2"


def test_adjust_colors_behaviour(proj: Project) -> None:
    palette = proj.load_palette("test")
    keys = list(palette.colors)

    def lightness(hexes: dict[str, str]) -> dict[str, float]:
        return {k: rgb_to_oklab(tuple(int(h[i : i + 2], 16) for i in (1, 3, 5)))[0] for k, h in hexes.items()}  # type: ignore[arg-type]

    original = lightness({k: palette.colors[k].hex for k in keys})
    darker = lightness(adjust_colors(palette, keys, Adjustment(lightness=-0.1)))
    assert all(darker[k] < original[k] + 1e-6 for k in keys if original[k] > 0.05)
    contrast = lightness(adjust_colors(palette, keys, Adjustment(contrast=1.3)))

    def spread(d: dict[str, float]) -> float:
        return max(d.values()) - min(d.values())

    assert spread(contrast) > spread(original) - 1e-6
    grey = adjust_colors(palette, ["1"], Adjustment(saturation=0.0))["1"]
    r, g, b = (int(grey[i : i + 2], 16) for i in (1, 3, 5))
    assert max(r, g, b) - min(r, g, b) <= 2
    # Order within a ramp (dark -> light) survives a contrast change.
    ramp_l = lightness(adjust_colors(palette, keys, Adjustment(contrast=0.7)))
    assert ramp_l["1"] < ramp_l["2"] and ramp_l["3"] < ramp_l["4"]


def test_apply_palette_hexes_keeps_comments_and_forms(tmp_path: Path) -> None:
    path = tmp_path / "p.pal.yaml"
    path.write_text(
        'name: p\n# my notes\ncolors:\n  "a": { hex: "#FF0000", name: red }  # keep me\n  "b": "#00ff00"\n  "c":\n    hex: "#0000ff"\n'
    )
    text = apply_palette_hexes(path, {"a": "#111111", "b": "#222222", "c": "#333333"}, new_name="q")
    assert text == (
        'name: q\n# my notes\ncolors:\n  "a": { hex: "#111111", name: red }  # keep me\n  "b": "#222222"\n  "c":\n    hex: "#333333"\n'
    )


def test_cli_palette_adjust_in_place_updates_assets(proj: Project) -> None:
    before = load_asset_or_raise(proj.root / "sprites" / "alpha.sprite.yaml", proj)
    assert main(["palette", "adjust", "test", "--lightness", "-0.1", "--ramp", "red"]) == 0
    palette = load_palette_file(proj.palette_path("test"))
    assert palette.colors["1"].hex != "#ff0000" and palette.colors["3"].hex == "#00ff00"  # only the red ramp
    after = load_asset_or_raise(proj.root / "sprites" / "alpha.sprite.yaml", load_project(proj.root))
    assert after.frames == before.frames and after.palette.colors["1"].hex == palette.colors["1"].hex
    assert (proj.root / "previews" / "palettes" / "test-adjust.png").exists()


def test_cli_palette_adjust_out_and_dry_run(proj: Project, capsys: pytest.CaptureFixture[str]) -> None:
    original = proj.palette_path("test").read_text()
    assert main(["palette", "adjust", "test", "--saturation", "0.5", "--dry-run"]) == 0
    assert proj.palette_path("test").read_text() == original
    assert main(["palette", "adjust", "test", "--saturation", "0.5", "--out", "test_pastel"]) == 0
    pastel = load_palette_file(proj.palette_path("test_pastel"))
    assert pastel.name == "test_pastel" and pastel.ramps == load_palette_file(proj.palette_path("test")).ramps
    assert main(["palette", "adjust", "test", "--saturation", "0.5", "--out", "test_pastel"]) == 1  # exists
    assert main(["palette", "adjust", "test"]) == 1  # nothing to do
    assert main(["palette", "adjust", "test", "--ramp", "nope", "--hue", "10"]) == 1


def test_mark_sets_and_inserts_fields(proj: Project) -> None:
    path = proj.root / "sprites" / "alpha.sprite.yaml"
    mark([path], "approved", 3)
    text = path.read_text()
    assert text.startswith("name: alpha\nstyle_version: 3\nstatus: approved\n") or text.startswith(
        "name: alpha\nstatus: approved\nstyle_version: 3\n"
    )
    mark([path], "draft", None)
    assert "status: draft" in path.read_text() and path.read_text().count("status:") == 1


def test_style_bump_flags_and_mark_clears(proj: Project) -> None:
    version = bump_style(proj, "more shadows", today=dt.date(2026, 1, 2))
    assert version == 2
    assert "style_version = 2" in (proj.root / "pagan.toml").read_text()
    style = (proj.root / "STYLE.md").read_text()
    assert style.index("- v2 (2026-01-02): more shadows") < style.index("- v1: initial style")
    project = load_project(proj.root)
    assert {f.rule for f in lint_paths(project).findings} == {"W006"}
    assert main(["mark", "--outdated", "--current"]) == 0
    assert not lint_paths(load_project(proj.root)).findings


def test_cli_status_json(proj: Project, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [a["name"] for a in data["assets"]] == ["alpha", "beta"]
    assert data["style_version"] == 1 and data["assets"][0]["needs"] == ["approve", "describe"]
    assert main(["status"]) == 0
    assert main(["style", "bump", "darker"]) == 0
    assert main(["mark", "alpha", "--status", "approved", "--current"]) == 0
    capsys.readouterr()
    main(["status", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["assets"][0]["needs"] == ["describe"] and data["assets"][1]["needs"][0] == "review for style v2"


def test_status_outside_a_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "empty").mkdir()
    monkeypatch.chdir(tmp_path / "empty")
    assert main(["status"]) == 1
    assert "no pagan.toml" in capsys.readouterr().out
