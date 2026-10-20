# MESH_PLAN.md — real 3D output: voxel models → meshes

Brief for the agent adding mesh export to PAGAN. Read [CLAUDE.md](CLAUDE.md) (conventions, versioning,
decisions log) and [PLAN.md](PLAN.md) §Milestone 4b first. Bug reports and feature requests from 3D games
arrive in [3D_Bugsandfeaturerequests.md](3D_Bugsandfeaturerequests.md). Triage them there and answer each one.

## Status (2026-10-20): M1–M8 done, released as v0.8.0 (owner accepted all defaults)

**Frozen (2026-10-20, owner):** no further 3D work in PAGAN. The voxel look isn't the smooth 3D look games like
LOOSE! want; that belongs in a separate tool. v0.9.0 shipped the LOOSE! bug fixes (D5-D10); mesh export stays
supported as is.

| | Milestone | Notes / deviations from the brief (all in CLAUDE.md's decisions log) |
|---|---|---|
| ☑ | M1 Static mesh export | glTF = (y, z, x) · voxel_size: the brief's (−y, z, x) mirrors the model. T-junctions are removed (edge vertices inserted), proven watertight by test. The ramp PNG sits next to the .glb (uri), not inside: Godot extracts embedded images into the project. Khronos validator: 0 errors/warnings. |
| ☑ | M2 Shading | Ramp texture **per model** (+ per variant), not per palette: variants are per asset. Width = lcm of ramp lengths, so u = brightness reproduces the sprite renderer's step exactly. The shader locks every sun; omni/spot add unlocked. |
| ☑ | M3 Parts, hierarchy, metadata | Hidden parts use KHR_node_visibility (scale 0 makes Godot's importer error). Rig parents also apply to sprite poses. Godot `-col`/`-convcol`/`-colonly` work; `-colonly` on an empty node doesn't, so box colliders are a box-mesh child. |
| ☑ | M4 Animations | Visibility per pose via KHR_animation_pointer; looping animations are `<name>-loop` in the glTF (Godot loops them and strips the suffix). |
| ☑ | M5 Godot | Shader as a `Shader` .tres (a .gdshader gets a random `.uid` sidecar). Hand-written inherited `.tscn` per model is stable across re-imports. `mesh_test.tscn` in CI. |
| ☑ | M6 Previews | `--orbit`, `--closeup`, `--engine` (Godot with a display), gallery. |
| ☑ | M7 World surfaces | `export_textures` on tilesets. Terrain: findings below. |
| ☑ | M8 Skill, docs, release | Skill "3D games" section, reference "Meshes", README, CHANGELOG 0.8.0. |

**M7 terrain findings (investigated, not built):**
- A heightmap terrain is just columns of voxels: a `heightmap:` part (a grid of height characters 0-9a-z plus
  a legend of materials per height band) would reuse everything (greedy meshing merges flat terraces, the
  ramp shader shades slopes, `export_textures` could texture tops). Fine for courtyards, hills and moats up
  to ~128×128 voxels (8×8 m at 16 voxels/m).
- World-scale terrain doesn't fit the voxel model: 256 m at 16 voxels/m is 4096² columns. It needs a numpy
  path that skips the per-voxel dicts, chunked meshes (one node per 32×32 m chunk for culling) and probably
  LOD. Collision should be a Godot `HeightMapShape3D` from the same grid (cheap), not mesh collision.
- Terraced voxel steps match the style; smooth slopes would need heightfield triangles (still palette-locked
  with the ramp shader, but no longer voxels).
- Authoring: a text grid is readable up to ~64×64; bigger terrain wants a PNG heightmap (`pagan import`-style)
  or a generator script on `pagan.api`.
- Recommendation: build the small `heightmap:` part when a game asks for it; for big worlds let the engine's
  terrain (e.g. Terrain3D) use PAGAN-exported heightmap PNGs + `export_textures`. Question for the owner in QUESTIONS.md.

## Why

Today a `.model.yaml` becomes 2D sprites: 1–32 headings from **one** camera elevation. That works for
top-down and 3/4 games. A true 3D game, where the camera flies freely, goes below models, and gets close
enough to hit an eye, can't use pre-rendered headings. It needs the voxel model as a **mesh** the engine
lights and draws from any angle.

The first customer is **LOOSE!**: a comedic medieval siege game in Godot 4.7.2 where you fly as the
arrow. Its needs are the test cases: goofy soldiers with separable parts (helmets, eyes as hit zones),
props (oil cauldrons, kegs), large structures (castle walls, a trebuchet with a moving arm, a siege
tower), and a pixel look made by rendering low-res (~480×270) and upscaling with nearest filtering.

PAGAN stays general-purpose. Nothing below is specific to that game. Use generic names and examples.

## Principles

- **Same source, new output.** A model that builds sprites today also builds a mesh, with no edits.
  New notation is additive and optional.
- **2D must not break.** Mesh export is opt-in (`"mesh"` in `export`). With it off, every existing
  output stays byte-identical: sprites, tilesets, model sprite sheets, manifest, Godot `.tres`. The
  existing golden tests and the committed `examples/godot/` build are the proof, so don't regenerate them
  for this work. New manifest keys appear only on assets that export meshes. New lint rules fire only
  when mesh export is on. Run the full suite plus the CI godot job before every release.
- **Engine-agnostic core:** binary glTF 2.0 (`.glb`). Godot extras are a convenience on top, as with
  SpriteFrames.
- **Palette-locked.** Colours come from a palette texture, never from free RGB, so `palette adjust`,
  palette variants and `style bump` keep working on meshes.
- **Deterministic:** byte-identical `.glb` for the same inputs. Write it with our own small writer
  (struct + numpy, no new dependency). Fixed ordering, float32 values rounded the same way the renderer
  rounds them, no timestamps and no generator-version string that changes per build (put the PAGAN
  version in `asset.generator` only if it's stable per release).
- **Tests with every milestone; CI green; version bump + CHANGELOG + tag per release** (this changes
  notation, settings and manifest).

## Output contract

`export = ["png", "mesh"]` (with `"godot"` for the Godot extras). Per model:

| File | What |
|---|---|
| `models/<name>.glb` | Mesh, part node hierarchy, animations, per-part metadata in `extras` |
| `models/<palette>.ramp.png` | Palette ramp texture shared by all meshes on that palette (see Shading) |
| `manifest.json` → `assets.<name>.mesh` | glb path, voxel size, bounds (metres), triangle count, parts (node name, pivot, AABB, metadata), animations (name, fps, loop, frame count) |

Sprites for the same model still build if `directions` is set. A model can be mesh-only (`directions: 0`
or `mesh_only: true`; pick one and log it).

### Coordinates and scale

- PAGAN model space: x = front (bow, heading `e`), y = left, z = up, 1 unit = 1 voxel.
- glTF: right-handed, +Y up, metres, and the model's front faces **+Z** (glTF convention). Map
  `(x, y, z)` → `(−y, z, x) · voxel_size` or whatever is correct. Prove it with an asymmetric fixture
  (different colour on front, left and top) and a test that checks face normals by colour.
- Godot 4 imports glTF unchanged, so the front is +Z. Document `look_at(target, Vector3.UP, true)`
  (`use_model_front`) for game code, and confirm it in the Godot verify scene.
- `origin` in the model file becomes the mesh origin (e.g. between the feet).
- Scale: `[mesh] voxel_size` (metres per voxel) is a **per-project setting**, chosen per game. It is
  registered in `settings.py` so `pagan config get/set mesh.voxel_size` works, and changing it re-exports
  every mesh (it never touches sprites). `pagan init` leaves it at the default (`0.0625`, 16 voxels per
  metre) and the skill (M8) teaches the agent to pick it with the owner when a project starts. Models can
  override it with a per-model `voxel_size` for big structures. Lint warns (new W rule) when a model
  overrides it, because mixed voxel sizes break the uniform-texel look. Allow it anyway.

## Milestones

### M1 — Static mesh export
- `mesh.py`: VoxelModel → mesh. Cull faces between filled voxels. **Greedy meshing** per face direction
  and per surface key (material + fixed key; see Shading). Merged quads must not create T-junction
  cracks that show at low resolution. Either avoid T-junctions or prove the cracks don't appear (render
  test in Godot).
- Flat face normals (the voxel look). Exact normals from shapes that know them (sails) are ignored for
  now. Note this in the decisions log.
- Thin `two_sided` materials: emit back faces (or `doubleSided` on that glTF material).
- glb writer: one buffer, accessors for POSITION/NORMAL/TEXCOORD_0/indices (uint16 when it fits, else
  uint32), one material per palette, sampler NEAREST/NEAREST, wrap CLAMP.
- `pagan build` writes it, the manifest gains `mesh`, stale cleanup covers `.glb` files.
- Performance: a 400×40×300-voxel wall (castle scale) must mesh in a few seconds, vectorised with numpy.
  Add a benchmark test marked slow.
- Tests: geometry decode (triangle count for a cube is 12; two touching boxes of the same material share
  no internal faces; greedy merge count for known shapes), determinism (two builds, same bytes), schema
  validity (validate the JSON chunk against the glTF 2.0 rules we use: accessor bounds, min/max present,
  buffer view alignment).
- **Done when:** the demo ship builds to a `.glb` that loads in Godot 4.7.2 headless, and a Blender/online
  glTF validator shows no errors (run manually once and log the result).

### M2 — Shading (palette-locked lighting in a real engine)
The sprite renderer picks a ramp step per pixel from normal · light. In an engine the light moves, so the
step has to be picked at runtime. Options, all behind `[mesh] shading`:
- `ramp` (default): the ramp texture has **one row per surface key** and **one column per ramp step**
  (dark → light; fixed keys and one-key materials fill their row). UV.y selects the row. UV.x points at the
  **middle step**, so any glTF viewer shows sensible flat colours. PAGAN ships a Godot shader
  (`pagan_ramp.gdshader`) that picks the column from the engine's lighting (N·L, shadow attenuation,
  `[light] wrap`, `ambient`) and quantises it to the ramp. Every lit pixel is then a palette colour
  (before fog or post effects). Research how to do this in Godot 4.7.2's `light()` with directional +
  omni lights and shadows. If exact palette-locking with several lights proves impossible, lock only the
  directional "sun", let other lights add on top, and record the decision.
- `baked`: bake the step per face from the project `[light]`. No shader needed. Fine for props seen from
  a fixed side. Surfaces merge per baked step (more triangles).
- `flat`: middle step only (= `[light] baked = false` today).
- Palette variants: one ramp texture per variant (`<palette>.<variant>.ramp.png`). Swapping a variant in
  game is a texture swap, not a new mesh.
- Tests: ramp texture layout golden image; `baked` steps match the sprite renderer's choice for the same
  normal and light (use the same function, don't copy it).

### M3 — Parts, hierarchy, metadata
Games need to move, detach and hit parts: helmets fly off, arrows stick in shields, ragdolls, a
trebuchet arm rotating about its axle. New optional model section `rig:`, keyed by existing part `id`s:

```yaml
rig:
  torso:  { pivot: [0, 0, 7] }
  head:   { pivot: [0, 0, 14], parent: torso }
  helmet: { pivot: [0, 0, 19], parent: head, meta: { hitzone: armour, detachable: true } }
  eye_l:  { parent: head, meta: { hitzone: eye } }
```

- Every part id becomes its own glTF node and mesh. Voxels without an id go to a `body` root node.
  `pivot` (model space, voxels; default = the part's bottom centre, as poses use now) is the node origin.
  `parent` builds the hierarchy (cycles and unknown ids are errors with rule ids). Unparented parts sit
  under `body`.
- `meta:` holds free key → scalar or string values, written to node `extras` (Godot imports these as node
  metadata; verify) and the manifest.
- Manifest per part: node path, pivot (metres), AABB (metres), voxel count, metadata. Games build their
  hitboxes from this. Optional `collision: box|convex|none` per part emits a glTF collision hint. Check
  whether Godot's `-col`/`-colonly` node-name suffixes still work in 4.7.2 and prefer them if so (behind
  a setting, default off, since they change node names).
- Hidden parts (overlays) become nodes hidden by default (scale 0 or `KHR_node_visibility`, whichever
  Godot 4.7.2 imports; verify). Carving overlays have no mesh equivalent: lint error when exporting a
  mesh, with a hint to use a hidden part instead.
- Lint: parts whose voxels are disconnected (warn; usually a typo), rig entries for unknown ids, a pivot
  outside the part's bounds (warn).

### M4 — Animations
- Each `animations:` entry becomes a glTF animation on the part nodes: translation from `offset`
  (voxels → metres) and rotation from `roll`/`pitch`/`yaw` about `about` (exact node rotation, no voxel
  resampling; the sprite path keeps resampling). Use STEP interpolation by default (pixel-art timing).
  Add an optional `interpolation: linear` per animation for smooth motion (trebuchet arm swing).
- `show`/hidden parts per pose → visibility keys (same mechanism as M3).
- fps → key times. Loop flag: find what Godot 4.7.2's glTF importer reads (name suffix `-loop` / `_loop`
  or import settings) and do that. If it needs a name change, put the real name in `extras` and the
  manifest.
- Tests: decoded key times and values for the demo sailor's walk and swing; determinism.

### M5 — Godot convenience (`export` has `"godot"`)
- Write `pagan_ramp.gdshader` once into the output dir, and a `ShaderMaterial` `.tres` per palette and
  variant (format copied from what Godot 4.7.2's ResourceSaver writes, as for SpriteFrames).
- `<name>.tscn`: an inherited scene of the `.glb` with the ramp material applied to every mesh, so games
  `instantiate()` one file. Check whether inherited scenes from glb are stable to hand-write; if not, use
  `material_override` set by a tiny attached script, or document the one-line game-side call instead.
  Pick the simplest option that survives Godot re-imports.
- Do **not** hand-write `.glb.import` files. If the defaults are wrong (e.g. texture filtering), handle it
  in the material or shader (`filter_nearest`), not the import file.
- `--verify-godot` loads every `.glb` and `.tscn` headlessly and checks node names, metadata and
  animation names against the manifest.
- `examples/godot/scenes/mesh_test.tscn`: the demo ship and sailor turning on a turntable under a moving
  sun with shadows, rendered at 480×270 and upscaled ×3 with nearest filtering. Add it to the CI godot job.

### M6 — 3D previews and review loop
Agents judge art by looking at previews. Meshes need views the sprite camera never gives:
- `pagan preview <model> --orbit`: a contact sheet of headings × elevations (default −30°, 0°, 30°, 60°,
  90°), rendered by the existing voxel renderer, so it needs no engine. Include **from below**: a flying
  camera sees undersides.
- `--closeup <part id>`: frame one part filling the image (eye, helmet), to check close-range detail.
- Optional, if a Godot binary is available: `pagan preview --engine` renders the `.tscn` through Godot
  headless (`--write-movie` or a viewport capture) so the agent can see the real ramp shader output.
- Update gallery to show mesh assets.

### M7 — World surfaces
Big flat things (ground, wall faces, roofs) can be voxel models, but repeating textures are cheaper:
- Tilesets: `export_textures: true` (per tileset) writes each tile, or a named tile group, as its own
  seamless PNG, so engines can repeat it (an atlas subrect can't repeat). Godot: a `StandardMaterial3D`
  or ramp `ShaderMaterial` `.tres` per texture with nearest filter, repeat on and an optional triplanar
  flag.
- The tiling check from `preview` applies to these textures.
- Investigate, don't build yet: `layers`-based terrain heightmaps → mesh. Report findings to the owner.

### M8 — Skill, docs, release
- Skill: a "3D game" section covering choosing the project's `voxel_size` with the owner at setup
  (`pagan config set mesh.voxel_size`), from the closest camera distance (things hit
  at close range need real voxels, e.g. an eye ≥ 2×2), rigging parts for gameplay, hit-zone metadata,
  reviewing with `--orbit`/`--closeup`, triangle budgets, when to use textures and when models.
- README "Using the output in a game" gets a 3D section (Godot snippet: instantiate, play animation,
  read part metadata, detach a part).
- Release per milestone or in groups (owner approves tags). The game pins the tag.

## Order and gates

- **M1 + M2 + M5 (minimal)** unblock the game's first art pass (static props, structures).
- **M3 + M4** unblock characters and the trebuchet/siege tower (moving parts, hit zones).
- M6 before heavy art production, since review quality depends on it.
- M7 when the game needs terrain and walls.
- Settings added (`[mesh] voxel_size`, `shading`, etc.) go into `settings.py`'s registry with meanings
  and refresh rules, like every other setting.

## Open questions for the owner (propose defaults, don't block)

1. Mesh-only models: `directions: 0` (recommended) or a `mesh_only` flag. **Built: `directions: 0`** (the default).

Decided (owner, 2026-10-19): `voxel_size` is a per-project setting chosen per game; the skill covers how
to choose it. Shading defaults to the palette-locked ramp shader.
