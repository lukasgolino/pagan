"""A private offscreen display for anything that must render through an engine (Godot's `--engine` previews).

Rendering never uses the desktop's display: a windowed engine pops up on the user's screen (and windowed engines
under WSLg can take a desktop down). Instead each run gets its own Xvfb display with Mesa's CPU renderers
(lavapipe for Vulkan, llvmpipe for OpenGL), their threads capped, and runs one at a time across processes.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

CPU_THREADS = 4  # Mesa's software renderers would otherwise take every core
_START_TIMEOUT = 15.0  # seconds for Xvfb to accept connections
_FIRST_DISPLAY = 90
_ICD_DIRS = (Path("/usr/share/vulkan/icd.d"), Path("/etc/vulkan/icd.d"))

MISSING = (
    "rendering through Godot needs Xvfb (an offscreen display; PAGAN never opens a window on your desktop): "
    "install it, e.g. `sudo apt install xvfb mesa-vulkan-drivers libgl1-mesa-dri`"
)


def available() -> bool:
    """Whether an offscreen display can be started here."""
    return shutil.which("Xvfb") is not None


@contextmanager
def display() -> Iterator[dict[str, str] | None]:
    """An environment for a subprocess that renders on a fresh offscreen display (None if Xvfb is missing or won't
    start). Only one offscreen display runs at a time (a lock file in the temp folder), so parallel commands queue."""
    xvfb = shutil.which("Xvfb")
    if xvfb is None:
        yield None
        return
    with _lock():
        server, number = _start(xvfb)
        try:
            yield None if number is None else _environment(number)
        finally:
            if server is not None:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


def _start(xvfb: str) -> tuple[subprocess.Popen[bytes] | None, str | None]:
    """Xvfb on the first free display from :90, once it accepts connections. An explicit number, not
    `-displayfd`: that fails where /tmp/.X11-unix isn't writable (WSLg), while the abstract socket still works."""
    for n in range(_FIRST_DISPLAY, _FIRST_DISPLAY + 40):
        if Path(f"/tmp/.X{n}-lock").exists() or connectable(str(n)):
            continue
        try:
            server = subprocess.Popen(
                [xvfb, f":{n}", "-screen", "0", "1280x1024x24", "-nolisten", "tcp"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )  # fmt: skip
        except OSError:
            return None, None
        deadline = time.monotonic() + _START_TIMEOUT
        while time.monotonic() < deadline and server.poll() is None:
            if connectable(str(n)):
                return server, str(n)
            time.sleep(0.05)
        if server.poll() is None:  # never came up: give up
            server.kill()
            server.wait()
            return None, None
        # it exited: the display was taken after all; try the next one
    return None, None


def connectable(number: str) -> bool:
    """Whether an X server accepts connections on display :number (abstract or file socket)."""
    for address in (f"\0/tmp/.X11-unix/X{number}", f"/tmp/.X11-unix/X{number}"):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            try:
                probe.connect(address)
                return True
            except OSError:
                continue
    return False


def _environment(number: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "VK_ICD_FILENAMES", "VK_DRIVER_FILES")}
    env.update(
        DISPLAY=f":{number}",
        XDG_SESSION_TYPE="x11",
        LIBGL_ALWAYS_SOFTWARE="1",  # OpenGL (Compatibility renderer): llvmpipe
        GALLIUM_DRIVER="llvmpipe",
        LP_NUM_THREADS=str(CPU_THREADS),
    )
    icds = sorted(str(p) for folder in _ICD_DIRS if folder.is_dir() for p in folder.glob("lvp_icd*.json"))
    if icds:  # Vulkan (Forward+, Mobile): lavapipe only, never the real GPU
        env["VK_ICD_FILENAMES"] = env["VK_DRIVER_FILES"] = os.pathsep.join(icds)
    return env


@contextmanager
def _lock() -> Iterator[None]:
    """One offscreen render at a time on this machine (POSIX file lock; a no-op where there's none)."""
    try:
        import fcntl
    except ImportError:  # no fcntl (Windows): no Xvfb there either
        yield
        return
    path = Path(tempfile.gettempdir()) / "pagan-offscreen.lock"
    with open(path, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
