# Build

Build output (any engine): manifest.json, sheets, pivots.

## Build output (any engine)

`manifest.json` in `output_dir` describes everything: per asset its kind, sheet, frame rects, animations
(frames, fps, loop, and `durations` when set; `loop_from` animations are split as below), pivot, `godot_offset`, headings (models), tiles (`name -> [column, row]` for
tilesets; an animated tile is listed by its animation name at its first frame's cell, and the tileset
gets `animations`), variants (each with its sheet/.tres unless `variant_sheets = false`, plus `swap`:
base colour -> variant colour as "#rrggbb" (or "#rrggbbaa" when translucent) for every colour it changes, and `swap_exact`: false when two
keys share a base colour but not a variant colour, so a shader swap would be wrong; with
`variant_sheets = false` that's error E006), `variant_axes` (per axis, per option: `swap`, `swap_exact`;
apply one option's swap per axis together - with `variant_sheets = false` the combinations aren't listed
in `variants`, the game composes them), and `normal_sheet` (when "normals" is exported: RGB = normal * 0.5 + 0.5, x right,
y up, z towards the viewer), `animation_order` (animation names in file order: JSON keys are unordered), `points` (sprites: point -> frame ->
[x, y] in output pixels from the frame's top-left; minus `pivot` = offset from the node's origin),
`nine_slice` (frame -> [left, top, right, bottom]), `mesh` (models with "mesh" exported: see Meshes),
`textures` (tilesets with `export_textures`: per texture `png`, `size`, `metres`, `tiles`, `variants`,
`godot_material`) and, for fonts, `font` (`glyph_order`, `glyphs`: char ->
`rect` [x, y, w, h] in the sheet + `advance` (+ `offset` [x, y] when set), `cell`, `ascent`, `descent`, `line_height`) and `font_file`
(an AngelCode BMFont `fonts/<name>.fnt` with its own copy of the sheet, `fonts/<name>.png`). Supersampled assets: `size`, frame rects and `pivot` are in output pixels
(`pivot` may be fractional), plus `supersample` and `source_size`; their sheets blend colours at edges, so
a shader swap by exact colour misses the blended pixels: use variant sheets for them. `base_variant` (when
set) names the base, also listed under `variants` with its sheet and an empty swap. Pivots aren't stored
in engine resources: apply them in the game.

Trimmed sprites (`trim: true`, or `[build] trim = true`): each frame is cropped to its non-transparent pixels and
the crops are packed in source order, `sheet_columns` per row (default up to 8), each row as tall as its tallest
crop, 1 px transparent gap between cells, never rotated. The entry gets `trim: true`, and each `frames` value is an
object instead of [x, y, w, h]: `size` (the full frame, unchanged), `trim_rect` ([x, y, w, h] of the crop in the
sheet) and `offset` ([x, y] of the crop's top-left inside the full frame). Draw a frame by placing its `trim_rect`
at `offset` within a `size` box: `pivot`, `godot_offset` and `points` stay in full-frame coordinates. A fully
transparent frame keeps its top-left pixel (a 1x1 transparent crop at offset [0, 0]), so every frame has a
region. The crop depends only on which source pixels are transparent, so variant sheets share the layout;
supersampled sprites are cropped in output pixels (rounded outwards). Fonts and `nine_slice` sprites can't be
trimmed (E001 with an explicit `trim: true`; the project default skips them); tilesets and models are never trimmed.
