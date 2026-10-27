---
name: pagan
description: Make and maintain pixel-art (and flat / vector-like arcade) game assets with PAGAN (Pixel Art Grammar And Notation) - sprites, characters, enemies, items, tiles, icons, 3D ships/vehicles/buildings rendered in 4/8/16 directions, animations - and change a game's art style over time (camera angle, light direction, darker, more contrast, pastel, more shadows, new palette). Use whenever a user or an orchestrating agent asks for game art, a sprite, an asset, a tileset, rotations/headings, an animation, or a look change, or mentions pagan / pagan.toml.
---

# PAGAN: making game art as text

PAGAN turns text into pixel art. You write palette-keyed grids (2D) or voxel shapes (3D) in YAML;
the `pagan` CLI lints them against the project's style rules, renders previews you can look at, and
builds engine-ready assets (PNG sheets, manifest.json, Godot SpriteFrames). Full notation:
[reference.md](reference.md). Everything below is the workflow.

## 0. Setup check

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
4. No `pagan.toml` yet -> do **First-time setup** (section 1) before drawing anything.

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

## 0c. Project settings are configurable, saved and shared

The project's look lives in `pagan.toml`, not in individual assets. **Run `pagan config show`** to see every
setting, its current value, its default and what it means. Every one can change at any time:

| Setting | Default | Change it when the owner says... |
|---|---|---|
| `camera.elevation` | 42 (top-down 3/4) | "the angle is too high/low", "more top-down", "more side-on" |
| `light.direction` | [-0.5, 0.45, 0.75] (top-left) | "light from the right", "sun overhead" |
| `light.ambient` / `light.shadow_strength` | 0.2 / 0.65 | "darker shadows", "softer shadows" |
| `light.baked` + `export` "normals" | true / off | "the game has its own lighting" (flat colors + normal maps) |
| `default_palette` | (chosen at setup) | "try a different palette" |
| `camera.scale` | 1 | "everything 3D should be bigger/smaller" |
| `camera.projection` + `tile` / `cell` / `z_step` | "orthographic" / [64, 32] / 16 / 0 | "models must match our 2:1 iso tiles exactly" -> "dimetric" (models: heading 45, directions 4) |
| `supersample` | 1 (off) | "smooth edges", "sprites rotate freely", "not pixel art" (draw at 2x, build smooths) |
| `godot.filter` / `godot.mipmaps` | inherit / false | "blurry/shimmering when rotated or scaled" (linear + mipmaps) |

`[camera]`/`[light]` only matter for 3D models; `config show` marks them unused when there are none.

`pagan config set <key> <value>` validates and saves the change (invalid values are rejected; nothing is
written). It then tells you what refreshes: **3D models re-render automatically** on the next `pagan
build`/`preview`; palette changes recolor every asset; **hand-drawn 2D sprites don't change**, so if they
must match a new angle or light, `pagan style bump "..."` and redraw them (section 4). Log the change in
BRIEF.md's feedback log. Use the defaults until someone asks for something else, and say which defaults
you used.

## 1. First-time setup (a new game)

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
   (it flies, goes below things, gets close) needs meshes: see section 3b and settle `voxel_size` now.

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
  `[camera] elevation` (top-down 3/4 ~ 40-45, straight down 90, side-on 10-15), `[light]`.
- Fill in BRIEF.md (game, perspective, mood, key assets) and STYLE.md (ramp intent, scale, outline,
  light, shading, animation rules). Log the owner's answers in BRIEF.md's feedback log.

## 2. Making an asset

**Ask only what you can't infer** (BRIEF/STYLE usually answer size, palette, outline). Typical
questions, with your defaults: what it looks like (colors, key features), size, 2D or 3D, how many
directions, which animations. Start with ONE asset and get it approved before making related ones.

**Size is the requester's choice.** PAGAN makes any size (sprites/tiles up to 4096x4096, e.g. a 1x 1920-wide
splash; model frames up to 1024). Small means less detail; that's the deal, so say so if a request is small for what it describes
(e.g. "a 16px knight with a visible crest" won't read). To go bigger:
- the same model, chunkier: raise `camera: { scale: 2 }` in the model and double `size`/`pivot`;
- more detail: model it with more voxels at scale 1. For characters keep real depth and chunky parts
  (torso 4-6 voxels deep, limbs 2-3 voxels thick, head ~1/3 of the height), or the side views turn into sticks.

**2D or 3D?**
- **3D model** (`pagan new model`) for anything that needs several headings or rotations (ships,
  vehicles, top-down characters that turn), props seen at angles, buildings. Headings come out
  consistent automatically and share the project light. Animate with poses (parts move by whole voxels).
- **2D sprite** (`pagan new sprite`) for icons, UI, items, front/side-view characters, effects, and
  anything flat. Also for **small props that need one view** (a 16px barrel, crate, potion): at 1 voxel
  per pixel a tiny model has too few voxels to read, so hand-draw it (or `pagan bake` a model and touch it up).
- **Shortcuts only when they don't cost quality:** `mirror: horizontal` and derived frames
  (`from`/`flip`/`shift`) save time, but mirroring lights both sides the same, which is wrong when the light
  comes from one side. Use them for front-facing symmetric subjects or where the difference can't be seen;
  never trade a worse sprite for less work.
- **Tileset** (`pagan new tiles`) for terrain; tiles must be seamless. Animated terrain (water, lava)
  is a tileset `animations:` entry, not a separate sprite. Check transitions between different tiles
  with `pagan preview <tileset> --scene layout.txt`.
- **UI and fonts:** a 9-slice panel/button gets `nine_slice: [l, t, r, b]` (the margins reach the manifest; a
  hollow centre may need `lint: { disable: [W001] }`); a pixel font is a sprite with `font:` (glyph order,
  cell, baseline, advance): the build writes its metrics to the manifest and a `.fnt` Godot loads as a FontFile.
- **2D sprites that turn** (birds, arrows, flat arcade ships) when a model isn't right: draw the shape once
  facing east and let `api.directional_frames` + `api.rotate_points` make every heading (same names as models).
- **Many similar assets or procedural shapes** (effect bursts, 16-tile corner sets, a family of ships,
  polygon ships with rims):
  write a generator script on `pagan.api` (reference.md) - never copy PAGAN's geometry or lint rules into
  your own code; they'd drift. Keep the script next to the art and regenerate rather than hand-edit.

**The loop** (cap at ~4 rounds, then show the owner what you have):
1. Scaffold: `pagan new sprite|model|tiles <name> --size WxH --description "..."` (description = what it
   is and what it should look like; future you will rely on it).
2. Author the grid / parts. Write rows carefully: every row exactly the frame width.
3. `pagan lint <file>` -> fix every error; read warnings (orphans, ramps, jitter) and fix real ones.
   A warning that's wrong *by design* for one asset (an expanding burst trips W005/W007) goes in that
   file's `lint: { disable: [...] }` or `lint: { for: { <frame>: [...] } }` - never in pagan.toml, which
   would hide real problems everywhere. Models: `pagan fit <model>` gives a size and pivot that fit
   every heading and pose; `--write` puts them in the file (after adding animations, run it again).
4. `pagan preview <name>` -> **open `previews/<name>/sheet.png` with the Read tool and look at it.**
   (It also writes 1x frames to `previews/<name>/native/` for scripted montages.) A sheet over 4096 px is
   split into pages: `sheet.png` is then an overview and each animation (models: each pose, every heading)
   gets `sheet.<animation>.png` (continued in `sheet.<animation>.2.png`, ...): open the pages too.
   Sprites meant to play together (a title, a hit and its sparks, a cutscene): put them in a
   `scenes/<name>.timeline.yaml` (reference: Timeline preview) and `pagan preview scenes/<name>.timeline.yaml
   --at 1.9,2.0` -> look at `previews/<name>.timeline/at.png` (and timeline.gif).
5. Self-review against STYLE.md and the reference assets (`pagan gallery` shows the whole set):
   silhouette readable at 1x? light from the right side? ramps used dark->light? no pillow shading?
   (flat style: clean shapes, even rims, no stray pixels.) Supersampled: judge `built_1x.png`, not the source.
   consistent with the other assets' size and detail? For animations: the "changes" row should only
   light up the parts that are meant to move - no jumps.
6. Show the owner: the sheet path (and GIF paths), a one-line summary, and any choice you made.
   If the owner isn't around, leave it `status: draft`, note it in BRIEF.md (wishlist: "awaiting review")
   with the choices and open questions, and move on.
7. On approval: `pagan mark <name> --status approved`, add it to BRIEF.md "Done" (and log feedback),
   `pagan build` (add `--verify-godot` if GODOT is set). Uncached models and Godot print `pagan: ...`
   progress on stderr; a first build of many big models can take minutes, so give the command a long
   timeout rather than assuming it hung.
8. **Report back** what the game side needs to use it (from `manifest.json`): the sheet / `.tres` paths,
   animation names, frame size, and:
   - **Pivot:** resources can't carry it. In Godot set `centered = true` and
     `offset = Vector2(godot_offset[0], godot_offset[1])` on the AnimatedSprite2D/Sprite2D (manifest value);
     elsewhere, draw the frame with its `pivot` pixel at the object's position.
   - **3D models:** one animation per heading (`e`, `ne`, ...) plus `<anim>_<heading>`; the game picks
     the heading from its movement direction.
   - **Animation order:** `animation_order` (manifest keys are sorted alphabetically).
   - **Tilesets:** a Godot `TileSet` `.tres` (`godot_tileset`) with every tile in atlas source 0 at the
     coordinates in the manifest's `tiles` (`name -> [column, row]`); no terrains/collision yet, set those
     up in the editor if needed.

**Trying alternatives:** asset names must be unique across sprites, tiles and models, so give
experiments their own names (`barrel_a`, `barrel_b`, or `pagan bake <model> --name <other>`), compare them
in `pagan gallery`, then delete the losers and keep the winner under the real name.

## 3. Follow-up requests on existing assets

- **"Give it 8 directions / rotations"**: if it's a 2D sprite, rebuild it as a model (`models/`) so
  every heading is consistent (`directions: 8`), matching the approved sprite's colors and proportions,
  then remove/rename the sprite (asset names must be unique). Models already have them: change
  `directions`.
- **New animation** (sword swing, walk, hop): models -> add parts with `id:` and an `animations:` entry
  with one pose per frame (parts move by whole voxels; `roll`/`pitch` tilt the whole model, e.g. a ship
  listing as it sinks; a part can rotate about a hinge, e.g. a falling mast). Damage and extras are
  `hidden: true` parts (overlays: they never alter the normal frames; with `carve: true` they cut holes)
  that poses `show`; 2D -> add frames (derive with `from`/`shift` where possible) and an
  `animations` entry (squash/stretch, tipping and pulsing: `from` + `scale`/`rotate`). Keep everything that shouldn't move on exactly the same pixels; check the changes
  row and W007. Typical frame counts: idle 2-4, walk 4-6, attack 3-5.
- **"Make an enemy / another character"**: new asset in the same style - same palette, outline, light,
  proportions; compare side by side with `pagan gallery`. Variants (`variants:` ramp_swap/key_swap/
  palette) are the cheap way to make recolored versions (elite enemy, night version, team colours);
  `pagan preview` writes variants.png to compare them. When the base colours are one of the set (team
  cyan + red/orange/...), name them with `base_variant: cyan` so the manifest lists all of them uniformly. Many variants of big models multiply sheet sizes:
  if the game can recolour in a shader, set `variant_sheets = false` and point it at each variant's
  `swap` table in manifest.json. **A look for a whole set** ("everything on the map gets an arctic
  version"): put the variant in the palette file (`variants: { arctic: { ramp_swap: ..., tags: [world] } }`),
  not into every asset; tilesets compare variants on their first drawn tile (`--frame NAME` for another, and
  `--scene` writes scene_variants.png).
- **A family of related assets** (character classes, unit types, building tiers): put the shared body in a
  `template: true` model and `extends:` it per member (add parts, `remove: [ids]`, override materials),
  so a fix to the base reaches all of them. **Colours that combine** (player colour × rank, team × armour
  tint): `variant_axes`, not one variant per combination.
- **Shadows, glows, light rays, smoke**: give the palette translucent colours (`"#00000080"`, `"#rrggbbaa"`)
  and draw them like any other key, instead of dithering or tinting in the game. Not for 3D models (opaque).
- **Out of palette keys** (62 ASCII letters/digits used): keep going with Unicode letters (à, é, ß, α, Ω...);
  see reference.md. Don't alias existing keys or copy the palette.

## 3b. 3D games (meshes)

When the game's camera moves freely in 3D, pre-rendered headings can't serve it: models must also build as
meshes (`.glb`). Same model files, no edits; sprites still build too unless a model is mesh-only
(`directions: 0`). Notation and output: reference.md "Meshes".

**Setup** (once, with the owner):
- `pagan config set export png,godot,mesh` (drop godot if the engine isn't Godot).
- **Pick `voxel_size` with the owner** (`pagan config set mesh.voxel_size <metres>`); it's the game's texel
  density, the same for every model. Work it out from the **closest the camera gets** and the render
  resolution: on-screen pixels per voxel ~ `screen_height_px * voxel_size / (2 * distance * tan(fov / 2))`.
  At the closest distance a voxel should cover a few pixels (chunky, readable), and anything gameplay hits
  at close range needs real voxels: an eye that is a hit zone is at least 2x2 voxels, a hand 2-3 thick.
  Example: 270 px tall, 70 degrees, closest 0.5 m, 0.0625 m voxels -> ~24 px per voxel up close, ~1 px at
  12 m. Default 0.0625 (16 voxels per metre: a 1.8 m soldier is ~29 voxels tall). Huge, distant structures
  may override `voxel_size` per model (W009 reminds you they'll look coarser), or be split into modules.
- `[mesh] shading`: `ramp` (default: palette-locked lighting from the game's sun, Godot shader), `baked`
  (fixed-side props, no shader), `flat` (the game shades). Godot scenes: Linear tonemapper, a
  DirectionalLight3D (the sun) with shadows.

**Making a 3D asset** - the loop from section 2, plus:
- **Rig for gameplay:** give an `id` to everything that moves, detaches or is hit (head, helmet, eyes,
  shield, a trebuchet arm). In `rig:` set `parent` (children follow: helmet -> head -> torso), `pivot` at the
  joint or hinge (shoulder, axle), `meta` for what game code reads (`hitzone: eye`, `detachable: true`,
  `armour: 2`), `collision: box | convex` where the game needs a shape. The manifest gives each part's node
  path, pivot and AABB (metres) for hitboxes. Only names and meanings the owner agreed; write them in BRIEF.md.
- **Covering parts and big buildings:** a part drawn over another (a bucket helm over the head) replaces its
  voxels, and an id left with none has no node (W013). Make the cover `shell: true` (hollow) instead; hollow
  `shell` towers and walls also stay far under the 2M-voxel cap.
- **Animations:** as poses; `interpolation: linear` for smooth mechanical motion (an arm swinging);
  keep the default step for pixel-art timing. Show/hide parts per pose for props that appear.
- **Review in 3D, not just the headings:** `pagan preview <model> --orbit` (undersides! a flying camera sees
  them) and `--closeup <part>` for anything seen up close (faces, hit zones); `--engine` shows the real
  shader in Godot when there's a display. Look at all of them before reporting.
- **Triangle budget:** read `triangles` in `pagan build --json`'s manifest. Big flat areas of one material
  merge into few triangles; noise (scattered single voxels, dithering, many materials) multiplies them.
  Rough budgets unless the owner says otherwise: a prop < 2k, a character < 5k, a big structure < 30k.
- **Models or textures?** Things with a silhouette and depth (characters, siege engines, towers) are models.
  Big repeating flat surfaces (ground, wall faces, roofs) are tile textures: a tileset with
  `export_textures` (seamless tiles, `groups` to break up repetition, `triplanar: true` in Godot).
- **Report back:** `godot_scene` (or `glb`), the part node paths and `meta` keys, animation names, the
  triangle count, `voxel_size`, and the preview paths.

## 4. Changing the look over time

Look changes go through the palette and the project light whenever possible, because then **every
asset updates at once** and stays consistent:

| Owner says | Do |
|---|---|
| "darker" / "lighter" | `pagan palette adjust <pal> --lightness -0.05` (or +) |
| "more contrast" | `pagan palette adjust <pal> --contrast 1.15` |
| "more pastel" / "muted" | `pagan palette adjust <pal> --saturation 0.6 --lightness 0.04` |
| "more vivid" | `--saturation 1.2` |
| "warmer" / "cooler" | `--warmth 0.02` / `--warmth -0.02` |
| "only the greens darker" | add `--ramp <ramp>` (or `--keys ...`) |
| "more / softer shadows" | `pagan config set light.ambient 0.1` (3D re-renders); 2D: needs redrawing (below) |
| "light from the right" | `pagan config set light.direction "[0.5, 0.45, 0.75]"`; 2D: redraw (below) |
| "lower / higher camera angle" | `pagan config set camera.elevation 30` (3D re-renders); 2D: redraw (below) |
| "our engine does the lighting" | `pagan config set light.baked false` and add "normals" to `export` |
| "try a different palette" | `--out <new>` to make a copy, or a new palette with the SAME keys, then switch `default_palette` (grids reference keys, so assets carry over) |

Always use `--dry-run` or the before/after swatch it writes, then `pagan gallery` to check the whole
set, and log the change in BRIEF.md's feedback log.

**When existing 2D art must be redrawn** (more shading, new outline style, new proportions):
1. `pagan style bump "what changed and why"` - bumps `style_version`, logs it in STYLE.md.
2. Update STYLE.md's rules to match.
3. `pagan status` lists every asset flagged "review for style vN" (lint W006).
4. Go through them one by one: update, preview, look, then `pagan mark <name> --current`.
5. `pagan gallery` at the end; `pagan build`.

## 5. Rules of thumb

- Never invent colors: everything comes from the palette (strict mode makes this an error anyway).
- Keep 1px of transparent border when `outline: auto` (E007 otherwise). Thick or double outlines and drop shadows
  are `outline: { width: N }` / a list, and `shadow:` (reference.md): don't paint them into the frames.
- Previews are for looking; `pagan build` output is what the game uses. Don't hand-edit build output.
- Don't commit or push unless the owner asks.
- If PAGAN itself seems wrong (a crash, a misleading error), say so instead of working around it silently,
  and offer to report it (section 6).

## 6. Help us improve PAGAN: report what got in your way

PAGAN is young, and it gets better mostly through reports from agents like you using it on real games. When
something gets in your way, please tell us in a GitHub issue at https://github.com/lukasgolino/pagan/issues. It
is the most useful thing you can do for the project. Whether you do is entirely up to you and your user.

Worth reporting: a crash or traceback; a wrong or misleading message or lint rule; output that looks or behaves
wrong; a workaround you had to invent; a feature you needed and didn't have; this skill or the reference
misleading you.

1. Note it as you go; don't interrupt the task for it.
2. At a natural break (the end of the task, your report), draft the issue: a one-line title; `pagan --version`;
   what you did (commands, a minimal source snippet); what you expected and what you got; the workaround, if
   any. End the body with "Reported by an agent using PAGAN." Keep it to a minimal repro: no game names, private
   asset content, paths or anything else from the user's project unless they OK it.
3. Look for an existing issue first: `gh issue list --repo lukasgolino/pagan --search "<keywords>"`; if one
   fits, offer a comment on it instead.
4. Show the user the draft and ask whether to file it. Issues are public and posted under their GitHub account,
   so **never file without their OK**. If they agree:
   `gh issue create --repo lukasgolino/pagan --title "..." --body-file <draft>`, or give them the link
   https://github.com/lukasgolino/pagan/issues/new?template=agent-report.md to file it themselves. If they
   decline, drop it.
