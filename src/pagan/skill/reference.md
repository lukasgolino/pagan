# PAGAN reference

Everything an agent needs to write PAGAN files. All source files are YAML. Quote palette keys and hex
values (`"0"`, `"#1a1c2c"`): an unquoted `#` starts a YAML comment.

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

## Palette - `palettes/<name>.pal.yaml`

```yaml
name: dusk
colors:                       # key = ONE letter or digit ("." is transparent)
  "0": { hex: "#140c1c", name: ink }
  "1": "#442434"              # short form: just the hex
  "α": "#2f6b9a"              # past 0-9 a-z A-Z: any other single Unicode letter
  "s": { hex: "#00000080", name: shadow }   # "#rrggbbaa": translucent (00 clear .. ff opaque)
ramps:                        # dark -> light; one ramp per material
  warm: ["1", "2", "3", "4"]
variants:                     # optional: palette-wide recolours every asset using this palette gets
  arctic: { ramp_swap: { grass: snow }, key_swap: { "5": "ε" }, tags: [world] }   # tags: only assets with one
base_variant: temperate       # optional: the base colours' name on assets that get these variants
```

Palette variants recolour within the palette (ramp_swap/key_swap, no `palette:`), so one "arctic pass"
reaches every world asset at once. An asset's own variant of the same name wins; `variants: { arctic: false }`
in an asset turns an inherited one off.

Keys: use 0-9, a-z, A-Z first (62), then Latin-1 letters (à-ÿ, À-Þ, ß) and Greek letters that don't look
like Latin ones (α-ω, Γ Δ Θ Λ Ξ Π Σ Φ Ψ Ω); any single Unicode letter or digit is accepted. Quote keys in
the palette file. Files are UTF-8; an accent typed as a separate combining mark is merged (NFC).

Translucent colours (`"#rrggbbaa"`) are for drop shadows, glows, light rays and smoke in sprites and
tilesets: the PNG pixel gets that alpha. The default `outline_color` is the darkest *opaque* colour, `pagan
import` snaps to opaque colours only, and 3D model materials must be opaque (E013). `[lint] require_opaque
= true` forbids them in a project (E015). `"#rrggbbff"` is the same as `"#rrggbb"`.

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
centre) of the shape, up to 8 per ring. The shadow goes under the sprite (only on transparent pixels); a
translucent colour (`"#00000080"`) suits it. Leave a transparent border as wide as all rings together, and room
for the shadow on its side (E007; with `skip_translucent` on every ring, translucent pixels may touch the edge). With `supersample`, widths and offsets are in source pixels.

## Tileset - `tiles/<name>.tiles.yaml`

```yaml
name: meadow
tile_size: [16, 16]
columns: 8                    # atlas width in tiles; tiles fill rows in file order (append-safe)
tile_shape: isometric         # optional: square (default) | isometric | half_offset_square | hexagon (Godot's TileSet)
tile_layout: diamond_down     # optional: stacked (default) | stacked_offset | stairs_right | stairs_down | diamond_right | diamond_down
tile_offset_axis: horizontal  # optional: horizontal (default) | vertical
tiles:
  grass: |
    ...16 rows of 16...
  grass_b: { from: grass, flip: horizontal }
  water_0: |
    ...
animations:                   # animated tiles: the animation's name is the tile's name
  water: { frames: [water_0, water_1, water_2, water_3], fps: 4 }   # always loops
  lava: { frames: [lava_0, lava_1], fps: 4, durations: [3, 1] }    # per-frame holds, as for sprites
  surf: { frames: [surf_0, surf_1, surf_2, surf_3], new_row: true }  # from column 0 of a fresh row
variants: ...                 # as for sprites
lint: { for: { shore_0000: [W004] } }   # e.g. a corner set's fully transparent tile
```

No mirror/outline. Tiles should be seamless (preview shows a 3x3 tiling; `pagan preview <tileset>
--scene layout.txt` draws a layout of different tiles to check the seams between them). With `tile_shape`
the Godot TileSet gets that shape/layout and the manifest a `tile_shape` entry; isometric tiles are previewed
(3x3 tiling, `--scene`) where Godot's TileMapLayer puts them (layout row r, column c = map cell (c, r)), so a 2:1
diamond (rows 2, 6, ..., 6, 2 for 8x4) shows its seams; `api.compose(tileset, layout, square=True)` = a plain grid. An animated
tile's frames sit side by side in the atlas (a new row if they don't fit, or always with `new_row: true`, so
the layout doesn't depend on how many tiles come before; longer than `columns`: a block `columns` wide); each
tile is a frame of at most one animation (the manifest's `tiles` gives every cell either way). Godot gets an animated atlas tile.

**Textures for 3D surfaces** (ground, wall faces, roofs: an atlas region can't repeat, a texture can):

```yaml
export_textures: true          # every tile (not animation frames) -> textures/<tileset>.<tile>.png
export_textures:
  tiles: [grass]               # all (default without groups) | none | [names]
  groups:                      # several tiles laid out as ONE texture (breaks up repetition)
    meadow_mix: |
      grass grass_flowers
      grass_flowers grass
  triplanar: true              # Godot material projects it in world space (no UVs needed)
```

Each texture is a seamless PNG (plus one per variant when `variant_sheets` is on); with "godot" a
`StandardMaterial3D` `.tres` per texture (nearest filter, repeat, alpha scissor if it has holes, triplanar at
the texture's size in metres = pixels x `[mesh] voxel_size`, the same texel density as the meshes). The
preview tiles every group 2x2 to check its seams.

## 3D model - `models/<name>.model.yaml`

```yaml
name: ship
description: "..."
size: [96, 96]                # frame size in pixels
pivot: [48, 60]               # where `origin` lands in every frame
origin: [35, 0, 0]            # model point on the pivot; default: centre of the bounds at the bottom
directions: 8                 # 1 | 4 | 8 | 16 | 32 -> frames e, ne, n, nw, w, sw, s, se (16 adds ene, nne...;
                              #   32 are h00..h31: h00 = east, counter-clockwise in 11.25 degree steps)
                              # 0 = a mesh only (3D games, `export` "mesh"): no sprites, size/pivot optional
voxel_size: 0.25              # meshes: metres per voxel for THIS model (overrides [mesh] voxel_size; W009)
heading: 0                    # first heading in degrees; 1 direction defaults to 270 (facing the camera).
                              # Frames are named by where they actually face: heading 45 with 4 directions
                              # gives ne, nw, sw, se; off-compass angles are named d010, d100, ...
outline: auto                 # default auto for models
camera: { elevation: 42, scale: 1 }               # optional override of any pagan.toml [camera] key
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
  swing_arm:
    fps: 12
    interpolation: linear       # meshes blend between poses (smooth arm swings); sprites still step
    poses: [...]
rig:                          # meshes: how parts become nodes (optional; every id is a node anyway)
  torso:  { pivot: [0, 0, 7] }                      # node origin (model voxels); default: the part's bottom centre
  head:   { pivot: [0, 0, 14], parent: torso }      # children follow their parent, in sprites too
  helmet: { parent: head, meta: { hitzone: armour, detachable: true }, collision: box }
  eye_l:  { parent: head, meta: { hitzone: eye } }  # meta: plain values -> node extras + manifest
variants: ...                 # as for sprites
lint: { for: { sinking: [W005] } }   # a pose animation name covers all its headings
```

Coordinates: x = the model's front, y = its left, z = up; whole voxels (1 voxel = `camera.scale`
pixels; with the dimetric camera, see below). Sizes count voxels: `cylinder` `height: 3` is 3 layers; `radius: 0` is 1 voxel wide, `radius: r` is
about 2r+1 wide; `box` corners are inclusive (`from: [0,0,0], to: [0,0,0]` is one voxel).
Pivot: from above at elevation e, the front of a round base sits about r·sin(e) pixels *below* the origin,
so put the pivot a few pixels above the frame's bottom (E007 tells you if the outline would be clipped). Heading 0 shows the front pointing right ("e"), 90 away from the camera ("n"), 270 towards it.
**Isometric tile games** (2:1 TileMap, e.g. 64x32 cells): `[camera] projection = "dimetric"`, `tile = [64, 32]`,
`cell = 16`. Every voxel then steps whole pixels: tile width / (2 cell) across and tile height / (2 cell) down
along x and y (2 and 1 here), `z_step` up (default tile height / cell = 2). A `cell` x `cell` floor is exactly
the hand-drawn tile diamond (rows 2, 6, ... 62, 62, ... 6, 2) and tiles at the grid pitch with no gaps or
overlap, so build floors, walls and furniture on whole cells (a 1-cell wall: 16 voxels wide). Use
`heading: 45` + `directions: 4` (frames ne, nw, sw, se); other headings are E013. A 1-voxel pose offset moves
whole pixels, so bobs and walk cycles don't shimmer (orthographic: one voxel of height is
cos(elevation) x scale px, e.g. 0.87 px at 30 degrees, and re-rasterises). Shading, outlines, normal maps
and meshes are as for the orthographic camera; `camera.scale` and `elevation` are unused.
`top:` gives a shape's top layer another material; `rim:` adds a 1-voxel wall around its top edge.
`shell: true` on a `box`, `cylinder` or `ellipsoid` keeps only its outer wall, 1 voxel thick (`shell: 2`: 2 thick):
a helmet that covers a head without swallowing it, or a big tower that stays under the 2M-voxel cap.
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
tags, status, style_version, lint and template; `materials`, `animations`, `variants`, `variant_axes` and
`rig` merge by name (this file wins); `parts` are the base's, minus ids listed in `remove: [ids]`, then this
file's. A removed part's inherited `rig` entry goes with it (inherited children hang from its parent). E.g. one `knight_base` body, then `knight_axe` / `knight_bow` that swap the weapon part and a
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
even sizes so a centred Godot sprite's `godot_offset` is whole pixels. `--write` puts the fit into the
file (`size` and `pivot` edited in place, comments kept), so a generator can write -> `pagan fit --write` -> lint.

## Meshes (3D games) - `export` has "mesh"

For a free 3D camera (flying, below models, close up), models also build as real meshes. Opt-in: without
"mesh" nothing changes. Per model:

| File | What |
|---|---|
| `models/<name>.glb` | binary glTF 2.0: one node per part, animations, metadata in node `extras` |
| `models/<name>.ramp.png` | the ramp texture: one row per material ramp, columns dark -> light (+ `<name>.<variant>.ramp.png`) |
| with "godot": `models/<name>.tscn` | the glb with PAGAN's materials on every surface: instantiate this |
| with "godot": `models/<name>[.<variant>][.two_sided].material.tres`, `models/pagan_ramp.tres` | materials and the ramp shader |

- **Axes and scale:** glTF/Godot +Y up, the model's front faces **+Z**, its left +X; 1 voxel = `[mesh]
  voxel_size` metres (default 0.0625 = 16 per metre; per model `voxel_size`). `origin` is the mesh origin.
  Godot: `look_at(target, Vector3.UP, true)` turns the front (+Z) towards a target.
- **Geometry:** voxel faces merged into rectangles (no cracks), flat normals (the voxel look). Each part is
  closed on its own, so a part can move or detach without leaving holes.
- **Shading** (`[mesh] shading`): `ramp` (default) - PAGAN's Godot shader picks the ramp step per pixel from
  the sun (every DirectionalLight3D) exactly like the sprite renderer (`[light]` ambient, wrap,
  shadow_strength), so lit pixels stay palette colours (exact in Forward+ and Compatibility; Mobile's 10-bit
  light buffer can shift dark colours a few levels); omni/spot lights add on top; use the Linear
  tonemapper; the light's colour/energy don't change the sun's result. Other glTF viewers show the middle
  step. `baked` - steps baked per voxel from the project light at heading 0 (unlit material, no shader:
  props seen from a fixed side). `flat` - middle step; the engine lights it normally.
- **Variants** are ramp textures: swapping one in game is a texture (material) swap, not a new mesh.
- **Parts:** every part id is a node (voxels without an id are the root node `body`); `rig:` sets pivots,
  parents and `meta`. Hidden parts are hidden nodes (KHR_node_visibility; Godot: `visible = false`), shown
  by animations. Hidden *carving* parts can't be meshes (E014): add a damaged part and hide the intact one.
  `collision: box | convex` is a hint in the node extras and the manifest; `[mesh] collision_suffixes = true`
  also names nodes for Godot's importer (convex -> `-convcol`, box -> a `<id>_box-colonly` box child).
- **Animations:** one glTF animation per model animation, part nodes keyed (STEP, or LINEAR with
  `interpolation: linear`; rotations are exact, not resampled). Looping ones are named `<name>-loop` in the
  glTF (Godot's importer loops them and drops the suffix, so in Godot they're just `<name>`).
- **Manifest** `assets.<name>.mesh`: `glb`, `ramp`, `voxel_size`, `shading`, `bounds` (min/max metres, model
  space), `triangles`, `vertices`, `root`, `parts` (per id: `node` path like `body/torso/head`, `parent` (`""` for the root),
  `pivot`, `aabb`, `voxels`, `triangles`, `meta`, `collision`, `hidden`), `animations` (`gltf_name`, `fps`,
  `loop`, `frames`, `interpolation`, `duration`), `animation_order`, `variants` (`ramp`, Godot materials),
  `godot_scene`, `godot_materials`. Mesh-only models (`directions: 0`) have `mesh_only: true` and no sheet.
- **Godot:** `var ship = load(mesh.godot_scene).instantiate()`; `ship.get_node("AnimationPlayer").play("walk")`;
  `ship.get_node("body/torso/head/helmet").get_meta("extras")["hitzone"]`; detach a part with
  `part.reparent(world)` (keeps its global transform). Swap a variant: on every MeshInstance3D, replace each
  surface override material that is `godot_materials[i]` with the variant's `godot_materials[i]`.
- **Review:** `pagan preview <model> --orbit` (every heading from -30 to 90 degrees elevation),
  `--closeup <part>`, `--engine` (the built .tscn rendered by Godot; needs a display).

## Timeline preview - `scenes/<name>.timeline.yaml`

Several sprites (or 3D models' frames) composed in time, to judge how they play together (does the flash
line up with the hit, is the glint readable over the letters). A preview only: `pagan build` and the
manifest never read it. `pagan lint` checks it with the project (E016; all problems, with lines and fixes).

```yaml
size: [640, 240]              # canvas, in output pixels (supersampled sprites are shown as built)
fps: 30                       # timeline frames per second (frames/f0000.png at t = 0, 1/30, ...)
duration: 6                   # seconds
background: "#101018"         # optional; default transparent (previews then show --bg)
layers:                       # drawn in list order (later on top), alpha-composited
  - {sprite: bg_smoke, anim: smoke, at: [0, 0], alpha: 0.6}
  - {sprite: letters, anim: a, at: [75, 200], start: 0.25, fade_in: 0.45}
  - {sprite: arrow, anim: fly, from: [-400, -60], to: [583, 131], start: 1.87, duration: 0.12, then: shudder}
  - {sprite: fx, anim: sparks, at: [583, 131], start: 1.99, variant: blue}
```

Layer fields (no others): `sprite` (asset name; sprites and 3D models, not tilesets), `anim` (an animation,
or a frame name shown still), `at: [x, y]` (where the sprite's pivot goes), `start` (seconds, default 0),
`duration`, `alpha` (0-1, default 1), `fade_in` / `fade_out` (seconds), `from` / `to` (instead of `at`:
a straight move over `duration`, rounded to whole pixels; the layer then stays at `to`), `then` (the
animation that follows when a one-shot `anim` (`loop: false`) ends; without it the last frame holds),
`variant`. `duration` without `from`/`to` = how long the layer is shown (default: to the end); `fade_out`
ends where the layer ends (with a move: the end of the timeline). Animations play from the layer's `start`
with their own fps, loop and `durations`. No easing, rotation or scale: use derived frames for those.
Times are exact (0.1 is 1/10 s), so output is identical on every machine.

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
- Big canvases (numpy): `Canvas.from_array(keys_array)` or `Canvas.from_array(index_array, "rstuv")` (negative =
  transparent), `to_array()`, `mask()` (bool, opaque); `distance_field(mask)` (signed, exact Euclidean between
  pixel centres: + inside, - outside), `bevel(mask, width, light)` -> 0..1 brightness of a bevelled shape,
  `dither(keys, t, x, y, matrix=4)` (ordered Bayer dithering between ramp steps; scalars or arrays from `np.mgrid`).
  Draw in numpy, hand PAGAN the keys.
- Lettering with a project font sprite (`font:`): `canvas.text(api.load("sprites/font.sprite.yaml"), "THWACK!", x,
  y, scale=1, key=None)` (a `Canvas` method; top-left at (x, y), the build's advances, `key` = one key for every pixel).
- Lettering from a real typeface: `text_mask("A", font="fonts/Serif.ttf", cap_height=104, variation={"wght": 900},
  anchor="baseline_centre", rotate=3, scale=(0.9, 1), supersample=4)` -> `.coverage` (0..1 floats), `.mask()`
  (bool), `.origin` (the anchor in the mask), `.advance` (kerning included), `.bbox`. Rotate/scale turn about the
  anchor, so a tilting letter's frames stay aligned; `variation` is axis values by tag or a named instance ("Bold").
  Then `distance_field(text.mask())` / `bevel(...)` for bevels, outlines and extrusions.
- Shading: `light_2d(project)` (the project's light for flat art), `sphere_light(dx, dy, light)`,
  `ramp_pick(keys, t)`, `hash01(x, y, seed)`, `periodic_noise(x, y, period, seed)` (seamless), `smoothstep`.
- Terrain: `corner_tiles(prefix, size, paint, seed, amp)` -> the 16 Match-Corners tiles
  `<prefix>_<NW><NE><SW><SE>`; `paint(field, x, y, corners)` returns a key, `field(x, y) >= 0.5` = upper
  terrain. `compose(tileset_asset, "a b\nb a")` -> a PIL image of a layout.
- 3D: `shape_cells(shape, spec)` = the voxels a part fills; `hull_reach(x, length, beam, bow, stern, keel)`;
  `sail_cells(at, width, height, bulge, brace, rig, yard)` -> cells with their cloth position (`u`, `row`),
  e.g. to place patches or gun ports exactly on a sail or hull side.
- 2D headings: `directional_frames(draw, size, directions=8)` -> one Canvas per heading, named like model
  headings (e, ne, n, ...; h00-h31); `draw(canvas, angle)` paints the shape turned to `angle` degrees,
  usually via `rotate_points(points, angle, about)` (a shape drawn facing east; counter-clockwise on screen).
- Files (numpy numbers are fine in sizes and fields): `sprite_yaml(name, size, frames, animations, **fields)`, `tileset_yaml(...)`, `write(path, text)`
  (writes only on change), `load(path)` -> parsed asset, `open_project(path)`, `palette(name, project)`.

## `pagan.toml`

```toml
palette_mode = "strict"            # strict: palette files only | open: inline palettes allowed
default_palette = "dusk"
output_dir = "../game/assets/generated"
preview_dir = "previews"
export = ["png", "godot"]          # PNG sheets + manifest always; + "godot" (.tres, needs project.godot above output_dir), "normals", "mesh" (.glb)
variant_sheets = true              # false: no sheet/.tres per variant, only its swap table in the manifest
supersample = 1                    # N > 1: sources drawn at N x, build box-filters down (smooth, non-pixel-art)
style_version = 1

[camera]                           # used by every model
elevation = 42                     # degrees above the horizon (90 = straight down)
scale = 1                          # pixels per voxel
projection = "orthographic"        # or "dimetric": exact pixel 2:1 tiles (elevation/scale unused; below)
tile = [64, 32]                    # dimetric: pixels per grid cell (width = 2 x height)
cell = 16                          # dimetric: voxels per grid cell side (must divide half the tile height)
z_step = 0                         # dimetric: pixels per voxel of height (0 = tile height / cell)

[light]
direction = [-0.5, 0.45, 0.75]     # towards the light: x right, y up-screen, z up
ambient = 0.2                      # unlit brightness; lower = darker shadows
shadows = true
shadow_strength = 0.65             # how dark cast shadows are
wrap = 0.3                         # light wrapping around curves (softer shading)
baked = true                       # false: flat colors for engine lighting (+ export "normals")

[mesh]                             # with export "mesh" (3D games)
voxel_size = 0.0625                # metres per voxel (0.0625 = 16 per metre); chosen per game, see the skill
shading = "ramp"                   # ramp (palette-locked engine lighting) | baked | flat
collision_suffixes = false         # Godot -convcol / -colonly node names for collision parts

[build]
trim = false                       # sprites without their own `trim:` are trimmed (fonts / nine_slice sprites never are)

[godot]                            # with export "godot"
mipmaps = false                    # true: PAGAN sets mipmaps/generate in each PNG's .import (kept across builds)
filter = "inherit"                 # SpriteFrames texture filter: inherit (node/project) | nearest | linear

[lint]
max_ramps_per_sprite = 3            # W003 for sprites/tilesets
max_ramps_per_model = 6             # W003 for 3D models (flat one-key materials don't count)           # W003
max_frame_change = 0.4             # W007
max_ramp_steps = 0                 # W008: most shades per ramp/material (0 = no limit)
disable = []                       # warning ids only
require_outline = false            # E011
require_opaque = false             # E015: no translucent "#rrggbbaa" colours in sprites/tilesets
```

## Commands (all accept `--json`; non-zero exit on errors)

Slow steps (a model render that isn't cached yet, Godot) print `pagan: ...` progress lines on stderr
(`--quiet` or `PAGAN_QUIET=1` turns them off; stdout and `--json` are unaffected). Models render in
several processes (`PAGAN_JOBS=N`, default: the CPU count up to 8; `1` = one process); output is identical.
Renders are cached in `<project>/.pagan-cache/`; `PAGAN_CACHE_DIR=/path` shares one cache between several
checkouts of the same art (e.g. agents' git worktrees), so a fresh checkout doesn't re-render every model.

| Command | Purpose |
|---|---|
| `pagan init [dir] [--open] [--godot DIR] [--perspective top-down\|top-down-3/4\|side\|iso] [--style pixel\|flat]` | create a project; perspective sets `[camera] elevation` (90/42/15/30) and BRIEF.md; `--style flat` = STYLE.md for flat / vector-like arcade art |
| `pagan new palette <name>` | starter palette |
| `pagan new sprite <name> [--size 16x16] [--frames N] [--directions 1\|4\|8] [--mirror] [--outline] [--palette P] [--description D]` | blank sprite; `--directions 4` scaffolds down/up/left frames + a mirrored right animation |
| `pagan new tiles <name> [--size] [--frames N]` | blank tileset |
| `pagan new model <name> [--size 64x64] [--directions 8]` | starter model (`--directions 0`: a mesh-only model for 3D games) |
| `pagan lint [paths] [--warnings-as-errors]` | errors + style warnings |
| `pagan preview <model> --orbit \| --closeup PART \| --engine [--all-previews]` | 3D review: orbit.png (8 headings x elevations -30, 0, 30, 60, 90: undersides too), closeup_<PART>.png (one part filling the view, in place and alone), engine.png (the built .tscn through Godot: needs a display); only these unless `--all-previews` |
| `pagan preview <asset...> [--scale N] [--grid] [--bg checker\|none\|#rrggbb] [--scene FILE] [--frame NAME] [--variants options\|all]` | sheet.png (labelled), montage.png (frames/headings packed on the background, e.g. `--bg "#1d3b53"` sea), frames/ and GIFs, all at the printed scale, plus native/ (1x frames and sheet, as `pagan render`); variants.png + variants_1x.png (base and every variant side by side: the first frame with pixels, or `--frame`) when the asset has variants (with `variant_axes`: each axis option on its own, named `<axis>.<option>`; `--variants all` = every combination); `--scene` (tilesets): scene.png from a layout file (rows of tile names, `.` = empty) and scene_variants.png; supersampled assets also get an "as built" row and built_1x.png (what the game gets) |
| `pagan preview scenes/<name>.timeline.yaml [--at 0.5,2.0] [--scale N] [--grid] [--bg ...]` | timeline: `previews/<name>.timeline/` frames/f0000.png..., timeline.gif, and with `--at` at.png (a contact sheet of those times) |
| `pagan gallery` | every asset in one image |
| `pagan render <asset...>` | native-size PNGs |
| `pagan palette show [palettes]` | swatches |
| `pagan palette adjust <pal> [--lightness d] [--contrast k] [--saturation k] [--hue deg] [--warmth d] [--ramp r] [--keys ...] [--out new] [--dry-run]` | change the look globally |
| `pagan import <png> [--palette P \| --open] [--scale N] [--name] [--out]` | PNG -> sprite (snaps colors, report) |
| `pagan bake <model> [--name]` | model -> editable sprite (default name `<model>_baked`) |
| `pagan fit <model> [--margin N] [--even] [--write]` | smallest size + pivot that fit every heading and pose |
| `pagan status` | catalogue + what needs attention |
| `pagan config show` / `get <key>` / `set <key> <value>` / `unset <key>` | project settings: value, default, meaning; validated edits; unset = back to default |
| `pagan mark <asset...> [--status approved] [--current] [--outdated]` | record reviews |
| `pagan style bump "note"` | new style version; flags older assets (W006) |
| `pagan build [--verify-godot] [--godot-timeout S]` | final assets + manifest (+ Godot .tres); each Godot step may take S seconds (default 600) |
| `pagan skill install [dir]` | install this skill into a repo's `.claude/skills/` |
| `pagan mcp [--project DIR] [--allow-godot]` | MCP server over stdio (needs `pagan[mcp]`) |

**MCP tools** (same JSON as the commands above): `status`, `read_docs`, `write_doc`, `log_feedback`,
`config_show`/`config_set`/`config_unset`, `palette_list`, `palette_show` (image), `palette_write`,
`palette_adjust` (dry run by default; image), `scaffold`, `read_asset`, `write_asset` (writes + lints +
preview image), `lint`, `preview` (image: sheet, montage, variants, built, orbit, closeup with `part`, or engine), `gallery` (image), `fit`,
`mark`, `style_bump`, `import_png` (path or base64), `build` (`verify_godot` needs `--allow-godot`),
`manifest`. Resources: `pagan://workflow`, `pagan://reference`, `pagan://brief`, `pagan://style`,
`pagan://manifest`, `pagan://palette/{name}`, `pagan://asset/{name}`. Prompts: `setup_new_game`,
`make_asset`, `change_the_look`, `review_asset`. Errors come back as results (`ok: false` + `findings`).

## Lint rules

Errors: E000 command/usage, E001 YAML/field, E002 unknown pixel key, E003 grid size, E004 missing
animation frame, E005 palette problem, E006 variant problem, E007 outline or shadow clipped at the edge, E008 pivot,
E009 inline palette in strict mode, E010 derived frame, E011 outline required, E012 duplicate asset name,
E013 model problem, E014 rig / mesh problem (unknown rig id or parent, parent cycle, a hidden carving part when
meshes are exported), E015 translucent colour with `require_opaque`, E016 timeline problem (`scenes/*.timeline.yaml`). E003 also: a size that isn't a multiple of `supersample`.

Warnings: W001 orphan pixel, W002 unused frame, W003 too many ramps, W004 empty frame, W005 visible area
jumps between frames, W006 made under an older style version, W007 too much change between frames,
W008 too many shades from one ramp (sprites) / in one material (models), when `max_ramp_steps` is set.
Mesh export only (`export` has "mesh"): W009 a model overrides `[mesh] voxel_size`, W010 a part's voxels are
separate pieces, W011 a rig pivot outside its part; W012 `directions: 0` (mesh only) without "mesh" in `export`.
W013 (any model): a part id has no voxels left, because later parts cover (or carve) all of it.
W014 (any asset): the built sheet is over 16384 px on a side (many engines, Godot too, won't load it): set
`sheet_columns` (sprites) or `columns` (tilesets), `trim: true` (mostly transparent sprite frames), or split the asset.
Turn warnings off project-wide with `[lint] disable`, or per asset/frame/animation with the file's `lint:`.
W001 isn't checked on 3D models (a rendered orphan can't be fixed pixel by pixel).

## Build output (any engine)

`manifest.json` in `output_dir` describes everything: per asset its kind, sheet, frame rects, animations
(frames, fps, loop, and `durations` when set; `loop_from` animations are split as below), pivot, `godot_offset`, headings (models), tiles (`name -> [column, row]` for
tilesets; an animated tile is listed by its animation name at its first frame's cell, and the tileset
gets `animations`), variants (each with its sheet/.tres unless `variant_sheets = false`, plus `swap`:
base colour -> variant colour as "#rrggbb" (or "#rrggbbaa" when translucent) for every colour it changes, and `swap_exact`: false when two
keys share a base colour but not a variant colour, so a shader swap would be wrong; with
`variant_sheets = false` that's error E006), `variant_axes` (per axis, per option: `swap`, `swap_exact`;
apply one option's swap per axis together - with `variant_sheets = false` the combinations aren't listed
in `variants`, the game composes them), and `normal_sheet` (when "normals" is exported: RGB = normal * 0.5 + 0.5, x right,
y up, z towards the viewer), `animation_order` (animation names in file order: JSON keys are unordered), `points` (sprites: point -> frame ->
[x, y] in output pixels from the frame's top-left; minus `pivot` = offset from the node's origin),
`nine_slice` (frame -> [left, top, right, bottom]), `mesh` (models with "mesh" exported: see Meshes),
`textures` (tilesets with `export_textures`: per texture `png`, `size`, `metres`, `tiles`, `variants`,
`godot_material`) and, for fonts, `font` (`glyph_order`, `glyphs`: char ->
`rect` [x, y, w, h] in the sheet + `advance` (+ `offset` [x, y] when set), `cell`, `ascent`, `descent`, `line_height`) and `font_file`
(an AngelCode BMFont `fonts/<name>.fnt` with its own copy of the sheet, `fonts/<name>.png`). Supersampled assets: `size`, frame rects and `pivot` are in output pixels
(`pivot` may be fractional), plus `supersample` and `source_size`; their sheets blend colours at edges, so
a shader swap by exact colour misses the blended pixels: use variant sheets for them. `base_variant` (when
set) names the base, also listed under `variants` with its sheet and an empty swap. Pivots aren't stored
in engine resources: apply them in the game.

Trimmed sprites (`trim: true`, or `[build] trim = true`): each frame is cropped to its non-transparent pixels and
the crops are packed in source order, `sheet_columns` per row (default up to 8), each row as tall as its tallest
crop, 1 px transparent gap between cells, never rotated. The entry gets `trim: true`, and each `frames` value is an
object instead of [x, y, w, h]: `size` (the full frame, unchanged), `trim_rect` ([x, y, w, h] of the crop in the
sheet) and `offset` ([x, y] of the crop's top-left inside the full frame). Draw a frame by placing its `trim_rect`
at `offset` within a `size` box: `pivot`, `godot_offset` and `points` stay in full-frame coordinates. A fully
transparent frame keeps its top-left pixel (a 1x1 transparent crop at offset [0, 0]), so every frame has a
region. The crop depends only on which source pixels are transparent, so variant sheets share the layout;
supersampled sprites are cropped in output pixels (rounded outwards). Fonts and `nine_slice` sprites can't be
trimmed (E001 with an explicit `trim: true`; the project default skips them); tilesets and models are never trimmed.

## Godot

`pagan build` writes `sprites/<name>.png` + `<name>.tres` (SpriteFrames, one animation per PAGAN
animation; sprites without animations get one per frame), `tiles/<name>.png` + `<name>.tres` (TileSet:
one atlas source, every tile created, animated tiles as atlas tile animations; add terrains/physics in
the editor), plus `manifest.json`. Fonts: Godot imports `fonts/<name>.fnt` as a FontFile
(`load("res://.../fonts/font_small.fnt")`; use it as a Label's `theme_override_fonts/font`). 9-slice: set a
NinePatchRect's `patch_margin_left/top/right/bottom` from the manifest's `nine_slice`.
Apply the pivot in code: `sprite.centered = true; sprite.offset = Vector2(godot_offset[0], godot_offset[1])`.
Trimmed sprites need nothing extra: each AtlasTexture's `margin` puts the crop back in place, so frames keep
their full size (and the same pivot/`godot_offset`) in SpriteFrames.
Project settings for crisp pixels: Default Texture Filter = Nearest, stretch mode `viewport`, scale mode
`integer`, snap 2D transforms to pixel.
Smooth, freely rotated or scaled sprites: `[godot] filter = "linear"` (the SpriteFrames' CanvasTexture
carries it) and `mipmaps = true` (PAGAN keeps `mipmaps/generate` in each PNG's `.import`; Godot keeps its
other import settings). TileSets have no filter of their own: set `texture_filter` on the TileMapLayer.
