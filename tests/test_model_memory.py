"""#64: big voxel models aren't kept for the whole build, normal maps are cached, render workers don't outlive
the build."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from conftest import make_project
from test_reports_r20_r29 import BOAT

import pagan.model
from pagan import jobs as pagan_jobs
from pagan.asset import load_asset
from pagan.build import build
from pagan.project import Project

CONFIG = 'default_palette = "test"\noutput_dir = "out"\nexport = ["png", "normals", "mesh"]\n'


def _boat(tmp_path: Path) -> tuple[Project, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    project = make_project(tmp_path, CONFIG)
    (project.root / "models").mkdir()
    path = project.root / "models" / "boat.model.yaml"
    path.write_text(BOAT.replace("directions: 32", "directions: 4"))
    return project, path


def _outputs(project: Project) -> dict[str, bytes]:
    result = build(project)
    assert not result.errors, [f.format() for f in result.errors]
    out = project.root / "out"
    return {str(p.relative_to(out)): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}


def test_big_models_are_rebuilt_on_demand_and_build_the_same(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAGAN_JOBS", "1")
    small, _ = _boat(tmp_path / "small")
    kept = _outputs(small)
    monkeypatch.setattr(pagan.model, "BIG_MODEL_VOXELS", 1)  # every model counts as big
    big, path = _boat(tmp_path / "big")
    assert _outputs(big) == kept
    asset, _ = load_asset(path, big)
    assert asset is not None and asset.mesh is not None
    assert asset.mesh._model is None  # not held after parsing
    voxels = dict(asset.mesh.model.voxels)
    assert voxels and asset.mesh._model is not None
    asset.mesh.release()
    assert asset.mesh._model is None and dict(asset.mesh.model.voxels) == voxels


def test_small_models_are_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAGAN_JOBS", "1")
    project, path = _boat(tmp_path)
    asset, _ = load_asset(path, project)
    assert asset is not None and asset.mesh is not None
    model = asset.mesh.model
    asset.mesh.release()
    assert asset.mesh.model is model


def test_normal_maps_come_from_the_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAGAN_JOBS", "1")
    project, path = _boat(tmp_path)
    first = _outputs(project)
    assert list((project.root / ".pagan-cache" / "models").glob("boat-*.normals.npz"))
    asset, _ = load_asset(path, project)
    assert asset is not None and asset.normal_maps is not None
    rendered = asset.normal_maps()

    def no_render(*_: object) -> None:
        raise AssertionError("normal maps rendered again")

    monkeypatch.setattr(pagan.model, "_render_scene", no_render)
    asset, _ = load_asset(path, project)
    assert asset is not None and asset.normal_maps is not None
    cached = asset.normal_maps()
    assert list(cached) == list(rendered) and all(np.array_equal(cached[f], rendered[f]) for f in rendered)
    assert _outputs(project) == first


def test_big_model_renders_stop_the_workers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAGAN_JOBS", "2")
    monkeypatch.setattr(pagan.model, "_MIN_PARALLEL_JOBS", 1)
    monkeypatch.setattr(pagan.model, "BIG_MODEL_VOXELS", 1)
    project, path = _boat(tmp_path)
    asset, findings = load_asset(path, project)
    assert asset is not None, [f.format() for f in findings]
    assert pagan_jobs._POOL is None


WORKERS = """
import time
from pagan import jobs
pool = jobs.pool(2)
list(pool.map(time.sleep, [0.2] * 4))  # both workers started
print(" ".join(str(p.pid) for p in pool._processes.values()), flush=True)
time.sleep(60)
"""


def _alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0]
    except OSError:
        return False
    return state != "Z"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")
def test_workers_exit_when_the_build_is_killed() -> None:
    proc = subprocess.Popen([sys.executable, "-c", WORKERS], stdout=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    pids = [int(p) for p in proc.stdout.readline().split()]
    assert len(pids) == 2 and all(_alive(p) for p in pids)
    os.kill(proc.pid, signal.SIGKILL)  # like the OOM killer: no cleanup runs
    proc.wait()
    deadline = time.monotonic() + 15
    while any(_alive(p) for p in pids) and time.monotonic() < deadline:
        time.sleep(0.1)
    leftover = [p for p in pids if _alive(p)]
    for p in leftover:
        os.kill(p, signal.SIGKILL)
    assert not leftover, "render workers outlived the killed build"
