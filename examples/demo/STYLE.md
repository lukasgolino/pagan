# Style bible

The rules that make this project's art look like itself. Agents read this before drawing anything and
check their previews against it. Mechanical rules also live in `pagan.toml` (`[lint]`, `[camera]`, `[light]`).

## 1. Palette

- Palette file: `palettes/ember.pal.yaml` (24 colors). `tide` and `arcade` are alternatives, not used here.
- Ramp intent:
  - `earth`: outlines (`0`), stone, rope, sails (`3`-`5`), neutral details
  - `fire`: wood (hulls, crates, cork), warm light, lanterns (`a` for glowing windows)
  - `moss`: grass, foliage, slimes
  - `sky`: glass, water, metal highlights
  - `rose`: liquids, flags, skin accents

## 2. Scale

- Items, creatures and tiles: 16x16. Characters about 12-14px tall.
- Ships and large vehicles: 3D models, 96x96 frames, 1px per voxel.
- Base resolution 480x270, integer-scaled.

## 3. Outlines

- 1px dark outline (`outline: auto`, darkest color `0`) on sprites and models. No outline on tiles.

## 4. Light

- From the top-left (`[light] direction = [-0.5, 0.45, 0.75]`). Highlights on top/left edges, darkest
  ramp step on the bottom/right.

## 5. Shading

- 3 steps per material for 16px sprites; 3-4 for models (set by the material's keys).
- No pillow shading. Dithering: never.

## 6. Proportions

- Chunky and readable at 1x: if a detail is a single isolated pixel, drop it (lint W001).

## 7. Animation

- Idle: 2 frames at 3-4 fps. Ship sail: 4 frames at 6 fps.
- Frames must not jump: the base/feet stay planted; check the preview's changes row (lint W007).

## 8. Do / Don't

Do:
- Use `mirror: horizontal` for symmetric front-facing creatures.
- Use 3D models for anything that needs several headings.

Don't:
- Flip lit art vertically (`flip: vertical`): the light ends up on the wrong side.
- Use more than 3 ramps in one asset (lint W003).

## 9. Reference sprites

- `models/ship.model.yaml`, `sprites/slime.sprite.yaml`, `sprites/potion.sprite.yaml`

## Changelog

Each look change that means existing art should be revisited gets a version (`pagan style bump "note"`).
Assets made under an older version get lint warning W006 until reviewed and stamped (`pagan mark --current`).

- v1: initial style
