# Palettes

Palette notation: keys, ramps, translucent colours, palette variants.

All source files are YAML. Quote palette keys and hex values (`"0"`, `"#1a1c2c"`): an unquoted `#` starts a YAML comment.

## Palette - `palettes/<name>.pal.yaml`

```yaml
name: dusk
colors:                       # key = ONE letter or digit ("." is transparent)
  "0": { hex: "#140c1c", name: ink }
  "1": "#442434"              # short form: just the hex
  "α": "#2f6b9a"              # past 0-9 a-z A-Z: any other single Unicode letter
  "s": { hex: "#00000080", name: shadow }   # "#rrggbbaa": translucent (00 clear .. ff opaque)
ramps:                        # dark -> light; one ramp per material
  warm: ["1", "2", "3", "4"]
variants:                     # optional: palette-wide recolours every asset using this palette gets
  arctic: { ramp_swap: { grass: snow }, key_swap: { "5": "ε" }, tags: [world] }   # tags: only assets with one
base_variant: temperate       # optional: the base colours' name on assets that get these variants
```

Palette variants recolour within the palette (ramp_swap/key_swap, no `palette:`), so one "arctic pass"
reaches every world asset at once. An asset's own variant of the same name wins; `variants: { arctic: false }`
in an asset turns an inherited one off.

Keys: use 0-9, a-z, A-Z first (62), then Latin-1 letters (à-ÿ, À-Þ, ß) and Greek letters that don't look
like Latin ones (α-ω, Γ Δ Θ Λ Ξ Π Σ Φ Ψ Ω); any single Unicode letter or digit is accepted. Quote keys in
the palette file. Files are UTF-8; an accent typed as a separate combining mark is merged (NFC).

Translucent colours (`"#rrggbbaa"`) are for drop shadows, glows, light rays and smoke in sprites and
tilesets: the PNG pixel gets that alpha. The default `outline_color` is the darkest *opaque* colour, `pagan
import` snaps to opaque colours only, and 3D model materials must be opaque (E013). `[lint] require_opaque
= true` forbids them in a project (E015). `"#rrggbbff"` is the same as `"#rrggbb"`.

## Hardware palettes

`hardware:` keeps a palette to what a real machine could show, so the art could have been drawn on it (and a 3D
game's retro pass in KILN quantises to the real thing):

| `hardware` | colours | at once |
|---|---|---|
| `cga` | the 16 RGBI colours (`#000000 #0000aa #00aa00 #00aaaa #aa0000 #aa00aa #aa5500 #aaaaaa #555555 #5555ff #55ff55 #55ffff #ff5555 #ff55ff #ffff55 #ffffff`) | 4 |
| `atari-st` | 3 bits per channel: each of r, g, b is one of 00 24 49 6d 92 b6 db ff (512 colours) | 16 |
| `atari-st-mono` | `#000000`, `#ffffff` | 2 |

A colour the machine can't show, too many colours, or a translucent colour is E017 (the message names the nearest
legal colour). CGA's 4-colour modes are a free background colour plus one fixed set of three (green/red/brown or
cyan/magenta/grey, low or high intensity; mode 5: cyan/red/grey); other combinations are W015.

`pagan new palette <name> --hardware cga` scaffolds a legal palette with ramps. `pagan palette snap <name>
[--hardware atari-st] [--dry-run]` moves every colour to the nearest legal one (Oklab; per channel for the ST)
and writes `hardware:` into the file; comments and layout are kept, and you remove extra colours by hand.
