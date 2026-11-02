"""#68: engine renders run on a private offscreen display, never the desktop's."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pagan import offscreen
from pagan.exporters import godot


def test_without_xvfb_nothing_renders_and_the_error_says_why(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    calls: list[list[str]] = []

    def run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    images, output = godot.render_views("godot", tmp_path, "res://x.tscn", 1.0, 0.0, [(0, 30)])
    assert images == [] and "Xvfb" in output
    assert all("--headless" in cmd for cmd in calls)  # only the headless import ran: no window, ever


@pytest.mark.skipif(not offscreen.available(), reason="needs Xvfb")
def test_offscreen_display_is_private_and_software_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    with offscreen.display() as env:
        assert env is not None
        assert env["DISPLAY"] != ":0" and "WAYLAND_DISPLAY" not in env
        assert env["LP_NUM_THREADS"] == str(offscreen.CPU_THREADS) and env["LIBGL_ALWAYS_SOFTWARE"] == "1"
        assert all("lvp_icd" in p for p in env.get("VK_ICD_FILENAMES", "").split(os.pathsep) if p)
        number = env["DISPLAY"][1:]
        assert offscreen.connectable(number)  # the server is up
    assert not offscreen.connectable(number)  # and gone afterwards
