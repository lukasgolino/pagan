# Making

Making an asset: 2D or 3D, sizes, the lint/preview/review loop, what to report.

## Making an asset

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
  write a generator script on `pagan.api` (`pagan docs api`) - never copy PAGAN's geometry or lint rules into
  your own code; they'd drift. Keep the script next to the art and regenerate rather than hand-edit.
  Generated art of a megapixel or more (title logos, backdrops): write the frames with `api.frames_png`
  (an indexed PNG + `frames_png:`) instead of text grids, so the source stays small.

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
   `scenes/<name>.timeline.yaml` (`pagan docs timeline`) and `pagan preview scenes/<name>.timeline.yaml
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
