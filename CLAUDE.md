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
mypy                     # strict type check (config in pyproject.toml)
pytest
```

CI (`.github/workflows/ci.yml`) runs install + mypy + pytest on Python 3.11–3.13 on every push/PR.

Try the demo project: `cd examples/demo && pagan palette show` → swatches in `examples/demo/previews/palettes/`.

## Layout

- `src/pagan/` — the package:
  - `cli.py` argparse commands; `findings.py` Finding/PaganError (rule ids, file:line output, JSON);
  - `yamlio.py` YAML loader (rejects duplicate keys, tracks line numbers via `LineMap`);
  - `palette.py` palette parsing/validation (files and inline); `project.py` `pagan.toml` + project discovery;
  - `swatch.py` palette swatch images; `templates/` files copied by `pagan init`.
- `tests/` — pytest suite
- `examples/demo/` — an example PAGAN project (palettes: ember, tide, arcade); tests keep it valid
- `.github/workflows/` — CI

## Conventions

- Python 3.11+, type hints everywhere, small single-purpose modules.
- Every feature lands with tests; CI must be green at the end of each milestone.
- Output must be deterministic (byte-identical builds).
- CLI: human-readable output by default, `--json` for machines, non-zero exit on error.
- Commit only when the owner has authorized it (currently: at sensible milestone points), as plain `git commit` under the owner's identity. NEVER add AI attribution (no Co-Authored-By trailers). Never push unless asked.
- Commit messages (when asked): imperative subject line, e.g. `Add palette loading`.
- Validation collects *all* findings in a file rather than stopping at the first, and every finding has a
  rule id, file, line where possible, a `where` path (e.g. `colors.4.hex`) and a message that says how to fix it.
- Dependencies: Pillow, PyYAML; dev: pytest, mypy, types-PyYAML. Others only if genuinely needed — log why below.

## Decisions log

- 2026-10-14: Repo is the tool only; package at repo root with `src/` layout (not `tools/pagan/`).
- 2026-10-14: Build backend is setuptools; version is defined once in `pyproject.toml` and read via `importlib.metadata`.
- 2026-10-14: CI matrix is Python 3.11, 3.12, 3.13.
- 2026-10-14: Licensed MIT (open source). Uses PEP 639 `license = "MIT"`, hence setuptools>=77.
- 2026-10-14: Rule id `E000` = command/usage error (e.g. project already exists, no pagan.toml found) — not a source-file rule.
- 2026-10-14: Palette colors accept `"#rrggbb"` shorthand as well as `{ hex, name }`; unquoted digit keys (YAML ints 0-9) are accepted.
- 2026-10-14: Palette file `name` must match its file name (`dusk.pal.yaml` → `name: dusk`), since sprites reference palettes by name.
- 2026-10-14: Unknown fields in palettes and `pagan.toml` are errors (catches typos like `colours`).
- 2026-10-14: Project layout is fixed (`palettes/`, `sprites/`, `tiles/` next to `pagan.toml`); only output/preview dirs are configurable.
- 2026-10-14: No `pagan.toml` found → commands run in open mode rooted at cwd, so single files work anywhere.
- 2026-10-14: Added mypy (strict) + types-PyYAML as dev deps and a CI step, to enforce "typed Python" from the plan.
- 2026-10-14: Swatch images use Pillow's bundled default font (needs Pillow>=10.1); swatches are previews, not build output.
