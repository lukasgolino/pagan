"""Shared machinery for slow work: the process pool (`PAGAN_JOBS`) and the on-disk cache folder (`PAGAN_CACHE_DIR`).

Work done in other processes is computed exactly as it would be in this one, so output never depends on it.
"""

from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path
from typing import Any

from pagan.project import Project

_POOL: Any = None  # one process pool for the whole run, started on first use
_ATEXIT: list[bool] = []


def workers() -> int:
    """Processes for slow work: PAGAN_JOBS if set (1 = no extra processes), else the CPU count, up to 8."""
    raw = os.environ.get("PAGAN_JOBS", "")
    if raw.strip().isdigit() and int(raw) >= 1:
        return int(raw)
    return max(1, min(8, os.cpu_count() or 1))


def pool(count: int) -> Any:
    """The run's process pool with `count` workers (forkserver on Linux, spawn elsewhere)."""
    global _POOL
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    if _POOL is None or _POOL._max_workers != count:
        shutdown()
        context = multiprocessing.get_context("forkserver" if sys.platform.startswith("linux") else "spawn")
        _POOL = ProcessPoolExecutor(count, mp_context=context, initializer=_watch_parent)
        if not _ATEXIT:
            atexit.register(shutdown)  # before interpreter teardown, so the pool's threads exit cleanly
            _ATEXIT.append(True)
    return _POOL


def shutdown() -> None:
    """Stop the pool's workers (the next `pool()` starts fresh ones): gives back the memory they hold."""
    global _POOL
    if _POOL is not None:
        _POOL.shutdown()
        _POOL = None


def _watch_parent() -> None:
    """In each worker: exit as soon as the process that started it dies (e.g. OOM-killed), instead of
    living on as an orphan that keeps its memory."""
    import multiprocessing
    import threading

    parent = multiprocessing.parent_process()
    if parent is None:
        return

    def wait() -> None:
        parent.join()
        os._exit(1)

    threading.Thread(target=wait, daemon=True).start()


def shared_cache_dir() -> Path | None:
    """PAGAN_CACHE_DIR: one cache for several checkouts of the same art (e.g. agents' git worktrees)."""
    shared = os.environ.get("PAGAN_CACHE_DIR", "").strip()
    return Path(shared).expanduser() if shared else None


def cache_dir(project: Project) -> Path:
    """The cache folder: PAGAN_CACHE_DIR, else `<project>/.pagan-cache/`."""
    return shared_cache_dir() or project.root / ".pagan-cache"
