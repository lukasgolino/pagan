# Style bible

The rules that make this project's art look like itself. Agents read this before drawing anything
and check their previews against it. Replace every **TODO** with a decision; the suggested defaults
are a reasonable starting point.

Rules that can be checked mechanically belong in `pagan.toml` too (see `[lint]`).

## 1. Palette

- Palette file: **TODO** (e.g. `palettes/my_palette.pal.yaml`, or "open" for per-sprite palettes)
- Ramp intent — what each ramp is for:
  - **TODO** e.g. `skin`: characters' skin; `foliage`: plants; `stone`: walls and floors; `ui`: interface only

## 2. Scale

- Base sprite / tile size: **TODO** (suggested: 16×16)
- Character height: **TODO** (suggested: 12–14 px in a 16 px tile)
- Target base resolution and integer scale: **TODO** (suggested: 320×180, scaled ×4 to 1280×720)

## 3. Outlines

- Style: **TODO** (suggested: 1 px dark outline using the darkest color)
- Selective outline (lighter outline on lit edges)? **TODO** (suggested: no)

## 4. Light

- Light direction: **TODO** (suggested: top-left)
- Highlights on edges facing the light; the darkest ramp step on the far side.

## 5. Shading

- Ramp steps per material: **TODO** (suggested: 3 — shadow, mid, highlight)
- No pillow shading (shading that just follows the outline inward from all sides).
- Dithering: **TODO** (suggested: allowed sparingly, only on large flat areas, never on small sprites)

## 6. Proportions

- Head-to-body ratio for characters: **TODO** (suggested: 1:1 to 1:2, chunky and readable)
- Detail level: readable at 1× scale; if a detail is a single isolated pixel, drop it.

## 7. Animation

- Default fps: **TODO** (suggested: 8)
- Frame counts: idle **TODO** (suggested 2–4), walk **TODO** (4–6), attack **TODO** (3–5)
- Squash and stretch: **TODO** (suggested: yes, subtle)

## 8. Do / Don't

Do:
- Use `mirror: horizontal` for symmetric subjects.
- Keep silhouettes readable as a solid shape.
- **TODO**

Don't:
- Use colors outside the palette.
- Leave orphan pixels (single pixels with no neighbours).
- **TODO**

## 9. Reference sprites

The approved sprites that define the look. Compare every new asset against these in preview.

- **TODO** (pick 2–4 once some art exists)
