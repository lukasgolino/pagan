"""#67: `pagan build` streams assets through (memory stays that of one asset, not the project), `pagan fit`
never suggests or writes an over-size frame, and the default worker count respects available memory."""

from __future__ import annotations

import gc
import json
import os
import tracemalloc
from pathlib import Path

import pytest

from conftest import make_project
from pagan import jobs
from pagan.build import build
from pagan.cli import main
from pagan.project import Project

MODEL = """\
name: {name}
palette: test
size: [64, 64]
pivot: [32, 44]
directions: 16
outline: auto
materials:
  hull: {{ keys: ["1", "2"] }}
parts:
  - box: {{ from: [0, 0, 0], to: [17, 17, 9], material: hull }}
"""


def _models(root: Path, count: int) -> Project:
    root.mkdir(parents=True)
    project = make_project(root, 'default_palette = "test"\noutput_dir = "out"\nexport = ["png", "normals"]\n')
    (root / "models").mkdir()
    for i in range(count):
        (root / "models" / f"m{i:02}.model.yaml").write_text(MODEL.format(name=f"m{i:02}"))
    return project


def _peak_build(project: Project) -> int:
    """Peak traced memory of a warm-cache build."""
    assert not build(project).errors  # renders into the cache
    gc.collect()
    tracemalloc.start()
    try:
        result = build(project)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert not result.errors and result.assets == len(list((project.root / "models").iterdir()))
    return peak


def test_build_memory_does_not_grow_with_the_number_of_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAGAN_JOBS", "1")
    few, many = _peak_build(_models(tmp_path / "few", 3)), _peak_build(_models(tmp_path / "many", 12))
    # Holding every asset (voxels + frames) until the end made 12 models cost about 4x 3 of them.
    assert many < few * 1.5, (few, many)


def test_fit_refuses_a_frame_over_the_size_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    project = make_project(tmp_path)
    (tmp_path / "models").mkdir()
    path = tmp_path / "models" / "wall.model.yaml"
    text = MODEL.format(name="wall").replace("to: [17, 17, 9]", "to: [5, 1200, 9]").replace("[64, 64]", "[1024, 1024]")
    path.write_text(text.replace("[32, 44]", "[512, 512]"))
    monkeypatch.chdir(project.root)
    assert main(["fit", str(path), "--write", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False and "limit" in report["findings"][0]["message"]
    assert path.read_text() == text.replace("[32, 44]", "[512, 512]")  # nothing written


def test_default_workers_respect_available_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAGAN_JOBS", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    monkeypatch.setattr(jobs, "available_memory", lambda: 3 * jobs.WORKER_MEMORY + 1)
    assert jobs.workers() == 3
    monkeypatch.setattr(jobs, "available_memory", lambda: jobs.WORKER_MEMORY // 2)
    assert jobs.workers() == 1
    monkeypatch.setattr(jobs, "available_memory", lambda: None)
    assert jobs.workers() == 8
    monkeypatch.setenv("PAGAN_JOBS", "12")
    assert jobs.workers() == 12  # an explicit PAGAN_JOBS wins
