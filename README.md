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

> **Status:** early development. Only `pagan --version` works so far. See [PLAN.md](PLAN.md) for the roadmap.

## Install (development)

Requires Python 3.11+.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pagan --version
pytest
```

## License

MIT — see [LICENSE](LICENSE).
