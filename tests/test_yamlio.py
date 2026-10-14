import pytest

from pagan.yamlio import LineMap, YamlError, parse_yaml


def test_mappings_remember_key_lines() -> None:
    data = parse_yaml("a: 1\nb:\n  c: 2\n")
    assert isinstance(data, LineMap)
    assert data.line_of("a") == 1
    assert data.line_of("b") == 2
    assert data["b"].line_of("c") == 3


def test_duplicate_key_is_an_error_with_line() -> None:
    with pytest.raises(YamlError) as exc:
        parse_yaml("a: 1\nb: 2\na: 3\n")
    assert "duplicate key 'a'" in exc.value.message
    assert "line 1" in exc.value.message
    assert exc.value.line == 3


def test_syntax_error_reports_line() -> None:
    with pytest.raises(YamlError) as exc:
        parse_yaml("a: [1, 2\nb: 3\n")
    assert exc.value.line is not None
    assert exc.value.message.startswith("invalid YAML")


def test_unhashable_key_is_an_error() -> None:
    with pytest.raises(YamlError, match="plain values"):
        parse_yaml("? [1, 2]\n: x\n")
