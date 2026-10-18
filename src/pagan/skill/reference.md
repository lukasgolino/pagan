# PAGAN reference

Everything an agent needs to write PAGAN files. All source files are YAML. Quote palette keys and hex
values (`"0"`, `"#1a1c2c"`): an unquoted `#` starts a YAML comment.

## Project layout

```
pagan.toml   BRIEF.md   STYLE.md
palettes/<name>.pal.yaml     sprites/<name>.sprite.yaml
tiles/<name>.tiles.yaml      models/<name>.model.yaml
previews/  (scratch, gitignored)    .pagan-cache/ (model render cache, gitignored)
```

Asset names: lowercase letters, digits, `_`, `-`; must match the file name and be unique across
sprites, tiles and models.

## Palette - `palettes/<name>.pal.yaml`

```yaml
name: dusk
colors:                       # key = ONE letter or digit ("." is transparent)
  "0": { hex: "#140c1c", name: ink }
  "1": "#442434"              # short form: just the hex
  "α": "#2f6b9a"              # past 0-9 a-z A-Z: any other single Unicode letter
ramps:                        # dark -> light; one ramp per material
  warm: ["1", "2", "3", "4"]
```

Keys: use 0-9, a-z, A-Z first (62), then Latin-1 letters (à-ÿ, À-Þ, ß) and Greek letters that don't look
like Latin ones (α-ω, Γ Δ Θ Λ Ξ Π Σ Φ Ψ Ω); any single Unicode letter or digit is accepted. Quote keys in
the palette file. Files are UTF-8; an accent typed as a separate combining mark is merged (NFC).

## Sprite - `sprites/<name>.sprite.yaml`

```yaml
name: slime
description: "Green slime enemy, front view."   # what it is / should look like (keep it current)
palette: dusk                 # optional when pagan.toml has default_palette; open mode allows inline
size: [16, 16]                # width, height of one frame (or "16x16")
pivot: [8, 16]                # anchor in pixel-edge coords (0..w, 0..h); default [w//2, h]
mirror: none                  # none | horizontal: author only the left ceil(w/2) columns
outline: auto                 # none | auto: 1px outline added around opaque pixels
outline_color: "0"            # default: the palette's darkest color
status: draft                 # draft | approved
style_version: 1              # the project style version it was made/reviewed under
tags: [enemy]
frames:
  idle_0: |                   # rows of keys; "." = transparent; every row exactly `width` chars
    ................
    ......0000......
  idle_1: { from: idle_0, shift: [0, 1] }        # derived frame: from + flip/shift
  left:   { from: idle_0, flip: horizontal }      # flip: horizontal | vertical | both
animations:
  idle: { frames: [idle_0, idle_1], fps: 4, loop: true }
  blink: [idle_0, idle_1]                         # short form: fps 8, loop true
  walk_right: { from: walk_left, flip: horizontal }   # mirrored animation: frames generated as walk_right_0..
variants:                     # recolors with identical geometry, built as <name>.<variant>; swaps apply
                              # to the final pixels, so every key is remapped wherever it's used
  fire: { ramp_swap: { green: warm } }            # ramps must be the same length
  ice:  { key_swap: { "5": "a", "6": "b" } }
  night: { palette: dusk_night }                  # same keys, another palette (+ swaps if needed)
variant_axes:                 # recolours that combine (any asset kind): one option per axis
  team: { red: { ramp_swap: { cloth: red } }, blue: { ramp_swap: { cloth: blue } } }
  rank: { none: {}, elite: { key_swap: { "4": "a" } } }   # {} = leave this axis as it is
                              # axes must recolour different keys; builds red+none, red+elite, blue+none...
base_variant: cyan            # optional (any asset kind): the base colours' name; the manifest lists the
                              # base sheet under variants.cyan too, so the game sees one uniform set
supersample: 2                # optional (any asset kind): drawn at 2x the size the game gets; the build
                              # box-filters it down (smooth edges, partial alpha). Default: pagan.toml `supersample`
lint:                         # optional: warnings off for this asset only (any asset kind)
  disable: [W005, W007]       # e.g. expanding bursts change shape by design
  for: { idle_1: [W001] }     # ...or only for some frames/tiles/animations
```

Frame order in the file = order in the sprite sheet (generated frames of mirrored animations come
after the written ones). Leave a 1px transparent border with `outline: auto`. Findings give `row`/`col`
1-based, counted in the grid as written (for `mirror: horizontal`, in the authored left half).

## Tileset - `tiles/<name>.tiles.yaml`

```yaml
name: meadow
tile_size: [16, 16]
columns: 8                    # atlas width in tiles; tiles fill rows in file order (append-safe)
tiles:
  grass: |
    ...16 rows of 16...
  grass_b: { from: grass, flip: horizontal }
  water_0: |
    ...
animations:                   # animated tiles: the animation's name is the tile's name
  water: { frames: [water_0, water_1, water_2, water_3], fps: 4 }   # always loops
variants: ...                 # as for sprites
lint: { for: { shore_0000: [W004] } }   # e.g. a corner set's fully transparent tile
```

No mirror/outline. Tiles should be seamless (preview shows a 3x3 tiling; `pagan preview <tileset>
--scene layout.txt` draws a layout of different tiles to check the seams between them). An animated
tile's frames sit side by side in the atlas (a new row if they don't fit; longer than `columns`: a
block `columns` wide); each tile is a frame of at most one animation. Godot gets an animated atlas tile.

## 3D model - `models/<name>.model.yaml`

```yaml
name: ship
description: "..."
size: [96, 96]                # frame size in pixels
pivot: [48, 60]               # where `origin` lands in every frame
origin: [35, 0, 0]            # model point on the pivot; default: centre of the bounds at the bottom
directions: 8                 # 1 | 4 | 8 | 16 | 32 -> frames e, ne, n, nw, w, sw, s, se (16 adds ene, nne...;
                              #   32 are h00..h31: h00 = east, counter-clockwise in 11.25 degree steps)
heading: 0                    # first heading in degrees; 1 direction defaults to 270 (facing the camera).
                              # Frames are named by where they actually face: heading 45 with 4 directions
                              # gives ne, nw, sw, se; off-compass angles are named d010, d100, ...
outline: auto                 # default auto for models
camera: { elevation: 42, scale: 1 }               # optional override of pagan.toml [camera]
light: { direction: [-0.5, 0.45, 0.75], ambient: 0.2, shadows: true }   # optional override of any [light] key
materials:                    # shade with a palette ramp (dark -> light)
  hull: { keys: ["6", "7", "8", "9"] }
  sail: { ramp: earth, two_sided: true }          # two_sided: thin cloth/leaves lit from both sides
  glow: { keys: ["a"] }                           # one key = flat, unshaded (lights, eyes)
parts:                        # applied in order; later parts overwrite earlier voxels
  - box: { from: [0, -7, 8], to: [14, 7, 11], material: hull, top: deck, rim: rail }
  - hull: { from: [0, 0, 0], length: 70, beam: 21, height: 8, bow: 0.38, stern: 0.08, material: hull, top: deck, rim: rail }
  - cylinder: { base: [36, 0, 8], height: 39, radius: 0, axis: z, material: mast }
  - ellipsoid: { center: [0, 0, 4], radii: [3, 3, 4], material: body }
  - line: { from: [66, 0, 9], to: [79, 0, 15], radius: 0, material: mast }
  - sail: { at: [36, 0, 13], width: 22, height: 14, bulge: 2.4, brace: 30, material: sail, yard: mast }
  - sail: { at: [17, 0, 14], width: 12, height: 13, rig: fore-aft, material: sail }   # luff at the mast, reaching aft
  - triangle: { points: [[62, 0, 10], [70, 0, 10], [53, 0, 30]], material: sail }       # jibs, lateens, fins, gables
  - layers:                   # literal voxels: one grid per z level, bottom first
      at: [0, 3, 0]           # grid col -> +x, grid row -> -y (seen from above, front to the right)
      legend: { w: hull, d: deck }
      grids:
        - |
          www
          www
        - |
          ddd
  - box: { from: [37, 0, 46], to: [42, 0, 47], material: flag }
    id: pennant               # names the part for poses
    mirror: true              # also add the reflection across y = 0
    carve: false              # true removes voxels instead of adding them
  - line: { from: [2, -4, 10], to: [8, -4, 16], material: steel }
    id: sword
    hidden: true              # an overlay: never in the normal frames; poses draw it with `show: [sword]`
  - box: { from: [20, 3, 6], to: [22, 3, 7], material: hull }
    id: shot_hole
    hidden: true
    carve: true               # hidden + carve: cuts a hole only in poses that `show: [shot_hole]`
animations:                   # one pose per frame; parts move by whole voxels (consistent frames)
  sail:
    fps: 6
    loop: true
    poses:
      - {}
      - { pennant: { offset: [0, 1, 0] } }
      - { hide: [pennant] }                     # hide: take parts away for this frame
      - { show: [sword], sword: { offset: [1, 0, -2] } }   # show: reveal hidden parts
  sinking:
    fps: 2
    loop: false
    poses:
      - { roll: 12 }                            # tilt the whole model about `origin` (exact, no resampling)
      - { roll: 25, pitch: 8, show: [shot_hole] }
      - { roll: 40, pitch: 15, mast: { roll: 60, about: [36, 0, 8] } }   # rotate one part about a hinge
variants: ...                 # as for sprites
lint: { for: { sinking: [W005] } }   # a pose animation name covers all its headings
```

Coordinates: x = the model's front, y = its left, z = up; whole voxels (1 voxel = `camera.scale`
pixels). Sizes count voxels: `cylinder` `height: 3` is 3 layers; `radius: 0` is 1 voxel wide, `radius: r` is
about 2r+1 wide; `box` corners are inclusive (`from: [0,0,0], to: [0,0,0]` is one voxel).
Pivot: from above at elevation e, the front of a round base sits about r·sin(e) pixels *below* the origin,
so put the pivot a few pixels above the frame's bottom (E007 tells you if the outline would be clipped). Heading 0 shows the front pointing right ("e"), 90 away from the camera ("n"), 270 towards it.
`top:` gives a shape's top layer another material; `rim:` adds a 1-voxel wall around its top edge.
`box` is inclusive of both corners. `hull` and `cylinder` are symmetric about their centre voxel, so their
widths are odd: `beam: 10` gives 9 voxels (use 11 for 11). `sail` `at` is where the sail's bottom edge
meets the mast: `rig: square` (default) hangs across the hull just forward of the mast (`brace` turns it
about the mast); `rig: fore-aft` lies along the hull with its leading edge at the mast, reaching `width`
voxels aft. `triangle` fills a flat triangle between three points (`thickness` 1-4 voxels) and shades with
its exact normal. Frames: `<heading>` (static) and `<anim>_<heading>_<i>`;
animations `<heading>` and `<anim>_<heading>` (1 direction: `main`, `<anim>_<i>`, `<anim>`).
`pagan bake <model>` writes the rendered frames as an editable sprite.

**Shared bases.** `template: true` marks a model that's only a base: linted and previewable, never built.
Another model starts from it with `extends: <base>`: it inherits everything except name, description,
tags, status, style_version, lint and template; `materials`, `animations`, `variants` and `variant_axes`
merge by name (this file wins); `parts` are the base's, minus ids listed in `remove: [ids]`, then this
file's. E.g. one `knight_base` body, then `knight_axe` / `knight_bow` that swap the weapon part and a
material. Each extending model is its own asset with its own sheet.

Hidden parts are overlays: they never change the normal frames, and a shown one is drawn over
everything (a hidden `carve` part cuts instead). A visible `carve` part removes voxels from everything
before it, hidden parts included. An id is either hidden or visible, not both.
Poses: `roll` (degrees about the front-back axis; positive lowers the right/-y side) and `pitch`
(positive tips the front down) tilt the whole model exactly. A part takes `offset` (whole voxels),
`roll`/`pitch`/`yaw` (degrees, yaw counter-clockwise from above) and `about: [x, y, z]` (hinge; default
the part's bottom centre); rotated parts are resampled, so keep rotations for things that fall or break.
Sizing: `pagan fit <model>` renders every heading and pose and prints the smallest `size` and `pivot`
that hold them all (origin stays on the pivot), plus the frames the current size clips. The frame always
holds the pivot, so overlays whose origin is their parent's pivot get a lint-valid size. `--even` pads to
even sizes so a centred Godot sprite's `godot_offset` is whole pixels.

## Recipes

**Top-down character (3D, ~22px tall in a 32x32 frame, walk cycle).** Separate parts with ids for
everything that moves; poses offset them by whole voxels so the body never jumps:

```yaml
parts:
  - box: { from: [-1, 1, 0], to: [0, 2, 6], material: trousers }     # left leg (boot: another box, same id)
    id: left_leg
  - box: { from: [-1, -2, 0], to: [0, -1, 6], material: trousers }
    id: right_leg
  - box: { from: [-1, -3, 7], to: [1, 3, 13], material: shirt }       # torso (7 wide, 3 deep)
  - box: { from: [-1, 4, 7], to: [0, 4, 12], material: shirt }        # arm; the right one at y = -4
    id: left_arm
  - box: { from: [-2, -2, 14], to: [2, 2, 18], material: skin }       # head (5 voxels)
  - box: { from: [3, 1, 16], to: [3, 1, 16], material: eye }          # eyes on the front face (+x)
    mirror: true
animations:
  walk:
    fps: 8
    poses:
      - { left_leg: { offset: [1, 0, 0] }, right_leg: { offset: [-1, 0, 0] }, left_arm: { offset: [-1, 0, 0] }, right_arm: { offset: [1, 0, 0] } }
      - {}
      - { left_leg: { offset: [-1, 0, 0] }, right_leg: { offset: [1, 0, 0] }, left_arm: { offset: [1, 0, 0] }, right_arm: { offset: [-1, 0, 0] } }
      - {}
```

Tips: keep hats/brims small (from above they hide the face); give the back of the head hair; a sword
swing: make the sword `hidden: true` so idle frames don't have it, then `show` it in the swing poses; for
big arcs use several sword parts (`sword_up`, `sword_mid`, `sword_down`, all hidden) and show one per pose.

**Ship / vehicle.** `hull` with `top:` deck and `rim:` rail, `box` castles, `cylinder` masts, `sail`s
braced ~30° so they read from every heading, `line` for spars, flags as small boxes with an `id` to animate.

**Icons and items (2D).** 16x16 sprite, `outline: auto`, light from the top-left, one or two ramps,
`mirror: horizontal` only if the light can be symmetric.

## Generator scripts: `pagan.api`

When a script is quicker than hand-written grids (effects, corner/terrain sets, families of ships), build
on `from pagan import api` instead of copying PAGAN's maths; it's versioned with PAGAN (`api.API_VERSION`).

- `api.Canvas(w, h)`: `put`, `rect`, `line` (`width=` for thick strokes, round ends), `circle`, `ellipse`, `ring`,
  `polygon(points, key)`, `triangle(a, b, c, key)`, `blit`, `flip`; for rect/ellipse/ring a key can be a
  function `(dx, dy) -> key` (offsets in radii, -1..1); for polygon/triangle a function `d -> key` (d = pixel
  centre's distance to the nearest edge in pixels: `lambda d: "rim" if d < 2 else "fill"` = a 2px rim);
  shapes fill pixels whose centres are strictly inside; `api.polygon_distance(points, x, y)` is the signed
  distance (+ inside). `fade(amount, seed)` dissolves from the edge,
  `scatter(n, key, seed, box, size)`, `orphans()` (exactly W001), `remove_orphans()`, `pair_orphans()`, `rows()`.
- Shading: `light_2d(project)` (the project's light for flat art), `sphere_light(dx, dy, light)`,
  `ramp_pick(keys, t)`, `hash01(x, y, seed)`, `periodic_noise(x, y, period, seed)` (seamless), `smoothstep`.
- Terrain: `corner_tiles(prefix, size, paint, seed, amp)` -> the 16 Match-Corners tiles
  `<prefix>_<NW><NE><SW><SE>`; `paint(field, x, y, corners)` returns a key, `field(x, y) >= 0.5` = upper
  terrain. `compose(tileset_asset, "a b\nb a")` -> a PIL image of a layout.
- 3D: `shape_cells(shape, spec)` = the voxels a part fills; `hull_reach(x, length, beam, bow, stern, keel)`;
  `sail_cells(at, width, height, bulge, brace, rig, yard)` -> cells with their cloth position (`u`, `row`),
  e.g. to place patches or gun ports exactly on a sail or hull side.
- Files: `sprite_yaml(name, size, frames, animations, **fields)`, `tileset_yaml(...)`, `write(path, text)`
  (writes only on change), `load(path)` -> parsed asset, `open_project(path)`, `palette(name, project)`.

## `pagan.toml`

```toml
palette_mode = "strict"            # strict: palette files only | open: inline palettes allowed
default_palette = "dusk"
output_dir = "../game/assets/generated"
preview_dir = "previews"
export = ["png", "godot"]          # PNG sheets + manifest always; + "godot" (.tres, needs project.godot above output_dir), "normals"
variant_sheets = true              # false: no sheet/.tres per variant, only its swap table in the manifest
supersample = 1                    # N > 1: sources drawn at N x, build box-filters down (smooth, non-pixel-art)
style_version = 1

[camera]                           # used by every model
elevation = 42                     # degrees above the horizon (90 = straight down)
scale = 1                          # pixels per voxel

[light]
direction = [-0.5, 0.45, 0.75]     # towards the light: x right, y up-screen, z up
ambient = 0.2                      # unlit brightness; lower = darker shadows
shadows = true
shadow_strength = 0.65             # how dark cast shadows are
wrap = 0.3                         # light wrapping around curves (softer shading)
baked = true                       # false: flat colors for engine lighting (+ export "normals")

[godot]                            # with export "godot"
mipmaps = false                    # true: PAGAN sets mipmaps/generate in each PNG's .import (kept across builds)
filter = "inherit"                 # SpriteFrames texture filter: inherit (node/project) | nearest | linear

[lint]
max_ramps_per_sprite = 3            # W003 for sprites/tilesets
max_ramps_per_model = 6             # W003 for 3D models           # W003
max_frame_change = 0.4             # W007
max_ramp_steps = 0                 # W008: most shades per ramp/material (0 = no limit)
disable = []                       # warning ids only
require_outline = false            # E011
```

## Commands (all accept `--json`; non-zero exit on errors)

| Command | Purpose |
|---|---|
| `pagan init [dir] [--open] [--godot DIR] [--perspective top-down\|top-down-3/4\|side\|iso] [--style pixel\|flat]` | create a project; perspective sets `[camera] elevation` (90/42/15/30) and BRIEF.md; `--style flat` = STYLE.md for flat / vector-like arcade art |
| `pagan new palette <name>` | starter palette |
| `pagan new sprite <name> [--size 16x16] [--frames N] [--directions 1\|4\|8] [--mirror] [--outline] [--palette P] [--description D]` | blank sprite; `--directions 4` scaffolds down/up/left frames + a mirrored right animation |
| `pagan new tiles <name> [--size] [--frames N]` | blank tileset |
| `pagan new model <name> [--size 64x64] [--directions 8]` | starter model |
| `pagan lint [paths] [--warnings-as-errors]` | errors + style warnings |
| `pagan preview <asset...> [--scale N] [--grid] [--bg checker\|none\|#rrggbb] [--scene FILE]` | sheet.png (labelled), montage.png (frames/headings packed on the background, e.g. `--bg "#1d3b53"` sea), frames/ and GIFs, all at the printed scale; variants.png + variants_1x.png (base and every variant side by side) when the asset has variants; `--scene` (tilesets): scene.png from a layout file (rows of tile names, `.` = empty); supersampled assets also get an "as built" row and built_1x.png (what the game gets) |
| `pagan gallery` | every asset in one image |
| `pagan render <asset...>` | native-size PNGs |
| `pagan palette show [palettes]` | swatches |
| `pagan palette adjust <pal> [--lightness d] [--contrast k] [--saturation k] [--hue deg] [--warmth d] [--ramp r] [--keys ...] [--out new] [--dry-run]` | change the look globally |
| `pagan import <png> [--palette P \| --open] [--scale N] [--name] [--out]` | PNG -> sprite (snaps colors, report) |
| `pagan bake <model> [--name]` | model -> editable sprite (default name `<model>_baked`) |
| `pagan fit <model> [--margin N] [--even]` | smallest size + pivot that fit every heading and pose |
| `pagan status` | catalogue + what needs attention |
| `pagan config show` / `get <key>` / `set <key> <value>` / `unset <key>` | project settings: value, default, meaning; validated edits; unset = back to default |
| `pagan mark <asset...> [--status approved] [--current] [--outdated]` | record reviews |
| `pagan style bump "note"` | new style version; flags older assets (W006) |
| `pagan build [--verify-godot]` | final assets + manifest (+ Godot .tres) |
| `pagan skill install [dir]` | install this skill into a repo's `.claude/skills/` |
| `pagan mcp [--project DIR] [--allow-godot]` | MCP server over stdio (needs `pagan[mcp]`) |

**MCP tools** (same JSON as the commands above): `status`, `read_docs`, `write_doc`, `log_feedback`,
`config_show`/`config_set`/`config_unset`, `palette_list`, `palette_show` (image), `palette_write`,
`palette_adjust` (dry run by default; image), `scaffold`, `read_asset`, `write_asset` (writes + lints +
preview image), `lint`, `preview` (image: sheet, montage, variants or built), `gallery` (image), `fit`,
`mark`, `style_bump`, `import_png` (path or base64), `build` (`verify_godot` needs `--allow-godot`),
`manifest`. Resources: `pagan://workflow`, `pagan://reference`, `pagan://brief`, `pagan://style`,
`pagan://manifest`, `pagan://palette/{name}`, `pagan://asset/{name}`. Prompts: `setup_new_game`,
`make_asset`, `change_the_look`, `review_asset`. Errors come back as results (`ok: false` + `findings`).

## Lint rules

Errors: E000 command/usage, E001 YAML/field, E002 unknown pixel key, E003 grid size, E004 missing
animation frame, E005 palette problem, E006 variant problem, E007 outline clipped at the edge, E008 pivot,
E009 inline palette in strict mode, E010 derived frame, E011 outline required, E012 duplicate asset name,
E013 model problem. E003 also: a size that isn't a multiple of `supersample`.

Warnings: W001 orphan pixel, W002 unused frame, W003 too many ramps, W004 empty frame, W005 visible area
jumps between frames, W006 made under an older style version, W007 too much change between frames,
W008 too many shades from one ramp (sprites) / in one material (models), when `max_ramp_steps` is set.
Turn warnings off project-wide with `[lint] disable`, or per asset/frame/animation with the file's `lint:`.
W001 isn't checked on 3D models (a rendered orphan can't be fixed pixel by pixel).

## Build output (any engine)

`manifest.json` in `output_dir` describes everything: per asset its kind, sheet, frame rects, animations
(frames, fps, loop), pivot, `godot_offset`, headings (models), tiles (`name -> [column, row]` for
tilesets; an animated tile is listed by its animation name at its first frame's cell, and the tileset
gets `animations`), variants (each with its sheet/.tres unless `variant_sheets = false`, plus `swap`:
base colour -> variant colour as "#rrggbb" for every colour it changes, and `swap_exact`: false when two
keys share a base colour but not a variant colour, so a shader swap would be wrong; with
`variant_sheets = false` that's error E006), `variant_axes` (per axis, per option: `swap`, `swap_exact`;
apply one option's swap per axis together - with `variant_sheets = false` the combinations aren't listed
in `variants`, the game composes them), and `normal_sheet` (when "normals" is exported: RGB = normal * 0.5 + 0.5, x right,
y up, z towards the viewer). Supersampled assets: `size`, frame rects and `pivot` are in output pixels
(`pivot` may be fractional), plus `supersample` and `source_size`; their sheets blend colours at edges, so
a shader swap by exact colour misses the blended pixels: use variant sheets for them. `base_variant` (when
set) names the base, also listed under `variants` with its sheet and an empty swap. Pivots aren't stored
in engine resources: apply them in the game.

## Godot

`pagan build` writes `sprites/<name>.png` + `<name>.tres` (SpriteFrames, one animation per PAGAN
animation; sprites without animations get one per frame), `tiles/<name>.png` + `<name>.tres` (TileSet:
one atlas source, every tile created, animated tiles as atlas tile animations; add terrains/physics in
the editor), plus `manifest.json`.
Apply the pivot in code: `sprite.centered = true; sprite.offset = Vector2(godot_offset[0], godot_offset[1])`.
Project settings for crisp pixels: Default Texture Filter = Nearest, stretch mode `viewport`, scale mode
`integer`, snap 2D transforms to pixel.
Smooth, freely rotated or scaled sprites: `[godot] filter = "linear"` (the SpriteFrames' CanvasTexture
carries it) and `mipmaps = true` (PAGAN keeps `mipmaps/generate` in each PNG's `.import`; Godot keeps its
other import settings). TileSets have no filter of their own: set `texture_filter` on the TileMapLayer.
