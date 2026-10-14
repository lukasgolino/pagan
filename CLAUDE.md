# CLAUDE.md

PAGAN (Pixel Art Grammar And Notation) is a standalone Python CLI that translates between AI and pixel
art: agents write pixel art as palette-keyed YAML grids, and PAGAN lints them and renders them to PNGs,
sprite sheets and engine assets (Godot first). This repo is the tool only — it is not tied to any game.
Read [PLAN.md](PLAN.md) for the full brief, milestones and progress.

## Setup and commands

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pagan --version          # or: python -m pagan --version
pytest
```

CI (`.github/workflows/ci.yml`) runs the same install + pytest on Python 3.11–3.13 on every push/PR.

## Layout

- `src/pagan/` — the package (`cli.py` is the argparse entry point; `templates/` is copied by `pagan init`)
- `tests/` — pytest suite
- `examples/demo/` — an example PAGAN project (palettes, sprites, tiles)
- `.github/workflows/` — CI

## Conventions

- Python 3.11+, type hints everywhere, small single-purpose modules.
- Every feature lands with tests; CI must be green at the end of each milestone.
- Output must be deterministic (byte-identical builds).
- CLI: human-readable output by default, `--json` for machines, non-zero exit on error.
- Commits: one per milestone (or logical step), imperative subject line, e.g. `Add palette loading`.
- Dependencies: Pillow, PyYAML, pytest (dev). Others only if genuinely needed — log why below.

## Decisions log

- 2026-10-14: Repo is the tool only; package at repo root with `src/` layout (not `tools/pagan/`).
- 2026-10-14: Build backend is setuptools; version is defined once in `pyproject.toml` and read via `importlib.metadata`.
- 2026-10-14: CI matrix is Python 3.11, 3.12, 3.13.
- 2026-10-14: Licensed MIT (open source). Uses PEP 639 `license = "MIT"`, hence setuptools>=77.
