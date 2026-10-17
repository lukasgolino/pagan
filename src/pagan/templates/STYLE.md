# Style bible

The rules that make this project's art look like itself. Agents read this before drawing anything
and check their previews against it. Replace every **TODO** with a decision; the suggested defaults
are a reasonable starting point.

Rules that can be checked mechanically belong in `pagan.toml` too (see `[lint]`).

These are **pixel-art** defaults (outline, painted light, shading ramps). For flat / vector-like arcade
art, they don't apply: start from the flat template instead (`pagan init --style flat`).

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
- Flip lit art vertically (`flip: vertical`): the highlights end up on the wrong side. Horizontal flips
  are fine for symmetric-ish lighting; for strict top-left light, draw or render each direction.
- Let anything jump between animation frames: the anchor (feet) and unchanged parts must stay on exactly
  the same pixels. Check the preview's "changes" rows; lint W007 flags large frame-to-frame churn.
- Use colors outside the palette.
- Leave orphan pixels (single pixels with no neighbours).
- **TODO**

## 9. Reference sprites

The approved sprites that define the look. Compare every new asset against these in preview.

- **TODO** (pick 2–4 once some art exists)

## Changelog

Each look change that means existing art should be revisited gets a version (`pagan style bump "note"`
bumps `style_version` in pagan.toml and adds an entry here, newest first). Assets made under an older
version get lint warning W006 until they're reviewed and stamped (`pagan mark --current <asset>`).
Palette edits and `[light]`/`[camera]` changes need no bump for 3D models (they re-render automatically);
bump when 2D sprites need redrawing to match.

- v1: initial style
