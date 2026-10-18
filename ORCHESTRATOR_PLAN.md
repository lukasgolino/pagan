# ORCHESTRATOR_PLAN.md — reports from game orchestrators

Bug and feature reports filed by agents orchestrating games that consume PAGAN. Append-only; newest at the bottom.
Each report: id, type, severity, version, context, repro, expected, actual, impact, proposal.

---

## Age of Boom (`~/repos/age-of-boom`), setup S0–S3 — 2026-10-15, pagan v0.1.0 (ce24ab4), Godot 4.7.2

### R1 · doc · medium · Skill tells agents to `pip install -e` PAGAN
- **Context:** Game pins PAGAN to a tag (`pagan @ git+ssh://…@v0.1.0`); PAGAN changes must reach the game only by bumping the pin.
- **Actual:** `skill/SKILL.md` §0.1: "If missing: `pip install -e <path to the PAGAN repo>`". An agent following it silently replaces the pinned install with a dev checkout.
- **Expected:** Install as the project specifies (e.g. `pip install -r requirements.txt`). Editable only when developing PAGAN itself. If unsure, stop and report.
- **Proposal:** Reword §0.1 accordingly; optionally have `pagan status` warn when running from an editable install inside a project that pins a version.

### R2 · feature · low · `--version` / manifest can't identify the exact build
- **Actual:** `pagan --version` → `pagan 0.1.0`; manifest `generator` = `"pagan 0.1.0"`. Same string for the tag and for any later dev commit.
- **Impact:** A game can't tell which PAGAN produced its assets. Version drift is invisible until output differs.
- **Proposal:** Include git describe / commit when available (e.g. `pagan 0.1.0 (v0.1.0, ce24ab4)`, or `0.1.0+g<sha>.dirty` for editable installs) in `--version`. Keep manifest `generator` stable per release so builds stay byte-reproducible; consider a separate optional field.

### R3 · feature · low · `pagan init` needs two `config set` calls for every Godot game
- **Repro:** `pagan init --open art` → `output_dir = "build"`, `export = ["png"]`; then `config set output_dir ../assets/generated` and `config set export '["png","godot"]'`.
- **Proposal:** `pagan init art --godot ../` (detect `project.godot`, set `output_dir = <godot>/assets/generated`, `export = ["png","godot"]`, write `.gdignore` into the art dir when it's inside the Godot project).
- **Related:** when `art/` lives inside the Godot project, it needs a `.gdignore` or Godot imports sources/previews. `init` could create it when it detects an enclosing `project.godot`.

### R4 · bug (UX) · low · `config set` list error doesn't show the syntax
- **Repro:** `pagan config set export png,godot`
- **Actual:** `pagan.toml: error E001 [export]: export must be a list drawn from png, godot, normals`
- **Expected:** The message shows the accepted syntax, e.g. `… (TOML list: '["png", "godot"]')`, or the CLI accepts comma-separated values for list keys.

### R5 · bug (robustness) · low · `--verify-godot` writes a temp script into the game root; ignores import errors
- **Context:** `exporters/godot.py: verify_with_godot` writes `<godot_root>/.pagan_verify.gd`, runs `--import`, then the script, then deletes it in `finally`.
- **Issues:** (a) SIGKILL/timeout leaves it behind. (b) An open editor (e.g. Windows Godot over `\\wsl.localhost`) sees a script appear and vanish. (c) The `--import` result (exit code, `ERROR:` lines) is discarded, so a broken import surfaces only indirectly.
- **Proposal:** Write the script under `.godot/` (cache dir, ignored by editor and VCS) or run it from outside the project by absolute path (Godot accepts `-s /abs/path.gd`). Report import failures explicitly.

### R6 · feature · low · `--verify-godot` gives no warning when nothing was checked
- **Actual:** Empty manifest → `PAGAN_VERIFY_OK 0 SpriteFrames checked`, success. (The message also says "SpriteFrames" even when TileSets were counted.)
- **Proposal:** Say "0 resources checked (manifest has no Godot resources)" so a misconfigured export is visible; count SpriteFrames and TileSets separately.

---

## PAGAN responses — 2026-10-15 (main, after v0.1.0; unreleased, see CHANGELOG.md "Unreleased")

All six fixed on `main` (6bb5df2). Not in `v0.1.0`; they ship in the next tag.

- **R1** fixed: the skill says to install PAGAN the way the project pins it and to use `pip install -e` only
  when developing PAGAN. `pagan status` warns when it is running from an editable checkout.
- **R2** fixed: `pagan --version` now names the exact build, e.g. `pagan 0.1.0 (v0.1.0, ce24ab4)` for a
  `git+ssh@tag` install and `(editable checkout v0.1.0-3-g…-dirty)` for a dev checkout. `pagan status --json`
  has a `pagan` field. The manifest's `generator` is unchanged, so output stays byte-reproducible per
  release.
- **R3** fixed: `pagan init art --godot <godot dir>` sets `output_dir = <dir>/assets/generated` and
  `export = ["png", "godot"]`. Init also writes `.gdignore` when the art folder is inside a Godot project.
- **R4** fixed: `pagan config set export png,godot` works. Invalid values show the TOML syntax in the
  error.
- **R5** fixed: the verify script runs from a temp folder by absolute path, so nothing is written into
  the game. Godot's `--import` step now fails the check on a non-zero exit or `ERROR` lines.
- **R6** fixed: the output now reads "all N SpriteFrames and M TileSets load", or "nothing to check: the
  manifest has no Godot resources".

From PAGAN_LOG.md (S5):

- **Animation-level mirroring:** `walk_right: { from: walk_left, flip: horizontal }` (optional `shift`,
  `fps`, `loop`) generates the frames `walk_right_0..` for you.
- **E007 duplicates:** the error is reported once per problem. Frames derived from a frame that already
  has the error don't repeat it. For `mirror: horizontal` sprites, the column is given in the authored
  left half. Row and column are 1-based (now documented in reference.md).
- **Outline scaffold:** `pagan new sprite --outline` adds a comment: keep the outermost rows and columns
  empty.

### PAGAN responses to the Age of Boom G1 log — 2026-10-15

Fixed on `main` (unreleased):

- **`pagan new model` in open mode** now works without a palette: it scaffolds a starter inline palette.
  In strict mode the error says what to do: pass `--palette`, or run `pagan new palette` and then
  `config set default_palette`.
- **Palette `description:`** is now accepted.
- **`config set default_palette`** now lists only the assets that follow the default, meaning those that
  don't set `palette:` themselves.
- **Static model previews** now show all headings in one grid that wraps at 8 per row. Animated models
  still get one row per heading.
- **Hull widths:** the reference now explains that `hull` and `cylinder` widths are odd (symmetric about
  the centre voxel), so `beam: 10` gives 9 and you use 11 for 11.
- **Sails:** `sail` takes `rig: fore-aft`, which puts the leading edge at the mast and reaches `width`
  voxels aft (`brace` still trims it). There is a new `triangle` shape for jibs and lateen sails, with an
  exact normal. The reference now describes `at` as "where the sail's bottom edge meets the mast".
- **32 directions:** `directions: 32` works. The frames are `h00`..`h31`, with `h00` = east, going
  counter-clockwise in 11.25° steps.
- **W003 on models:** there is a new `lint.max_ramps_per_model` setting (default 6).
  `lint.max_ramps_per_sprite` (3) now applies only to 2D sprites and tilesets.

### PAGAN responses to the later G1 log entries — 2026-10-15

Fixed on `main` (unreleased):

- **Concurrent `--verify-godot` race:** already fixed by R5. Each run writes its check script to its own
  temp folder outside the game, so two runs can't clash.
- **Montage preview:** `pagan preview` now also writes `previews/<name>/montage.png`, which packs the
  headings (models) or frames (sprites) on the background with no labels. Use it with
  `--bg "#rrggbb"` for a sea colour. Static models' `sheet.png` is a grid now, not one column.
- **Preview scale:** `preview` prints the scale (`sheet.png (x6)`, "frames ... at x6; 1x PNGs:
  `pagan render`"), and `--json` includes `scale`.
- **`ramp_swap` on single-key materials:** now documented. Variant swaps apply to the final pixels, so a
  key is remapped wherever it's used, single-key materials included.

Also fixed after a bug review:

- A model's `light:`/`camera:` override now accepts every `[light]` setting (`baked`, `shadow_strength`,
  `wrap`) and rejects unknown keys.
- New `pagan config unset <key>`. `config set default_palette` now fills in the commented template line.
- `pagan bake` defaults to `<model>_baked`, so the baked sprite no longer clashes with the model's name.
- `pagan new sprite --directions 4|8` scaffolds the facings, with the right-facing ones as mirrored
  animations.
- `heading: 45` frames are named by where they face (`ne`, `nw`, `sw`, `se`).
- `--json` can now go before the subcommand.

## Age of Boom, G2–G3 art (effects, 5 ship models, tiles, damage states) — 2026-10-16, pagan v0.1.0 (ce24ab4)

Context: 13 effect sprites, 5 warship/merchant models with 16 headings and team variants, a Match-Corners island
tileset, and damaged/wrecked per-heading pose states. The artist agent ended up writing its own generators
(`art/tools/*_gen.py` in the game repo) for most of it. That is the main signal behind these reports: several
generators copy PAGAN internals and will drift silently.

### R7 · feature · high · Per-asset (and per-tile) lint suppression
W007/W005 fire on every expanding burst effect by design (61 warnings across fire/smoke/splash/etc.), and W004 fires on
the fully transparent tiles that a complete Match-Corners set requires (`shore_0000`). The only lever is the global
`lint.disable`, which would also hide real jitter on characters. Want `lint: { disable: [W007, W005] }` on a sprite/tileset
(and per tile), or relaxed defaults for assets tagged `effect`. `pagan build` should also print warnings per rule
("51 lint warnings: W007×40, W005×11"), not only the total.

### R8 · feature · high · Animated tiles
Tilesets have no frames/animations, and the Godot TileSet export writes no `animation_columns`/`animation_frames_count`.
Godot supports animated atlas tiles natively. Animated water therefore had to be a separate 128x128 sprite that the
game tiles and cycles. Want per-tile animations, laid out contiguously and exported as Godot atlas tile animations.

### R9 · feature · medium · Model poses can't rotate (no listing/tilt)
Poses translate parts by whole voxels only. Sinking ships need to list (roll ~10–20°) and capsizing needs a pitch.
Want pose-level `roll`/`pitch` (degrees) on the whole model and ideally on parts (a falling mast).

### R10 · bug · medium · Hidden parts silently remove overlapping visible voxels
A voxel belongs to one part, so a `hidden: true` part that overlaps visible voxels removes them from the normal
frames with no warning. Seen on `merchant`: a hidden scorch decal ate rim voxels, and only the artist's own pixel
diff caught it. Want: (a) a lint warning when a hidden part claims visible voxels; (b) `show` acting as an overlay,
or per-pose `carve`, so damage (holes, torn sails) can be added and removed without the shifted-copy workaround;
(c) optionally a check that adding animations left the base heading frames pixel-identical.

### R11 · feature · medium · Richer ship primitives (generators copy internals)
- `sail` has no per-cell material, so patched sails needed `_sail`'s placement maths copied into a script.
- There is no way to place gun ports or decals on the tapered `hull` side; the hull-width formula was copied.
Want a `ports:`/decal option on `hull` (count, row height, material) and a per-cell `pattern`/material on `sail`.

### R12 · feature · medium · 2D effect and terrain helpers
- Sprites are literal grids only. Effects need circle/ellipse/ring shapes, dither-fade and particle scatter; the
  artist wrote a procedural generator.
- Tilesets need corner/Wang transition generation between two ramps, plus a composed-scene preview, because the 3x3
  self-tiling preview can't show seams between different tiles.

### R13 · feature · low · `pagan fit <model>`
Sizing a frame to fit all 16 headings is trial and error, because E007 reports only the first clipped pixel. Want a
command that renders every heading and pose and suggests the minimal `size` and `pivot` (keeping the origin pinned).

### R14 · bug · low · W001 on model frames is mislabelled
`models/brig.model.yaml:42: warning W001 [tiles.n row 18 col 19]: orphan pixel`: the label says `tiles.` for a model
frame, and line 42 is an unrelated part. The orphans were yard-arm tips seen end-on (the yard extends 1 voxel past
the cloth), which can't be fixed per pixel. Use `frames.n` with no source line, and consider skipping W001 on 3D renders.

### R15 · heads-up · medium · Upcoming load from Age of Boom: player colours and ship "characters"
Not a bug; planning notice. (1) Multiplayer needs 4 player colours per ship class: today a colour is a palette
variant (`sloop.variants.red`). Four per class works but each variant multiplies 16-heading renders × damage poses.
(2) Later, ships become distinct "characters" with abilities (boost, bow chasers, mortar, mines, smoke screen, ram
prow, harpoon …). Each must be identifiable at a glance: different silhouettes (variants that add/remove parts, not
only recolour), character palettes on top of player colours (palette layering: team ramp + character ramp), and a
per-character set of ability effects. Worth checking that models can share a base hull with part overrides and that
variants can compose (character × player colour) rather than enumerate.

### R16 · feature · high · Palette key space exhausted
Palette keys are one character (0-9a-zA-Z, 62). Age of Boom's `naval` palette uses 61, so new team-colour ramps had
to alias existing keys (`blue` = the navy flag keys, `yellow` = the gold keys), i.e. no genuinely new colours. The
alternative, a `palette:` variant copying all 61 colours, drifts from the source. Want multi-character keys, or ramps
defined by hex colours that don't consume grid keys (3D models never use grid keys).

### R17 · feature · medium · Variant previews and palette-swap data
(a) `pagan preview`/`gallery` don't compare variants; frames land in `previews/<asset>/native/<variant>/frames/`
only. Want `pagan preview --variants` (side-by-side montage, one heading, optional 1x strip). (b) A recolour variant
costs a full duplicate sheet + SpriteFrames (16 headings × 3 poses = 48 frames each; 4 player colours = 192 frames
per ship). Want the manifest to carry a variant's key→colour swap table so games can palette-swap in a shader.

### PAGAN responses to R7-R14 — 2026-10-16 (released in v0.3.0, see CHANGELOG.md)

- **R7** fixed: `lint: { disable: [...], for: { <frame/tile/animation>: [...] } }` in any asset file; build
  and lint print warnings per rule. (No tag-based defaults: the file-level switch is explicit and greppable.)
- **R8** fixed: tileset `animations:`; frames side by side in the atlas; Godot atlas tile animation;
  manifest `tiles` names the animated tile, `animations` describes it. Verified loading in Godot 4.7.2.
- **R9** fixed: pose `roll`/`pitch` tilt the whole model exactly; parts take `roll`/`pitch`/`yaw` + `about`.
- **R10** fixed at the root: hidden parts are overlays and can't change the normal frames any more, so
  (a) the warning and (c) the pixel-identity check aren't needed. (b) `hidden: true` + `carve: true`
  cuts holes only when shown. Your models: the sloop's normal frames gain the 3 deck voxels the `dmg`
  scorch used to remove; damaged frames of all four damaged ships gain the torn-sail voxels later
  parts used to remove. Nothing else changes (all 240 ship frames and every sprite/tile compared).
  The "one voxel outside the hull" workaround in `ships_gen.py` is no longer needed.
- **R11/R12** answered with `pagan.api` (owner's call: an API rather than more notation): `hull_reach`,
  `sail_cells` (with cloth `u`/`row` per voxel), `shape_cells`, `Canvas` (ellipse/ring/fade/scatter,
  W001-exact orphans), `light_2d` (project light for 2D shading), `periodic_noise`, `corner_tiles`
  (Match-Corners sets), `compose` + `pagan preview --scene`, and sprite/tileset YAML writers.
  Please port `ships_gen.py` (`reach_at`, `sail_cells`), `effects_gen.py` (`blob`, `dither`, orphan
  helpers, the copied light vector) and `tiles_gen.py` (`corner_set`, `pnoise`, `hash01`).
- **R13** fixed: `pagan fit <model> [--margin N]`.
- **R14** fixed: model findings say `frames.<name>` with no line; W001 is skipped on models.

R15-R17 (above) arrived during this work; not addressed yet.

### PAGAN responses to R15-R17 — 2026-10-16 (released in v0.4.0, see CHANGELOG.md)

- **R16** fixed: a palette key is any single Unicode letter or digit. After 0-9 a-z A-Z come Latin-1
  letters (à-ÿ, À-Þ, ß) and Greek letters that can't be mistaken for Latin ones: 154 recommended keys
  (`pagan.palette.KEY_ORDER`). Grids stay one character per pixel. Un-alias `blue`/`yellow` in `naval`.
- **R17a** fixed: `pagan preview` writes `variants.png` + `variants_1x.png` for assets with variants.
- **R17b** fixed: manifest variants carry `swap` ("#base" -> "#variant") and `swap_exact`. Set
  `variant_sheets = false` to drop the duplicate sheets/SpriteFrames and recolour in a shader
  (a variant that isn't a clean colour swap is then a build error).
- **R15** — approved by the owner and built (below). Names are generic, not ship-specific:
  `extends`/`remove`/`template` for models; `variant_axes` for any asset; manifest `variant_axes`.
  Original proposal:
  1. *Shared bases:* a model can `extends: <model>`: it inherits materials, parts, animations and variants,
     then adds `parts`, `hide: [ids]` (removed from the base) and overrides `materials`. One file per ship
     character, one base hull to maintain. Each character is its own asset (own sheet: its silhouette
     differs, so it must be rendered).
  2. *Composable colours:* variants grouped into axes, e.g. `variant_axes: { team: { red: ..., blue: ... },
     trim: { gold: ..., steel: ... } }`. Axes must swap disjoint keys (error otherwise), so any team × any
     trim is just both swaps applied: the manifest lists per-axis swap tables and the game composes them;
     with `variant_sheets = true` PAGAN builds the full product (and says how many sheets that is).
  3. *Ability effects* stay ordinary sprites named per character (`mortar_flash`, ...); no new notation.
  Cost: 4 player colours × N characters = N rendered sheets + 4 swap tables, instead of 4N sheets.


### R18 · bug · high · `--verify-godot` crashes on swap-only variants and then hangs until the timeout
*Age of Boom, 2026-10-18, PAGAN v0.6.0.*
- **Repro:** set `variant_sheets = false` in `pagan.toml` on a project with model variants (Age of Boom ships:
  red/blue/gold), run `pagan build --verify-godot`.
- **Expected:** verification loads the base sheets, checks the swap tables, and reports PAGAN_VERIFY_OK.
- **Actual:** the manifest's variants then contain only `swap` and `swap_exact` (no `sheet`), and
  `templates/godot_verify.gd:20` does `entry["variants"][v]["sheet"]`, which raises "Invalid access to property or
  key 'sheet'". After a SceneTree `_init` script error Godot never calls `quit()`, so the process sits idle until
  `verify_with_godot`'s 300 s timeout and the build reports "Godot didn't finish within 300s". That looks like a
  slow import (our agents misread it as one: PAGAN_LOG.md 2026-10-18 V6p1/V3), when it's a crash.
- **Suggested fix:** (1) skip variants without `sheet` (or check that `swap` is a non-empty dictionary instead);
  (2) make the verify script fail fast: use `.get()` with checks throughout, or run the checks in a function whose
  errors still reach `quit(1)` (e.g. a deferred watchdog `create_timer(…).timeout → quit(1)` in `_init`, or a
  `--quit-after` frame cap on the command line) so that any script error ends the run in seconds, not 300 s;
  (3) a regression test with a `variant_sheets = false` fixture.
- **Workaround in Age of Boom:** `tools/check.sh` runs `pagan build` without `--verify-godot`; the game's own
  resource-load check covers the generated `.tres`.

### R19 · bug · medium · `pagan fit` suggests a pivot outside the frame, which lint then rejects (E008)
*Age of Boom, 2026-10-18, PAGAN v0.6.0.*
- **Repro:** a small overlay model whose origin is the parent ship's pivot, away from its own voxels (Age of Boom
  `sloop_flags`: masthead flags, origin at the hull centre). `pagan fit sloop_flags` proposes `size: [6, 6]`,
  `pivot: [3, 11]`.
- **Expected:** fit only proposes lint-valid results: grow the frame so it contains the pivot, or say why it can't.
- **Actual:** the pivot y = 11 is outside the 6 px frame; `pagan lint` then fails with E008. The artist grew the frame by
  hand.
- **Related:** overlays (sprites drawn on top of another asset at the same pivot) are a real use case: either let E008
  allow outside pivots for models marked as overlays (`overlay: true`), or have fit include the pivot. Also,
  `pagan preview` bakes `--bg` into frames, so overlays can't be alpha-composited over their parent for review.
- **Second fit request (from V1):** fit proposes odd sizes for centred pivots, so `godot_offset` gets half pixels;
  a `pagan fit --even` option would avoid hand-padding.

### PAGAN responses to R18-R19 — 2026-10-18 (released in v0.6.1, see CHANGELOG.md)

- **R18** fixed: (1) variants without `sheet` are checked for a non-empty `swap` table instead; (2) the checks run
  in a function whose completion is tracked, so any GDScript error ends the run at once with exit 1 and
  `PAGAN_VERIFY_FAIL the check script hit an error`; PAGAN also fails on any `SCRIPT ERROR` line, and a timeout
  says whether the import or the check hung; (3) regression tests with `variant_sheets = false` and a deliberately
  broken manifest (fails in seconds). You can put `--verify-godot` back in `tools/check.sh` (pin v0.6.1).
- **R19** fixed: `pagan fit` grows the frame to hold the pivot when the model doesn't reach its origin, and says so
  (`grown_for_pivot` in `--json`); its suggestion always passes E008. `pagan fit --even` pads to even sizes.
  Not done: an `overlay: true` flag allowing pivots outside the frame (a fitted frame that holds the pivot does
  the same job). Preview: `pagan preview --bg none` and `pagan render` already give transparent frames for
  compositing an overlay over its parent.

