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

> **Status:** early development. Palettes and projects work; sprites are next. See [PLAN.md](PLAN.md) for the roadmap.

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
pagan new palette dusk       # scaffolds palettes/dusk.pal.yaml
pagan palette show           # renders swatches to previews/palettes/*.png
```

Every command accepts `--json` for machine-readable output and exits non-zero on errors.
See `examples/demo/` for an example project with three palettes.

## License

MIT — see [LICENSE](LICENSE).
