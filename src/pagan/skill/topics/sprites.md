# Sprites

Sprite notation: grids, derived frames, outline, shadow, animations, variants, fonts, 9-slice, trim.

## Sprite - `sprites/<name>.sprite.yaml`

```yaml
name: slime
description: "Green slime enemy, front view."   # what it is / should look like (keep it current)
palette: dusk                 # optional when pagan.toml has default_palette; open mode allows inline
size: [16, 16]                # width, height of one frame (or "16x16"); up to 4096 each (models: 1024)
sheet_columns: 8              # optional: frames per sheet row (default up to 8); W014 if the sheet passes 16384 px
trim: true                    # optional: frames cropped to their content and packed (default: pagan.toml [build] trim)
pivot: [8, 16]                # anchor in pixel-edge coords (0..w, 0..h); default [w//2, h]
mirror: none                  # none | horizontal: author only the left ceil(w/2) columns
outline: auto                 # none | auto: 1px outline added around opaque pixels (see "Outlines and shadows")
outline_color: "0"            # default: the palette's darkest opaque color
status: draft                 # draft | approved
style_version: 1              # the project style version it was made/reviewed under
tags: [enemy]
frames:
  idle_0: |                   # rows of keys; "." = transparent; every row exactly `width` chars
    ................
    ......0000......
  idle_1: { from: idle_0, shift: [0, 1] }        # derived frame: from + flip/shift
  left:   { from: idle_0, flip: horizontal }      # flip: horizontal | vertical | both
  land:   { from: idle_0, scale: [1.2, 0.8] }     # squash/stretch about the pivot (number = both axes)
  tip:    { from: idle_0, rotate: 6, about: [8, 16] }   # degrees, + = clockwise; about: pivot (default) | center | [x, y]
animations:
  idle: { frames: [idle_0, idle_1], fps: 4, loop: true }
  blink: [idle_0, idle_1]                         # short form: fps 8, loop true
  hit: { frames: [a, b, c], fps: 10, durations: [1, 1, 3] }   # holds: c shows 3/10 s (Godot frame duration)
  rise: { frames: [r0, r1, r2, r3], loop_from: 2 }   # intro r0 r1 once, then r2 r3 loop (see below)
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
                              # (up to 256 combinations; no limit with variant_sheets = false, where over 256
                              # no combinations are made: the game composes the axes' swaps)
base_variant: cyan            # optional (any asset kind): the base colours' name; the manifest lists the
                              # base sheet under variants.cyan too, so the game sees one uniform set
supersample: 2                # optional (any asset kind): drawn at 2x the size the game gets; the build
                              # box-filters it down (smooth edges, partial alpha). Default: pagan.toml `supersample`
lint:                         # optional: warnings off for this asset only (any asset kind)
  disable: [W005, W007]       # e.g. expanding bursts change shape by design
  for: { idle_1: [W001] }     # ...or only for some frames/tiles/animations
  max_ramps: 9                # W003's limit for this asset (e.g. a sheet of unrelated pickups)
nine_slice: [4, 4, 4, 4]      # optional: 9-slice margins left, top, right, bottom (px), or per frame:
                              # { frame: [4, 4, 4, 4] }; carried into the manifest (NinePatchRect patch margins)
points:                       # optional: named attachment points (sockets) for particles, weapons, hit boxes
  muzzle: [12, 7]             # [x, y] in pixel-edge coords like pivot: the same in every frame
  fire: { wob00: [30, 12], wob01: [31, 10] }   # or per frame (only the frames listed; derived frames too)
font:                         # optional: the frames are a font's glyphs (manifest metrics + <name>.fnt)
  glyphs: " !\"#ABC..."       # characters in glyph order (or a list of strings, joined)
  cell: [6, 8]                # glyph cell: frames are cut into cells row by row (default: one glyph per frame)
  baseline: 7                 # rows from the cell top to the baseline (default: cell height)
  advance: auto               # auto = drawn width + spacing | N fixed (default: cell width)
  spacing: 1                  # auto advance: pixels after each glyph
  space: 3                    # auto advance of blank glyphs such as " " (default: half the cell)
  line_height: 9              # default: cell height
  advances: { "i": 4, "1": 5 }  # optional: per-character advance (source metrics), over advance/auto
  offsets: { "j": -1, "g": [0, 1] }  # optional: per-character draw offset x or [x, y] from the pen (.fnt xoffset/yoffset)
  skip_blank: true            # optional: blank cells aren't glyphs (except " " etc.), so the engine falls back to another font
```

Frame order in the file = order in the sprite sheet (generated frames of mirrored animations come
after the written ones). Derived frames apply flip, then scale/rotate (nearest neighbour, about the pivot
unless `about` says otherwise), then shift; E010 if opaque pixels would leave the canvas. Leave a 1px transparent border with `outline: auto`. Findings give `row`/`col`
1-based, counted in the grid as written (for `mirror: horizontal`, in the authored left half).

**Big generated art as an indexed PNG** (`frames_png:`, sprites): instead of (or before) `frames:`, frames come from
the cells of an indexed (palette-mode) PNG next to the file, so a megapixel sprite isn't megabytes of YAML:

```yaml
frames_png:
  file: logo.frames.png       # relative to this file; must be an indexed (mode P) PNG inside the project
  keys: { 0: ".", 1: "a", 2: "b" }   # every PNG palette index used -> a palette key or "." (PNG colours are ignored)
  frames: [logo_0, logo_1, logo_2]   # cell names in reading order; cells are `size` (left half with mirror)
frames:                       # optional: more frames after the PNG's, e.g. derived from them
  logo_3: { from: logo_2, shift: [0, 1] }
```

The PNG is a grid of frame-sized cells (as many columns as fit its width), read left to right, top to bottom;
unnamed cells after the last name must be empty. PNG frames are linted, outlined and built exactly like grid
frames (findings name the frame and its row/col in the cell, on the `frames_png` line). Write one from a
generator with `api.frames_png(...)`. Text grids stay the default: use a PNG only for generated art too big to read.

**Intro, then a loop** (`loop_from: N`): frames before index N play once, then frames N.. loop. Engines such as
Godot loop a whole animation only, so the build exports two: `<name>` = the intro (frames 0..N-1, loop false) and
`<name>_loop` = the rest (loop true), each with its share of `durations`. The manifest's `<name>` entry carries
`loop_from: N` and `next: "<name>_loop"`; game code plays `next` when the intro finishes (Godot:
`animation_finished`). Preview GIFs play the intro once, then the loop three times. N runs from 1 to frames - 1,
the animation must loop, and no other animation may be called `<name>_loop` (E001). Mirrored animations copy it.

**Outlines and shadows** (sprites; PAGAN adds them to every frame, so frames stay plain shapes):

```yaml
outline: { width: 3, color: "0" }                            # a 3px ring (round corners); color default: outline_color
outline: [{ width: 2, color: "0" }, { width: 1, color: "7" }]  # stacked, innermost first: ink + light rim
outline: { width: 1, skip_translucent: true }                # ring only opaque pixels: glows/halos ("#rrggbbaa") stay soft
shadow: { offset: [3, 4], color: "s" }                       # drop shadow of the outlined shape (+x right, +y down)
```

Width 1 is exactly `outline: auto`; wider rings take every transparent pixel within `width` pixels (centre to
centre) of the shape, up to 8 output pixels per ring (8 x `supersample` source pixels). The shadow goes under the sprite (only on transparent pixels); a
translucent colour (`"#00000080"`) suits it. Leave a transparent border as wide as all rings together, and room
for the shadow on its side (E007; with `skip_translucent` on every ring, translucent pixels may touch the edge). With `supersample`, widths and offsets are in source pixels.
