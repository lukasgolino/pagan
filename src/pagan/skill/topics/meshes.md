# Meshes

3D games: voxel_size, meshes (.glb), rigs, triangle budgets, mesh notation.

## 3b. 3D games (meshes)

When the game's camera moves freely in 3D, pre-rendered headings can't serve it: models must also build as
meshes (`.glb`). Same model files, no edits; sprites still build too unless a model is mesh-only
(`directions: 0`). Notation and output: below.

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

**Making a 3D asset** - the loop in `pagan docs making`, plus:
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
  shader in Godot (offscreen; needs Xvfb). Look at all of them before reporting.
- **Triangle budget:** read `triangles` in `pagan build --json`'s manifest. Big flat areas of one material
  merge into few triangles; noise (scattered single voxels, dithering, many materials) multiplies them.
  Rough budgets unless the owner says otherwise: a prop < 2k, a character < 5k, a big structure < 30k.
- **Models or textures?** Things with a silhouette and depth (characters, siege engines, towers) are models.
  Big repeating flat surfaces (ground, wall faces, roofs) are tile textures: a tileset with
  `export_textures` (seamless tiles, `groups` to break up repetition, `triplanar: true` in Godot).
- **Report back:** `godot_scene` (or `glb`), the part node paths and `meta` keys, animation names, the
  triangle count, `voxel_size`, and the preview paths.


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
  `--closeup <part>`, `--engine` (the built .tscn rendered by Godot; renders offscreen, needs Xvfb).
