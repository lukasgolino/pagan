"""LOOSE! title-logo reports R30-R38 (GitHub issues #1-#9): translucent palette colours (#2)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from conftest import make_project
from pagan.asset import load_asset
from pagan.importer import import_png
from pagan.manage import Adjustment, adjust_colors
from pagan.palette import parse_palette
from pagan.project import Project, load_project
from pagan.render import frame_image, sheet_image
from pagan.swatch import render_swatch

ALPHA_PALETTE = """\
name: glow
colors:
  "0": "#101010"
  "1": "#f0d040"
  "s": { hex: "#00000080", name: shadow }
  "g": "#FFE08040"
  "o": "#203040ff"
ramps:
  gold: ["0", "1"]
"""


def _alpha_project(root: Path, config: str = "") -> Project:
    root.mkdir(parents=True, exist_ok=True)
    project = make_project(root, f'default_palette = "glow"\n{config}')
    (root / "palettes" / "glow.pal.yaml").write_text(ALPHA_PALETTE)
    return load_project(root)


def _sprite(project: Project, body: str, name: str = "spark") -> Path:
    path = project.root / "sprites" / f"{name}.sprite.yaml"
    path.write_text(f"name: {name}\nsize: [3, 3]\n{body}")
    return path


def rules(findings: list) -> set[str]:  # type: ignore[type-arg]
    return {f.rule for f in findings}


# --- R31 (#2): translucent palette colours ----------------------------------------------------


def test_palette_accepts_rrggbbaa_and_normalises_opaque() -> None:
    palette, findings = parse_palette(
        {"name": "p", "colors": {"0": "#00000080", "1": "#AABBCCFF", "2": {"hex": "#ff000000"}}}
    )
    assert palette is not None, findings
    assert palette.colors["0"].hex == "#00000080" and palette.colors["0"].rgba == (0, 0, 0, 128)
    assert palette.colors["1"].hex == "#aabbcc" and palette.colors["1"].alpha == 255  # "ff" = opaque, one spelling
    assert palette.colors["2"].alpha == 0
    _, bad = parse_palette({"name": "p", "colors": {"0": "#0000008"}})
    assert rules(bad) == {"E005"} and "#rrggbbaa" in bad[0].message


def test_translucent_pixels_render_with_their_alpha(tmp_path: Path) -> None:
    project = _alpha_project(tmp_path)
    asset, findings = load_asset(_sprite(project, 'frames:\n  a: |\n    s1g\n    ...\n    ...\n'), project)
    assert asset is not None, [f.format() for f in findings]
    image = frame_image(asset, "a")
    assert image.getpixel((0, 0)) == (0, 0, 0, 128)
    assert image.getpixel((1, 0)) == (240, 208, 64, 255)
    assert image.getpixel((2, 0)) == (255, 224, 128, 64)
    assert sheet_image(asset).getpixel((0, 0)) == (0, 0, 0, 128)


def test_default_outline_colour_is_the_darkest_opaque_one(tmp_path: Path) -> None:
    project = _alpha_project(tmp_path)
    asset, findings = load_asset(_sprite(project, "outline: auto\nframes:\n  a: |\n    ...\n    .1.\n    ...\n"), project)
    assert asset is not None, [f.format() for f in findings]
    assert asset.outline_color == "0"  # not the translucent black "s"


def test_require_opaque_is_opt_in(tmp_path: Path) -> None:
    body = 'frames:\n  a: |\n    s1.\n    ...\n    ...\n'
    project = _alpha_project(tmp_path / "free")
    asset, _ = load_asset(_sprite(project, body), project)
    assert asset is not None
    strict = _alpha_project(tmp_path / "strict", "[lint]\nrequire_opaque = true\n")
    asset, findings = load_asset(_sprite(strict, body), strict)
    assert asset is None and rules(findings) == {"E015"} and "s" in findings[0].message
    opaque_only, findings = load_asset(_sprite(strict, 'frames:\n  a: |\n    01.\n    ...\n    ...\n', "plain"), strict)
    assert opaque_only is not None, [f.format() for f in findings]


def test_models_reject_translucent_materials(tmp_path: Path) -> None:
    project = _alpha_project(tmp_path)
    (project.root / "models").mkdir()
    path = project.root / "models" / "crate.model.yaml"
    path.write_text(
        "name: crate\nsize: [16, 16]\ndirections: 1\nmaterials:\n  wood: { keys: [\"0\", \"s\"] }\n"
        "parts:\n  - { box: [0, 0, 0, 3, 3, 3], material: wood }\n"
    )
    asset, findings = load_asset(path, project)
    assert asset is None
    assert any(f.rule == "E013" and "translucent" in f.message for f in findings), [f.format() for f in findings]


def test_palette_adjust_keeps_alpha(tmp_path: Path) -> None:
    project = _alpha_project(tmp_path)
    palette = project.load_palette("glow")
    out = adjust_colors(palette, ["s", "1"], Adjustment(lightness=0.1))
    assert out["s"].endswith("80") and len(out["s"]) == 9
    assert len(out["1"]) == 7


def test_import_snaps_to_opaque_colours_only(tmp_path: Path) -> None:
    project = _alpha_project(tmp_path)
    image = Image.new("RGBA", (2, 1), (0, 0, 0, 255))  # pure black: "s" is closer by RGB, but translucent
    rows, _, _ = import_png(image, palette=project.load_palette("glow"), scale=1)
    assert rows == ["00"]


def test_swatch_draws_translucent_colours(tmp_path: Path) -> None:
    project = _alpha_project(tmp_path)
    image = render_swatch(project.load_palette("glow"))
    assert image.width > 0 and image.height > 0
