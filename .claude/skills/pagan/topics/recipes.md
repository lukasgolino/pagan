# Recipes

Recipes: common assets step by step.

## Recipes

**Top-down character (3D, ~22px tall in a 32x32 frame, walk cycle).** Separate parts with ids for
everything that moves; poses offset them by whole voxels so the body never jumps:

```yaml
parts:
  - box: { from: [-1, 1, 0], to: [0, 2, 6], material: trousers }     # left leg (boot: another box, same id)
    id: left_leg
  - box: { from: [-1, -2, 0], to: [0, -1, 6], material: trousers }
    id: right_leg
  - box: { from: [-1, -3, 7], to: [1, 3, 13], material: shirt }       # torso (7 wide, 3 deep)
  - box: { from: [-1, 4, 7], to: [0, 4, 12], material: shirt }        # arm; the right one at y = -4
    id: left_arm
  - box: { from: [-2, -2, 14], to: [2, 2, 18], material: skin }       # head (5 voxels)
  - box: { from: [3, 1, 16], to: [3, 1, 16], material: eye }          # eyes on the front face (+x)
    mirror: true
animations:
  walk:
    fps: 8
    poses:
      - { left_leg: { offset: [1, 0, 0] }, right_leg: { offset: [-1, 0, 0] }, left_arm: { offset: [-1, 0, 0] }, right_arm: { offset: [1, 0, 0] } }
      - {}
      - { left_leg: { offset: [-1, 0, 0] }, right_leg: { offset: [1, 0, 0] }, left_arm: { offset: [1, 0, 0] }, right_arm: { offset: [-1, 0, 0] } }
      - {}
```

Tips: keep hats/brims small (from above they hide the face); give the back of the head hair; a sword
swing: make the sword `hidden: true` so idle frames don't have it, then `show` it in the swing poses; for
big arcs use several sword parts (`sword_up`, `sword_mid`, `sword_down`, all hidden) and show one per pose.

**Ship / vehicle.** `hull` with `top:` deck and `rim:` rail, `box` castles, `cylinder` masts, `sail`s
braced ~30° so they read from every heading, `line` for spars, flags as small boxes with an `id` to animate.

**Icons and items (2D).** 16x16 sprite, `outline: auto`, light from the top-left, one or two ramps,
`mirror: horizontal` only if the light can be symmetric.
