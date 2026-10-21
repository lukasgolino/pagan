# SPACIO_USEREPORT.MD — PAGAN use report from Space IO

Reports from building **Space IO** (`~/repos/space-io`), a space1.io replica in Godot 4.7.2.
Art target is **not** traditional pixel art: high-contrast neon arcade, straight top-down 2D, sprites rotated
freely by the engine. That makes this a stress test of PAGAN outside its pixel-art comfort zone.

Append-only; newest at the bottom. Each report: id, type, severity, version, context, repro, expected,
actual, impact, proposal. Positives are logged too (prefix `OK`) so they aren't regressed.

Setup: PAGAN pinned `pagan @ git+ssh://git@github.com/lukasgolino/PAGAN.git@v0.4.0` →
`pagan 0.4.0 (v0.4.0, f23a10c)`. Art home `space-io/art/`, generator `art/tools/gen_art.py` (pagan.api).

---

## Session 1 — 2026-10-17, setup + ship / laser / explosion

### S1 · feature · medium · No way to say "straight top-down 2D" at init; 3D camera defaults leak into 2D projects
- **Context:** Purely 2D top-down game; no models.
- **Actual:** `pagan init art --godot .` writes `[camera] elevation = 42` and a full `[light]` block. Nothing asks
  or records the perspective; we had to know to `config set camera.elevation 90`. STYLE.md / BRIEF.md
  templates are also pitched at 3/4 pixel-art (character head ratios, walk cycles).
- **Expected:** Perspective is a first-class project choice.
- **Proposal:** `pagan init --perspective top-down|top-down-3/4|side|iso` (sets elevation, writes it into
  BRIEF.md). When a project has no models, `config show` / `status` could mark `[camera]` as unused rather
  than presenting 42° as a meaningful default.

### S2 · feature · high · `pagan.api.Canvas` has no polygon fill or distance-to-edge helpers
- **Context:** Arcade / vector-style ships are polygons (arrowheads, wings, fins). Canvas offers rect, ellipse,
  circle, ring, line only.
- **Actual:** We wrote our own even-odd point-in-polygon and point-to-segment distance in the game's generator to
  fill a hull and draw a 2px inner rim (`inside()`, `edge_distance()` in `art/tools/gen_art.py`). The skill
  explicitly says not to copy PAGAN's geometry into game code, but there's nothing to call.
- **Proposal:** `Canvas.polygon(points, key)` where a callable key receives the pixel's distance to the
  nearest edge (or a separate `Canvas.polygon_sdf(points)` → per-pixel signed distance). That one primitive
  makes rims, bevels and inner glows trivial. Also `Canvas.triangle`, and `line(..., width=)` for thick strokes.

### S3 · feature · high · No anti-aliased / supersampled output for freely-rotated, non-pixel-art sprites
- **Context:** Ships rotate continuously (any angle), so nearest-neighbour pixel art shimmers. Wanted: crisp
  but smooth "vector arcade" edges.
- **Workaround:** author every sprite at 2× its on-screen size and let Godot downscale (linear filter + mipmaps).
  Costs 4× texture memory, and the edge AA quality depends on the engine.
- **Proposal:** optional build-time downsample, e.g. `pagan.toml` `[build] supersample = 2` (or per asset):
  author at 2×/4×, build writes box-filtered PNGs with partial alpha. Palette purity is lost in the *output*
  only (sources stay keyed, lint still applies). Clearly opt-in; off by default for pixel-art projects.

### S4 · feature · medium · No control over the Godot texture import settings PAGAN's output gets
- **Context:** Downscaled/rotated sprites need `mipmaps/generate=true` (and linear filtering). Godot writes
  `<png>.import` with defaults (mipmaps off) on first import.
- **Actual:** We patch `.import` files from a game-side script after `pagan build` (fragile; easy to forget).
- **Proposal:** `[godot] mipmaps = true` / `filter = "linear"` in `pagan.toml` (or per asset), and have
  the exporter write the `.import` files (or a `.tres` `CanvasTexture` / texture filter on the SpriteFrames).
  At minimum document how to set them so a rebuild doesn't lose them.

### S5 · bug · low · `Canvas.ellipse` with radius ≈ n + 0.5 leaves single-pixel nubs at the extremes
- **Repro:** `api.Canvas(32,12).ellipse(16, 6, 15.5, 5.5, "b")` → one stray pixel sticking out at the top and
  bottom centre (and left/right), because the pixel-centre-inside test includes boundary pixels exactly on
  the radius.
- **Expected:** a smooth oval. Lint doesn't flag nubs (they have a neighbour, so not W001).
- **Proposal:** use a strict `<` test, or a small epsilon, or document "use radii like 15.4".

### S6 · feature · low · The base asset can't be named as a variant
- **Context:** Team colours as variants: base art is cyan; variants `red`, `orange`, … The game wants the
  uniform set `cyan, red, orange, …`.
- **Actual:** The base is just `ship`; the game special-cases "cyan = base".
- **Proposal:** `base_variant: cyan` field, so the manifest lists the base under that name too
  (`variants.cyan` → the base sheet), or `variant_axes`-style naming for the default option.

### OK1 · Variants via `ramp_swap` are excellent for team colours
- One hull drawn in the `cyan` ramp, 7 `ramp_swap` variants → 8 correct team sheets + `.tres`, manifest
  `swap` tables, and `variants.png` to eyeball them all. Zero friction.

### OK2 · Preview loop
- `pagan preview` sheet + changes row + `variants_1x.png` answered every question we had without opening an
  image editor. `build --verify-godot` worked first time.

### S7 · doc · medium · Skill/templates steer every project toward detailed pixel art; nothing for flat/vector arcade styles
- **Context:** The brief asked for "high contrast arcade graphics, not traditional pixel art" (space1.io: flat
  neon triangles, glowing line lasers).
- **Actual:** Following the skill (outline: auto, light from top-left, ramps dark→light, "no pillow shading",
  cockpit/engine detail) the first attempt was a detailed pixel-art fighter with outline and shading. It was rejected as
  "the wrong route"; the right answer was a flat filled triangle with a pale rim and no outline. The STYLE.md
  template has no slot for "flat / unshaded / no outline / glow done by the engine", and the skill's first-time
  setup questions (perspective, mood, sizes, outline, light) never ask "pixel art or flat vector-like?".
- **Proposal:** add a "Rendering style" question to skill §1 (pixel art | flat/vector arcade | painterly) with a
  short recipe per style; a `flat` STYLE.md template (no light, no outline, fill + rim, engine glow); and say
  explicitly that `outline`/light/ramp rules are pixel-art defaults, not requirements.

### S8 · OK · Tilesets work as plain repeating background textures
- `stars_far`/`stars_near` are one-tile 512px tilesets; the game uses the manifest `sheet` PNG as a
  `texture_repeat` region in `Parallax2D`. Seamless by construction. `scatter()` was exactly right.

### S9 · OK · Stale variant outputs are cleaned on rebuild
- Renaming the `mint` variant to `blue`: `pagan build` reported "6 stale removed" and deleted the old
  `*.mint.png/.tres`. (Godot's `.import` siblings went too.) Nice.

### S10 · feature · low · Diagonal edges at 2x show stair steps in previews
- Related to S3. The triangle's 2x edges are visibly stepped in `pagan preview`; in-game they're smoothed by
  the 0.5x mipmapped downscale, but previews don't show what the game shows. A `--display-scale 0.5 --filter
  linear` preview (or the S3 supersample) would show the real look without running the game.

---

## PAGAN responses to S1-S10 — 2026-10-17 (in v0.5.0, see CHANGELOG.md; tag pending approval)

- **S1** fixed: `pagan init --perspective top-down|top-down-3/4|side|iso` sets `camera.elevation`
  (90/42/15/30) and writes it into BRIEF.md (also a "Rendering style" line). `config show` marks
  `[camera]`/`[light]` "(unused: no 3D models)"; `--json` has `used`.
- **S2** fixed: `Canvas.polygon(points, key)` (callable key gets distance to the nearest edge in px:
  `lambda d: "rim" if d < 2 else "fill"`), `Canvas.triangle`, `line(..., width=)`, `api.polygon_distance`.
  Port `inside()` / `edge_distance()` in `art/tools/gen_art.py` to these.
- **S3** fixed: `supersample = 2` in pagan.toml (or `supersample:` per asset). Draw at 2x; build writes
  box-filtered (alpha-weighted) PNGs at 1x with partial alpha. Manifest `size`/frames/`pivot` are output
  pixels (pivot may be fractional) + `supersample`, `source_size`. Size not a multiple -> E003.
  Caveat: blended edge pixels don't match `swap` tables, so shader recolouring misses them; keep variant sheets.
- **S4** fixed: `[godot] mipmaps = true` (PAGAN sets `mipmaps/generate` in each PNG's `.import`, only that
  line, survives rebuilds) and `filter = "linear"` (CanvasTexture `texture_filter` on the SpriteFrames).
  Verified in Godot 4.7.2. TileSets: set `texture_filter` on the TileMapLayer. Drop the game-side patch script.
- **S5** fixed: ellipse/ring exclude pixel centres exactly on the edge (`API_VERSION` 2). Regenerate: art
  using half-integer radii loses its nubs.
- **S6** fixed: `base_variant: cyan` -> manifest `base_variant` and `variants.cyan` = the base sheet/.tres
  with an empty swap. Remove the "cyan = base" special case.
- **S7** fixed: `pagan init --style flat` writes a flat STYLE.md (fill + rim, no outline/light, engine
  glow, supersample/filter settings). Skill §1 asks "Rendering style" with a recipe per style and says
  outline/light/ramps are pixel-art defaults.
- **S10** fixed via S3: supersampled assets' previews get an "as built" row (box-filtered, same on-screen
  size) and `built_1x.png`. With `supersample = 2`, author at 2x as now but drop the engine 0.5x downscale.
