# Godot

Godot: SpriteFrames, TileSets, fonts, meshes, filters.

## Godot

`pagan build` writes `sprites/<name>.png` + `<name>.tres` (SpriteFrames, one animation per PAGAN
animation; sprites without animations get one per frame), `tiles/<name>.png` + `<name>.tres` (TileSet:
one atlas source, every tile created, animated tiles as atlas tile animations; add terrains/physics in
the editor), plus `manifest.json`. Fonts: Godot imports `fonts/<name>.fnt` as a FontFile
(`load("res://.../fonts/font_small.fnt")`; use it as a Label's `theme_override_fonts/font`). 9-slice: set a
NinePatchRect's `patch_margin_left/top/right/bottom` from the manifest's `nine_slice`.
Apply the pivot in code: `sprite.centered = true; sprite.offset = Vector2(godot_offset[0], godot_offset[1])`.
Trimmed sprites need nothing extra: each AtlasTexture's `margin` puts the crop back in place, so frames keep
their full size (and the same pivot/`godot_offset`) in SpriteFrames.
Project settings for crisp pixels: Default Texture Filter = Nearest, stretch mode `viewport`, scale mode
`integer`, snap 2D transforms to pixel.
Smooth, freely rotated or scaled sprites: `[godot] filter = "linear"` (the SpriteFrames' CanvasTexture
carries it) and `mipmaps = true` (PAGAN keeps `mipmaps/generate` in each PNG's `.import`; Godot keeps its
other import settings). TileSets have no filter of their own: set `texture_filter` on the TileMapLayer.
