from pathlib import Path

import pytest

from pagan.findings import PaganError
from pagan.project import Config, LintConfig, discover_project, find_project_root, load_project


def write_config(root: Path, text: str) -> None:
    (root / "pagan.toml").write_text(text)


def test_find_project_root_searches_parents(tmp_path: Path) -> None:
    write_config(tmp_path, "")
    nested = tmp_path / "sprites" / "deep"
    nested.mkdir(parents=True)
    assert find_project_root(nested) == tmp_path.resolve()


def test_no_project_means_open_mode(tmp_path: Path) -> None:
    project = discover_project(tmp_path)
    assert project.config_path is None
    assert project.config.palette_mode == "open"


def test_empty_config_uses_defaults(tmp_path: Path) -> None:
    write_config(tmp_path, "")
    assert load_project(tmp_path).config == Config()


def test_full_config(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        'palette_mode = "open"\ndefault_palette = "dusk"\noutput_dir = "../game/gen"\n'
        'preview_dir = "pv"\nexport = ["png", "godot"]\n'
        '[lint]\nmax_ramps_per_sprite = 4\ndisable = ["W001"]\nrequire_outline = true\n',
    )
    project = load_project(tmp_path)
    assert project.config == Config(
        palette_mode="open",
        default_palette="dusk",
        output_dir="../game/gen",
        preview_dir="pv",
        export=("png", "godot"),
        lint=LintConfig(max_ramps_per_sprite=4, disable=("W001",), require_outline=True),
    )
    assert project.preview_dir == tmp_path.resolve() / "pv"


@pytest.mark.parametrize(
    "text, where",
    [
        ('palette_mode = "loose"\n', "palette_mode"),
        ("default_palette = 3\n", "default_palette"),
        ('export = ["unity"]\n', "export"),
        ('typo = "x"\n', "typo"),
        ("[lint]\nmax_ramps_per_sprite = 0\n", "lint.max_ramps_per_sprite"),
        ('[lint]\nrequire_outline = "yes"\n', "lint.require_outline"),
        ("[lint]\nfoo = 1\n", "lint.foo"),
    ],
)
def test_invalid_config(tmp_path: Path, text: str, where: str) -> None:
    write_config(tmp_path, text)
    with pytest.raises(PaganError) as exc:
        load_project(tmp_path)
    assert [f.where for f in exc.value.findings] == [where]
    assert exc.value.findings[0].rule == "E001"


def test_invalid_toml(tmp_path: Path) -> None:
    write_config(tmp_path, "palette_mode = \n")
    with pytest.raises(PaganError) as exc:
        load_project(tmp_path)
    assert "invalid TOML" in exc.value.findings[0].message


def test_unknown_palette_lists_known_ones(tmp_path: Path) -> None:
    write_config(tmp_path, "")
    (tmp_path / "palettes").mkdir()
    (tmp_path / "palettes" / "dusk.pal.yaml").write_text('name: dusk\ncolors: {"a": "#000000"}\n')
    project = load_project(tmp_path)
    assert project.load_palette("dusk").name == "dusk"
    with pytest.raises(PaganError) as exc:
        project.load_palette("dawn")
    assert "palettes: dusk" in exc.value.findings[0].message


def test_non_utf8_config(tmp_path: Path) -> None:
    (tmp_path / "pagan.toml").write_bytes(b"palette_mode = \"\xff\"\n")
    with pytest.raises(PaganError) as exc:
        load_project(tmp_path)
    assert "UTF-8" in exc.value.findings[0].message
