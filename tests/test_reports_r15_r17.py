"""Fixes for orchestrator reports R16-R17 (ORCHESTRATOR_PLAN.md): Unicode palette keys, variant swap data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import LoadFn, make_project
from pagan.build import build
from pagan.cli import main
from pagan.palette import KEY_ORDER, is_key, load_palette_file
from pagan.project import Project, load_project


def _palette(path: Path, keys: str) -> Path:
    lines = ["name: big", "colors:"] + [f'  "{k}": "#{i:02x}{i:02x}{i:02x}"' for i, k in enumerate(keys)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_unicode_keys(tmp_path: Path) -> None:
    assert len(KEY_ORDER) > 150 and len(set(KEY_ORDER)) == len(KEY_ORDER) and all(is_key(k) for k in KEY_ORDER)
    palette = load_palette_file(_palette(tmp_path / "big.pal.yaml", KEY_ORDER))
    assert len(palette.colors) == len(KEY_ORDER) and "Ω" in palette.colors
    assert not is_key(".") and not is_key("#") and not is_key(" ") and not is_key("ab")


def test_bad_key_message(tmp_path: Path) -> None:
    from pagan.findings import PaganError

    with pytest.raises(PaganError) as exc:
        load_palette_file(_palette(tmp_path / "big.pal.yaml", "a#"))
    assert "Unicode letter" in exc.value.findings[0].message


def test_unicode_grid_and_nfc(project: Project, load: LoadFn) -> None:
    _palette(project.root / "palettes" / "big.pal.yaml", "0éα")
    # the second row spells é as e + combining accent; NFC makes it the same one-character key
    asset, findings = load("name: thing\npalette: big\nsize: [2, 2]\nframes:\n  a: |\n    éα\n    éα\n")
    assert asset is not None, [f.format() for f in findings]
    assert asset.frames["a"] == ("éα", "éα")


def test_import_can_use_more_than_62_colors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL import Image

    image = Image.new("RGBA", (10, 10))
    image.putdata([(i * 2, 255 - i, (i * 7) % 256, 255) for i in range(100)])
    image.save(tmp_path / "many.png")
    make_project(tmp_path, 'palette_mode = "open"\n')
    monkeypatch.chdir(tmp_path)
    assert main(["import", "many.png", "--open", "--max-colors", "100"]) == 0
    text = (tmp_path / "sprites" / "many.sprite.yaml").read_text(encoding="utf-8")
    assert "à" in text


VARIANT_SPRITE = """\
name: flag
size: [2, 1]
frames:
  a: |
    12
variants:
  green: {{ ramp_swap: {{ red: green }} }}
  {extra}
"""


def _godot_project(tmp_path: Path, extra: str = "", sheets: bool = True) -> Project:
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "project.godot").write_text("config_version=5\n")
    (tmp_path / "game" / "art").mkdir()
    config = 'default_palette = "test"\noutput_dir = "../gen"\nexport = ["png", "godot"]\n'
    project = make_project(tmp_path / "game" / "art", config + f"variant_sheets = {'true' if sheets else 'false'}\n")
    (project.root / "sprites" / "flag.sprite.yaml").write_text(VARIANT_SPRITE.format(extra=extra))
    return load_project(project.root)


def test_manifest_swap_tables(tmp_path: Path) -> None:
    result = build(_godot_project(tmp_path))
    assert not result.errors, [f.format() for f in result.errors]
    manifest = json.loads((tmp_path / "game" / "gen" / "manifest.json").read_text())
    green = manifest["assets"]["flag"]["variants"]["green"]
    assert green["swap"] == {"#ff0000": "#00ff00", "#ff8080": "#80ff80"} and green["swap_exact"] is True
    assert green["sheet"].endswith("flag.green.png") and (tmp_path / "game" / "gen" / "sprites" / "flag.green.tres").exists()


def test_variant_sheets_off(tmp_path: Path) -> None:
    result = build(_godot_project(tmp_path, sheets=False))
    assert not result.errors, [f.format() for f in result.errors]
    manifest = json.loads((tmp_path / "game" / "gen" / "manifest.json").read_text())
    assert set(manifest["assets"]["flag"]["variants"]["green"]) == {"swap", "swap_exact"}
    assert not (tmp_path / "game" / "gen" / "sprites" / "flag.green.png").exists()


def test_ambiguous_swap(tmp_path: Path) -> None:
    # Keys 1 and 6 share #ff0000; the variant recolours only key 1, so #ff0000 has two targets.
    project = _godot_project(tmp_path, sheets=False)
    palette = project.root / "palettes" / "test.pal.yaml"
    palette.write_text(palette.read_text().replace('"6": { hex: "#ffffff", name: white }', '"6": { hex: "#ff0000", name: also_red }'))
    (project.root / "sprites" / "flag.sprite.yaml").write_text(
        "name: flag\nsize: [2, 1]\nframes:\n  a: |\n    16\nvariants:\n  split: { key_swap: { \"1\": \"3\" } }\n"
    )
    result = build(load_project(project.root))
    assert any(f.rule == "E006" and "can't be a colour swap" in f.message for f in result.errors)
    (project.root / "pagan.toml").write_text((project.root / "pagan.toml").read_text().replace("variant_sheets = false", "variant_sheets = true"))
    result = build(load_project(project.root))
    assert not result.errors
    manifest = json.loads((tmp_path / "game" / "gen" / "manifest.json").read_text())
    assert manifest["assets"]["flag"]["variants"]["split"]["swap_exact"] is False


def test_variant_preview(project: Project, load: LoadFn, capsys: pytest.CaptureFixture[str]) -> None:
    load(VARIANT_SPRITE.format(extra=""), "flag")
    assert main(["preview", str(project.root / "sprites" / "flag.sprite.yaml"), "--json"]) == 0
    output = json.loads(capsys.readouterr().out)["outputs"][0]
    assert Path(output["variants"]).is_file() and Path(output["variants_1x"]).is_file()
    from PIL import Image

    assert Image.open(output["variants_1x"]).size == (2 * 2 + 1, 1)
