# Style bible (flat / vector arcade)

The rules that make this project's art look like itself. Agents read this before drawing anything
and check their previews against it. Replace every **TODO** with a decision; the suggested defaults
are a reasonable starting point.

This project is **not** traditional pixel art: flat shapes, strong colour contrast, no outlines and no
painted light; glow and lighting (if any) are done by the engine. PAGAN's pixel-art defaults (dark
outline, light from the top-left, 3-step ramps, no pillow shading) don't apply here.

## 1. Palette

- Palette file: **TODO** (e.g. `palettes/neon.pal.yaml`)
- Few, saturated colours on a dark background. Per object: a **fill** and a paler **rim** (2 keys); team
  colours as ramps of the same length so `variants: { red: { ramp_swap: { cyan: red } } }` recolours them.

## 2. Shapes

- Objects are simple filled shapes: triangles, polygons, circles, capsules. Silhouette first; no texture,
  no dithering, no single-pixel detail.
- Fill + rim: `api.Canvas.polygon(points, lambda d: rim if d < 2 else fill)` (d = distance to the edge in
  pixels). Lines and lasers: `line(..., width=3)`.
- Size on screen: **TODO** (e.g. ship 32 px, bullet 6 px)

## 3. Edges and rotation

- Sprites rotate freely in game: **TODO** (suggested: yes)
- If so, draw at 2x and let the build smooth the edges: `pagan config set supersample 2` (sources are
  drawn at 2x the size the game gets; the build writes anti-aliased PNGs). Check `previews/<asset>/built_1x.png`.
- Godot: `pagan config set godot.filter linear` and `pagan config set godot.mipmaps true`.

## 4. Light and outline

- Outline: none (`outline: none`, the default).
- Light: none painted in; no shading ramps. Glow, bloom and lights: done by the engine.
- 3D models (if any): `pagan config set light.baked false` for flat colours.

## 5. Animation

- Default fps: **TODO** (suggested: 12)
- Effects (explosions, hits) as expanding/fading shapes: `Canvas.ring`, `circle`, `fade`.

## 6. Do / Don't

Do:
- Keep every object readable as a solid shape at its in-game size.
- **TODO**

Don't:
- Add pixel-art shading, dithering or outlines.
- Use colours outside the palette.
- **TODO**

## 7. Reference sprites

The approved sprites that define the look. Compare every new asset against these in preview.

- **TODO** (pick 2–4 once some art exists)

## Changelog

Each look change that means existing art should be revisited gets a version (`pagan style bump "note"`
bumps `style_version` in pagan.toml and adds an entry here, newest first). Assets made under an older
version get lint warning W006 until they're reviewed and stamped (`pagan mark --current <asset>`).

- v1: initial style
