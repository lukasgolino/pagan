# Tilesets

Tileset notation: tiles, layouts, animated tiles, textures.

## Tileset - `tiles/<name>.tiles.yaml`

```yaml
name: meadow
tile_size: [16, 16]
columns: 8                    # atlas width in tiles; tiles fill rows in file order (append-safe)
tile_shape: isometric         # optional: square (default) | isometric | half_offset_square | hexagon (Godot's TileSet)
tile_layout: diamond_down     # optional: stacked (default) | stacked_offset | stairs_right | stairs_down | diamond_right | diamond_down
tile_offset_axis: horizontal  # optional: horizontal (default) | vertical
tiles:
  grass: |
    ...16 rows of 16...
  grass_b: { from: grass, flip: horizontal }
  water_0: |
    ...
animations:                   # animated tiles: the animation's name is the tile's name
  water: { frames: [water_0, water_1, water_2, water_3], fps: 4 }   # always loops
  lava: { frames: [lava_0, lava_1], fps: 4, durations: [3, 1] }    # per-frame holds, as for sprites
  surf: { frames: [surf_0, surf_1, surf_2, surf_3], new_row: true }  # from column 0 of a fresh row
variants: ...                 # as for sprites
lint: { for: { shore_0000: [W004] } }   # e.g. a corner set's fully transparent tile
```

No mirror/outline. Tiles should be seamless (preview shows a 3x3 tiling; `pagan preview <tileset>
--scene layout.txt` draws a layout of different tiles to check the seams between them). With `tile_shape`
the Godot TileSet gets that shape/layout and the manifest a `tile_shape` entry; isometric tiles are previewed
(3x3 tiling, `--scene`) where Godot's TileMapLayer puts them (layout row r, column c = map cell (c, r)), so a 2:1
diamond (rows 2, 6, ..., 6, 2 for 8x4) shows its seams; `api.compose(tileset, layout, square=True)` = a plain grid. An animated
tile's frames sit side by side in the atlas (a new row if they don't fit, or always with `new_row: true`, so
the layout doesn't depend on how many tiles come before; longer than `columns`: a block `columns` wide); each
tile is a frame of at most one animation (the manifest's `tiles` gives every cell either way). Godot gets an animated atlas tile.

**Textures for 3D surfaces** (ground, wall faces, roofs: an atlas region can't repeat, a texture can):

```yaml
export_textures: true          # every tile (not animation frames) -> textures/<tileset>.<tile>.png
export_textures:
  tiles: [grass]               # all (default without groups) | none | [names]
  groups:                      # several tiles laid out as ONE texture (breaks up repetition)
    meadow_mix: |
      grass grass_flowers
      grass_flowers grass
  triplanar: true              # Godot material projects it in world space (no UVs needed)
```

Each texture is a seamless PNG (plus one per variant when `variant_sheets` is on); with "godot" a
`StandardMaterial3D` `.tres` per texture (nearest filter, repeat, alpha scissor if it has holes, triplanar at
the texture's size in metres = pixels x `[mesh] voxel_size`, the same texel density as the meshes). The
preview tiles every group 2x2 to check its seams.
