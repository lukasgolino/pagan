# MCP_PLAN.md — a PAGAN MCP server

Brief for the agent building PAGAN's MCP server. Read [CLAUDE.md](CLAUDE.md) (conventions, versioning,
decisions log), then `src/pagan/skill/SKILL.md` and `reference.md`: the server exposes that workflow
to agents that don't have the Claude skill.

## Goal

Any MCP client (Claude Code, Claude Desktop, Cursor, an orchestrator agent built on the Agent SDK)
can make, check, preview and build PAGAN art without shelling out to the CLI. The skill stays the
recommended path for Claude Code. The MCP server is the same capability for every other client, and a
stronger contract for orchestrators: typed tools, structured JSON results, and images the model can see.

Non-goals: no image generation, no hosted service, no new notation. Every tool is a thin layer over
code that already exists (`cli.py` handlers, `build.py`, `lint.py`, `preview.py`, `manage.py`,
`settings.py`, `api.py`). If a tool needs logic the CLI doesn't have, add it to the library first,
with tests, then expose it in both places.

## Shape

- **Package:** `src/pagan/mcp_server.py` (one module; split only if it passes ~600 lines).
- **Dependency:** the official Python SDK (`mcp`, FastMCP API) as an **optional extra**:
  `pip install "pagan[mcp]"`. The core install stays Pillow + PyYAML + numpy. Log the dependency in
  CLAUDE.md's decisions log. The owner must approve it; it is genuinely needed.
- **Entry point:** `pagan mcp [--project DIR] [--allow-godot]` runs a stdio server. Streamable HTTP
  comes later, only if someone asks.
- **Project scope:** the server is bound to one PAGAN project, given by `--project` (default: the
  nearest `pagan.toml` from the cwd). No tool reads or writes outside that project's root, its
  `output_dir` and its `preview_dir`.
- **Install line for the docs:**
  `claude mcp add pagan -- uvx --from "pagan[mcp] @ git+https://github.com/lukasgolino/pagan@v0.6.0" pagan mcp --project ./art`

## Tools

Every tool returns the same JSON its CLI command prints with `--json` (same keys, so one contract).
Errors are not exceptions. They are results with `ok: false` and `findings` (rule id, file, line,
`where`, message), because an agent fixes them the same way it fixes lint output.

| Tool | Wraps | Notes |
|---|---|---|
| `status` | `pagan status --json` | Catalogue, style version, what needs attention. Recommend calling it first. |
| `read_brief` | BRIEF.md + STYLE.md | Text; also exposed as resources (below). |
| `update_brief` | — | Append a dated line to BRIEF.md's feedback log, or replace a section. Text edits only. |
| `config_show` / `config_set` / `config_unset` | `settings.py` | Validated; returns what refreshes. |
| `palette_list` / `palette_show` | `swatch.py` | `palette_show` returns the swatch PNG as image content. |
| `palette_write` | — | Write `palettes/<name>.pal.yaml` from text, then validate. Returns findings. |
| `palette_adjust` | `cmd_palette_adjust` | Defaults to `dry_run: true`; returns the before/after swatch image. |
| `scaffold` | `pagan new sprite\|tiles\|model` | Returns the new file's text. |
| `read_asset` | — | Source text of an asset by name. |
| `write_asset` | — | Write a sprite/tileset/model source by name and kind, then **lint it in the same call**. Returns findings plus a small preview image when it parses. This is the main loop tool. |
| `lint` | `lint_paths` | Whole project or named assets. |
| `preview` | `write_previews` | Returns the contact sheet as image content (downscaled to ≤1568px on the long side), plus the paths of the GIFs, montage, variants and built_1x. Option `which`: sheet, montage, variants, built. |
| `gallery` | `gallery` | Image content. |
| `fit` | `fit_model` | |
| `mark` / `style_bump` | `manage.py` | |
| `import_png` | `importer.py` | Path must be inside the project, or the image is passed as base64. |
| `build` | `build()` | `verify_godot` only when the server was started with `--allow-godot` (it runs a binary). |
| `manifest` | `manifest.json` | Optional asset filter. Orchestrators read frame rects, pivots, animations and swap tables here. |

Write tools say `destructiveHint` / `idempotentHint` in their annotations; read tools say `readOnlyHint`.

## Resources and prompts

- **Resources:** `pagan://reference` (reference.md), `pagan://workflow` (SKILL.md without the
  frontmatter), `pagan://brief`, `pagan://style`, `pagan://manifest`, `pagan://palette/{name}`,
  `pagan://asset/{name}` (source text).
- **Prompts** (the skill's sections as MCP prompts, for clients without skills): `setup_new_game`,
  `make_asset`, `change_the_look`, `review_asset`. Each one tells the model to read BRIEF/STYLE, use
  `write_asset` → `lint` → `preview`, and **look at the image before reporting**.
- **Server instructions** (the `instructions` field): five lines pointing at `pagan://workflow` and
  saying "call `status` first, never invent colours, always preview before reporting".

## Safety and limits

- Resolve every path and reject anything outside the project/output/preview dirs (including symlinks).
  Test this with `../`, absolute paths and symlinks.
- Asset and palette names must match `NAME_RE`. Source writes go only to `palettes/`, `sprites/`,
  `tiles/` and `models/` with the right suffix, plus BRIEF.md and STYLE.md.
- Cap source text at 2 MB and images returned to the model at ~1 MB. Above the cap, return the path
  instead.
- No tool runs arbitrary code. Generator scripts (`pagan.api`) stay outside the MCP: the agent runs them
  itself if its client allows that.
- Stdout belongs to the protocol. Make sure nothing in the code paths the server uses prints (the CLI
  handlers print). Call the library functions, not the `cmd_*` handlers, or capture their output.

## Tests (`tests/test_mcp.py`)

- Use an in-process client session from the SDK against a temp project (conftest `make_project`), so
  no subprocess is needed.
- For every tool: one happy path, one error path (findings shape), and the JSON keys equal the CLI's
  `--json` output.
- Path-escape tests, a name-validation test, and a test that `verify_godot` is refused without
  `--allow-godot`.
- An image-content test: `preview` returns a valid PNG under the cap.
- `pytest` skips this file when the `mcp` extra isn't installed. CI installs `.[dev,mcp]`.
- mypy strict passes. The SDK is typed; add an override only if needed.

## Docs and release

- README: an "Use from any agent (MCP)" section with the install line and three example requests.
- reference.md: a tools table. SKILL.md: one line saying "if PAGAN tools (MCP) are available, prefer
  them over the CLI; same workflow".
- Tool names and schemas are a public contract: changing them means a version bump (add this to
  CHANGELOG's list). Release as **0.6.0**. Ask the owner before tagging.
- Optional, after release: list on the MCP registries (registry.modelcontextprotocol.io, glama,
  mcp.so). Ask first: that publishes.

## Milestones

1. The extra, `pagan mcp` and the server skeleton: `status`, `lint`, `config_show`, with tests and CI.
2. The authoring loop: `scaffold`, `read_asset`, `write_asset`, `preview` with image content. Then
   end-to-end in Claude Code: "make a 16x16 potion" works with only the MCP (skill uninstalled).
3. Everything else in the tools table, plus resources and prompts.
4. Hardening: the path tests, caps, the stdout audit, and a run of each prompt in Claude Desktop.
5. Docs, CHANGELOG, version bump; then the owner approves the tag.

## Open questions (defaults in bold)

1. Transport: **stdio only** / also HTTP.
2. Should `write_asset` also build? **No** (build stays explicit: it writes into the game).
3. Return preview images inline by default: **yes**, with `inline: false` to get paths only.
4. One server per project (**yes**), or a `project` argument on every tool.

## Status — 2026-10-17 (v0.6.0)

Built: `src/pagan/mcp_server.py`, `pagan mcp`, extra `pagan[mcp]` (SDK `mcp` 2.x: `MCPServer`), 23 tools,
7 resources, 4 prompts, `tests/test_mcp.py` (in-process client), docs, CHANGELOG. Checked over real stdio
against `examples/demo`. Tools run the CLI handlers with `--json` rather than separate library calls, so
the JSON is identical by construction. Tool renames vs. the table above: `read_brief` -> `read_docs`,
`update_brief` -> `write_doc` + `log_feedback`.

Not done yet:
- A live run in Claude Code/Desktop with the skill uninstalled ("make a 16x16 potion").
- Listing on MCP registries (publishing: ask the owner).
