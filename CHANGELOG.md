# Changelog

PAGAN follows [semantic versioning](https://semver.org/). Game projects should pin a release tag
(e.g. `pip install "git+https://github.com/lukasgolino/pagan.git@v0.1.0"`).

A new version (and tag) is cut for **any** change to:
- the notation (palette, sprite, tileset or model files),
- `pagan.toml` settings,
- `manifest.json` or exporter output (PNG layout, Godot resources),
- rendering results (the pixels a given source produces).

While on 0.x, a minor bump (0.1 -> 0.2) may change any of these; read the notes before upgrading.
Patch bumps (0.1.0 -> 0.1.1) never change them.

## Unreleased

From orchestrator reports R1-R6 (ORCHESTRATOR_PLAN.md) and the Age of Boom PAGAN log.

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
