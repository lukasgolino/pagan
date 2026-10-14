# PAGAN — Pixel Art Grammar And Notation

PAGAN is a translator between AI and pixel art. It defines a small text notation for pixel art —
palette-keyed grids written in YAML — that an AI agent can write fluently, and a Python tool that reads
the same notation and turns it into PNGs, sprite sheets, and game-engine-ready assets.

```yaml
frames:
  idle_0: |
    .....000000.....
    ....05566650....
    ...0556776650...
```

> **Status:** early development, but the full pipeline works: palettes, 2D sprites and tilesets, 3D voxel
> models rendered from 8 headings, previews, lint, import, and builds into Godot 4. See [PLAN.md](PLAN.md).

## Install (development)

Requires Python 3.11+.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pagan --version
pytest
```

## Quick start

```sh
pagan init my-art            # creates pagan.toml, STYLE.md, palettes/, sprites/, tiles/
cd my-art
pagan new palette dusk       # scaffolds palettes/dusk.pal.yaml; then set default_palette = "dusk" in pagan.toml
pagan palette show           # renders swatches to previews/palettes/*.png

pagan new sprite potion --size 16x16 --description "red health potion"   # 2D: edit the grid
pagan new model ship --size 96x96 --directions 8                          # 3D: shapes + materials
pagan lint                   # format errors + style warnings
pagan preview potion         # upscaled sheet, frames and GIFs in previews/potion/
pagan gallery                # every asset side by side
pagan build                  # sheets + manifest (+ Godot SpriteFrames) into output_dir
```

Every command accepts `--json` for machine-readable output and exits non-zero on errors.
See `examples/demo/` for an example project (palettes, a potion, a slime, meadow tiles and an
8-heading 3D ship) and `examples/godot/` for the Godot project it builds into: open it in Godot 4.7 and
press Play.

## License

MIT — see [LICENSE](LICENSE).
