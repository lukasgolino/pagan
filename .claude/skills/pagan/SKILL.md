---
name: pagan
description: Make and maintain pixel-art game assets with PAGAN (Pixel Art Grammar And Notation) - sprites, characters, enemies, items, tiles, icons, 3D ships/vehicles/buildings rendered in 4/8/16 directions, animations - and change a game's art style over time (camera angle, light direction, darker, more contrast, pastel, more shadows, new palette). Use whenever a user or an orchestrating agent asks for game art, a sprite, an asset, a tileset, rotations/headings, an animation, or a look change, or mentions pagan / pagan.toml.
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
2. **Perspective** - top-down 3/4 (default), straight top-down, side-on, or isometric. Sets `[camera]`.
3. **Mood / references** - e.g. "warm and earthy", "neon", "Stardew-like", "Hyper Light Drifter".
4. **Sizes** - small things 16x16 (default) or 32x32; big things (vehicles, bosses) e.g. 64-96px.
5. **Look rules** - dark 1px outline (default) or none; light from the top-left (default).
6. **Engine** - Godot 4 (default; give the path to the Godot project) or plain PNGs.

Then:
- `pagan init art` inside the game repo (`--godot <godot project dir>` to build straight into it;
  `--open` only for throwaway prototypes). Inside a Godot project, init writes `.gdignore` so Godot
  doesn't import the art sources.
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

**Size is the requester's choice.** PAGAN makes any size (sprites/tiles up to 1024x1024; models any frame
size). Small means less detail; that's the deal, so say so if a request is small for what it describes
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
- **Many similar assets or procedural shapes** (effect bursts, 16-tile corner sets, a family of ships):
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
   every heading and pose (after adding animations, run it again).
4. `pagan preview <name>` -> **open `previews/<name>/sheet.png` with the Read tool and look at it.**
5. Self-review against STYLE.md and the reference assets (`pagan gallery` shows the whole set):
   silhouette readable at 1x? light from the right side? ramps used dark->light? no pillow shading?
   consistent with the other assets' size and detail? For animations: the "changes" row should only
   light up the parts that are meant to move - no jumps.
6. Show the owner: the sheet path (and GIF paths), a one-line summary, and any choice you made.
   If the owner isn't around, leave it `status: draft`, note it in BRIEF.md (wishlist: "awaiting review")
   with the choices and open questions, and move on.
7. On approval: `pagan mark <name> --status approved`, add it to BRIEF.md "Done" (and log feedback),
   `pagan build` (add `--verify-godot` if GODOT is set).
8. **Report back** what the game side needs to use it (from `manifest.json`): the sheet / `.tres` paths,
   animation names, frame size, and:
   - **Pivot:** resources can't carry it. In Godot set `centered = true` and
     `offset = Vector2(godot_offset[0], godot_offset[1])` on the AnimatedSprite2D/Sprite2D (manifest value);
     elsewhere, draw the frame with its `pivot` pixel at the object's position.
   - **3D models:** one animation per heading (`e`, `ne`, ...) plus `<anim>_<heading>`; the game picks
     the heading from its movement direction.
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
  `animations` entry. Keep everything that shouldn't move on exactly the same pixels; check the changes
  row and W007. Typical frame counts: idle 2-4, walk 4-6, attack 3-5.
- **"Make an enemy / another character"**: new asset in the same style - same palette, outline, light,
  proportions; compare side by side with `pagan gallery`. Variants (`variants:` ramp_swap/key_swap/
  palette) are the cheap way to make recolored versions (elite enemy, night version, team colours);
  `pagan preview` writes variants.png to compare them. Many variants of big models multiply sheet sizes:
  if the game can recolour in a shader, set `variant_sheets = false` and point it at each variant's
  `swap` table in manifest.json.
- **A family of related assets** (character classes, unit types, building tiers): put the shared body in a
  `template: true` model and `extends:` it per member (add parts, `remove: [ids]`, override materials),
  so a fix to the base reaches all of them. **Colours that combine** (player colour × rank, team × armour
  tint): `variant_axes`, not one variant per combination.
- **Out of palette keys** (62 ASCII letters/digits used): keep going with Unicode letters (à, é, ß, α, Ω...);
  see reference.md. Don't alias existing keys or copy the palette.

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
- Keep 1px of transparent border when `outline: auto` (E007 otherwise).
- Previews are for looking; `pagan build` output is what the game uses. Don't hand-edit build output.
- Don't commit or push unless the owner asks.
- If PAGAN itself seems wrong (a crash, a misleading error), say so instead of working around it silently.
