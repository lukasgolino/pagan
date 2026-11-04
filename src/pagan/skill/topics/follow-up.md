# Follow up

Follow-up requests: directions, new animations, enemies, variants, families, translucency.

## Follow-up requests on existing assets

- **"Give it 8 directions / rotations"**: if it's a 2D sprite, rebuild it as a model (`models/`) so
  every heading is consistent (`directions: 8`), matching the approved sprite's colors and proportions,
  then remove/rename the sprite (asset names must be unique). Models already have them: change
  `directions`.
- **New animation** (sword swing, walk, hop): models -> add parts with `id:` and an `animations:` entry
  with one pose per frame (parts move by whole voxels; `roll`/`pitch` tilt the whole model, e.g. a ship
  listing as it sinks; a part can rotate about a hinge, e.g. a falling mast). Damage and extras are
  `hidden: true` parts (overlays: they never alter the normal frames; with `carve: true` they cut holes)
  that poses `show`; 2D -> add frames (derive with `from`/`shift` where possible) and an
  `animations` entry (squash/stretch, tipping and pulsing: `from` + `scale`/`rotate`). Keep everything that shouldn't move on exactly the same pixels; check the changes
  row and W007. Typical frame counts: idle 2-4, walk 4-6, attack 3-5.
- **"Make an enemy / another character"**: new asset in the same style - same palette, outline, light,
  proportions; compare side by side with `pagan gallery`. Variants (`variants:` ramp_swap/key_swap/
  palette) are the cheap way to make recolored versions (elite enemy, night version, team colours);
  `pagan preview` writes variants.png to compare them. When the base colours are one of the set (team
  cyan + red/orange/...), name them with `base_variant: cyan` so the manifest lists all of them uniformly. Many variants of big models multiply sheet sizes:
  if the game can recolour in a shader, set `variant_sheets = false` and point it at each variant's
  `swap` table in manifest.json. **A look for a whole set** ("everything on the map gets an arctic
  version"): put the variant in the palette file (`variants: { arctic: { ramp_swap: ..., tags: [world] } }`),
  not into every asset; tilesets compare variants on their first drawn tile (`--frame NAME` for another, and
  `--scene` writes scene_variants.png).
- **A family of related assets** (character classes, unit types, building tiers): put the shared body in a
  `template: true` model and `extends:` it per member (add parts, `remove: [ids]`, override materials),
  so a fix to the base reaches all of them. **Colours that combine** (player colour × rank, team × armour
  tint): `variant_axes`, not one variant per combination.
- **Shadows, glows, light rays, smoke**: give the palette translucent colours (`"#00000080"`, `"#rrggbbaa"`)
  and draw them like any other key, instead of dithering or tinting in the game. Not for 3D models (opaque).
- **Out of palette keys** (62 ASCII letters/digits used): keep going with Unicode letters (à, é, ß, α, Ω...);
  see `pagan docs palettes`. Don't alias existing keys or copy the palette.
