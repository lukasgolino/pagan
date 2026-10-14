# Art brief

The long-term memory for this project's art: what the game is, what it needs, and decisions made along
the way. Agents read this (with STYLE.md) before making or changing any asset, and keep it up to date.
`pagan status` lists what exists; this file says what's *wanted* and why.

> This is PAGAN's demo project; the "game" is a small example used to exercise every feature.

## The game

- **Title / working name:** Tidewake (demo)
- **Genre and core loop:** top-down naval exploration: sail between islands, trade, fight slimes on land
- **Perspective:** top-down 3/4 (`[camera] elevation = 42`)
- **Mood / references:** warm, earthy, hand-painted adventure maps; late-afternoon light
- **Target resolution:** 480x270, integer-scaled (see `examples/godot/project.godot`)

## Characters and key assets

- **Player ship** (`models/ship.model.yaml`): three-masted wooden ship, 96x96, 8 headings, pennants
  flutter in the `sail` animation. No water in the sprite: it sits on a separately animated sea.
- **Sailor** (`models/sailor.model.yaml`): deckhand, 32x32, 8 headings, 4-frame walk (legs/arms swing,
  body stays put).
- **Slime** (`sprites/slime.sprite.yaml`): green enemy, 16x16, symmetric, 2-frame idle squash.
- **Potion** (`sprites/potion.sprite.yaml`): red health potion item, 16x16.
- **Meadow** (`tiles/meadow.tiles.yaml`): island grass tiles, 16x16, seamless.

## Asset wishlist

- [ ] Sea tiles (animated), 16x16
- [ ] Island coast tiles
- [ ] Enemy ship (variant of the player ship with darker sails)

## Done

- Player ship, sailor, slime, potion, meadow tiles (style v1)

## Decisions and feedback log

- 2026-10-14: Ship must have no water under it (it moves freely on the sea) and 8 headings; built as a
  3D model so headings stay consistent.
- 2026-10-14: Animation frames must not jump: unchanged parts stay on the same pixels (lint W007,
  preview "changes" rows).
