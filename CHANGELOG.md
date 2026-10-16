# Changelog

PAGAN follows [semantic versioning](https://semver.org/). Game projects should pin a release tag
(e.g. `pip install "git+ssh://git@github.com/lukasgolino/PAGAN.git@v0.2.0"`).

A new version (and tag) is cut for **any** change to:
- the notation (palette, sprite, tileset or model files),
- `pagan.toml` settings,
- `manifest.json` or exporter output (PNG layout, Godot resources),
- rendering results (the pixels a given source produces).

While on 0.x, a minor bump (0.1 -> 0.2) may change any of these; read the notes before upgrading.
Patch bumps (0.1.0 -> 0.1.1) never change them.

## 0.2.0 — 2026-10-15

From orchestrator reports R1-R6 (ORCHESTRATOR_PLAN.md), the Age of Boom PAGAN log, and review round 3.

### Upgrading from 0.1.0

- `manifest.json` `generator` becomes `"pagan 0.2.0"`: expect every manifest to change once on the
  first build. Sheets and `.tres` files are unchanged for the same sources.
- Models with a non-zero `heading` get frames and animations named by where they face (`heading: 45`,
  4 directions: `ne, nw, sw, se` instead of `e, n, w, s`). Models with `heading: 0` and 1-direction
  models (`main`) are unchanged.
- W003 for 3D models now uses `lint.max_ramps_per_model` (default 6) instead of
  `max_ramps_per_sprite` (3), so some model warnings go away.
- `pagan bake` without `--name` now writes `<model>_baked`, not `<model>`.
- A model's `light:`/`camera:` override with unknown keys is now an error (E013); it used to be ignored.

### Changes

- `pagan --version` names the exact build: `pagan 0.1.0 (v0.1.0, ce24ab4)` for a pinned git install,
  `(editable checkout <git describe>)` for a dev checkout; `pagan status` shows it and warns on editable
  installs. The manifest's `generator` is unchanged (output stays byte-reproducible per release).
- `pagan init --godot <dir>` builds straight into `<dir>/assets/generated` with Godot resources; init writes
  `.gdignore` when the art folder is inside a Godot project.
- `pagan config set` accepts comma-separated lists (`png,godot`); errors show the TOML syntax.
- `--verify-godot` runs its check script from a temp folder (nothing written into the game), fails on Godot
  import errors, and reports how many SpriteFrames/TileSets it checked (and says so when there are none).
- Mirrored animations: `walk_right: { from: walk_left, flip: horizontal }` generates the flipped frames.
- E007 is reported once per problem (not again for derived frames), with authored columns for mirrored sprites.
- Skill: install PAGAN the way the project pins it, never `pip install -e` unless developing PAGAN.
- From the game's G1 log: palette files accept `description`; `pagan new model` works in open mode without
  a palette (inline starter palette) and its strict-mode error says how to fix it; `config set
  default_palette` lists only the assets that follow the default; static models preview as one heading
  grid; new `lint.max_ramps_per_model` (default 6) for W003 on models.
- Models: `directions: 32` (frames `h00`..`h31`); sails take `rig: fore-aft` (luff at the mast, reaching
  aft); new `triangle` shape (jibs, lateens, fins, gables) with an exact normal. Docs: `sail` `at`,
  odd hull/cylinder widths.
- Review round 3: a model's `camera:`/`light:` override accepts every `[light]` setting and rejects unknown
  keys; `config set` replaces multi-line arrays, fills the commented `# default_palette` template line, and
  reports dates/inline tables as errors; new `pagan config unset`; `pagan mark` never writes a broken file
  (empty values handled, flow-style files refused); `--json` also works before the subcommand.
- `bake` defaults to `<model>_baked` (no name clash); `config set` hints when `light.baked`/"normals" don't
  match; model headings are named by where they face (`heading: 45` -> ne, nw, sw, se).
- `pagan new sprite --directions 4|8` scaffolds the facings (right-hand ones as mirrored animations).
- `pagan preview` writes `montage.png` (frames/headings packed on the background, no labels) and reports
  its scale. Docs: "png" output is always on; variant swaps remap keys wherever they're used.

## 0.1.0 — 2026-10-15

First release.

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
