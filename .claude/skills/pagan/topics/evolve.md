# Evolve

Changing the look over time: palette adjust, config, style bump.

## Changing the look over time

Look changes go through the palette and the project light whenever possible, because then **every
asset updates at once** and stays consistent:

| Owner says | Do |
|---|---|
| "darker" / "lighter" | `pagan palette adjust <pal> --lightness -0.05` (or +) |
| "more contrast" | `pagan palette adjust <pal> --contrast 1.15` |
| "more pastel" / "muted" | `pagan palette adjust <pal> --saturation 0.6 --lightness 0.04` |
| "more vivid" | `--saturation 1.2` |
| "warmer" / "cooler" | `--warmth 0.02` / `--warmth -0.02` |
| "only the greens darker" | add `--ramp <ramp>` (or `--keys ...`) |
| "more / softer shadows" | `pagan config set light.ambient 0.1` (3D re-renders); 2D: needs redrawing (below) |
| "light from the right" | `pagan config set light.direction "[0.5, 0.45, 0.75]"`; 2D: redraw (below) |
| "lower / higher camera angle" | `pagan config set camera.elevation 30` (3D re-renders); 2D: redraw (below) |
| "our engine does the lighting" | `pagan config set light.baked false` and add "normals" to `export` |
| "try a different palette" | `--out <new>` to make a copy, or a new palette with the SAME keys, then switch `default_palette` (grids reference keys, so assets carry over) |

Always use `--dry-run` or the before/after swatch it writes, then `pagan gallery` to check the whole
set, and log the change in BRIEF.md's feedback log.

**When existing 2D art must be redrawn** (more shading, new outline style, new proportions):
1. `pagan style bump "what changed and why"` - bumps `style_version`, logs it in STYLE.md.
2. Update STYLE.md's rules to match.
3. `pagan status` lists every asset flagged "review for style vN" (lint W006).
4. Go through them one by one: update, preview, look, then `pagan mark <name> --current`.
5. `pagan gallery` at the end; `pagan build`.
