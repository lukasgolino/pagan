"""#7 (R36): big sprites: indexed-PNG frame sources (`frames_png:`), the per-sprite cache and parallel builds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from conftest import make_project
from pagan import api, asset as asset_module, spritecache
from pagan.asset import load_asset
from pagan.build import build
from pagan.lint import lint_paths
from pagan.project import Project

GRID = """\
name: blob
size: [6, 4]
outline: auto
frames:
  a: |
    ......
    ..12..
    ..21..
    ......
  b: |
    ......
    .122..
    ..21..
    ......
  c: { from: a, flip: horizontal }
animations:
  pulse: { frames: [a, b, c], fps: 8 }
"""


def _png(path: Path, cells: list[list[str]], width: int, keys: str = ".12", columns: int = 2, mode: str = "P") -> None:
    """An indexed PNG of `cells` (rows of characters), index = position in `keys`."""
    height = len(cells[0])
    rows = -(-len(cells) // columns)
    data = np.zeros((rows * height, columns * width), dtype=np.uint8)
    for i, cell in enumerate(cells):
        x, y = (i % columns) * width, (i // columns) * height
        for dy, row in enumerate(cell):
            for dx, ch in enumerate(row):
                data[y + dy, x + dx] = keys.index(ch)
    image = Image.fromarray(data, "P")
    image.putpalette([0, 0, 0, 255, 0, 0, 255, 128, 128])
    (image.convert("RGB") if mode == "RGB" else image).save(path)


def _png_sprite(project: Project, frames_png: str, extra: str = "") -> Path:
    path = project.sprites_dir / "blob.sprite.yaml"
    path.write_text(
        "name: blob\nsize: [6, 4]\noutline: auto\n"
        f"frames_png: {frames_png}\n{extra}"
        "animations:\n  pulse: { frames: [a, b, c], fps: 8 }\n"
    )
    return path


CELLS = [["......", "..12..", "..21..", "......"], ["......", ".122..", "..21..", "......"]]
KEYS = '{ 0: ".", 1: "1", 2: "2" }'


def _outputs(project: Project) -> dict[str, bytes]:
    out = project.root / "out"
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}


def _project(root: Path) -> Project:
    root.mkdir(parents=True, exist_ok=True)
    return make_project(root, 'default_palette = "test"\noutput_dir = "out"\n')


def test_frames_png_builds_like_the_grid(tmp_path: Path) -> None:
    grid = _project(tmp_path / "grid")
    (grid.sprites_dir / "blob.sprite.yaml").write_text(GRID)
    png = _project(tmp_path / "png")
    _png(png.sprites_dir / "blob.png", CELLS, 6)
    _png_sprite(png, f"{{ file: blob.png, keys: {KEYS}, frames: [a, b] }}", "frames:\n  c: { from: a, flip: horizontal }\n")
    a, _ = load_asset(grid.sprites_dir / "blob.sprite.yaml", grid)
    b, findings = load_asset(png.sprites_dir / "blob.sprite.yaml", png)
    assert a is not None and b is not None, findings
    assert a.frames == b.frames and list(b.frames) == ["a", "b", "c"]
    assert b.png_frames == {"a", "b"} and b.frames_png == (png.sprites_dir / "blob.png").resolve()
    assert not build(grid).errors and not build(png).errors
    assert _outputs(grid) == _outputs(png)


@pytest.mark.parametrize(
    ("spec", "rule", "text"),
    [
        (f"{{ file: blob.png, keys: {KEYS}, frames: [a, b, x] }}", "E003", "has 4 cells"),  # noqa: E501 - not reached
        ('{ file: blob.png, keys: { 0: ".", 1: "1" }, frames: [a, b] }', "E002", "index 2"),
        ('{ file: blob.png, keys: { 0: ".", 1: "1", 2: "z" }, frames: [a, b] }', "E002", "isn't '.' or a palette key"),
        (f"{{ file: blob.png, keys: {KEYS}, frames: [a] }}", "E003", "has pixels but no name"),
        (f"{{ file: missing.png, keys: {KEYS}, frames: [a, b] }}", "E001", "can't read"),
        (f"{{ file: ../../outside.png, keys: {KEYS}, frames: [a, b] }}", "E001", "outside the project"),
        (f"{{ file: blob.png, keys: {KEYS}, frames: [a, a] }}", "E001", "listed twice"),
        (f"{{ file: blob.png, keys: {KEYS}, frames: [a, b], extra: 1 }}", "E001", "unknown frames_png field"),
    ],
)
def test_frames_png_errors(project: Project, spec: str, rule: str, text: str) -> None:
    if "x]" in spec:
        _png(project.sprites_dir / "blob.png", CELLS, 6)  # 2 cells, 3 names
        text = "names 3 frames, but the PNG has 2 cells"
    else:
        _png(project.sprites_dir / "blob.png", CELLS, 6)
    path = _png_sprite(project, spec, "frames:\n  c: { from: a }\n")
    asset, findings = load_asset(path, project)
    assert asset is None
    assert any(f.rule == rule and text in f.message for f in findings), [f.format() for f in findings]


def test_frames_png_must_be_indexed_and_fit_the_frame_size(project: Project) -> None:
    _png(project.sprites_dir / "blob.png", CELLS, 6, mode="RGB")
    path = _png_sprite(project, f"{{ file: blob.png, keys: {KEYS}, frames: [a, b] }}", "frames:\n  c: { from: a }\n")
    assert any("indexed" in f.message for f in load_asset(path, project)[1])
    _png(project.sprites_dir / "blob.png", [[r + "." for r in c] for c in CELLS], 7)
    assert any(f.rule == "E003" and "whole number" in f.message for f in load_asset(path, project)[1])


def test_frames_png_name_clash_with_frames(project: Project) -> None:
    _png(project.sprites_dir / "blob.png", CELLS, 6)
    path = _png_sprite(project, f"{{ file: blob.png, keys: {KEYS}, frames: [a, b] }}", "frames:\n  a: { from: b }\n  c: { from: a }\n")
    assert any("also in frames_png.frames" in f.message for f in load_asset(path, project)[1])


def test_frames_png_findings_point_at_the_cell(project: Project) -> None:
    cells = [["......", "..1...", "......", "......"], CELLS[1]]
    _png(project.sprites_dir / "blob.png", cells, 6)
    path = _png_sprite(project, f"{{ file: blob.png, keys: {KEYS}, frames: [a, b] }}", "frames:\n  c: { from: b }\n")
    w001 = [f for f in lint_paths(project).findings if f.rule == "W001"]
    assert w001 and w001[0].line == 4 and w001[0].where == "frames.a row 2 col 3"
    assert path.read_text().splitlines()[3].startswith("frames_png")


def test_api_frames_png_round_trip(project: Project) -> None:
    frames = {"a": api.Canvas(6, 4).rect(1, 1, 3, 2, "1"), "b": api.Canvas(6, 4).rect(2, 1, 4, 2, "2")}
    spec = api.frames_png(project.sprites_dir / "blob.png", frames, (6, 4), api.palette("test", project))
    assert spec == {"file": "blob.png", "keys": {0: ".", 1: "1", 2: "2"}, "frames": ["a", "b"]}
    text = api.sprite_yaml("blob", (6, 4), {}, frames_png=spec)
    assert "frames:\n" not in text.replace("frames: [", "")
    path = api.write(project.sprites_dir / "blob.sprite.yaml", text)
    asset, findings = load_asset(path, project)
    assert asset is not None, findings
    assert {n: list(g) for n, g in asset.frames.items()} == {n: c.rows() for n, c in frames.items()}


# --- cache ------------------------------------------------------------------------------------


@pytest.fixture
def cache_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spritecache, "CACHE_MIN_PIXELS", 0)
    monkeypatch.setenv("PAGAN_JOBS", "1")


def _no_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any) -> Any:
        raise AssertionError("parsed again instead of using the cache")

    monkeypatch.setattr(asset_module, "parse_asset", fail)


def test_cache_hit_gives_the_same_results(project: Project, cache_everything: None, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(project.root)
    (project.sprites_dir / "blob.sprite.yaml").write_text(GRID.replace("outline: auto\n", "").replace("..21..\n    ......\n  c", "..21..\n    2.....\n  c"))
    first = lint_paths(project)
    assert any(f.rule == "W001" for f in first.findings)
    assert not build(project).errors
    built = _outputs(project)
    assert list((project.root / ".pagan-cache" / "sprites").iterdir())
    with monkeypatch.context() as m:
        _no_parsing(m)
        second = lint_paths(project)
        (project.root / "out" / "sprites" / "blob.png").unlink()
        assert not build(project).errors
    assert [f.to_dict() for f in second.findings] == [f.to_dict() for f in first.findings]
    assert second.assets[0].frames == first.assets[0].frames
    assert _outputs(project) == built


@pytest.mark.parametrize("change", ["source", "palette", "config", "png"])
def test_cache_misses_when_an_input_changes(project: Project, cache_everything: None, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    _png(project.sprites_dir / "blob.png", CELLS, 6)
    path = _png_sprite(project, f"{{ file: blob.png, keys: {KEYS}, frames: [a, b] }}", "frames:\n  c: { from: a }\n")
    asset, _ = load_asset(path, project)
    assert asset is not None and asset.cache_key is not None
    if change == "source":
        path.write_text(path.read_text().replace("fps: 8", "fps: 9"))
    elif change == "palette":
        palette = project.palettes_dir / "test.pal.yaml"
        palette.write_text(palette.read_text().replace("#ff0000", "#fe0000"))
        project._palettes.clear()
    elif change == "config":
        (project.root / "pagan.toml").write_text('default_palette = "test"\nstyle_version = 2\n')
        project = type(project)(project.root, type(project.config)(default_palette="test", style_version=2), project.config_path)
    else:
        _png(project.sprites_dir / "blob.png", [CELLS[1], CELLS[0]], 6)
    calls: list[int] = []
    real = asset_module.parse_asset
    def counting(*args: Any) -> Any:
        calls.append(1)
        return real(*args)

    monkeypatch.setattr(asset_module, "parse_asset", counting)
    again, _ = load_asset(path, project)
    assert calls and again is not None
    if change == "png":
        assert again.frames["a"] == asset.frames["b"]


def test_small_sprites_are_not_cached(project: Project) -> None:
    (project.sprites_dir / "blob.sprite.yaml").write_text(GRID)
    asset, _ = load_asset(project.sprites_dir / "blob.sprite.yaml", project)
    assert asset is not None and asset.cache_key is None
    assert not (project.root / ".pagan-cache").exists()


def test_cache_key_covers_the_code() -> None:
    assert len(spritecache.code_fingerprint()) == 64
    spritecache.code_fingerprint.cache_clear()
    old = spritecache.CACHE_VERSION
    try:
        before = spritecache.code_fingerprint()
        spritecache.CACHE_VERSION = old + "x"
        spritecache.code_fingerprint.cache_clear()
        assert spritecache.code_fingerprint() != before
    finally:
        spritecache.CACHE_VERSION = old
        spritecache.code_fingerprint.cache_clear()


# --- parallel ---------------------------------------------------------------------------------


def _big_project(root: Path) -> Project:
    """Two sprites of 4 frames at 512x512 (1 MP each: cached and built in parallel), stored as small PNGs."""
    project = _project(root)
    for s in range(2):
        frames = {}
        for i in range(4):
            canvas = api.Canvas(512, 512)
            canvas.ellipse(256, 256, 100 + 20 * i, 80 + 10 * s, "1").ellipse(256, 256, 40, 40, "2")
            frames[f"f{i}"] = canvas
        spec = api.frames_png(project.sprites_dir / f"big{s}.png", frames, (512, 512))
        api.write(project.sprites_dir / f"big{s}.sprite.yaml", api.sprite_yaml(f"big{s}", (512, 512), {}, {"go": {"frames": list(frames)}}, frames_png=spec, variants={"dim": {"key_swap": {"1": "3"}}}))
    return project


def test_parallel_build_is_identical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAGAN_JOBS", "1")
    serial = _big_project(tmp_path / "serial")
    serial_lint = lint_paths(serial)
    assert not build(serial).errors
    monkeypatch.setenv("PAGAN_JOBS", "2")
    parallel = _big_project(tmp_path / "parallel")
    parallel_lint = lint_paths(parallel)
    assert all(a.cache_key is not None for a in parallel_lint.assets)
    assert not build(parallel).errors
    assert [f.message for f in parallel_lint.findings] == [f.message for f in serial_lint.findings]
    assert _outputs(parallel) == _outputs(serial)
    manifest = json.loads((parallel.root / "out" / "manifest.json").read_text())
    assert set(manifest["assets"]) == {"big0", "big1"} and "dim" in manifest["assets"]["big0"]["variants"]
