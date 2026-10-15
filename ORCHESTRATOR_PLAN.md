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
