# Setup

Setup check, who you work for, first-time setup, project layout.

## Setup check

1. `pagan --version` (it shows the exact build, e.g. `pagan 0.1.0 (v0.1.0, ce24ab4)`). If missing, install
   it **the way the project specifies** (its requirements file / pinned tag, e.g.
   `pip install -r requirements.txt`). Never replace a pinned install with an editable checkout
   (`pip install -e`) unless you are developing PAGAN itself; if unsure, stop and ask.
2. Find the art project: `pagan status` (it says so if there's no `pagan.toml` here or above), or look for one
   (`find . -name pagan.toml -not -path '*/node_modules/*'`). That folder is the game's **art home**:
   - `BRIEF.md` - what the game is, its key assets, the wishlist, and a dated feedback log
   - `STYLE.md` - how the art must look, with a versioned changelog
   - `pagan.toml` - palette, camera, light, lint rules, output dir
   - `palettes/`, `sprites/`, `tiles/`, `models/` - the sources; every asset has a `description`
3. **Always read BRIEF.md and STYLE.md before making or changing anything**, and run `pagan status`.
   They are your memory between sessions: the chosen palette, sizes, perspective, references and
   every decision the owner made live there, not in your head.
4. No `pagan.toml` yet -> do **First-time setup** (below) before drawing anything.

**PAGAN as MCP tools:** if you have PAGAN tools (`status`, `write_asset`, `preview`, ...), use them instead of
the CLI; the workflow below is the same (`write_asset` lints, `preview` returns the image to look at).


## 0b. Who you're working for

You may be talking to a human, or (often) to an **orchestrator agent** that is building the game and
comes to you for art. Either way:
- Batch questions into ONE message, each with your recommended default, and say you'll use the defaults
  if there's no answer. Never block: an orchestrator may answer later or not at all.
- Report results so a program can use them: the asset name, its files (`pagan build --json` /
  `manifest.json` entries: sheet, frame rects, animations, pivot), the preview sheet path, and any
  decision you made. `manifest.json` in the output dir is the contract with the game (any engine).
- Godot export (`.tres`) is a convenience when the game uses Godot; PAGAN is engine-agnostic.


## First-time setup (a new game)

Ask once, in ONE compact message, each question with a recommended default so the owner can just say
"defaults":

1. **The game** - name, genre, what the player does. (needed for BRIEF.md)
2. **Rendering style** - traditional pixel art (default), or flat / vector-like arcade shapes (neon
   triangles, glowing lines, no outlines or painted light), or painterly. Ask this; don't assume pixel art.
3. **Perspective** - top-down 3/4 (default), straight top-down, side-on, or isometric. Sets `[camera]`.
4. **Mood / references** - e.g. "warm and earthy", "neon", "Stardew-like", "Hyper Light Drifter".
5. **Sizes** - small things 16x16 (default) or 32x32; big things (vehicles, bosses) e.g. 64-96px.
   Does the game rotate or scale sprites freely? (then: supersample, below)
6. **Look rules** (pixel art) - dark 1px outline (default) or none; light from the top-left (default).
7. **Engine** - Godot 4 (default; give the path to the Godot project) or plain PNGs.
8. **2D or 3D game?** - a 2D game (incl. top-down 3/4) uses sprites (default). A game with a free 3D camera
   (it flies, goes below things, gets close) needs meshes: see `pagan docs meshes` and settle `voxel_size` now.

Recipes per rendering style:
- **Pixel art** - the rest of this skill's defaults: outline, light from the top-left, ramps dark -> light,
  no pillow shading. These are pixel-art defaults, not PAGAN requirements.
- **Flat / vector arcade** - `pagan init --style flat`: no outline, no painted light or shading ramps;
  each object is a filled shape with a paler rim (`api.Canvas.polygon(points, lambda d: rim if d < 2 else
  fill)`), lines/lasers with `line(..., width=)`; glow and lighting are done by the engine. If sprites rotate
  freely: `pagan config set supersample 2` (draw at 2x, the build writes smooth anti-aliased PNGs) and in Godot
  `godot.filter linear` + `godot.mipmaps true`. Show the owner one flat shape before detailing anything.
- **Painterly** - pixel-art workflow with more ramp steps, soft dithering and no outline; consider
  `supersample 2` for soft edges.

Then:
- `pagan init art --perspective <top-down|top-down-3/4|side|iso> --style <pixel|flat>` inside the game repo
  (`--godot <godot project dir>` to build straight into it; `--open` only for throwaway prototypes). The
  perspective sets `[camera] elevation` and is written into BRIEF.md. Inside a Godot project, init writes
  `.gdignore` so Godot doesn't import the art sources.
- Palette: propose 2-3 palettes (16-32 colors, grouped into ramps dark -> light; one ramp per material:
  skin, wood, foliage, stone, metal, cloth...). Write them to `palettes/`, run `pagan palette show`,
  **look at the swatches**, show the owner the paths, let them pick or tweak. Set `default_palette`.
- `pagan.toml`: `output_dir` (e.g. `../game/assets/generated`), `export = ["png", "godot"]`,
  `[camera] elevation` (top-down 3/4 ~ 40-45, straight down 90, side-on 10-15, level 0), `[light]`.
- Fill in BRIEF.md (game, perspective, mood, key assets) and STYLE.md (ramp intent, scale, outline,
  light, shading, animation rules). Log the owner's answers in BRIEF.md's feedback log.


## Project layout

```
pagan.toml   BRIEF.md   STYLE.md
palettes/<name>.pal.yaml     sprites/<name>.sprite.yaml
tiles/<name>.tiles.yaml      models/<name>.model.yaml
scenes/<name>.timeline.yaml  (previews of sprites together in time; never built)
previews/  (scratch, gitignored)    .pagan-cache/ (model render cache, gitignored)
```

Asset names: lowercase letters, digits, `_`, `-`; must match the file name and be unique across
sprites, tiles and models.
