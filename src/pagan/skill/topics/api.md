# Api

Generator scripts: the pagan.api Python API.

## Generator scripts: `pagan.api`

When a script is quicker than hand-written grids (effects, corner/terrain sets, families of ships), build
on `from pagan import api` instead of copying PAGAN's maths; it's versioned with PAGAN (`api.API_VERSION`).

- `api.Canvas(w, h)`: `put`, `rect`, `line` (`width=` for thick strokes, round ends), `circle`, `ellipse`, `ring`,
  `polygon(points, key)`, `triangle(a, b, c, key)`, `blit`, `flip`; for rect/ellipse/ring a key can be a
  function `(dx, dy) -> key` (offsets in radii, -1..1); for polygon/triangle a function `d -> key` (d = pixel
  centre's distance to the nearest edge in pixels: `lambda d: "rim" if d < 2 else "fill"` = a 2px rim);
  shapes fill pixels whose centres are strictly inside; `api.polygon_distance(points, x, y)` is the signed
  distance (+ inside). `fade(amount, seed)` dissolves from the edge,
  `scatter(n, key, seed, box, size)`, `orphans()` (exactly W001), `remove_orphans()`, `pair_orphans()`, `rows()`.
- Big canvases (numpy): `Canvas.from_array(keys_array)` or `Canvas.from_array(index_array, "rstuv")` (negative =
  transparent), `to_array()`, `mask()` (bool, opaque); `distance_field(mask)` (signed, exact Euclidean between
  pixel centres: + inside, - outside), `bevel(mask, width, light)` -> 0..1 brightness of a bevelled shape,
  `dither(keys, t, x, y, matrix=4)` (ordered Bayer dithering between ramp steps; scalars or arrays from `np.mgrid`).
  Draw in numpy, hand PAGAN the keys.
- Lettering with a project font sprite (`font:`): `canvas.text(api.load("sprites/font.sprite.yaml"), "THWACK!", x,
  y, scale=1, key=None)` (a `Canvas` method; top-left at (x, y), the build's advances, `key` = one key for every pixel).
- Built-in pixel fonts, no project or palette needed: `canvas.text(api.pixel_font("3x5"), "EXIT", x, y, key="k")`
  (`key` required). `"3x5"` and `"5x7"`, printable ASCII, monospaced (advance 4 / 6 px, line height 6 / 8); the
  3x5 font letters lowercase with its uppercase glyphs. Generators only: for in-game text, draw a `font:` sprite.
- Lettering from a real typeface: `text_mask("A", font="fonts/Serif.ttf", cap_height=104, variation={"wght": 900},
  anchor="baseline_centre", rotate=3, scale=(0.9, 1), supersample=4)` -> `.coverage` (0..1 floats), `.mask()`
  (bool), `.origin` (the anchor in the mask), `.advance` (kerning included), `.bbox`. Rotate/scale turn about the
  anchor, so a tilting letter's frames stay aligned; `variation` is axis values by tag or a named instance ("Bold").
  Then `distance_field(text.mask())` / `bevel(...)` for bevels, outlines and extrusions.
- Shading: `light_2d(project)` (the project's light for flat art), `sphere_light(dx, dy, light)`,
  `ramp_pick(keys, t)`, `hash01(x, y, seed)`, `periodic_noise(x, y, period, seed)` (seamless), `smoothstep`.
- Terrain: `corner_tiles(prefix, size, paint, seed, amp)` -> the 16 Match-Corners tiles
  `<prefix>_<NW><NE><SW><SE>`; `paint(field, x, y, corners)` returns a key, `field(x, y) >= 0.5` = upper
  terrain. `compose(tileset_asset, "a b\nb a")` -> a PIL image of a layout.
- 3D: `shape_cells(shape, spec)` = the voxels a part fills; `hull_reach(x, length, beam, bow, stern, keel)`;
  `sail_cells(at, width, height, bulge, brace, rig, yard)` -> cells with their cloth position (`u`, `row`),
  e.g. to place patches or gun ports exactly on a sail or hull side.
- 2D headings: `directional_frames(draw, size, directions=8)` -> one Canvas per heading, named like model
  headings (e, ne, n, ...; h00-h31); `draw(canvas, angle)` paints the shape turned to `angle` degrees,
  usually via `rotate_points(points, angle, about)` (a shape drawn facing east; counter-clockwise on screen).
- Files (numpy numbers are fine in sizes and fields): `sprite_yaml(name, size, frames, animations, **fields)`, `tileset_yaml(...)`, `write(path, text)`
  (writes only on change), `load(path)` -> parsed asset, `open_project(path)`, `palette(name, project)`.
- Big generated sprites: `spec = api.frames_png("sprites/logo.frames.png", frames, size, palette=None, columns=8)`
  writes the frames as an indexed PNG (only on change) and returns the `frames_png:` value; then
  `sprite_yaml("logo", size, {}, animations, frames_png=spec)` (keep the sprite file next to the PNG).
  `palette` only makes the PNG show real colours in image viewers.
