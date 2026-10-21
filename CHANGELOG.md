# Changelog

All notable changes to PAGAN are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Game projects should pin a release tag
(e.g. `pip install "git+ssh://git@github.com/lukasgolino/pagan.git@v0.8.0"`).

A new version (and tag) is cut for **any** change to:
- the notation (palette, sprite, tileset or model files),
- `pagan.toml` settings,
- `manifest.json` or exporter output (PNG layout, Godot resources),
- rendering results (the pixels a given source produces),
- the CLI's `--json` output and the MCP tools (names, arguments, result keys).

While on 0.x, a minor bump (0.1 -> 0.2) may change any of these; entries marked **Breaking** say what to
check before upgrading. Patch bumps (0.1.0 -> 0.1.1) never change existing behaviour. Every release changes
the manifest's `generator` (`"pagan X.Y.Z"`), so expect every manifest to change once per upgrade.

## [Unreleased]

## [0.12.0] - 2026-10-21

### Added

- Derived frames can scale and rotate: `{ from: idle, scale: [1.2, 0.8], rotate: 6, about: pivot }` (nearest
  neighbour; `about` is `pivot` (default), `center` or `[x, y]`). Order: flip, scale/rotate, shift; E010 if opaque
  pixels would leave the canvas (#4).

## [0.11.0] - 2026-10-21

### Added

- Wide and stacked outlines on sprites: `outline: { width: 3, color: "0" }` (a round ring up to 8 px) and a list of
  rings, innermost first (ink + light rim). `outline: auto` is unchanged (#3).
- `shadow: { offset: [dx, dy], color }` on sprites: a drop shadow of the outlined shape under every frame (#3).

### Changed

- E007 accounts for the total outline width and for shadows that would leave the canvas (#3).

## [0.10.0] - 2026-10-21

### Added

- Translucent palette colours: `"#rrggbbaa"` (00 = clear, ff = opaque) for drop shadows, glows, light rays and
  smoke; sprite and tileset pixels get that alpha in every PNG, and variant `swap` tables carry it (#2).
- `[lint] require_opaque = true` (E015) forbids translucent colours in a project's sprites and tilesets (#2).

### Changed

- The default `outline_color` is the darkest *opaque* colour; `pagan import` snaps to opaque colours only;
  palette swatches show translucent colours over a checker; `pagan palette adjust` keeps each colour's alpha.
  Palettes without translucent colours behave exactly as before (#2).
- `"#rrggbbff"` is read as `"#rrggbb"`. 3D model materials must be opaque (E013) (#2).

## [0.9.1] - 2026-10-21

### Added

- The skill asks agents to report what got in their way (crashes, misleading messages, workarounds, missing
  features) as GitHub issues: a minimal-repro draft, a duplicate check, and filing only with the user's OK.
  `.github/ISSUE_TEMPLATE/agent-report.md` and the `agent-report` label. Run `pagan skill install` to update a
  project's copy of the skill.

## [0.9.0] - 2026-10-20

From LOOSE!'s first weeks with meshes (3D_Bugsandfeaturerequests.md D5-D10). 2D output is unchanged.

### Added

- `shell: true` (or a wall thickness, `shell: 2`) on `box`, `cylinder` and `ellipsoid`: only the outer wall, so a
  helmet can cover a head and a big tower stays under the 2M-voxel cap (D7).
- W013 (any model): a part id has no voxels left because later parts cover or carve all of it; E014 (rig) and pose
  errors about that id say why (D7).

### Changed

- Ramp shader: lit pixels are palette colours in the Compatibility renderer too (it works in sRGB space, so the
  ramp was converted twice and came out pale). Forward+ and Compatibility are exact; Mobile can be a few levels off in
  dark colours (10-bit light buffer). CI renders the demo meshes in all three renderers (D5).
- `extends` + `remove`: a removed part's inherited `rig` entry goes with it, and inherited rig children of a removed part
  hang from its parent; rig entries the extending file writes are still checked (D6).
- `pagan preview --closeup`: the "in place" rows are framed on the part like its own row (surroundings cropped at the
  edges), and views are 128 px (D8).
- Manifest: a mesh's root part has `parent: ""` instead of `null`, so every field has one type (D9).

### Fixed

- `--verify-godot` failed on every mesh-only model ("texture <null>"): mesh-only models have no sheet to check (D10).

## [0.8.0] - 2026-10-20

From 3D games (3D_Bugsandfeaturerequests.md D1-D4, MESH_PLAN.md). Opt-in: without "mesh" in `export` and
`export_textures`, every sprite, tileset and Godot resource is byte-identical to 0.7.0 (the manifest's
`generator` changes, as with every release).

### Added

- `export` "mesh": every 3D model also builds `models/<name>.glb` (binary glTF 2.0: greedy-meshed voxels without
  T-junctions, flat normals, one node per part, animations) and `models/<name>.ramp.png` (palette ramp texture, one row
  per material ramp; plus `<name>.<variant>.ramp.png` per variant). The manifest's `mesh` per model: glb, ramp,
  voxel_size, shading, bounds and part AABBs (metres, glTF axes: front +Z, left +X, up +Y), triangles, parts (node path,
  parent, pivot, aabb, voxels, meta, collision, hidden), animations (gltf_name, fps, loop, frames, interpolation,
  duration), variants (ramp).
- `[mesh]` settings: `voxel_size` (metres per voxel, default 0.0625), `shading` (`ramp` | `baked` | `flat`),
  `collision_suffixes` (Godot `-convcol` / `-colonly` names).
- Models: `directions: 0` (mesh only, no sprites; `size` optional), `voxel_size` (per-model override), `rig:` (per part id:
  `pivot`, `parent`, `meta`, `collision: box | convex | none`), animation `interpolation: step | linear` (meshes).
  Rig children follow their parents' pose moves and hiding, in sprites too.
- With "godot" and "mesh": `models/pagan_ramp.tres` (palette-locked ramp shader), `<name>[.<variant>][.two_sided].material.tres`
  and `<name>.tscn` (the glb with PAGAN's materials applied); `--verify-godot` loads every glb and tscn and checks part
  nodes, metadata, visibility, animations and materials against the manifest.
- Lint: E014 (rig / mesh problems), and with mesh export W009 (model overrides voxel_size), W010 (part in several
  pieces), W011 (rig pivot outside its part); W012 (mesh-only model without mesh export).
- `pagan preview <model> --orbit` (orbit.png: 8 headings x elevations -30, 0, 30, 60, 90), `--closeup PART`
  (closeup_<PART>.png: one part filling the view, in place and alone), `--engine` (engine.png: the built .tscn
  rendered by Godot; needs a display), `--all-previews`; JSON keys `orbit`, `closeup`, `engine`. MCP
  `preview(which="orbit" | "closeup" | "engine", part=...)`. Mesh-only models preview as orbit sheets and
  appear in the gallery.
- Tilesets: `export_textures` (`true`, or `tiles`, `groups` of tiles laid out as one texture, `triplanar`):
  `textures/<tileset>.<name>.png` per tile/group (+ per variant), and with "godot" a StandardMaterial3D `.tres`
  each (nearest, repeat, optional world triplanar at the meshes' texel density); manifest `textures`; the
  preview tiles each group 2x2.
- `pagan init`'s pagan.toml has a commented `[mesh]` section; the skill has a "3D games" section.
- Demo: the ship and sailor export as meshes (the sailor has a `rig`: head hit zone, detachable hat), the
  meadow exports textures, and `examples/godot/scenes/mesh_test.tscn` shows them under a moving sun (CI runs it).

### Changed

- Building big boxes is several times faster (bulk voxel insertion); renders are unchanged.

## [0.7.0] - 2026-10-19

From Age of Boom reports R20-R29 (ORCHESTRATOR_PLAN.md). Existing sources build to the same pixels; the
manifest gains keys (below), so every manifest changes once.

### Added

- `nine_slice: [left, top, right, bottom]` (or `{ frame: [...] }`) on sprites; the manifest carries
  `nine_slice: { frame: [l, t, r, b] }` (R20).
- `font:` on sprites (`glyphs`, `cell`, `baseline`, `line_height`, `advance: auto | N`, `spacing`, `space`):
  the frames, or cells cut from them, are glyphs. The build writes `font` metrics (per glyph `rect` and
  `advance`, `ascent`, `descent`, `line_height`) to the manifest and an AngelCode BMFont `fonts/<name>.fnt` with its own
  page image `fonts/<name>.png` (`font_file`), which Godot imports as a FontFile; `--verify-godot` loads it (R21).
- `animation_order` in the manifest: animation names in file order (R22).
- Progress lines on stderr for slow steps (uncached model renders, Godot import and check); `--quiet` or
  `PAGAN_QUIET=1` turns them off. `pagan build --godot-timeout SECONDS`. `PAGAN_CACHE_DIR` shares the model
  render cache between checkouts (git worktrees); cache files are written atomically (R23).
- Tileset animations take `new_row: true`: the animation starts at column 0 of a fresh atlas row (R24).
- `pagan preview --frame NAME` picks the frame variants.png compares; `--scene` also writes
  scene_variants.png when the tileset has variants (MCP `preview(frame=...)`) (R25).
- Palette-wide variants: `variants:` (ramp_swap / key_swap within the palette, optional `tags`) and
  `base_variant` in a palette file; every asset using the palette (with one of the tags) gets them, its own
  variant of the same name wins, and `variants: { name: false }` turns one off (R26).
- `pagan.api.directional_frames(draw, size, directions)` and `api.rotate_points(points, degrees, about)`:
  2D sprites in every heading, named like model headings (R27).
- `pagan preview` also writes 1x frames and sheets to `previews/<asset>/native/` (as `pagan render`), listed
  as `native` in `--json` (R28).
- `lint: { max_ramps: N }`: W003's limit for one asset (R29).

### Changed

- Models render in several processes (`PAGAN_JOBS`, default: CPU count up to 8); output is byte-identical.
  YAML is parsed with libyaml when PyYAML has it. A cold (uncached) build of Age of Boom's art (70 assets,
  15 models) went from ~78 s to ~30 s on 6 cores.
- `--verify-godot`'s default limit per Godot step is 600 s (was 300 s); its summary also counts fonts.
- variants.png / variants_1x.png show the first frame with pixels (was: the first frame, which for corner
  tilesets is empty).

### Fixed

- `--verify-godot` with `variant_sheets = false` failed on every asset with a `base_variant` (its entry has
  no sheet and an empty swap by design).

## [0.6.1] - 2026-10-18

From Age of Boom reports R18-R19 (ORCHESTRATOR_PLAN.md).

### Added

- `pagan fit --even` (and MCP `fit(even=...)`) pads to even sizes so `godot_offset` is whole pixels.
- `pagan fit --json` reports `grown_for_pivot`.

### Fixed

- `pagan build --verify-godot` crashed with `variant_sheets = false` (swap-only variants have no `sheet`);
  they are now checked for a swap table instead.
- An error in the Godot check script hung the run until the 300 s timeout; it now fails within seconds
  with `PAGAN_VERIFY_FAIL`. A timeout says whether the import or the check hung.
- `pagan fit` could propose a pivot outside the frame (E008) for models that don't reach their origin
  (overlays whose origin is the parent's pivot); the frame now grows to hold the pivot.

## [0.6.0] - 2026-10-17

### Added

- `pagan mcp [--project DIR] [--allow-godot]`: PAGAN as an MCP server over stdio, for any MCP client
  (optional extra: `pip install "pagan[mcp]"`). 23 tools that mirror the CLI (same JSON), with preview,
  swatch and gallery images returned inline; `write_asset` writes a source and lints it in one call.
  Resources for the workflow, notation, BRIEF/STYLE, manifest, palettes and assets; prompts for setting up
  a game, making an asset, changing the look and reviewing an asset. The server only touches its project,
  output and preview dirs, and runs Godot only with `--allow-godot`.

### Changed

- The MCP tools, their arguments and result keys are part of the public contract (a change to them is a
  version bump, like the CLI's `--json` output).

## [0.5.0] - 2026-10-17

From the Space IO use report S1-S10 (SPACIO_USEREPORT.MD): flat / vector-like arcade art, freely
rotated sprites. Every new setting defaults to the old behaviour.

### Added

- `pagan init --perspective top-down|top-down-3/4|side|iso` sets `[camera] elevation` (90/42/15/30) and
  writes the choice into BRIEF.md (S1).
- `pagan init --style flat` writes a STYLE.md for flat / vector-like arcade art (fill + rim, no outline,
  no painted light, engine glow) (S7). The skill asks for the rendering style at setup and has a recipe
  per style.
- `pagan.api` (S2): `Canvas.polygon(points, key)` (even-odd; a callable key gets the pixel's distance to
  the nearest edge, for rims and bevels), `Canvas.triangle`, `Canvas.line(..., width=)` for thick strokes,
  `api.polygon_distance` (signed distance to a polygon's outline).
- Supersampling (S3, S10): `supersample = N` in pagan.toml or per asset. Sources are drawn at N x the
  output size; `pagan build` box-filters sheets (alpha-weighted, integer maths, byte-stable) into smooth
  PNGs with partial alpha. The manifest gives output-pixel `size`/frames/`pivot` (may be fractional) plus
  `supersample` and `source_size`. Lint E003 if a size isn't a multiple of N. `pagan preview` adds an
  "as built" row and `built_1x.png`.
- Godot import settings (S4): `[godot] mipmaps = true` sets `mipmaps/generate` in each built PNG's
  `.import` (only that line; Godot keeps the rest and reimports); `[godot] filter = "nearest"|"linear"`
  puts a texture filter on the SpriteFrames (a CanvasTexture around the sheet). Verified in Godot 4.7.2.
- `base_variant: <name>` on any asset (S6): the manifest lists the base sheet under that name in
  `variants` too (empty swap), so a game sees one uniform set of team colours; previews label it.

### Changed

- `pagan config show` marks `[camera]`/`[light]` as unused when the project has no 3D models
  (`--json`: `used`).
- The pixel-art STYLE.md template says its rules are pixel-art defaults.

### Fixed

- **Breaking:** `pagan.api` ellipses and rings (`API_VERSION` 2) no longer fill pixels whose centre lies
  exactly on the edge (half-integer radii, e.g. 15.5 around 16, used to leave 1px nubs at the extremes).
  Generators using such radii produce slightly different grids; nothing changes for other radii.

## [0.4.0] - 2026-10-16

From orchestrator reports R15-R17 (ORCHESTRATOR_PLAN.md).

### Added

- Variant swap tables (R17b): each variant in `manifest.json` has `swap` (base "#rrggbb" -> variant
  "#rrggbb" for every colour it changes) and `swap_exact`. Sheets and `.tres` files are unchanged.
- New setting `variant_sheets` (default true): false skips the per-variant sheets and `.tres` files for
  games that recolour in a shader; a variant that can't be expressed as a colour swap is then an error (E006).
- `pagan preview` writes `variants.png` (base + every variant, labelled) and `variants_1x.png` when an
  asset has variants (R17a).
- Shared bases (R15): a model can `extends: <model>` (inherit, `remove: [ids]` base parts, add parts,
  override materials/animations/variants by name); `template: true` marks a base that is linted but never
  built. Editing a base re-renders everything that extends it.
- Combinable recolours (R15): `variant_axes: { axis: { option: recolour | {} } }` on any asset. Axes must
  recolour different keys; every combination becomes a variant named `<option>+<option>` (built as sheets
  when `variant_sheets = true`), and the manifest gets per-axis swap tables (`variant_axes`).
- Demo: the ship has a `blue` team variant.

### Changed

- Palette keys can be any single Unicode letter or digit (R16): after 0-9 a-z A-Z, use Latin-1
  (à-ÿ, À-Þ, ß) and Greek letters. `pagan import --open` can extract up to 154 colours. Swatches draw
  the keys with a system font that has the glyphs (DejaVu Sans, Arial...) when there is one.
- Source files are NFC-normalized when read (only matters for accents typed as combining marks).

## [0.3.0] - 2026-10-16

From orchestrator reports R7-R14 (ORCHESTRATOR_PLAN.md, Age of Boom G2-G3).

### Added

- Per-asset lint suppression (R7): `lint: { disable: [W005, W007], for: { <frame|tile|animation>: [W004] } }`
  in any sprite, tileset or model (a model's pose animation name covers all its headings). `pagan build`
  and `pagan lint` count warnings per rule (`W007×40, W005×11`); `build --json` has `warnings_by_rule`.
- Animated tiles (R8): tileset `animations: { water: { frames: [...], fps } }`. Frames are laid out side by
  side in the atlas; the Godot TileSet gets an animated atlas tile (verified in Godot 4.7.2); the manifest
  lists the tile by its animation name and adds `animations` to the tileset entry. Tilesets without
  animations are laid out and exported exactly as before.
- Pose rotation (R9): `roll`/`pitch` in a pose tilt the whole model about its origin (rendered exactly);
  a part takes `roll`/`pitch`/`yaw` and `about: [x, y, z]` (hinge) as well as `offset`.
- Hidden carve parts (R10): `hidden: true` + `carve: true` cut holes only in poses that show them.
- `pagan.api` (R11, R12): a stable Python API for generator scripts: `Canvas` drawing (ellipse, ring,
  fade, scatter, orphan handling matching W001), project-light shading, seamless noise, Match-Corners
  tile generation, tile-layout `compose`, the exact `hull`/`sail` geometry (`hull_reach`, `sail_cells`,
  `shape_cells`) and canonical sprite/tileset YAML writers.
- `pagan preview <tileset> --scene layout.txt` draws a layout of different tiles (R12).
- `pagan fit <model>` (R13): the smallest size and pivot that fit every heading and pose, and which
  frames the current size clips.
- Demo: animated `water` tileset.

### Changed

- **Breaking:** hidden parts are overlays. A `hidden: true` part never changes the normal frames, and when
  a pose shows it, it's drawn over everything. Before, a hidden part that overlapped visible voxels cut
  them out of the normal frames, and visible parts placed later cut holes in it. Affected models render
  differently where that happened (Age of Boom: the sloop's deck had 3 voxels missing in every heading;
  the torn-sail copies were missing voxels in the damaged frames).
- **Breaking:** an id used by both hidden and visible parts is an error (E013).
- Model render caches are invalidated (`RENDERER_VERSION` 4): the first build re-renders every model.
- E007 on models counts the clipped frames and points at `pagan fit`.

### Removed

- W001 (orphan pixel) is no longer checked on 3D models.

### Fixed

- Model findings said `tiles.<name>` and pointed at the `parts:` line; they now say `frames.<name>` with
  no source line (R14).

## [0.2.0] - 2026-10-15

From orchestrator reports R1-R6 (ORCHESTRATOR_PLAN.md), the Age of Boom PAGAN log, and review round 3.

### Added

- `pagan --version` names the exact build: `pagan 0.1.0 (v0.1.0, ce24ab4)` for a pinned git install,
  `(editable checkout <git describe>)` for a dev checkout; `pagan status` shows it and warns on editable
  installs. The manifest's `generator` is unchanged (output stays byte-reproducible per release).
- `pagan init --godot <dir>` builds straight into `<dir>/assets/generated` with Godot resources; init writes
  `.gdignore` when the art folder is inside a Godot project.
- Mirrored animations: `walk_right: { from: walk_left, flip: horizontal }` generates the flipped frames.
- Palette files accept `description`.
- New `lint.max_ramps_per_model` (default 6) for W003 on models.
- Models: `directions: 32` (frames `h00`..`h31`); sails take `rig: fore-aft` (luff at the mast, reaching
  aft); new `triangle` shape (jibs, lateens, fins, gables) with an exact normal.
- New `pagan config unset`.
- `pagan new sprite --directions 4|8` scaffolds the facings (right-hand ones as mirrored animations).
- `pagan preview` writes `montage.png` (frames/headings packed on the background, no labels) and reports
  its scale.

### Changed

- **Breaking:** models with a non-zero `heading` get frames and animations named by where they face
  (`heading: 45`, 4 directions: `ne, nw, sw, se` instead of `e, n, w, s`). Models with `heading: 0` and
  1-direction models (`main`) are unchanged.
- **Breaking:** `pagan bake` without `--name` writes `<model>_baked`, not `<model>` (no name clash).
- **Breaking:** a model's `light:`/`camera:` override with unknown keys is an error (E013); it used to be
  ignored. The override accepts every `[light]` setting.
- W003 for 3D models uses `lint.max_ramps_per_model` instead of `max_ramps_per_sprite` (3), so some model
  warnings go away.
- `pagan config set` accepts comma-separated lists (`png,godot`); errors show the TOML syntax. It replaces
  multi-line arrays, fills the commented `# default_palette` template line, reports dates/inline tables as
  errors, and hints when `light.baked`/"normals" don't match.
- `config set default_palette` lists only the assets that follow the default.
- `--verify-godot` runs its check script from a temp folder (nothing written into the game), fails on Godot
  import errors, and reports how many SpriteFrames/TileSets it checked (and says so when there are none).
- `pagan new model` works in open mode without a palette (inline starter palette); its strict-mode error
  says how to fix it.
- Static models preview as one heading grid.
- `--json` also works before the subcommand.
- Skill: install PAGAN the way the project pins it, never `pip install -e` unless developing PAGAN.
- Docs: `sail` `at`, odd hull/cylinder widths; "png" output is always on; variant swaps remap keys
  wherever they're used.

### Fixed

- E007 was reported again for derived frames; it is reported once per problem, with authored columns for
  mirrored sprites.
- `pagan mark` could write a broken file; empty values are handled and flow-style files are refused.

## [0.1.0] - 2026-10-15

### Added

- Notation: palettes with ramps; 2D sprites (mirror, outline, derived frames, animations, variants);
  tilesets; 3D voxel models (primitives and layer grids, materials as ramps, 1/4/8/16 headings,
  pose animations with hidden/shown parts).
- Project settings in `pagan.toml`, viewable and editable with `pagan config` (camera, light, palette,
  lint rules); 3D models re-render when they change.
- Commands: init, new, lint, preview, gallery, render, palette show/adjust, import, bake, status, mark,
  style bump, config, build (`--verify-godot`), skill install.
- Build output: PNG sheets, `manifest.json`, optional normal maps; Godot 4 SpriteFrames and TileSet `.tres`.
- Lint: errors E000-E013, warnings W001-W008.
- Claude skill (`pagan skill install`) with the workflow and a full notation reference.

[Unreleased]: https://github.com/lukasgolino/pagan/compare/v0.12.0...HEAD
[0.12.0]: https://github.com/lukasgolino/pagan/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/lukasgolino/pagan/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/lukasgolino/pagan/compare/v0.9.1...v0.10.0
[0.9.1]: https://github.com/lukasgolino/pagan/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/lukasgolino/pagan/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/lukasgolino/pagan/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/lukasgolino/pagan/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/lukasgolino/pagan/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/lukasgolino/pagan/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/lukasgolino/pagan/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/lukasgolino/pagan/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/lukasgolino/pagan/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/lukasgolino/pagan/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lukasgolino/pagan/releases/tag/v0.1.0
