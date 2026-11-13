"""Hardware palettes (#91): `hardware: cga | atari-st | atari-st-mono`, E017/W015, scaffolds and `palette snap`."""

import json
from pathlib import Path

import pytest

from pagan.cli import main
from pagan.findings import Finding
from pagan.hardware import CGA_COLORS, HARDWARE, ST_LEVELS, cga_set
from pagan.lint import lint_paths
from pagan.palette import KEY_ORDER, Palette, load_palette_file, parse_palette
from pagan.project import load_project
from pagan.yamlio import parse_yaml


def parse(text: str) -> tuple[Palette | None, list[Finding]]:
    return parse_palette(parse_yaml(text))


def palette(hardware: str, *hexes: str) -> str:
    rows = "\n".join(f'  "{KEY_ORDER[i]}": "{h}"' for i, h in enumerate(hexes))
    return f"name: p\nhardware: {hardware}\ncolors:\n{rows}\n"


def rules(findings: list[Finding]) -> list[str]:
    return [f.rule for f in findings]


def test_tables() -> None:
    assert len(CGA_COLORS) == 16 and len(set(CGA_COLORS)) == 16
    assert ST_LEVELS == (0, 36, 73, 109, 146, 182, 219, 255)
    assert len(HARDWARE["atari-st"].colors) == 512
    assert HARDWARE["atari-st-mono"].colors == ("#000000", "#ffffff")


def test_legal_palettes_parse() -> None:
    for text in (
        palette("cga", "#000000", "#55ffff", "#ff55ff", "#ffffff"),
        palette("cga", "#0000aa", "#00aa00", "#aa0000", "#aa5500"),  # any background + palette 0 low
        palette("atari-st", "#000000", "#244992", "#ffdb00", "#b6b6b6"),
        palette("atari-st-mono", "#000000", "#ffffff"),
    ):
        pal, findings = parse(text)
        assert pal is not None and findings == [], text
        assert pal.hardware in HARDWARE


def test_unknown_hardware() -> None:
    pal, findings = parse(palette("amiga", "#000000"))
    assert pal is None and rules(findings) == ["E017"]
    assert "cga, atari-st, atari-st-mono" in findings[0].message


def test_colour_the_machine_cant_show_names_the_nearest() -> None:
    pal, findings = parse(palette("atari-st", "#000000", "#123456"))
    assert pal is None and rules(findings) == ["E017"]
    assert findings[0].where == "colors.1" and findings[0].line == 5
    assert "nearest is #002449" in findings[0].message
    _, findings = parse(palette("atari-st-mono", "#000000", "#808080"))
    assert "nearest is" in findings[0].message


def test_too_many_colours() -> None:
    pal, findings = parse(palette("atari-st-mono", "#000000", "#ffffff", "#000000"))
    assert pal is not None  # two keys with one colour: still one colour on screen
    pal, findings = parse(palette("cga", "#000000", "#55ffff", "#ff55ff", "#ffffff", "#aa0000"))
    assert pal is None and rules(findings) == ["E017"] and "shows 4 at once" in findings[0].message
    many = [f"#{level:02x}0000" for level in ST_LEVELS] + [f"#00{level:02x}00" for level in ST_LEVELS[1:]] + ["#0000ff", "#0000db"]
    pal, findings = parse(palette("atari-st", *many))
    assert pal is None and "17 colours" in findings[0].message


def test_translucent_colours_are_errors() -> None:
    pal, findings = parse(palette("atari-st", "#00000080"))
    assert pal is None and rules(findings) == ["E017"] and "translucent" in findings[0].message


def test_cga_set_warning() -> None:
    assert cga_set(["#000000", "#55ffff", "#ff5555", "#ffffff"]) == "mode 5 high (cyan/red/white)"
    assert cga_set(["#000000", "#55ffff", "#ff5555", "#ffff55"]) is None
    pal, findings = parse(palette("cga", "#000000", "#55ffff", "#ff5555", "#ffff55"))
    assert pal is not None and rules(findings) == ["W015"]


def test_nearest() -> None:
    st = HARDWARE["atari-st"]
    assert st.nearest("#fefefe") == "#ffffff" and st.nearest("#123456") == "#002449"
    assert HARDWARE["cga"].nearest("#f0f000") == "#ffff55"
    assert HARDWARE["atari-st-mono"].nearest("#202020") == "#000000"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Path:
    monkeypatch.chdir(tmp_path)
    assert main(["init", "art"]) == 0
    monkeypatch.chdir(tmp_path / "art")
    capsys.readouterr()
    return tmp_path / "art"


@pytest.mark.parametrize("hardware", list(HARDWARE))
def test_new_palette_hardware_is_legal(project: Path, hardware: str) -> None:
    assert main(["new", "palette", "p", "--hardware", hardware]) == 0
    pal = load_palette_file(project / "palettes" / "p.pal.yaml")
    assert pal.hardware == hardware
    assert len(pal.colors) == HARDWARE[hardware].max_colors
    assert pal.ramps


def test_lint_reports_palette_warnings(project: Path) -> None:
    (project / "palettes" / "p.pal.yaml").write_text(palette("cga", "#000000", "#55ffff", "#ff5555", "#ffff55"))
    result = lint_paths(load_project(project), [project / "palettes"])
    assert rules(result.findings) == ["W015"] and not result.errors
    assert main(["config", "set", "lint.disable", '["W015"]']) == 0
    assert lint_paths(load_project(project), [project / "palettes"]).findings == []


def test_palette_snap(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = project / "palettes" / "p.pal.yaml"
    path.write_text('name: p\n# keep me\ncolors:\n  "0": "#101010"\n  "1": { hex: "#f0f000", name: lamp }\n')
    assert main(["palette", "snap", "p", "--hardware", "cga", "--dry-run", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["changes"] == {"0": "#000000", "1": "#ffff55"} and result["written"] is False
    assert "#101010" in path.read_text()
    assert main(["palette", "snap", "p", "--hardware", "cga"]) == 0
    text = path.read_text()
    assert "hardware: cga" in text and "# keep me" in text and "name: lamp" in text
    pal = load_palette_file(path)
    assert pal.hardware == "cga" and [c.hex for c in pal.colors.values()] == ["#000000", "#ffff55"]
    capsys.readouterr()
    assert main(["palette", "snap", "p"]) == 0  # the file's own hardware now; nothing left to change
    assert "snapped 0 colour(s)" in capsys.readouterr().out


def test_palette_snap_needs_a_target(project: Path) -> None:
    (project / "palettes" / "p.pal.yaml").write_text('name: p\ncolors:\n  "0": "#101010"\n')
    assert main(["palette", "snap", "p"]) == 1
