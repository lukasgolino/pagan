# Models

3D model notation: materials, parts, primitives, poses, rig, cameras.

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
  - ring: { center: [10, 0, 20], outer: 4, inner: 3, height: 1, axis: x, material: steel }   # open annulus: gauges, wheels, ducts
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
`ring` is a flat open annulus (no caps, unlike a `cylinder` shell): the cells whose centres lie `inner` to `outer`
voxels from the axis through `center`, `height` layers (default 1) from the center's layer towards +axis.
`center` (or `centre`) is a whole voxel along the axis; across it a half voxel (`[0.5, 0.5, 2]` with axis z)
gives even widths. `outer: 4, inner: 3` is a ring 9 voxels across, about 1 thick (its diagonals touch only at
corners; `outer - inner` of 1.5 or more closes them); `inner: 0` fills the disc.
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
