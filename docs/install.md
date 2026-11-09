# Install

PAGAN is a Python package (Python 3.11+; Pillow, PyYAML and numpy come with it). Install a pinned
release, so every machine building the art gets the same pixels. The package is `pagan-gen` on PyPI (`pagan` there is
another project); the command and the import are `pagan`:

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install "pagan-gen==0.22.0"     # or from git: "pagan-gen @ git+https://github.com/lukasgolino/pagan@v0.22.0"
pagan --version
```

Tags and what changed in each: [CHANGELOG.md](../CHANGELOG.md). A game project should pin one (in its
`requirements.txt` or tool setup) and upgrade on purpose: any release may change rendered pixels or the manifest.

Optional extras:

- MCP server for any agent: installed with PAGAN; `pagan mcp --project <art folder>`, or without an install
  `uvx pagan-gen mcp --project <art folder>` (see the [README](../README.md#using-pagan-from-any-agent-mcp)).
- Claude skill: `pagan skill install` in the game repo copies it to `.claude/skills/pagan/`.
- Godot checks (`pagan build --verify-godot`, `pagan preview --engine`): a Godot 4 binary, found via `GODOT=/path/to/godot`.

Working on PAGAN itself:

```sh
git clone https://github.com/lukasgolino/pagan && cd pagan
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
mypy && pytest
```

Next: the [tutorial](tutorial.md).
