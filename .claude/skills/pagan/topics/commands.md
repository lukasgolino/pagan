# Commands

Every command and its flags.

## Commands (all accept `--json`; non-zero exit on errors)

Slow steps (a model render that isn't cached yet, Godot) print `pagan: ...` progress lines on stderr
(`--quiet` or `PAGAN_QUIET=1` turns them off; stdout and `--json` are unaffected). Models render in
several processes (`PAGAN_JOBS=N`, default: the CPU count up to 8, and at most one per GiB of available memory; `1` = one process);
output is identical.
Renders are cached in `<project>/.pagan-cache/`; `PAGAN_CACHE_DIR=/path` shares one cache between several
checkouts of the same art (e.g. agents' git worktrees), so a fresh checkout doesn't re-render every model.
Big sprites and tilesets (a megapixel or more of source pixels) are cached there too: the parsed frames, their
lint findings and built sheets, keyed by the file, its PNG, every palette, pagan.toml and PAGAN's own code, so a
cache hit is always what a fresh run gives. Two or more uncached big ones are parsed, linted and rendered in
parallel (`PAGAN_JOBS`); output is identical.

| Command | Purpose |
|---|---|
| `pagan init [dir] [--open] [--godot DIR] [--perspective top-down\|top-down-3/4\|side\|iso] [--style pixel\|flat]` | create a project; perspective sets `[camera] elevation` (90/42/15/30) and BRIEF.md; `--style flat` = STYLE.md for flat / vector-like arcade art |
| `pagan new palette <name>` | starter palette |
| `pagan new sprite <name> [--size 16x16] [--frames N] [--directions 1\|4\|8] [--mirror] [--outline] [--palette P] [--description D]` | blank sprite; `--directions 4` scaffolds down/up/left frames + a mirrored right animation |
| `pagan new tiles <name> [--size] [--frames N]` | blank tileset |
| `pagan new model <name> [--size 64x64] [--directions 8]` | starter model (`--directions 0`: a mesh-only model for 3D games) |
| `pagan lint [paths] [--warnings-as-errors]` | errors + style warnings |
| `pagan preview <model> --orbit \| --closeup PART \| --engine [--all-previews]` | 3D review: orbit.png (8 headings x elevations -30, 0, 30, 60, 90: undersides too), closeup_<PART>.png (one part filling the view, in place and alone), engine.png (the built .tscn through Godot: renders offscreen, needs Xvfb); only these unless `--all-previews` |
| `pagan preview <asset...> [--scale N] [--grid] [--bg checker\|none\|#rrggbb] [--scene FILE] [--frame NAME] [--variants options\|all]` | sheet.png (labelled; over 4096 px on a side it's split into pages: sheet.png = overview (headings or frames outside animations, variants, as-built/tiling rows, an index of pages) + one page per animation, `sheet.<animation>.png` (models: per pose, every heading), each wrapped to 4096 px wide and continued in `sheet.<animation>.2.png`, `.3`, ... (the overview in `sheet.2.png`) when taller; the `--json` result lists them in `sheet_pages`), montage.png (frames/headings packed on the background, e.g. `--bg "#1d3b53"` sea), frames/ and GIFs, all at the printed scale, plus native/ (1x frames and sheet, as `pagan render`); variants.png + variants_1x.png (base and every variant side by side: the first frame with pixels, or `--frame`) when the asset has variants (with `variant_axes`: each axis option on its own, named `<axis>.<option>`; `--variants all` = every combination); `--scene` (tilesets): scene.png from a layout file (rows of tile names, `.` = empty) and scene_variants.png; supersampled assets also get an "as built" row and built_1x.png (what the game gets) |
| `pagan preview scenes/<name>.timeline.yaml [--at 0.5,2.0] [--scale N] [--grid] [--bg ...]` | timeline: `previews/<name>.timeline/` frames/f0000.png..., timeline.gif, and with `--at` at.png (a contact sheet of those times) |
| `pagan gallery` | every asset in one image |
| `pagan render <asset...>` | native-size PNGs |
| `pagan palette show [palettes]` | swatches |
| `pagan palette adjust <pal> [--lightness d] [--contrast k] [--saturation k] [--hue deg] [--warmth d] [--ramp r] [--keys ...] [--out new] [--dry-run]` | change the look globally |
| `pagan import <png> [--palette P \| --open] [--scale N] [--name] [--out]` | PNG -> sprite (snaps colors, report) |
| `pagan bake <model> [--name]` | model -> editable sprite (default name `<model>_baked`) |
| `pagan fit <model> [--margin N] [--even] [--write]` | smallest size + pivot that fit every heading and pose |
| `pagan status` | catalogue + what needs attention |
| `pagan config show` / `get <key>` / `set <key> <value>` / `unset <key>` | project settings: value, default, meaning; validated edits; unset = back to default |
| `pagan mark <asset...> [--status approved] [--current] [--outdated]` | record reviews |
| `pagan style bump "note"` | new style version; flags older assets (W006) |
| `pagan build [--verify-godot] [--godot-timeout S]` | final assets + manifest (+ Godot .tres); each Godot step may take S seconds (default 600) |
| `pagan docs [topic...] [--search words]` | these docs: list the topics, print one, or find the paragraphs you need |
| `pagan skill install [dir]` | install this skill into a repo's `.claude/skills/` |
| `pagan mcp [--project DIR] [--allow-godot]` | MCP server over stdio (`uvx pagan-gen mcp` without an install) |

**MCP tools** (same JSON as the commands above): `status`, `docs` (these topics), `read_docs`, `write_doc`, `log_feedback`,
`config_show`/`config_set`/`config_unset`, `palette_list`, `palette_show` (image), `palette_write`,
`palette_adjust` (dry run by default; image), `scaffold`, `read_asset`, `write_asset` (writes + lints +
preview image), `lint`, `preview` (image: sheet, montage, variants, built, orbit, closeup with `part`, or engine; `page: <animation>` = that page of a split sheet), `gallery` (image), `fit` (`write: true` edits the model's size and pivot),
`mark`, `style_bump`, `import_png` (path or base64), `build` (`verify_godot` needs `--allow-godot`),
`manifest`. Resources: `pagan://workflow`, `pagan://docs/{topic}`, `pagan://brief`, `pagan://style`,
`pagan://manifest`, `pagan://palette/{name}`, `pagan://asset/{name}`. Prompts: `setup_new_game`,
`make_asset`, `change_the_look`, `review_asset`. Errors come back as results (`ok: false` + `findings`).
