import json
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


def run_json(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, object]]:
    code = main([*args, "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"pagan {__version__}"


def test_runs_as_module() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pagan", "--version"], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == f"pagan {__version__}"


# --- init ---


def test_init_creates_a_loadable_project(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, result = run_json(["init", "art"], capsys)
    assert code == 0 and result["ok"] is True
    root = in_tmp / "art"
    for name in ("pagan.toml", "STYLE.md", ".gitignore", "palettes", "sprites", "tiles"):
        assert (root / name).exists(), name
    assert load_project(root).config.palette_mode == "strict"
    assert (root / ".gitignore").read_text() == "previews/\n"


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
    assert "already exists" in result["findings"][0]["message"]  # type: ignore[index]


# --- new palette ---


def test_new_palette_is_valid(in_tmp: Path) -> None:
    main(["init"])
    assert main(["new", "palette", "dusk"]) == 0
    palette = load_palette_file(in_tmp / "palettes" / "dusk.pal.yaml")
    assert palette.name == "dusk" and palette.ramps


def test_new_palette_needs_a_project(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, result = run_json(["new", "palette", "dusk"], capsys)
    assert code == 1
    assert "pagan init" in result["findings"][0]["message"]  # type: ignore[index]


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
