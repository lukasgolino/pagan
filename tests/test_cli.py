import argparse
import json
import os
from typing import Any
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from pagan import __version__
from pagan.cli import main
from pagan.palette import load_palette_file
from pagan.project import load_project

PALETTE = """\
name: duo
colors:
  "0": { hex: "#102030", name: dark }
  "1": { hex: "#f0e0d0", name: light }
ramps:
  all: ["0", "1"]
"""


@pytest.fixture
def in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run_json(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    code = main([*args, "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip().startswith(f"pagan {__version__}")


def test_runs_as_module() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pagan", "--version"], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip().startswith(f"pagan {__version__}")


# --- init ---


def test_init_creates_a_loadable_project(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, result = run_json(["init", "art"], capsys)
    assert code == 0 and result["ok"] is True
    root = in_tmp / "art"
    for name in ("pagan.toml", "STYLE.md", ".gitignore", "palettes", "sprites", "tiles", "models"):
        assert (root / name).exists(), name
    assert load_project(root).config.palette_mode == "strict"
    assert (root / ".gitignore").read_text() == "previews/\n.pagan-cache/\n"


def test_init_open_mode(in_tmp: Path) -> None:
    assert main(["init", "--open"]) == 0
    assert load_project(in_tmp).config.palette_mode == "open"


def test_init_keeps_existing_files(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (in_tmp / "STYLE.md").write_text("mine")
    code, result = run_json(["init"], capsys)
    assert code == 0
    assert result["skipped"] == ["STYLE.md"]
    assert (in_tmp / "STYLE.md").read_text() == "mine"


def test_init_refuses_existing_project(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["init"]) == 0
    capsys.readouterr()
    code, result = run_json(["init"], capsys)
    assert code == 1 and result["ok"] is False
    assert "already exists" in result["findings"][0]["message"]


# --- new palette ---


def test_new_palette_is_valid(in_tmp: Path) -> None:
    main(["init"])
    assert main(["new", "palette", "dusk"]) == 0
    palette = load_palette_file(in_tmp / "palettes" / "dusk.pal.yaml")
    assert palette.name == "dusk" and palette.ramps


def test_new_palette_needs_a_project(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, result = run_json(["new", "palette", "dusk"], capsys)
    assert code == 1
    assert "pagan init" in result["findings"][0]["message"]


def test_new_palette_refuses_overwrite_and_bad_names(in_tmp: Path) -> None:
    main(["init"])
    assert main(["new", "palette", "dusk"]) == 0
    assert main(["new", "palette", "dusk"]) == 1
    assert main(["new", "palette", "Bad Name"]) == 1


# --- palette show ---


def test_palette_show_renders_every_color(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["init"])
    (in_tmp / "palettes" / "duo.pal.yaml").write_text(PALETTE)
    capsys.readouterr()
    code, result = run_json(["palette", "show"], capsys)
    assert code == 0
    outputs = result["outputs"]
    assert outputs == [{"palette": "duo", "path": "previews/palettes/duo.png", "colors": 2, "ramps": 1}]
    image = Image.open(in_tmp / "previews" / "palettes" / "duo.png").convert("RGB")
    colors = image.getcolors(maxcolors=1 << 20)
    assert colors is not None
    present = {rgb for _, rgb in colors}
    assert {(0x10, 0x20, 0x30), (0xF0, 0xE0, 0xD0)} <= present


def test_palette_show_is_deterministic(in_tmp: Path) -> None:
    path = in_tmp / "duo.pal.yaml"
    path.write_text(PALETTE)
    main(["palette", "show", str(path), "--out", "a.png"])
    main(["palette", "show", str(path), "--out", "b.png"])
    assert (in_tmp / "a.png").read_bytes() == (in_tmp / "b.png").read_bytes()


def test_palette_show_reports_invalid_palette(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = in_tmp / "bad.pal.yaml"
    path.write_text('name: bad\ncolors:\n  "a": "#12345"\n')
    code = main(["palette", "show", str(path)])
    assert code == 1
    assert "bad.pal.yaml:3: error E005 [colors.a.hex]" in capsys.readouterr().out


def test_palette_show_by_name_needs_project(in_tmp: Path) -> None:
    assert main(["palette", "show", "dusk"]) == 1


# --- new sprite / tiles, render, lint ---


def test_new_sprite_then_lint_and_render(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["init"])
    (in_tmp / "palettes" / "duo.pal.yaml").write_text(PALETTE)
    assert main(["new", "sprite", "hero", "--size", "8x8", "--palette", "duo", "--frames", "2", "--mirror"]) == 0
    text = (in_tmp / "sprites" / "hero.sprite.yaml").read_text()
    assert "mirror: horizontal" in text and "idle: { frames: [idle_0, idle_1]" in text
    assert "    ....\n" in text  # authored half width
    capsys.readouterr()
    code, result = run_json(["lint"], capsys)
    assert code == 0  # blank frames are only warnings
    assert {f["rule"] for f in result["findings"]} == {"W004"}
    assert main(["render", "hero"]) == 0
    assert (in_tmp / "previews" / "hero" / "native" / "frames" / "idle_0.png").exists()
    assert (in_tmp / "previews" / "hero" / "native" / "sheet.png").exists()


def test_new_tiles(in_tmp: Path) -> None:
    main(["init"])
    (in_tmp / "palettes" / "duo.pal.yaml").write_text(PALETTE)
    assert main(["new", "tiles", "floor", "--size", "4x4", "--palette", "duo", "--frames", "3"]) == 0
    assert "tile_2: |" in (in_tmp / "tiles" / "floor.tiles.yaml").read_text()


def test_new_sprite_requires_palette_in_strict_mode(in_tmp: Path) -> None:
    main(["init"])
    assert main(["new", "sprite", "hero"]) == 1


def test_new_sprite_open_mode_gets_inline_palette(in_tmp: Path) -> None:
    main(["init", "--open"])
    assert main(["new", "sprite", "hero", "--size", "4x4"]) == 0
    assert "\n  colors:\n" in (in_tmp / "sprites" / "hero.sprite.yaml").read_text()
    assert main(["lint"]) == 0


def test_lint_exit_codes(in_tmp: Path) -> None:
    main(["init", "--open"])
    sprite = in_tmp / "sprites" / "x.sprite.yaml"
    sprite.write_text('name: x\npalette:\n  colors:\n    "1": "#ffffff"\nsize: [2, 1]\nframes:\n  a: |\n    1.\n')
    assert main(["lint"]) == 0  # one orphan-pixel warning
    assert main(["lint", "--warnings-as-errors"]) == 1
    sprite.write_text(sprite.read_text().replace("1.", "1z"))
    assert main(["lint"]) == 1
    assert main(["lint", "nope/"]) == 1


def test_render_reports_errors(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["init", "--open"])
    assert main(["render", "missing"]) == 1
    assert "no such asset" in capsys.readouterr().out


def test_commands_use_the_project_containing_the_file(in_tmp: Path) -> None:
    (in_tmp / "art").mkdir()
    (in_tmp / "elsewhere").mkdir()
    main(["init", "art"])
    (in_tmp / "art" / "pagan.toml").write_text('default_palette = "duo"\n')
    (in_tmp / "art" / "palettes" / "duo.pal.yaml").write_text(PALETTE)
    (in_tmp / "art" / "sprites" / "dot.sprite.yaml").write_text("name: dot\nsize: [1, 1]\nframes:\n  a: |\n    1\n")
    os.chdir(in_tmp / "elsewhere")
    assert main(["lint", "../art"]) == 0
    assert main(["render", "../art/sprites/dot.sprite.yaml"]) == 0
    assert (in_tmp / "art" / "previews" / "dot" / "native" / "frames" / "a.png").exists()


def test_frame_named_sheet_does_not_clobber_sheet(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["init", "--open"])
    (in_tmp / "sprites" / "d.sprite.yaml").write_text(
        'name: d\npalette:\n  colors:\n    "1": "#ffffff"\nsize: [2, 1]\nframes:\n  sheet: |\n    11\n  other: |\n    11\n'
    )
    capsys.readouterr()
    code, result = run_json(["render", "d"], capsys)
    assert code == 0
    files = result["outputs"][0]["files"]
    assert len(files) == len(set(files)) == 3


def test_preview_and_gallery(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["init", "--open"])
    (in_tmp / "sprites" / "d.sprite.yaml").write_text(
        'name: d\npalette:\n  colors:\n    "1": "#ffffff"\nsize: [2, 2]\nframes:\n  a: |\n    11\n    11\n'
        "  b: { from: a }\nanimations:\n  idle: [a, b]\n"
    )
    capsys.readouterr()
    code, result = run_json(["preview", "d", "--scale", "4", "--grid", "--bg", "#202020"], capsys)
    assert code == 0
    assert result["outputs"][0]["sheet"] == "previews/d/sheet.png"
    assert result["outputs"][0]["gifs"] == ["previews/d/idle.gif"]
    code, result = run_json(["gallery"], capsys)
    assert code == 0 and result["assets"] == 1
    assert (in_tmp / "previews" / "gallery.png").exists()
    assert main(["preview", "d", "--bg", "plaid"]) == 1


# --- skill ---

REPO = Path(__file__).parent.parent


def test_skill_install(tmp_path: Path) -> None:
    assert main(["skill", "install", str(tmp_path)]) == 0
    skill = (tmp_path / ".claude" / "skills" / "pagan" / "SKILL.md").read_text()
    assert skill.startswith("---\nname: pagan\n")
    assert (tmp_path / ".claude" / "skills" / "pagan" / "reference.md").exists()


def test_repo_skill_copy_is_current() -> None:
    # The repo's own .claude/skills/pagan must match the packaged skill: run `pagan skill install` after editing.
    for name in ("SKILL.md", "reference.md"):
        packaged = (REPO / "src" / "pagan" / "skill" / name).read_text()
        assert (REPO / ".claude" / "skills" / "pagan" / name).read_text() == packaged, name


def test_reference_lists_every_command() -> None:
    reference = (REPO / "src" / "pagan" / "skill" / "reference.md").read_text()
    from pagan.cli import build_parser

    parser = build_parser()
    subparsers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    for command in subparsers.choices:
        assert f"`pagan {command}" in reference, f"reference.md doesn't document `pagan {command}`"


def test_reference_lists_every_rule() -> None:
    reference = (REPO / "src" / "pagan" / "skill" / "reference.md").read_text()
    from pagan.lint import WARNING_RULES

    for rule in WARNING_RULES:
        assert rule in reference
    for number in range(15):
        assert f"E{number:03d}" in reference
