# PLAN.md — PAGAN (Pixel Art Grammar And Notation)

> **To the agent reading this:** This is your brief. Read it fully before doing anything.
> It was written with the project owner, who is an experienced software engineer and is
> deliberately trying out "vibe coding": they bring the ideas and judgment, you do most of the building.
> Your first job is described in **§11 First session checklist**.
> The owner's stance: *"we can figure it out as we go."* This plan is a direction, not a contract.

---

## 1. The big picture

**PAGAN is a translator between AI and pixel art.** It defines a small text language — the PAGAN
notation — that an AI agent can write fluently, and a Python tool that understands the same language
and turns it into PNGs, sprite sheets, and engine-ready assets.

> The agent speaks PAGAN. Python speaks PAGAN. So the agent's text becomes game art.

**This repo is the tool only.** It is not tied to any particular game. Anyone can install PAGAN in their
own project, optionally define a palette and style rules, and have an agent build assets for them.
When the owner (or anyone) later makes a game, that game lives in *its own* repo and uses PAGAN as a tool.

The intended workflow, in any project that uses PAGAN: someone says *"make me a rusty key"* or *"make a
slime enemy with an idle and hop animation"*, and the agent can author it, render it, look at it, fix it,
and drop it into the project's asset folder ready to use.

### What PAGAN offers: constraints, *when you want them*

A cohesive, non-generic look comes from **constraints consistently enforced**: one palette organized into
shading ramps, one grid/sprite scale, written style rules, and a tool that makes breaking them loud.
PAGAN supports all of that — but **it does not force it**:

- **Strict mode** — a project defines a shared palette (and optionally a STYLE.md + lint config).
  Every asset must use it. Best for a cohesive game look.
- **Open mode** — no project palette. Each sprite declares its own small palette inline, chosen freely
  by the agent. Best for one-offs, prototyping, or "just make me something".

Either way, the *grammar* (format validation, lint) and the *notation* (index grids) stay the same.

### What we explicitly decided NOT to do

- **No AI image generators / hosted services** (e.g. MagicPixel MCP was considered and rejected). Art is authored as data.
- **No raw per-pixel hex input.** Even in open mode, grids use single-character **palette keys**, and
  the colors are defined once (in a palette file or inline). Reasons:
  1. In strict mode, hex input would let off-palette colors sneak in. Keys make that impossible.
  2. A 32×32 sprite in hex is ~1024 tokens of `#RRGGBB`; one typo shifts a row invisibly.
     A key grid is ~4× smaller and its *shape is readable as text*, so the agent can see and fix mistakes.
  3. Keys make palette swaps (fire/ice variants, night versions) a one-line operation.
- **No baked-in "pixel size" / upscaling in assets.** Assets stay at native resolution (e.g. 16×16).
  Engines scale them up with nearest-neighbor filtering. Upscaling is only for previews.

---

## 2. How the owner wants to work (working agreements)

- **Vibe coding.** The owner will judge behavior and output, not review every line. Optimize for things
  that are easy to *verify by running*: tests, previews, clear CLI output.
- **Small, verifiable steps.** Work in the milestones in §9. Finish one, show the result, commit, then move on.
- **Commit after each milestone** with a clear message. Never rewrite history.
- **Ask before big or hard-to-reverse decisions** (changing file formats once examples exist, restructuring
  the repo, publishing anything). Small decisions: make them, note them in `CLAUDE.md`.
- **Dependencies:** prefer the standard library + the core deps in §4. Other Python libraries are fine
  **if genuinely needed** — add them, and log why in `CLAUDE.md`'s decisions log.
- **Keep `CLAUDE.md` current** (see §8). It is the memory between sessions.
- **Don't over-engineer.** v1 should be small. Features listed as "later" stay later unless the owner asks.
- **Show, don't describe.** When art is produced, render a preview and show it (or tell the owner which
  file to open). When a feature is done, show the command and its output.

---

## 3. Repository layout

This repo is a standard Python project for the tool, plus examples:

```
/
├── PLAN.md                  # this file (do not delete; may update §9 progress)
├── CLAUDE.md                # living conventions + decisions log (see §8)
├── README.md                # human-facing intro + how to install and use
├── pyproject.toml           # package metadata; exposes the `pagan` command
├── .gitignore
├── .github/workflows/       # CI (from Milestone 0)
├── src/
│   └── pagan/               # the package (palette.py, sprite.py, render.py, lint.py, cli.py, ...)
│       └── templates/       # files `pagan init` copies into a user's project (pagan.toml, STYLE.md, ...)
├── tests/                   # pytest; fixtures + golden images
└── examples/
    └── demo/                # an example PAGAN project, used for docs, demos and manual testing
        ├── pagan.toml
        ├── STYLE.md
        ├── palettes/
        ├── sprites/
        └── tiles/
```

### A PAGAN *project* (in someone else's repo)

`pagan init [dir]` scaffolds this wherever the user wants their art source to live:

```
<project art dir>/
├── pagan.toml               # project config: palette mode, default palette, lint settings, output dir, export target
├── STYLE.md                 # optional style bible (template provided)
├── palettes/                # *.pal.yaml (strict mode; may be empty in open mode)
├── sprites/                 # *.sprite.yaml
└── tiles/                   # *.tiles.yaml
```

- The art dir is the source of truth. The build output dir (set in `pagan.toml`, e.g. a Godot
  project's `assets/generated/`) is derived output.
- The build **must be deterministic** (same input → byte-identical output), so projects can commit generated output.
- Previews go to a gitignored scratch dir (default `previews/` next to `pagan.toml`).
- PAGAN finds the project by looking for `pagan.toml` in the current dir or its parents (like git does).

---

## 4. The tool: PAGAN — Pixel Art Grammar And Notation

The name was chosen by the owner and is final. A *notation* for writing pixel art as text (key grids)
plus a *grammar* of rules about what valid, on-style art looks like (format validation, lint, style bible).

Naming conventions:
- **PAGAN** (caps) in prose and docs; `pagan` (lowercase) for the Python package, the CLI command, and file names.
- Project config file is `pagan.toml`.
- If the package is ever published to PyPI, check name availability first (`pagan` may be taken; `pagan-art` is a fallback). Ask the owner before publishing.
- The README opens with the name and its expansion.

### Tech
- **Python 3.11+** (`tomllib` from the stdlib reads `pagan.toml`).
- Core dependencies:
  - **Pillow** — image creation/saving (the standard Python imaging library)
  - **PyYAML** — source file format
  - **pytest** — tests (dev only)
  - Others allowed when genuinely needed (see §2).
- `pyproject.toml` at the repo root, `src/` layout, installable with `pip install -e .`, exposes a
  `pagan` command and also runs as `python -m pagan`.
- CLI via `argparse`.
- Every command: clear human output by default, `--json` flag for machine-readable output, non-zero exit code on errors.

### Commands (v1)

| Command | What it does |
|---|---|
| `pagan init [dir] [--open]` | Scaffold a PAGAN project (`pagan.toml`, `STYLE.md` template, folders). `--open` sets open palette mode. |
| `pagan new sprite <name> --size 16x16 [--palette P]` | Scaffold a new `.sprite.yaml` with an empty transparent grid (inline palette stub in open mode). |
| `pagan new palette <name>` | Scaffold a palette file. |
| `pagan lint [paths...]` | Validate source files against format + style rules (§7). Default: the whole project. |
| `pagan render <file>` | Render one source file to native-res PNG(s) in the previews dir (fast iteration). |
| `pagan preview <file> [--scale 8] [--grid] [--bg checker\|color]` | Upscaled preview PNG: each frame, plus a contact sheet of all frames; animated GIF per animation. Prints output paths. **This is how an agent "looks" at its work.** |
| `pagan palette show <palette or sprite>` | Render a palette (file or a sprite's inline one) as a swatch image with keys, names, and ramps labeled. |
| `pagan build [paths...]` | Lint, then produce final outputs into the configured output dir (sheets, manifest, engine files). Deterministic. |
| `pagan import <png> [--palette P] [--scale auto] [--out file.sprite.yaml]` | Convert an existing PNG into a sprite source file: detect/undo upscaling; with `--palette`, snap every pixel to the nearest palette color (perceptual distance, OKLab or CIELAB) and report how much changed; without it (open mode), extract the image's colors into an inline palette. |

"Later" (not v1, don't build unless asked): `--watch` mode, exporters for engines other than Godot,
Godot `TileSet` `.tres` generation, autotile/terrain rules, layer composition, a shape-drawing DSL,
palette-swap batch export for whole sets, an MCP server wrapper around the CLI.

---

## 5. Source file formats (the PAGAN notation)

All source files are YAML. Pixel grids use YAML block scalars (`|`) so they read like pictures.

### 5.1 Palette — `palettes/<name>.pal.yaml`

```yaml
name: dusk
# Each key is ONE character used in pixel grids. Allowed: 0-9 a-z A-Z (62 max).
# "." is reserved for transparent and must not be defined here.
colors:
  "0": { hex: "#140c1c", name: ink }        # darkest; typical outline color
  "1": { hex: "#442434", name: plum_dark }
  "2": { hex: "#854c30", name: rust }
  "3": { hex: "#d27d2c", name: amber }
  "4": { hex: "#dad45e", name: straw }
  # ...
ramps:
  # shadow -> mid -> highlight. Used for shading rules, variants, and lint hints.
  warm:  ["1", "2", "3", "4"]
  green: ["5", "6", "7"]
```

Rules:
- Keys are single characters, unique; hex must be `#RRGGBB` (alpha is not per-color; transparency is only `.`).
- Every ramp entry must exist in `colors`. A color may appear in multiple ramps.
- `name` on a color and `ramps` are optional but encouraged (they help the agent and enable `ramp_swap`).
- In a project meant to look cohesive, the palette is its identity: the agent should propose palettes
  and let the human choose, not silently invent the final one.

### 5.2 Sprite — `sprites/<name>.sprite.yaml`

```yaml
name: slime
palette: dusk             # strict mode: a palette file name
# --- OR, open mode: an inline palette (same shape as a palette file's colors/ramps) ---
# palette:
#   colors:
#     "0": { hex: "#1a1c2c" }
#     "5": { hex: "#38b764" }
#   ramps:
#     green: ["5", "6", "7"]
size: [16, 16]            # width, height in native pixels
pivot: [8, 15]            # origin point in pixels (feet/center), exported as an offset
mirror: none              # none | horizontal  (see below)
outline: none             # none | auto        (see below)
outline_color: "0"        # used when outline: auto

frames:
  idle_0: |
    ................
    ................
    .....000000.....
    ....05566650....
    ...0556776650...
    ...0556666650...
    ...0555555550...
    ....00000000....
    ................
    ...
  idle_1: |
    ...

animations:
  idle: { frames: [idle_0, idle_1], fps: 4, loop: true }
  hop:  { frames: [hop_0, hop_1, hop_2], fps: 10, loop: false }

variants:
  # Generated recolors. Either a direct key map, or a ramp-to-ramp swap (same length ramps).
  fire: { ramp_swap: { green: warm } }
  ice:  { key_swap: { "5": "a", "6": "b", "7": "c" } }

tags: [enemy, overworld]  # free-form, for searching/organizing
```

Rules:
- `palette` is either a palette name (string) or an inline palette (mapping). Whether inline palettes
  are allowed is set by `pagan.toml` (`palette_mode = "strict" | "open"`); strict mode makes inline palettes a lint error.
- Every frame grid must be exactly `size` (rows = height, each row = width chars), unless `mirror` applies.
- `.` = transparent. Any other char must be a key in the palette.
- **`mirror: horizontal`**: author only the left `ceil(width/2)` columns; the tool reflects them.
  For odd widths the center column is not duplicated. Great for symmetric creatures/items — halves the work and guarantees symmetry.
- **`outline: auto`**: the tool adds a 1px outline (4-neighborhood) of `outline_color` around all
  non-transparent pixels, *inside* the canvas. Lint errors if the outline would clip at the canvas edge.
- Frames referenced by animations must exist; unused frames are a lint warning.
- `variants` produce extra outputs (`slime_fire`, `slime_ice`) with identical geometry.

### 5.3 Tileset — `tiles/<name>.tiles.yaml`

```yaml
name: dungeon_floor
palette: dusk              # or inline, as for sprites
tile_size: [16, 16]
columns: 8                 # layout of the output atlas
tiles:
  floor_a: |
    ...16 rows...
  floor_b: |
    ...
  wall_top: |
    ...
```

Output is an atlas PNG + a JSON manifest mapping tile names to atlas coordinates. Tile order in the atlas
is the order in the file (stable, so atlas coordinates don't shift when appending).

### 5.4 Project config — `pagan.toml`

Sketch (finalize while building):

```toml
palette_mode = "strict"        # "strict" | "open"
default_palette = "dusk"       # strict mode
output_dir = "../game/assets/generated"
preview_dir = "previews"
export = ["png", "godot"]      # exporters to run on build

[lint]
max_ramps_per_sprite = 3       # W003
disable = []                   # e.g. ["W001"]
require_outline = false
```

---

## 6. The style bible — `STYLE.md` (per project, optional)

STYLE.md belongs to a *PAGAN project*, not to this repo. PAGAN ships a **template** (`pagan init` copies it)
with placeholders and suggested defaults. A project's STYLE.md is what makes *that* project's art look
like itself. The template covers:

1. **Palette** — which palette file (or "open"), and the intent of each ramp (skin, foliage, stone, metal, UI…).
2. **Scale** — base sprite/tile size (e.g. 16×16), character height in pixels, target base resolution and integer scale.
3. **Outlines** — none / dark outline / colored (selective) outline; outline color rules.
4. **Light** — light direction (e.g. top-left); highlights on lit edges, darkest ramp step on far side.
5. **Shading** — ramp steps per material; no pillow-shading (shading that just follows the outline inward); dithering allowed or not, and where.
6. **Proportions** — head-to-body ratio for characters, chunky vs. detailed, readability at 1× scale.
7. **Animation** — default fps, frame counts for idle/walk/attack, squash & stretch yes/no.
8. **Do / Don't list** — concrete rules an agent can check itself against.
9. **Reference sprites** — 2–4 approved "golden" sprites that define the look. New assets get compared against them in preview.

Mechanically checkable rules should also be lint settings in `pagan.toml` (§7). Rules that can't be checked
(light direction, proportions) are for the agent's self-review using previews.

The `examples/demo/` project in this repo has a filled-in STYLE.md as a worked example.

---

## 7. Lint rules

`pagan lint` reports **errors** (build fails) and **warnings** (build continues). Each finding has file,
frame, row/col where relevant, a rule id, and a message.

Errors:
- `E001` YAML parse error / missing required field
- `E002` unknown pixel character (not `.` and not a palette key)
- `E003` frame dimensions don't match `size` (row count or row width), accounting for `mirror`
- `E004` animation references a missing frame
- `E005` palette problems: unknown palette, bad hex, duplicate key, `.` defined, ramp references unknown key
- `E006` variant swap references unknown key/ramp, or ramp lengths differ in `ramp_swap`
- `E007` `outline: auto` would clip at canvas edge
- `E008` pivot outside canvas
- `E009` inline palette used in a strict-mode project

Warnings:
- `W001` orphan pixel (single opaque pixel with no opaque 8-neighbors) — usually a mistake
- `W002` unused frame
- `W003` sprite uses colors from > N ramps (N configurable) — style drift hint
- `W004` frame is fully transparent
- `W005` animation frames have very different opaque bounding boxes (possible jitter)

Configurable per project via `pagan.toml` (turn rules on/off, thresholds, required outline).
Lint also works with no `pagan.toml` at all (sensible defaults, open mode), so a single file can be checked anywhere.

---

## 8. `CLAUDE.md`

Short, living file at repo root. Any agent reads it at session start. Include:
- one-paragraph project summary + pointer to PLAN.md,
- how to install and run pagan and its tests,
- repo layout summary,
- conventions (Python style, typed code, test expectations, commit message style),
- a **Decisions log**: dated one-liners for every non-obvious decision made (including any added dependency and why).

---

## 9. Milestones

Work through these in order. Each ends with: tests pass, `CLAUDE.md` updated, a short summary to the
owner with what to look at, and a commit. Mark progress here by checking the box. Expect the order and
scope to shift as we go.

### ☑ Milestone 0 — Repo scaffolding
- Create the layout from §3, `.gitignore` (Python caches, venvs, build artifacts, `previews/`), README, CLAUDE.md.
- `pagan` package skeleton (`src/` layout, root `pyproject.toml`), `pagan --version` working, pytest running one trivial test.
- GitHub Actions CI (`.github/workflows/ci.yml`): on every push and PR, install the package and run pytest
  on the supported Python versions (3.11+). Start minimal; it grows with the code (see §10).
- **Done when:** `pip install -e . && pagan --version && pytest` all succeed locally, and the CI workflow is in place
  (green once the repo is pushed to GitHub).

### ☐ Milestone 1 — Palettes + project config
- Palette loading/validation (file and inline), `pagan.toml` loading with defaults, project discovery.
- `pagan palette show`, `pagan init`, `pagan new palette`.
- Ship 2–3 example palettes (16–32 colors, organized into ramps, different moods) in `examples/demo/`
  and render swatches for the owner to look at.
- Draft the `STYLE.md` template.
- **Done when:** `pagan init` creates a working project, and `pagan palette show` renders the example palettes.

### ☐ Milestone 2 — Sprite format, render, lint
- Sprite parsing (named and inline palettes), `mirror`, `outline: auto`, `new sprite`, `render`, `lint` (all E-rules, W001–W004).
- Golden-image tests: small fixture sprites rendered and compared byte-for-byte to committed expected PNGs.
- Determinism test: building twice yields identical bytes.
- **Done when:** a fixture sprite with mirror + outline renders correctly and every lint rule has a test that triggers it.

### ☐ Milestone 3 — Preview loop
- `preview`: upscaled frames, contact sheet with frame labels, optional grid lines, checkerboard background,
  animated GIF per animation at its fps.
- **Done when:** the agent can run `pagan preview X`, open the resulting PNG with its image-reading tool,
  and judge it. Demonstrate by drawing **3 test sprites** in `examples/demo/` (one item, one creature with
  an idle animation, one tile) and iterating on them with the owner.

### ☐ Milestone 4 — Variants, tilesets, import
- `variants` (key_swap, ramp_swap), tileset format + atlas + JSON manifest, `import` (snap-to-palette and open-mode extraction, with a change report).
- **Done when:** a variant renders correctly, a 4-tile tileset builds into an atlas with correct coordinates,
  and importing a deliberately off-palette PNG produces a clean sprite file plus a report.

### ☐ Milestone 5 — Build + Godot exporter
- `pagan build` outputs into the configured output dir:
  - one spritesheet PNG per sprite (frames in a grid, deterministic order),
  - tileset atlases,
  - a `manifest.json` describing everything generated, including pivots.
- Godot exporter (first engine target; keep exporters pluggable so others can be added later):
  - a **`SpriteFrames` `.tres`** per animated sprite (Godot 4 text resource format, `format=3`), using
    `AtlasTexture` sub-resources pointing into the sheet, with each animation's fps and loop flag,
  - pivot documented for use as `AnimatedSprite2D.offset`.
  - Do **not** hand-write Godot `.import` files; Godot generates them. Check the exact `.tres` syntax
    against the Godot 4 docs or a resource saved by the editor rather than from memory.
- Verification: a small Godot 4 test project under `examples/` (ask the owner for the Godot version first),
  with a demo scene showing every generated sprite/animation. If a Godot binary is available, validate
  headlessly (`godot --headless --path <proj> -s <script>` loading every generated `.tres`), exposed as
  `pagan build --verify-godot` or a separate script.
- **Done when:** the example Godot project opens, the demo scene runs, and sprites are crisp and correctly animated.

### ☐ Milestone 6 — The Claude skill (how to use PAGAN)
- **Priority note:** this skill is *required* before PAGAN is used to build assets for a real game.
  Everything in §12 can wait; this cannot.
- Write a Claude skill that ships with PAGAN (e.g. `pagan init` can drop `.claude/skills/make-asset/SKILL.md`
  into a user's project) and encodes the full workflow so any agent or sub-agent can handle "create the asset for X":
  1. Read the project's `STYLE.md` (if any) and look at the golden reference previews.
  2. Clarify only if the request is truly ambiguous (size? animated? which ramps?).
  3. Scaffold with `pagan new`, author the grid (use `mirror` when symmetric).
  4. `lint` → fix → `preview` → **look at the preview image** → self-review against STYLE.md and the references → iterate (cap at a few rounds).
  5. `build`, then report back with the preview path and what was created.
- Also document the PAGAN notation itself concisely enough to fit in an agent's context (a "language reference").
- Base it on what actually happened in Milestones 3–5, not on guesses.
- **Done when:** a fresh agent given only "make a wooden barrel prop" in the demo project produces a lint-clean, on-style asset.

---

## 10. Quality bar

- Typed Python (type hints throughout), small modules (`palette.py`, `sprite.py`, `render.py`, `lint.py`, `project.py`, `exporters/godot.py`, `cli.py`, …).
- Tests for every format rule and every lint rule; golden-image tests for rendering.
- **CI as we go:** tests are written alongside the code, and CI runs them on every push. Every milestone ends
  with CI green. When new checks are worth automating (e.g. type checking, a determinism check), add them to CI
  in the same milestone that introduces them.
- Deterministic output: stable ordering everywhere, no timestamps or randomness in generated files, PNGs saved with fixed settings and no metadata that varies.
- Error messages point to file, frame, row, column, and say how to fix.
- **Nothing in the tool is specific to one game or one project.** Project-specific choices live in the
  user's PAGAN project (palette, STYLE.md, `pagan.toml`).

---

## 11. First session checklist (start here)

1. Read this file, then create Milestone 0 and commit.
2. Proceed to Milestone 1. Things to raise with the owner along the way (don't block on them; propose defaults):
   - Example palettes: moods to showcase in `examples/demo/`.
   - Exact `pagan.toml` shape and open-mode details, once the first version exists to react to.
   - Godot version for the Milestone 5 test project (default: latest stable 4.x).

The owner will steer from there. Keep momentum, keep things small, and show results early.

---

## 12. Future (not scheduled — don't start unless the owner asks)

These are wanted eventually, but are well beyond v1. (The Claude skill is Milestone 6; basic CI starts in Milestone 0.)

- **Documentation** — proper user docs beyond the README: install, the PAGAN notation reference,
  `pagan.toml` reference, lint rule reference, exporter docs, worked examples.
- **Release automation** — version tagging, changelog, PyPI publish via GitHub Actions (ask before publishing anything).
  Regular CI is *not* future work; it starts in Milestone 0 (see §10).
- **Website** — a project site (e.g. GitHub Pages) hosting the docs and a gallery of example art.

