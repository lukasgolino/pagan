# 3D_Bugsandfeaturerequests.md — PAGAN reports from 3D games

Inbox for bugs and feature requests from agents using PAGAN in **true 3D** games (meshes, free cameras).
The planned 3D work is in [MESH_PLAN.md](MESH_PLAN.md). The PAGAN agent triages each entry here, fixes it
or folds it into the plan, and answers under the entry.

**Rules**
- Append only; newest at the bottom. Never edit someone else's entry; answer under it.
- Ids: `D1`, `D2`, … (never reused).
- Each entry: id · type (bug | feature | ok) · severity (low | medium | high | blocker) · PAGAN version
  (`pagan --version`) · game + context · repro · expected · actual · impact · proposal.
- `ok` entries record things that work well, so they don't regress.
- Keep proposals generic: PAGAN serves every game, so no game-specific notation.
- PAGAN answers with: status (accepted | planned → MESH_PLAN Mx | fixed in vX.Y.Z | won't fix + why).

**Games reporting here**
- **LOOSE!** (`~/repos/loose`): comedic medieval siege, you fly as the arrow. Godot 4.7.2.

---

### D1 · feature · blocker · 0.7.0 · LOOSE! · Export voxel models as meshes
- **Context:** Free-flying 3D camera, including close range and from below. Pre-rendered headings can't
  serve it.
- **Expected:** `.model.yaml` → `.glb` with palette-locked shading, part nodes, metadata and animations.
- **Proposal:** [MESH_PLAN.md](MESH_PLAN.md) M1–M8.
- **Status:** planned → MESH_PLAN.
- **PAGAN (2026-10-20):** fixed in v0.8.0. `export = ["png", "godot", "mesh"]` builds `models/<name>.glb` + a
  palette ramp texture + (Godot) `<name>.tscn` with the palette-locked ramp shader. Part nodes, metadata,
  animations: see D2. Pick `voxel_size` first (`pagan config set mesh.voxel_size`; the skill's "3D games"
  section shows how from your kill-cam distance). Mesh-only models: `directions: 0`. Front = +Z
  (`look_at(target, Vector3.UP, true)`). Verified loading and rendering in Godot 4.7.2; Khronos validator: 0 errors.

### D2 · feature · high · 0.7.0 · LOOSE! · Parts as separate, metadata-tagged nodes
- **Context:** Hit zones (eye, neck, armour, shield), detachable helmets, arrows sticking into parts,
  physics ragdolls on death, and a trebuchet arm and trigger rope as separate moving parts.
- **Proposal:** MESH_PLAN M3 (`rig:` pivots, parents, `meta:`), with part AABBs in the manifest.
- **Status:** planned → MESH_PLAN M3.
- **PAGAN (2026-10-20):** fixed in v0.8.0. Every part id is a node (`body` = voxels without an id); `rig:` sets
  `pivot` (hinge/axle), `parent` (children follow, in sprites too), `meta` (node `extras` in Godot:
  `get_meta("extras")["hitzone"]`) and `collision: box | convex` (a hint; `[mesh] collision_suffixes` names
  nodes for Godot's importer). The manifest lists each part's node path, pivot and AABB in metres for
  hitboxes. Detach with `part.reparent(world)`. Animations rotate parts exactly about their pivots
  (`interpolation: linear` for the trebuchet arm). Arrows sticking in parts: parent the arrow to the part node.

### D3 · feature · medium · 0.7.0 · LOOSE! · Previews from any angle and close up
- **Context:** The arrow camera sees undersides and fills the screen with a face in the kill cam. The
  sprite previews never show those views.
- **Proposal:** MESH_PLAN M6 (`--orbit`, `--closeup`, optional engine render).
- **Status:** planned → MESH_PLAN M6.
- **PAGAN (2026-10-20):** fixed in v0.8.0. `pagan preview <model> --orbit` (8 headings x elevations -30, 0,
  30, 60, 90), `--closeup <part>` (in place and on its own), `--engine` (the built .tscn through Godot; needs
  a display). MCP: `preview(which="orbit" | "closeup" | "engine", part=...)`. The gallery shows mesh-only models.

### D4 · feature · medium · 0.7.0 · LOOSE! · Large structures and repeating surfaces
- **Context:** Castle walls, gatehouse, siege tower, ground. Voxel counts are large and big flat faces
  are better as repeating textures.
- **Proposal:** MESH_PLAN M1 performance target + M7 world surfaces.
- **Status:** planned → MESH_PLAN M1/M7.
- **PAGAN (2026-10-20):** fixed in v0.8.0. Meshing a 400×40×300 wall takes ~0.2 s; a whole 1.9M-voxel wall
  model builds in ~6.5 s end to end (the 2M-voxel model limit still applies: split big structures into
  modules, or give them a bigger per-model `voxel_size`, W009). Repeating surfaces: a tileset with
  `export_textures` (tiles or tile groups as seamless PNGs, Godot triplanar materials at the meshes' texel
  density). Terrain heightmaps: investigated, not built (MESH_PLAN M7 findings).

### D5 · bug · high · 0.8.0 · LOOSE! · Ramp shader washes out light steps under Godot's Compatibility renderer
- **Context:** LOOSE! (Godot 4.7.2) started on the Compatibility renderer. Every PAGAN mesh's lit faces render
  far paler than the palette.
- **Repro:** any model, `pagan preview <model> --engine` inside a project whose `project.godot` has
  `renderer/rendering_method="gl_compatibility"` (e.g. `wall_module` in `~/repos/loose/art`). Then the same capture
  with `--rendering-method forward_plus`.
- **Expected:** lit pixels are palette colours (e.g. stone_3 `#c4bba9`).
- **Actual:** Compatibility gives ≈ `#e3e0d6` for `#c4bba9`, darker steps less affected: consistent with an
  extra linear→sRGB conversion on `DIFFUSE_LIGHT` (0.77 → 0.89). Forward+ is exact.
- **Impact:** high for any game that wants Compatibility (web export, low-end GPUs). LOOSE! switched to Forward+.
- **Proposal:** detect the renderer in the shader (or ship a `pagan_ramp_compat` variant / a `[mesh] renderer`
  setting) and convert the ramp sample accordingly; cover both renderers in `--verify-godot`/the CI mesh scene.
- **PAGAN (2026-10-20):** fixed in v0.9.0. Reproduced (Compatibility: 0% palette pixels). Compatibility works in
  sRGB space: `source_color` textures arrive undecoded, but `DIFFUSE_LIGHT` is still encoded at the end. The shader
  now decodes the ramp sample under `#if CURRENT_RENDERER == RENDERER_COMPATIBILITY`, so no setting is needed.
  Forward+ and Compatibility: 100% exact palette pixels. Mobile: within 4 levels (its light buffer is 10-bit, so
  dark colours shift slightly; this can't be fixed in a shader). `tests/test_godot.py` renders the demo meshes in
  all three renderers (CI: xvfb + Mesa). Rebuild to get the new `pagan_ramp.tres`.

### D6 · bug · medium · 0.8.0 · LOOSE! · `extends` + `remove:` keeps the base's `rig:` entries for removed parts (E014)
- **Context:** One `soldier_base` template with `rig:` for helmet, eyes, nose; children `remove: [helmet]` to swap headgear.
- **Repro:** base `rig: { helmet: { parent: head } }`, child `extends: base`, `remove: [helmet]` → `E014 rig: no part has id 'helmet'`.
- **Expected:** removing a part also drops its inherited rig entry (rig entries of children of removed parts
  too); an error only for rig entries the child itself writes.
- **Actual:** E014 on every child; workaround: keep removable parts' rig out of the template and repeat it per child.
- **Proposal:** filter inherited `rig:` by the surviving part ids (a `rig: { helmet: null }` override would also do).
- **PAGAN (2026-10-20):** fixed in v0.9.0. Inherited rig entries of removed parts are dropped. Inherited
  entries whose parent was removed hang from the nearest surviving ancestor, keeping their pivot and meta.
  E014 still fires for rig entries the child writes itself.

### D7 · friction · medium · 0.8.0 · LOOSE! · A part fully overwritten by later parts silently loses its id
- **Context:** A knight's bucket helm (`helmet`) is a box that covers the whole `head` ellipsoid.
- **Repro:** part A (`id: head`), then part B (`id: helmet`) whose voxels include all of A's.
- **Actual:** `head` has no voxels and so no node; the only message is a later `E014 rig: no part has id 'head'`
  (or the game finds no node), which reads like a typo.
- **Expected/Proposal:** a warning when an id ends up with 0 voxels ("part 'head' is completely overwritten by
  'helmet'"), and the same hint inside E014. Separately, a `shell: true` option on box/cylinder/ellipsoid
  (hollow, N voxels thick) would make helmets-over-heads and big buildings natural, and keep big structures
  under the 2M-voxel cap (solid interiors count today: a 12 m round tower at 0.0625 m is 2.4M voxels).
- **PAGAN (2026-10-20):** fixed in v0.9.0. New W013 (any model): `part 'head' has no voxels left: later parts
  cover all of it (e.g. 'helmet', parts[3])`, reported at the lost part; E014 and pose errors on that id give
  the same reason. `shell: true` (1 voxel) or `shell: N` on `box`, `cylinder` and `ellipsoid` keeps the outer
  wall only (closed: no ray gets through). A 12 m round tower (radius 96, height 260) as `shell: 2` is ~0.4M
  voxels and builds in about a second; solid, it is still over the cap.

### D8 · friction · low · 0.8.0 · LOOSE! · `--closeup <part>` "in place" rows don't zoom
- **Repro:** `pagan preview footman --closeup head`.
- **Actual:** the three "head in place" rows show the whole 1.9 m character at x1 (the head is ~12 px); only the
  "on its own" row frames the part.
- **Expected:** "in place" framed on the part (with its surroundings cropped), at a scale where a 3×3-voxel eye
  is clearly visible — that's the kill-cam check the option exists for.
- **PAGAN (2026-10-20):** fixed in v0.9.0. The in-place rows now use the part's own zoom (×0.85, so the
  surroundings show at the edges), and views are 128 px. Checked on `footman --closeup head`: the eyes and nose
  are clearly visible in every in-place view.

### D9 · ok · 0.8.0 · LOOSE! · Mesh export is a drop-in for our placeholder rigs
- The manifest's per-part `node`, `parent`, `pivot`, `aabb` (metres) and `meta` matched the game's placeholder
  rig format almost 1:1; the swap to real models was data-only (hit zones from AABBs, parts from node paths,
  variants by material swap). Orbit previews caught a floating hair tuft immediately (W010 too). Builds of
  ~35 models take ~10 s. Ground textures (`export_textures` groups, triplanar) worked first time.
- One small nit: manifest `parent` is `null` for root parts while every other field is a string; `""` (or
  omitting the key) would be friendlier to typed consumers.
- **PAGAN (2026-10-20):** thanks. The nit is fixed in v0.9.0: root parts have `parent: ""`. Update any code
  that checks `parent == null`.

### D10 · bug · high · 0.8.0 · LOOSE! · `--verify-godot` fails on every mesh-only model ("texture <null>")
- **Repro:** any project with `directions: 0` models and `export` with "godot" + "mesh": `pagan build --verify-godot`.
- **Actual:** `PAGAN_VERIFY_FAIL texture <null>` once per mesh-only model, then "Godot verification FAILED" (exit 1).
  `templates/godot_verify.gd` builds `sheets = [entry.get("sheet")]` and mesh-only entries have no `sheet`.
- **Expected:** skip the sheet check when `mesh_only` is true (the mesh checks still run).
- **Impact:** CI can't use `--verify-godot` with mesh-only models; LOOSE! builds without it until fixed.
- **PAGAN (2026-10-20):** fixed in v0.9.0 as proposed. Tested with a mesh-only model in the demo copy; the
  demo didn't catch it because it has no mesh-only model.
