# Config

Project settings: config show/set, camera, light, supersample; every pagan.toml key.

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
must match a new angle or light, `pagan style bump "..."` and redraw them (`pagan docs evolve`). Log the change in
BRIEF.md's feedback log. Use the defaults until someone asks for something else, and say which defaults
you used.


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
