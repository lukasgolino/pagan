"""Timeline previews: scenes/<name>.timeline.yaml composed in time (#16)."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import pytest
from PIL import Image

from conftest import make_project
from pagan.cli import main
from pagan.lint import lint_paths
from pagan.project import Project
from pagan.timeline import Timeline, gif_durations, load_timeline, parse_times

BLUE, RED, WHITE = (0, 0, 255, 255), (255, 0, 0, 255), (255, 255, 255, 255)

DOT = """\
name: dot
size: [2, 2]
frames:
  a: |
    55
    55
  b: |
    11
    11
animations:
  blink: { frames: [a, b], fps: 2, loop: true }
  pop: { frames: [a, b], fps: 2, loop: false, durations: [1, 3] }
  hold: { frames: [b], fps: 2, loop: true }
variants:
  pale: { key_swap: { "5": "6" } }
"""

BIG = """\
name: big
size: [4, 4]
pivot: [0, 0]
supersample: 2
frames:
  a: |
    5555
    5555
    5555
    5555
"""


@pytest.fixture
def scene_project(tmp_path: Path) -> Project:
    project = make_project(tmp_path)
    (tmp_path / "sprites" / "dot.sprite.yaml").write_text(DOT)
    (tmp_path / "sprites" / "big.sprite.yaml").write_text(BIG)
    (tmp_path / "scenes").mkdir()
    return project


def scene(project: Project, layers: str, header: str = "size: [8, 4]\nfps: 4\nduration: 4\n", name: str = "s") -> Path:
    path = project.scenes_dir / f"{name}.timeline.yaml"
    path.write_text(header + "layers:\n" + layers)
    return path


def loaded(project: Project, layers: str, **kw: str) -> Timeline:
    timeline, findings = load_timeline(scene(project, layers, **kw), project)
    assert timeline is not None, [f.format() for f in findings]
    assert not findings
    return timeline


def px(image: Image.Image, x: int, y: int) -> tuple[int, ...]:
    return tuple(image.getpixel((x, y)))  # type: ignore[arg-type]


def test_pivot_goes_to_at_and_layers_draw_in_order(scene_project: Project) -> None:
    t = loaded(scene_project, "  - {sprite: dot, anim: a, at: [3, 4]}\n  - {sprite: dot, anim: b, at: [4, 4]}\n")
    image = t.render(Fraction(0))
    # dot's default pivot is bottom centre (1, 2): at [3, 4] -> top-left (2, 2)
    assert px(image, 2, 2) == BLUE
    assert px(image, 3, 3) == RED  # the second layer covers the first
    assert px(image, 4, 3) == RED and px(image, 5, 3) == (0, 0, 0, 0)
    assert px(image, 0, 0) == (0, 0, 0, 0)


def test_looping_animation_follows_fps(scene_project: Project) -> None:
    t = loaded(scene_project, "  - {sprite: dot, anim: blink, at: [1, 2]}\n")
    colours = [px(t.render(t.frame_time(i)), 0, 0) for i in range(6)]  # 4 fps timeline, 2 fps animation
    assert colours == [BLUE, BLUE, RED, RED, BLUE, BLUE]


def test_one_shot_durations_hold_and_then(scene_project: Project) -> None:
    held = loaded(scene_project, "  - {sprite: dot, anim: pop, at: [1, 2]}\n")
    # pop: a for 1 step (0.5 s), b for 3 steps (1.5 s), then holds b
    assert [px(held.render(Fraction(n, 4)), 0, 0) for n in (0, 1, 2, 7, 12)] == [BLUE, BLUE, RED, RED, RED]
    chained = loaded(scene_project, "  - {sprite: dot, anim: pop, at: [1, 2], then: blink, start: 1}\n")
    assert px(chained.render(Fraction(1, 2)), 0, 0) == (0, 0, 0, 0)  # not started yet
    # pop ends 2 s after its start (t = 3): blink restarts from its first frame
    assert [px(chained.render(Fraction(n, 4)), 0, 0) for n in (11, 12, 13, 14)] == [RED, BLUE, BLUE, RED]


def test_move_is_linear_and_rounded_then_stays(scene_project: Project) -> None:
    t = loaded(scene_project, "  - {sprite: dot, anim: a, from: [1, 2], to: [7, 2], duration: 2}\n")

    def left(time: Fraction) -> int:
        image = t.render(time)
        return min(x for x in range(8) if px(image, x, 0)[3])

    assert left(Fraction(0)) == 0
    assert left(Fraction(1, 2)) == 2  # 1 + 6 * 0.25 = 2.5 -> 3 (half up), minus pivot 1
    assert left(Fraction(1)) == 3
    assert left(Fraction(3)) == 6  # arrived: stays at `to`


def test_alpha_fades_and_duration(scene_project: Project) -> None:
    t = loaded(scene_project, "  - {sprite: dot, anim: a, at: [1, 2], alpha: 0.5, fade_in: 1, duration: 2, fade_out: 0.5}\n")
    assert px(t.render(Fraction(0)), 0, 0) == (0, 0, 0, 0)  # fade_in starts at 0
    assert px(t.render(Fraction(1, 2)), 0, 0) == (0, 0, 255, 64)  # 255 * 0.5 * 0.5 = 63.75
    assert px(t.render(Fraction(1)), 0, 0) == (0, 0, 255, 128)
    assert px(t.render(Fraction(7, 4)), 0, 0) == (0, 0, 255, 64)  # fading out towards t = 2
    assert px(t.render(Fraction(2)), 0, 0) == (0, 0, 0, 0)  # shown for `duration` only


def test_alpha_composites_over_background(scene_project: Project) -> None:
    header = 'size: [4, 4]\nfps: 1\nduration: 1\nbackground: "#ff0000"\n'
    t = loaded(scene_project, "  - {sprite: dot, anim: a, at: [1, 2], alpha: 0.5}\n", header=header)
    assert px(t.render(Fraction(0)), 0, 0) == (127, 0, 128, 255)
    assert px(t.render(Fraction(0)), 3, 3) == (255, 0, 0, 255)


def test_variant_and_supersample(scene_project: Project) -> None:
    t = loaded(scene_project, "  - {sprite: dot, anim: a, at: [1, 2], variant: pale}\n  - {sprite: big, anim: a, at: [6, 0]}\n")
    image = t.render(Fraction(0))
    assert px(image, 0, 0) == WHITE
    # big is drawn at 2x: shown as built (2x2), pivot [0, 0] -> top-left at the `at`
    assert px(image, 6, 0) == BLUE and px(image, 7, 1) == BLUE
    assert px(image, 5, 0) == (0, 0, 0, 0)


def test_errors_are_all_collected_with_lines_and_hints(scene_project: Project) -> None:
    layers = (
        "  - {sprite: dott, anim: a, at: [0, 0]}\n"
        "  - {sprite: dot, anim: blnk, at: [0, 0]}\n"
        "  - {sprite: dot, anim: a, at: [0, 0], variant: pail}\n"
        "  - {sprite: dot, anim: blink, at: [0, 0], then: a}\n"
        "  - {sprite: dot, anim: a, from: [0, 0]}\n"
        "  - {sprite: dot, anim: a, at: [0, 0], ease: in}\n"
    )
    header = "size: [8, 4]\nfps: 0\nduration: 4\nzoom: 2\n"
    timeline, findings = load_timeline(scene(scene_project, layers, header=header), scene_project)
    assert timeline is None
    by_where = {f.where: f for f in findings}
    assert all(f.rule == "E016" for f in findings)
    assert by_where["zoom"].line == 4
    assert by_where["fps"].line == 2
    assert "did you mean 'dot'" in by_where["layers.0.sprite"].message
    assert by_where["layers.0.sprite"].line == 6
    assert "did you mean 'blink'" in by_where["layers.1.anim"].message
    assert "did you mean 'pale'" in by_where["layers.2.variant"].message
    assert "never ends" in by_where["layers.3.then"].message
    assert any("both from and to" in f.message for f in findings if f.where == "layers.4.from")
    assert any("needs duration" in f.message for f in findings if f.where == "layers.4.from")
    assert "unknown layer field 'ease'" in by_where["layers.5.ease"].message


def test_tilesets_are_refused(scene_project: Project) -> None:
    (scene_project.tiles_dir / "floor.tiles.yaml").write_text("name: floor\ntile_size: [2, 2]\ntiles:\n  t: |\n    11\n    11\n")
    _, findings = load_timeline(scene(scene_project, "  - {sprite: floor, anim: t, at: [0, 0]}\n"), scene_project)
    assert any("is a tileset" in f.message for f in findings)


def test_project_lint_covers_scenes_but_build_ignores_them(scene_project: Project) -> None:
    scene(scene_project, "  - {sprite: nope, anim: a, at: [0, 0]}\n")
    result = lint_paths(scene_project)
    assert [f.rule for f in result.errors] == ["E016"]
    assert not lint_paths(scene_project, scenes=False).errors
    from pagan.build import build

    built = build(scene_project)
    assert not built.errors
    manifest = json.loads((scene_project.output_dir / "manifest.json").read_text())
    assert set(manifest["assets"]) == {"dot", "big"}


def test_broken_sprite_is_reported_once_by_lint(scene_project: Project) -> None:
    (scene_project.sprites_dir / "dot.sprite.yaml").write_text(DOT.replace("55\n    55\n  b", "5x\n    55\n  b"))
    scene(scene_project, "  - {sprite: dot, anim: a, at: [1, 2]}\n")
    result = lint_paths(scene_project)
    messages = [f.message for f in result.errors if f.rule == "E016"]
    assert len(messages) == 1 and "has errors; fix them first" in messages[0]


def test_cli_preview_writes_frames_gif_and_contact_sheet(scene_project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(scene_project.root)
    path = scene(scene_project, "  - {sprite: dot, anim: blink, at: [1, 2]}\n", header="size: [4, 4]\nfps: 4\nduration: 1.5\n")
    assert main(["preview", str(path.relative_to(scene_project.root)), "--at", "0.5,1", "--json"], show_progress=False) == 0
    out = json.loads(capsys.readouterr().out)["outputs"][0]
    folder = scene_project.preview_dir / "s.timeline"
    assert out["timeline"] == "s"
    assert sorted(p.name for p in (folder / "frames").iterdir()) == [f"f{i:04d}.png" for i in range(6)]
    assert (folder / "timeline.gif").is_file() and (folder / "at.png").is_file()
    first = {p: p.read_bytes() for p in folder.rglob("*.png")} | {folder / "timeline.gif": (folder / "timeline.gif").read_bytes()}
    # deterministic, and a shorter timeline leaves no stale frames
    assert main(["preview", str(path), "--at", "0.5,1"], show_progress=False) == 0
    assert {p: p.read_bytes() for p in first} == first
    path.write_text(path.read_text().replace("duration: 1.5", "duration: 0.5"))
    assert main(["preview", str(path)], show_progress=False) == 0
    assert len(list((folder / "frames").iterdir())) == 2


def test_cli_preview_option_mixups_are_usage_errors(scene_project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(scene_project.root)
    path = str(scene(scene_project, "  - {sprite: dot, anim: a, at: [1, 2]}\n"))
    assert main(["preview", "dot", "--at", "1"], show_progress=False) == 1
    assert main(["preview", path, "--scene", "layout.txt"], show_progress=False) == 1
    assert main(["preview", path, "--at", "9"], show_progress=False) == 1  # past the end
    assert main(["preview", path, "--at", "x"], show_progress=False) == 1


def test_times_and_gif_clock() -> None:
    assert parse_times("0.5, 2.1") == [Fraction(1, 2), Fraction(21, 10)]
    with pytest.raises(ValueError):
        parse_times("-1")
    assert gif_durations(Fraction(30), 3) == [30, 40, 30]  # 33.3 ms on a 10 ms clock, no drift
    assert gif_durations(Fraction(4), 2) == [250, 250]


def test_demo_timeline_lints_clean() -> None:
    from pagan.project import load_project

    demo = load_project(Path(__file__).parent.parent / "examples" / "demo")
    path = demo.scenes_dir / "yard.timeline.yaml"
    timeline, findings = load_timeline(path, demo)
    assert timeline is not None and not findings
