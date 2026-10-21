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
> models rendered from 8 headings or exported as real meshes (glTF) for 3D games, previews, lint, import, and
> builds into Godot 4. See [CHANGELOG.md](CHANGELOG.md) and the [issues](https://github.com/lukasgolino/pagan/issues).

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

## Using the output in a game

`pagan build` writes PNG sheets and `manifest.json` (frame rects, animations, pivots, tile coordinates)
for any engine. With `export = ["png", "godot"]` it also writes Godot 4 resources:

- **Sprites and 3D models:** `<name>.tres` SpriteFrames. Godot resources can't hold the pivot, so apply
  it on the node, using the asset's `godot_offset` from the manifest:

  ```gdscript
  $AnimatedSprite2D.sprite_frames = load("res://assets/generated/sprites/ship.tres")
  $AnimatedSprite2D.centered = true
  $AnimatedSprite2D.offset = Vector2(0.0, -12.0)   # manifest: assets.ship.godot_offset
  $AnimatedSprite2D.play("sail_ne")                 # 3D models: one animation per heading
  ```

- **Tilesets:** `tiles/<name>.tres` is a TileSet with every tile in atlas source 0; the manifest's `tiles`
  gives each tile name's atlas coordinates. Terrains, collision and other tile data are set up in Godot.

### 3D games: meshes

For a free 3D camera, add `"mesh"` to `export`: every 3D model also builds `models/<name>.glb` (binary glTF:
one node per part, animations, part metadata) plus a palette ramp texture, and with `"godot"` a
`models/<name>.tscn` with PAGAN's palette-locked ramp shader applied. Pick the project's texel density with
`pagan config set mesh.voxel_size 0.0625` (metres per voxel). Models face +Z, +Y is up, the model's `origin`
is the mesh origin; `rig:` in a model sets part pivots, parents and metadata (hit zones, detachable parts).

```gdscript
var soldier: Node3D = load("res://assets/generated/models/soldier.tscn").instantiate()  # manifest: mesh.godot_scene
add_child(soldier)
soldier.look_at(target, Vector3.UP, true)                  # true: the model's front (+Z) faces the target
soldier.get_node("AnimationPlayer").play("walk")           # looping animations loop
var helmet: Node3D = soldier.get_node("body/torso/head/helmet")   # manifest: mesh.parts.helmet.node
if helmet.get_meta("extras").get("detachable", false):    # rig meta -> node metadata "extras"
    helmet.reparent(get_tree().current_scene)              # knock it off: keeps its place in the world
```

Light the scene with a DirectionalLight3D (shadows on) and use the Linear tonemapper: the ramp shader then
keeps every lit pixel a palette colour (Forward+ and Compatibility renderers; Mobile can be a few levels off in
dark colours). Big repeating surfaces (ground, walls) are tileset textures:
`export_textures` writes repeatable PNGs and triplanar Godot materials. Review models with
`pagan preview <model> --orbit` (all headings, from below too), `--closeup <part>` and `--engine`.
`examples/godot/scenes/mesh_test.tscn` shows the demo meshes on turntables under a moving sun.

## Using PAGAN with Claude

PAGAN ships a Claude skill that teaches an agent the whole workflow: setting up a game's art folder,
asking the right questions, drawing/modelling, looking at previews, and changing the look over time.

```sh
pagan skill install          # copies it to <repo>/.claude/skills/pagan/
```

Then just ask: "I'm making a naval exploration game; make the player's ship, three masts, 8 headings."

## Using PAGAN from any agent (MCP)

`pagan mcp` runs PAGAN as an [MCP](https://modelcontextprotocol.io) server, so any MCP client (Claude
Desktop, Claude Code, Cursor, your own agent) can make, lint, preview and build art for one project. Tools
return the same JSON as the CLI's `--json`, and previews come back as images the model can look at.

```sh
pip install "pagan[mcp] @ git+https://github.com/lukasgolino/pagan@v0.12.0"
claude mcp add pagan -- pagan mcp --project ./art          # or any client: command `pagan mcp --project <dir>`
```

Add `--allow-godot` to let the build tool verify output in a headless Godot. Then ask: "make a 16x16
health potion", "give the zombie an attack animation", "make the whole game a bit darker".

## License

MIT — see [LICENSE](LICENSE).
