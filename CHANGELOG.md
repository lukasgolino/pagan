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
