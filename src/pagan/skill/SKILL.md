---
name: pagan
description: Make and maintain pixel-art (and flat arcade) game assets with PAGAN - sprites, items, tiles, icons, fonts, 3D models rendered in 4-16 directions or built as meshes, animations - and change the art style over time (camera, light, darker, new palette). Use whenever a user or an orchestrating agent asks for game art, a sprite, a tileset, rotations, an animation or a look change, or mentions pagan / pagan.toml.
---

# PAGAN: game art as text

You write palette-keyed grids (2D) or voxel shapes (3D) in YAML; the `pagan` CLI lints them against the
project's style rules, renders previews you look at, and builds PNG sheets, `manifest.json` and Godot
resources. This page is the core. Everything else is a topic: **`pagan docs <topic>`** prints one,
`pagan docs --search <words>` finds the paragraphs you need. Read only the topics your task needs.

| Topic | When |
|---|---|
| `setup` | no `pagan.toml` yet; what to ask the owner; project layout |
| `config` | camera, light, supersample, every `pagan.toml` key (`pagan config show`) |
| `making` | the full asset loop: 2D or 3D, sizes, review, what to report |
| `follow-up` | more directions, a new animation, an enemy in the same style, recolours, families |
| `palettes`, `sprites`, `tilesets`, `models` | the notation of each source type |
| `meshes` | 3D games: `voxel_size`, `.glb` meshes, rigs, triangle budgets |
| `timeline`, `recipes`, `api` | timeline previews, worked recipes, generator scripts (`pagan.api`) |
| `commands`, `lint`, `build`, `godot` | every command, every lint rule, the manifest, Godot wiring |
| `evolve` | "darker", "more contrast", "light from the right": changing every asset at once |
| `report` | filing what got in your way |

## Every task

1. `pagan --version` (missing: install the version the project pins; never swap a pinned install for an
   editable checkout). `pagan status` finds the art home (the folder with `pagan.toml`) and lists the assets.
   No project: `pagan docs setup`.
2. **Read BRIEF.md and STYLE.md first**: they are your memory between sessions (palette, sizes, perspective,
   references, every decision the owner made).
3. Ask only what you can't infer, in ONE message, each question with a default; go on with the defaults.
   Start with one asset and get it approved before related ones. Size is the requester's choice: say so when
   a request is small for what it describes.
4. 2D or 3D: a **model** (`pagan new model`) for anything seen from several headings or at angles (ships,
   vehicles, turning characters, buildings); a **sprite** (`pagan new sprite`) for icons, UI, items, side-view
   characters, effects and small one-view props; a **tileset** (`pagan new tiles`) for seamless terrain.
   Many similar assets: a generator script on `pagan.api` (`api`), never PAGAN's geometry copied into your code.
5. The loop, about four rounds at most: scaffold with `--size WxH --description "..."`; write the grid (every
   row exactly the frame width) or parts; `pagan lint <file>` and fix every error and every real warning (a
   warning wrong by design goes in that file's `lint: { disable: [...] }`); `pagan preview <name>` and **open
   `previews/<name>/sheet.png`** (pages `sheet.<anim>.png` when it is split); models: `pagan fit <model>`.
6. Self-review against STYLE.md (`pagan gallery` shows the whole set): readable at 1x, light from the right
   side, ramps dark to light, no pillow shading, the animation "changes" row lights up only what moves.
7. Show the owner the sheet path and the choices you made; without an owner, leave `status: draft` and note it
   in BRIEF.md. On approval: `pagan mark <name> --status approved`, `pagan build` (give it a long timeout), and
   report from `manifest.json`: sheet / `.tres` paths, animation names, frame size, the pivot (`godot_offset`).

**MCP:** with PAGAN tools (`status`, `write_asset`, `preview`, `docs`...), use them instead of the CLI; same
workflow. **Orchestrators:** report what a program can use; `manifest.json` is the contract with the game.

## Spend few tokens

- `pagan docs <topic>` instead of reading PAGAN's source or a whole reference. A question the topics don't
  answer is worth a report (`report`).
- Prefer `--json` and read only the fields you need; look at a preview once per change.
- One command that answers the question beats several probes: `pagan status`, `pagan config show`.

## Rules of thumb

- Never invent colours: everything comes from the palette. Quote keys and hex values in YAML (`"0"`,
  `"#1a1c2c"`): an unquoted `#` starts a comment.
- Keep 1 px of transparent border with `outline: auto` (E007). Thick outlines and shadows are `outline:` and
  `shadow:` settings, not painted into frames.
- Look changes go through the palette and project settings, so every asset changes at once (`evolve`).
- Mirroring and derived frames save time but light both sides the same: never trade a worse sprite for less work.
- Previews are for looking; `pagan build` output is what the game uses. Don't hand-edit build output. Don't
  commit or push unless asked.
- PAGAN seems wrong (a crash, a misleading error)? Say so and offer to report it (`pagan docs report`).
