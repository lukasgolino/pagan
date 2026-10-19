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
