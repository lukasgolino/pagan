# Tutorial: your first sprite

Ten minutes from an empty folder to a built, animated sprite. Needs PAGAN installed ([install.md](install.md)).

## 1. A project and a palette

```sh
pagan init my-art                      # pagan.toml, STYLE.md, BRIEF.md, palettes/, sprites/, tiles/, models/
cd my-art
pagan new palette dusk                 # palettes/dusk.pal.yaml: four greys to start with
pagan config set default_palette dusk  # sprites that don't name a palette use it
pagan palette show                     # swatches in previews/palettes/dusk.png
```

A palette maps one-character keys to colours, and groups them into ramps (dark to light). Sprites are written
in those keys, so changing the palette recolours everything at once.

## 2. A sprite

```sh
pagan new sprite gem --size 8x8 --description "a grey gem"
```

Open `sprites/gem.sprite.yaml` and draw: one character per pixel, `.` is transparent, every row exactly as wide
as the sprite. Replace `frames:` with two frames and an animation:

```yaml
frames:
  main: |
    ........
    ...00...
    ..0230..
    .023310.
    .012210.
    ..0110..
    ...00...
    ........
  shine: |
    ........
    ...00...
    ..0330..
    .023310.
    .012210.
    ..0110..
    ...00...
    ........
animations:
  idle: { frames: [main, shine], fps: 2 }
```

## 3. Lint and look

```sh
pagan lint                             # errors (E...) and style warnings (W...), each with file:line and a fix
pagan preview gem                      # previews/gem/: upscaled sheet, frames and an animated GIF
```

Fix what lint reports and look at the preview after every change; [lint rules](reference/lint-rules.md)
explains each rule.

## 4. Build

```sh
pagan build                            # build/sprites/gem.png + build/manifest.json
```

`manifest.json` lists every frame's rectangle, the animations, the pivot and the variants: it is what a game
reads. To build straight into a Godot project, set `output_dir` to a folder inside it and add `"godot"` to
`export` (`pagan config set export '["png", "godot"]'`): each sprite then also gets a SpriteFrames `.tres`.

## Next

- More of the notation (derived frames, outlines, variants, tilesets, 3D models): the skill's
  [reference](../src/pagan/skill/reference.md), and [every field](reference/notation.md) in one list.
- Every `pagan.toml` setting: [settings](reference/settings.md).
- Let an agent do it: `pagan skill install` (Claude) or `pagan mcp` (any MCP client); see the [README](../README.md).
- A bigger example: `examples/demo/` (palettes, sprites, tiles, a 3D ship) and the Godot project it builds into.
