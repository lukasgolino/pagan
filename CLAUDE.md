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

CI (`.github/workflows/ci.yml`) runs install + mypy + pytest on Python 3.11–3.13 on every push/PR, and a
`godot` job that downloads Godot 4.7.2, rebuilds the demo into `examples/godot/` (failing if the committed
output differs), verifies every generated resource loads, and runs the demo scene headless.

Godot tests (`tests/test_godot.py`) skip unless a Godot 4 binary is available: `GODOT=/path/to/godot pytest`.
After changing demo art or rendering: `cd examples/demo && pagan build` and commit `examples/godot/assets/generated/`.

Try the demo project: `cd examples/demo && pagan palette show` → swatches in `examples/demo/previews/palettes/`.

## Layout

- `src/pagan/` — the package:
  - `cli.py` argparse commands; `findings.py` Finding/PaganError (rule ids, file:line output, JSON);
  - `yamlio.py` YAML loader (rejects duplicate keys, tracks line numbers via `LineMap`);
  - `palette.py` palette parsing/validation (files and inline); `project.py` `pagan.toml` + project discovery;
  - `asset.py` sprite + tileset parsing (grids, mirror, derived frames, outline, animations, variants, metadata);
  - `render.py` frames/sheets to RGBA images + deterministic PNG saving; `lint.py` warnings W001-W006;
  - `preview.py` upscaled frames, contact sheets (with animation "changes" rows), GIFs, tiling check, gallery;
  - `color.py` OKLab/OKLCh conversions + gamut mapping; `importer.py` PNG -> sprite (scale detection, snapping);
  - `voxel.py` voxel model + renderer (grid ray traversal, smoothed/exact normals, wrap light, soft shadows);
  - `model.py` `.model.yaml` parsing (materials, primitives, poses) -> Asset, with a render cache in `.pagan-cache/`;
  - `build.py` `pagan build` (sheets, manifest.json, stale cleanup); `exporters/godot.py` SpriteFrames .tres + headless verify;
  - `manage.py` long-term management: catalogue (`pagan status`), palette adjust, `mark`, `style bump` (text edits keep comments);
  - `settings.py` registry of every pagan.toml setting (default, meaning, what it refreshes) + safe `pagan config set` edits;
  - `api.py` stable Python API for generator scripts (drawing, shading, corner sets, exact hull/sail geometry, YAML writers);
  - `swatch.py` palette swatch images; `templates/` files copied by `pagan init`.
- `tests/fixtures/golden/` — golden-image project; `expected/*.png` are hand-checked. After an intended
  rendering change, inspect, then regenerate with `PAGAN_UPDATE_GOLDEN=1 pytest tests/test_render.py`.
- `tests/` — pytest suite
- `src/pagan/skill/` — the Claude skill (SKILL.md workflow + reference.md notation); `pagan skill install` copies it.
  `.claude/skills/pagan/` is this repo's installed copy: after editing the skill run `pagan skill install` (a test checks they match).
- `examples/demo/` — an example PAGAN project (palettes: ember, tide, arcade); tests keep it valid
- `examples/godot/` — Godot 4.7 project receiving the demo's build output; `scenes/art_test.tscn` shows everything
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
- Versioning: bump `version` in pyproject.toml, add a CHANGELOG.md entry and tag `vX.Y.Z` for ANY change to the
  notation, pagan.toml settings, manifest/exporter output or rendered pixels (game repos pin tags). Ask before pushing tags.
- Dependencies: Pillow, PyYAML, numpy; dev: pytest, mypy, types-PyYAML. Others only if genuinely needed — log why below.

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
- 2026-10-14: Golden tests compare decoded pixels exactly (not PNG bytes: zlib builds may differ across machines); a separate test checks byte-identical output between two runs.
- 2026-10-14: Sprites and tilesets share one `Asset` type (`kind` = sprite | tileset); tilesets have no mirror/outline/animations.
- 2026-10-14: Derived frames: a frame may be `{ from: other, flip: horizontal|vertical|both, shift: [dx, dy] }` — cheap rotations/bobs without redrawing (E010 for problems).
- 2026-10-14: `outline_color` defaults to the palette's darkest color (by luminance), not a fixed key.
- 2026-10-14: `pivot` is in pixel-edge coordinates, 0..w × 0..h; default is bottom centre `[w // 2, h]`.
- 2026-10-14: Variants can also swap to another palette (`palette: night`), not just ramp_swap/key_swap.
- 2026-10-14: Asset metadata for long-term management: `description`, `tags`, `status` (draft|approved), `style_version` (vs. pagan.toml `style_version`, W006).
- 2026-10-14: Only warnings can be disabled in `[lint] disable`.
- 2026-10-14: Animation consistency is a first-class concern (owner feedback): W007 measures frame-to-frame pixel churn after the best ±2px alignment; preview sheets show a "changes" row per animation (magenta = changed, cyan = removed).
- 2026-10-14: `pagan render`/`preview`/`lint` find the project from the target path, not the cwd.
- 2026-10-14: GIF frame durations are rounded to 10ms (GIF's resolution).
- 2026-10-14: `pagan import` picks the largest uniform block size as the upscale factor (gcd of pixel run lengths); snapping uses nearest OKLab color; open mode orders extracted keys darkest-first so "0" suits outlines.
- 2026-10-14: 3D voxel models (`models/*.model.yaml`) are first-class assets (kind "model"): rendered with the project-wide `[camera]`/`[light]` so all 3D assets match; frames per heading (`e`, `ne`, ...), pose animations as `<anim>_<heading>`. Poses move parts by whole voxels, so animation frames stay pixel-consistent.
- 2026-10-14: Renderer: exact grid traversal per pixel; normals from the occupancy gradient, or exact from shapes that know them (sails); wrap lighting (0.3) and partial shadows (0.65) read better at pixel scale than hard Lambert; parts never shadow themselves. Trig results are rounded to 12 decimals for cross-platform byte stability.
- 2026-10-14: Model renders are cached in `<project>/.pagan-cache/models/` keyed by file text + materials + camera + light + RENDERER_VERSION (bump it when rendering changes).
- 2026-10-14: `.tres` format copied from what Godot 4.7.2's ResourceSaver writes (format=3, no uid/load_steps); IDs are deterministic (`1_sheet`, `AtlasTexture_<n>`), frames shared between animations. Verified by loading in headless Godot 4.7.2.
- 2026-10-14: Sprites without animations export one single-frame animation per frame (so every sprite gets a SpriteFrames). Tilesets export atlas + manifest only.
- 2026-10-14: `pagan build` always builds the whole project (partial builds would leave an incomplete manifest); only changed files are rewritten; files listed in the previous manifest but no longer produced are deleted (plus Godot's .import sidecar).
- 2026-10-14: Variant outputs are named `<asset>.<variant>.png/.tres` (a dot can't occur in asset names, so no clashes).
- 2026-10-14: Example Godot project: 480x270 viewport, integer scaling ×3 window, nearest filtering, pixel snapping. Base resolution is an open question for the owner.
- 2026-10-14: Long-term asset management: a PAGAN project folder is the single home for a game's art (BRIEF.md = what's wanted + feedback log, STYLE.md = how it looks + versioned changelog, assets carry description/status/style_version). `pagan palette adjust` (OKLab lightness/contrast/saturation/hue/warmth) changes every asset at once; `pagan style bump` flags assets for review (W006) until `pagan mark --current`.
- 2026-10-14: Source-file edits by PAGAN (`palette adjust`, `mark`, `style bump`) are line-level text edits, never YAML re-serialisation, so comments and layout survive.
- 2026-10-15: numpy added (owner approved): the voxel renderer traces all rays in lockstep (same Amanatides-Woo algorithm and float operations as before, so output is byte-identical) and W007 is vectorised. Cold demo lint ~11s -> ~3s.
- 2026-10-15: PAGAN's role (owner): a sprite service driven by an orchestrator agent; engine-agnostic, `manifest.json` is the contract; Godot export is a convenience.
- 2026-10-15: Every look setting is configurable and saved (`pagan config show/get/set`, registry in settings.py). `config set` validates the whole resulting config before writing and reports what refreshes (models re-render; hand-drawn 2D assets listed for review).
- 2026-10-15: Engine lighting: `[light] baked = false` renders models with each material's middle step (flat albedo); `export` "normals" writes `<name>.normal.png` (OpenGL convention: x right, y up, z to viewer) and the Godot .tres wraps the sheet in a CanvasTexture with the normal map. Verified loading in Godot 4.7.2.
- 2026-10-15: Godot TileSet `.tres` per tileset (format copied from Godot 4.7.2's ResourceSaver; one atlas source, every tile created, tile_size written explicitly); manifest gets `tiles: name -> [column, row]`. Pivots stay in the manifest (`godot_offset`), documented for game code.
- 2026-10-15: Sizes are the requester's choice (owner): skill explains the detail trade-off and the two ways up (camera.scale for chunkier, more voxels for detail).
- 2026-10-15: Release v0.1.0 tagged locally (owner approved); CHANGELOG.md defines what forces a version bump.
- 2026-10-15: Release v0.2.0 tagged locally (owner approved): orchestrator reports R1-R6, Age of Boom log fixes, review round 3.
- 2026-10-16: Hidden model parts are overlays (never change normal frames; shown = drawn on top; hidden+carve = pose-only hole); an id is hidden or visible, not both.
- 2026-10-16: Whole-model `roll`/`pitch` are rendered exactly (camera rotation, no resampling); part rotations resample voxels (forward + inverse mapping, no gaps).
- 2026-10-16: Generators get `pagan.api` instead of more notation (owner, R11/R12); its functions are the ones the primitives use, and it's covered by versioning (`API_VERSION`).
- 2026-10-16: Animated tiles: frames side by side in the atlas (new row if they don't fit); tilesets without animations keep the old layout byte for byte.
- 2026-10-16: Per-asset `lint:` (disable / for) instead of tag-based defaults: explicit in the file.
