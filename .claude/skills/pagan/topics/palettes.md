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
