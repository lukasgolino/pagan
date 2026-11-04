# Timeline

Timeline previews: sprites composed in time.

## Timeline preview - `scenes/<name>.timeline.yaml`

Several sprites (or 3D models' frames) composed in time, to judge how they play together (does the flash
line up with the hit, is the glint readable over the letters). A preview only: `pagan build` and the
manifest never read it. `pagan lint` checks it with the project (E016; all problems, with lines and fixes).

```yaml
size: [640, 240]              # canvas, in output pixels (supersampled sprites are shown as built)
fps: 30                       # timeline frames per second (frames/f0000.png at t = 0, 1/30, ...)
duration: 6                   # seconds
background: "#101018"         # optional; default transparent (previews then show --bg)
layers:                       # drawn in list order (later on top), alpha-composited
  - {sprite: bg_smoke, anim: smoke, at: [0, 0], alpha: 0.6}
  - {sprite: letters, anim: a, at: [75, 200], start: 0.25, fade_in: 0.45}
  - {sprite: arrow, anim: fly, from: [-400, -60], to: [583, 131], start: 1.87, duration: 0.12, then: shudder}
  - {sprite: fx, anim: sparks, at: [583, 131], start: 1.99, variant: blue}
```

Layer fields (no others): `sprite` (asset name; sprites and 3D models, not tilesets), `anim` (an animation,
or a frame name shown still), `at: [x, y]` (where the sprite's pivot goes), `start` (seconds, default 0),
`duration`, `alpha` (0-1, default 1), `fade_in` / `fade_out` (seconds), `from` / `to` (instead of `at`:
a straight move over `duration`, rounded to whole pixels; the layer then stays at `to`), `then` (the
animation that follows when a one-shot `anim` (`loop: false`) ends; without it the last frame holds),
`variant`. `duration` without `from`/`to` = how long the layer is shown (default: to the end); `fade_out`
ends where the layer ends (with a move: the end of the timeline). Animations play from the layer's `start`
with their own fps, loop and `durations`. No easing, rotation or scale: use derived frames for those.
Times are exact (0.1 is 1/10 s), so output is identical on every machine.
