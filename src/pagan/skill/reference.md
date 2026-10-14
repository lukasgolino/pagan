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
colors:                       # key = ONE character: 0-9 a-z A-Z ("." is transparent)
  "0": { hex: "#140c1c", name: ink }
  "1": "#442434"              # short form: just the hex
ramps:                        # dark -> light; one ramp per material
  warm: ["1", "2", "3", "4"]
```

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
variants:                     # recolors with identical geometry, built as <name>.<variant>
  fire: { ramp_swap: { green: warm } }            # ramps must be the same length
  ice:  { key_swap: { "5": "a", "6": "b" } }
  night: { palette: dusk_night }                  # same keys, another palette (+ swaps if needed)
```

Frame order in the file = order in the sprite sheet. Leave 1px transparent border with `outline: auto`.

## Tileset - `tiles/<name>.tiles.yaml`

```yaml
name: meadow
tile_size: [16, 16]
columns: 8                    # atlas width in tiles; tiles fill rows in file order (append-safe)
tiles:
  grass: |
    ...16 rows of 16...
  grass_b: { from: grass, flip: horizontal }
variants: ...                 # as for sprites
```

No mirror/outline/animations. Tiles should be seamless (preview shows a 3x3 tiling).

## 3D model - `models/<name>.model.yaml`

```yaml
name: ship
description: "..."
size: [96, 96]                # frame size in pixels
pivot: [48, 60]               # where `origin` lands in every frame
origin: [35, 0, 0]            # model point on the pivot; default: centre of the bounds at the bottom
directions: 8                 # 1 | 4 | 8 | 16 -> frames e, ne, n, nw, w, sw, s, se (16 adds ene, nne...)
heading: 0                    # first heading in degrees; 1 direction defaults to 270 (facing the camera)
outline: auto                 # default auto for models
camera: { elevation: 42, scale: 1 }               # optional override of pagan.toml [camera]
light: { direction: [-0.5, 0.45, 0.75], ambient: 0.2, shadows: true }   # optional override
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
    hidden: true              # not in the static frames; poses reveal it with `show: [sword]`
animations:                   # one pose per frame; parts move by whole voxels (consistent frames)
  sail:
    fps: 6
    loop: true
    poses:
      - {}
      - { pennant: { offset: [0, 1, 0] } }
      - { hide: [pennant] }                     # hide: take parts away for this frame
      - { show: [sword], sword: { offset: [1, 0, -2] } }   # show: reveal hidden parts
variants: ...                 # as for sprites
```

Coordinates: x = the model's front, y = its left, z = up; whole voxels (1 voxel = `camera.scale`
pixels). Sizes count voxels: `cylinder` `height: 3` is 3 layers; `radius: 0` is 1 voxel wide, `radius: r` is
about 2r+1 wide; `box` corners are inclusive (`from: [0,0,0], to: [0,0,0]` is one voxel).
Pivot: from above at elevation e, the front of a round base sits about r·sin(e) pixels *below* the origin,
so put the pivot a few pixels above the frame's bottom (E007 tells you if the outline would be clipped). Heading 0 shows the front pointing right ("e"), 90 away from the camera ("n"), 270 towards it.
`top:` gives a shape's top layer another material; `rim:` adds a 1-voxel wall around its top edge.
`box` is inclusive of both corners. Frames: `<heading>` (static) and `<anim>_<heading>_<i>`;
animations `<heading>` and `<anim>_<heading>` (1 direction: `main`, `<anim>_<i>`, `<anim>`).
`pagan bake <model>` writes the rendered frames as an editable sprite.

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

## `pagan.toml`

```toml
palette_mode = "strict"            # strict: palette files only | open: inline palettes allowed
default_palette = "dusk"
output_dir = "../game/assets/generated"
preview_dir = "previews"
export = ["png", "godot"]          # godot needs output_dir inside a Godot project (project.godot)
style_version = 1

[camera]                           # used by every model
elevation = 42                     # degrees above the horizon (90 = straight down)
scale = 1                          # pixels per voxel

[light]
direction = [-0.5, 0.45, 0.75]     # towards the light: x right, y up-screen, z up
ambient = 0.2                      # unlit brightness; lower = darker shadows
shadows = true

[lint]
max_ramps_per_sprite = 3           # W003
max_frame_change = 0.4             # W007
max_ramp_steps = 0                 # W008: most shades per ramp/material (0 = no limit)
disable = []                       # warning ids only
require_outline = false            # E011
```

## Commands (all accept `--json`; non-zero exit on errors)

| Command | Purpose |
|---|---|
| `pagan init [dir] [--open]` | create a project |
| `pagan new palette <name>` | starter palette |
| `pagan new sprite <name> [--size 16x16] [--frames N] [--mirror] [--outline] [--palette P] [--description D]` | blank sprite |
| `pagan new tiles <name> [--size] [--frames N]` | blank tileset |
| `pagan new model <name> [--size 64x64] [--directions 8]` | starter model |
| `pagan lint [paths] [--warnings-as-errors]` | errors + style warnings |
| `pagan preview <asset...> [--scale N] [--grid] [--bg checker\|none\|#rrggbb]` | sheet.png, frames/, GIFs |
| `pagan gallery` | every asset in one image |
| `pagan render <asset...>` | native-size PNGs |
| `pagan palette show [palettes]` | swatches |
| `pagan palette adjust <pal> [--lightness d] [--contrast k] [--saturation k] [--hue deg] [--warmth d] [--ramp r] [--keys ...] [--out new] [--dry-run]` | change the look globally |
| `pagan import <png> [--palette P \| --open] [--scale N] [--name] [--out]` | PNG -> sprite (snaps colors, report) |
| `pagan bake <model> [--name]` | model -> editable sprite |
| `pagan status` | catalogue + what needs attention |
| `pagan mark <asset...> [--status approved] [--current] [--outdated]` | record reviews |
| `pagan style bump "note"` | new style version; flags older assets (W006) |
| `pagan build [--verify-godot]` | final assets + manifest (+ Godot .tres) |
| `pagan skill install [dir]` | install this skill into a repo's `.claude/skills/` |

## Lint rules

Errors: E000 command/usage, E001 YAML/field, E002 unknown pixel key, E003 grid size, E004 missing
animation frame, E005 palette problem, E006 variant problem, E007 outline clipped at the edge, E008 pivot,
E009 inline palette in strict mode, E010 derived frame, E011 outline required, E012 duplicate asset name,
E013 model problem.

Warnings: W001 orphan pixel, W002 unused frame, W003 too many ramps, W004 empty frame, W005 visible area
jumps between frames, W006 made under an older style version, W007 too much change between frames,
W008 too many shades from one ramp (sprites) / in one material (models), when `max_ramp_steps` is set.

## Godot

`pagan build` writes `sprites/<name>.png` + `<name>.tres` (SpriteFrames, one animation per PAGAN
animation; sprites without animations get one per frame) and `tiles/<name>.png`, plus `manifest.json`
with frame rects, pivots and `godot_offset` (use as `AnimatedSprite2D.offset` with `centered = true`).
Project settings for crisp pixels: Default Texture Filter = Nearest, stretch mode `viewport`, scale mode
`integer`, snap 2D transforms to pixel.
