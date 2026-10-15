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
