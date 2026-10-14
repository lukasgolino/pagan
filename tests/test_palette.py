from pathlib import Path

import pytest

from pagan.findings import Finding, PaganError
from pagan.palette import Palette, load_palette_file, parse_palette
from pagan.yamlio import parse_yaml

VALID = """\
name: test
colors:
  "0": { hex: "#000000", name: ink }
  "1": { hex: "#FF8800" }
  2: "#ffffff"
ramps:
  warm: ["0", "1", 2]
"""


def parse(text: str, **kwargs: object) -> tuple[Palette | None, list[Finding]]:
    return parse_palette(parse_yaml(text), **kwargs)  # type: ignore[arg-type]


def errors(text: str, **kwargs: object) -> list[Finding]:
    palette, findings = parse(text, **kwargs)
    assert palette is None
    return findings


def test_valid_palette() -> None:
    palette, findings = parse(VALID)
    assert findings == []
    assert palette is not None
    assert list(palette.colors) == ["0", "1", "2"]
    assert palette.colors["0"].name == "ink"
    assert palette.colors["1"].hex == "#ff8800"  # normalized to lowercase
    assert palette.colors["1"].rgb == (255, 136, 0)
    assert palette.colors["2"].hex == "#ffffff"  # shorthand string form, unquoted int key
    assert palette.ramps == {"warm": ("0", "1", "2")}


def test_ramps_are_optional() -> None:
    palette, _ = parse('name: x\ncolors:\n  "a": "#123456"\n')
    assert palette is not None and palette.ramps == {}


def test_missing_name_and_colors() -> None:
    findings = errors("ramps: {}\n")
    messages = [f.message for f in findings]
    assert "missing required field 'name'" in messages
    assert "missing required field 'colors'" in messages
    assert all(f.rule == "E001" for f in findings)


def test_inline_palette_needs_no_name() -> None:
    palette, findings = parse('colors:\n  "a": "#123456"\n', inline=True)
    assert findings == [] and palette is not None and palette.name is None


def test_not_a_mapping() -> None:
    assert errors("- a\n- b\n")[0].rule == "E001"


def test_unknown_field() -> None:
    findings = errors('name: x\ncolours:\n  "a": "#123456"\n')
    assert any(f.rule == "E001" and "unknown field 'colours'" in f.message for f in findings)


def test_name_must_match_file() -> None:
    findings = errors('name: other\ncolors:\n  "a": "#123456"\n', expected_name="test")
    assert findings[0].rule == "E005" and "expected 'test'" in findings[0].message


def test_bad_hex_has_line_and_location() -> None:
    findings = errors('name: x\ncolors:\n  "a": "#123456"\n  "b": { hex: "#12345" }\n')
    assert len(findings) == 1
    assert findings[0].rule == "E005"
    assert findings[0].line == 4
    assert findings[0].where == "colors.b.hex"


def test_unquoted_hex_in_flow_mapping_is_a_yaml_error_with_hint(tmp_path: Path) -> None:
    # Inside { ... } the "#" comments out the closing brace, so this is a YAML syntax error.
    path = tmp_path / "x.pal.yaml"
    path.write_text('name: x\ncolors:\n  "a": { hex: "#000000" }\n  "b": { hex: #123456 }\n')
    with pytest.raises(PaganError) as exc:
        load_palette_file(path)
    finding = exc.value.findings[0]
    assert finding.rule == "E001"
    assert 'line 4 has an unquoted hex color' in finding.message


def test_unquoted_hex_in_block_mapping_explains_yaml_comment() -> None:
    findings = errors('name: x\ncolors:\n  "a":\n    hex: #123456\n')
    assert "quote" in findings[0].message


def test_unquoted_shorthand_hex_explains_yaml_comment() -> None:
    findings = errors('name: x\ncolors:\n  "a": #123456\n')
    assert "quote" in findings[0].message


@pytest.mark.parametrize("key", ['"."', '"ab"', '"-"', "10", "true"])
def test_invalid_keys(key: str) -> None:
    findings = errors(f'name: x\ncolors:\n  {key}: "#123456"\n')
    assert findings[0].rule == "E005"


def test_duplicate_key_after_normalizing() -> None:
    findings = errors('name: x\ncolors:\n  1: "#000000"\n  "1": "#ffffff"\n')
    assert findings[0].rule == "E005" and "duplicate" in findings[0].message


def test_ramp_unknown_key() -> None:
    findings = errors('name: x\ncolors:\n  "a": "#123456"\nramps:\n  r: ["a", "z"]\n')
    assert [f.rule for f in findings] == ["E005"]
    assert "'z'" in findings[0].message and findings[0].where == "ramps.r"


def test_ramp_repeated_key() -> None:
    findings = errors('name: x\ncolors:\n  "a": "#123456"\nramps:\n  r: ["a", "a"]\n')
    assert "twice" in findings[0].message


def test_ramp_does_not_repeat_errors_for_invalid_colors() -> None:
    # "b" has a bad hex: report that once, not again as an unknown ramp key.
    findings = errors('name: x\ncolors:\n  "a": "#123456"\n  "b": "nope"\nramps:\n  r: ["a", "b"]\n')
    assert len(findings) == 1 and findings[0].where == "colors.b.hex"


def test_empty_ramp() -> None:
    findings = errors('name: x\ncolors:\n  "a": "#123456"\nramps:\n  r: []\n')
    assert findings[0].rule == "E005"


def test_unknown_color_field() -> None:
    findings = errors('name: x\ncolors:\n  "a": { hex: "#123456", alpha: 0.5 }\n')
    assert findings[0].rule == "E001" and "alpha" in findings[0].message


def test_load_palette_file(tmp_path: Path) -> None:
    path = tmp_path / "test.pal.yaml"
    path.write_text(VALID)
    palette = load_palette_file(path)
    assert palette.name == "test" and palette.path == path


def test_load_palette_file_yaml_error(tmp_path: Path) -> None:
    path = tmp_path / "test.pal.yaml"
    path.write_text('name: test\nname: again\ncolors: {"a": "#000000"}\n')
    with pytest.raises(PaganError) as exc:
        load_palette_file(path)
    finding = exc.value.findings[0]
    assert finding.rule == "E001" and finding.line == 2 and finding.path == path


def test_load_palette_file_checks_file_name(tmp_path: Path) -> None:
    path = tmp_path / "other.pal.yaml"
    path.write_text(VALID)
    with pytest.raises(PaganError) as exc:
        load_palette_file(path)
    assert exc.value.findings[0].rule == "E005"
