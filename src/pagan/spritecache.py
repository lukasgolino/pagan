"""Cache for big 2D sprites and tilesets: the parsed asset, its lint findings and its built sheets, on disk.

Parsing, linting and rendering a sprite of many megapixels takes seconds; most builds don't change it. An entry
is keyed by everything the results depend on: the source file's bytes and path, every palette file, the project
config, PAGAN's own code (a hash of every module, plus CACHE_VERSION) and the libraries that render and encode.
Files the source reads besides itself (`frames_png:`) are hashed into the entry and checked on every hit. So a
hit is always what parsing again would give, also between unreleased code changes.

Only assets with at least CACHE_MIN_PIXELS source pixels are stored (small ones parse faster than a cache file
loads). Entries live in `<project>/.pagan-cache/sprites/` (or PAGAN_CACHE_DIR). Caching is an optimisation only:
any problem reading or writing the cache means the work is just done again.
"""

from __future__ import annotations

import functools
import hashlib
import os
import pickle
import platform
import shutil
import zlib
from pathlib import Path
from typing import Any

from pagan import jobs
from pagan.asset import Asset
from pagan.findings import Finding
from pagan.palette import PALETTE_SUFFIX
from pagan.project import Project

CACHE_VERSION = "1"  # bump when what an entry holds changes shape (code changes are caught by the fingerprint)
CACHE_MIN_PIXELS = 1 << 20  # source pixels (frame size x frames) from which an asset is cached
_SHARED_KEEP = 8  # entries kept per asset name in a shared PAGAN_CACHE_DIR


@functools.cache
def code_fingerprint() -> str:
    """A hash of PAGAN's code and the libraries whose behaviour the results depend on."""
    import numpy
    import PIL
    import yaml

    digest = hashlib.sha256()
    for part in (CACHE_VERSION, platform.python_version(), PIL.__version__, numpy.__version__, yaml.__version__, zlib.ZLIB_RUNTIME_VERSION):
        digest.update(f"{part}\0".encode())
    package = Path(__file__).resolve().parent
    for module in sorted(package.rglob("*.py")):
        digest.update(module.relative_to(package).as_posix().encode() + b"\0" + module.read_bytes() + b"\0")
    return digest.hexdigest()


def source_key(path: Path, project: Project) -> str | None:
    """The cache key for parsing `path` in `project`, or None if the source can't be read."""
    digest = hashlib.sha256(code_fingerprint().encode())
    try:
        parts: list[bytes] = [
            str(path).encode(),
            str(path.resolve()).encode(),
            str(project.root).encode(),
            str(project.config_path).encode(),
            repr(project.config).encode(),
            path.read_bytes(),
        ]
        palettes = project.palettes_dir
        if palettes.is_dir():
            for palette in sorted(palettes.glob(f"*{PALETTE_SUFFIX}")):
                parts += [palette.name.encode(), palette.read_bytes()]
    except OSError:
        return None
    for part in parts:
        digest.update(len(part).to_bytes(8, "little") + part)
    return digest.hexdigest()[:24]


def _entry_dir(project: Project, path: Path, key: str) -> Path:
    return jobs.cache_dir(project) / "sprites" / f"{path.name.split('.')[0]}-{key}"


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(file: Path) -> Any:
    try:
        with file.open("rb") as handle:
            return pickle.load(handle)
    except (OSError, pickle.UnpicklingError, EOFError, AttributeError, ImportError, ValueError, TypeError):
        return None  # missing or unreadable: do the work again


def _write(file: Path, value: Any) -> None:
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        scratch = file.with_name(f".{file.name}.{os.getpid()}.tmp")
        with scratch.open("wb") as handle:
            pickle.dump(value, handle, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(scratch, file)  # atomic: another process never reads half a file
    except OSError:
        pass  # caching is an optimisation only


def is_big(asset: Asset) -> bool:
    width, height = asset.size
    return width * height * len(asset.base_frames) >= CACHE_MIN_PIXELS


def has(path: Path, project: Project, key: str) -> bool:
    """Whether there's an entry for this key (without reading it)."""
    return (_entry_dir(project, path, key) / "asset.pickle").is_file()


def load(path: Path, project: Project, key: str) -> tuple[Asset, list[Finding]] | None:
    """A cached parse of `path`, if there is one and the files it read are unchanged."""
    entry = _read(_entry_dir(project, path, key) / "asset.pickle")
    if not (isinstance(entry, dict) and isinstance(entry.get("asset"), Asset)):
        return None
    try:
        if any(_file_hash(Path(dep)) != digest for dep, digest in entry["deps"].items()):
            return None
    except OSError:
        return None
    return entry["asset"], list(entry["findings"])


def store(path: Path, project: Project, key: str, asset: Asset, findings: list[Finding]) -> Asset:
    """Cache a parse (big assets only). Returns the asset, tagged with its key when it was stored."""
    if not is_big(asset):
        return asset
    try:
        deps = {str(dep): _file_hash(dep) for dep in ([asset.frames_png] if asset.frames_png is not None else [])}
    except OSError:
        return asset
    folder = _entry_dir(project, path, key)
    _clean_others(folder)
    object.__setattr__(asset, "cache_key", key)
    _write(folder / "asset.pickle", {"asset": asset, "findings": findings, "deps": deps})
    return asset


def _clean_others(folder: Path) -> None:
    """Other entries for the same asset name are stale: a project's own cache keeps the latest only, a shared one
    (several checkouts on different branches) the newest few."""
    stem = folder.name.rsplit("-", 1)[0]
    try:
        others = [p for p in folder.parent.glob(f"{stem}-*") if p.name.rsplit("-", 1)[0] == stem and p != folder]
        others.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    keep = _SHARED_KEEP - 1 if jobs.shared_cache_dir() is not None else 0
    for stale in others[keep:]:
        shutil.rmtree(stale, ignore_errors=True)


def _asset_dir(asset: Asset, project: Project) -> Path | None:
    if asset.cache_key is None or asset.path is None:
        return None
    return _entry_dir(project, asset.path, asset.cache_key)


def load_lint(asset: Asset, project: Project) -> list[Finding] | None:
    folder = _asset_dir(asset, project)
    found = _read(folder / "lint.pickle") if folder is not None else None
    return found if isinstance(found, list) else None


def store_lint(asset: Asset, project: Project, findings: list[Finding]) -> None:
    folder = _asset_dir(asset, project)
    if folder is not None:
        _write(folder / "lint.pickle", findings)


def load_sheets(asset: Asset, project: Project) -> dict[str, bytes]:
    """Built sheet PNGs by output stem (`<name>` / `<name>.<variant>`), as far as they're cached."""
    folder = _asset_dir(asset, project)
    found = _read(folder / "sheets.pickle") if folder is not None else None
    return found if isinstance(found, dict) else {}


def store_sheets(asset: Asset, project: Project, sheets: dict[str, bytes]) -> None:
    folder = _asset_dir(asset, project)
    if folder is not None and sheets:
        _write(folder / "sheets.pickle", {**load_sheets(asset, project), **sheets})
