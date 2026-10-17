"""The MCP server (`pagan mcp`), driven in-process by the SDK's client. Skipped without the "mcp" extra."""

from __future__ import annotations

import base64
import io
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import anyio
import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402
from mcp.types import CallToolResult, ImageContent, TextContent  # noqa: E402
from PIL import Image  # noqa: E402

from conftest import make_project  # noqa: E402
from pagan.cli import main  # noqa: E402
from pagan.mcp_server import create_server  # noqa: E402

SPRITE = """\
name: gem
size: [4, 4]
frames:
  a: |
    .12.
    1222
    1222
    .12.
"""


def run(root: Path, body: Callable[[Client], Awaitable[Any]], allow_godot: bool = False) -> Any:
    async def go() -> Any:
        async with Client(create_server(root, allow_godot)) as client:
            return await body(client)

    return anyio.run(go)


def call(root: Path, tool: str, args: dict[str, Any] | None = None, allow_godot: bool = False) -> CallToolResult:
    async def body(client: Client) -> CallToolResult:
        return await client.call_tool(tool, args or {})

    result: CallToolResult = run(root, body, allow_godot)
    return result


def data(result: CallToolResult) -> dict[str, Any]:
    """The JSON result (structured content, or the first text block)."""
    if isinstance(result.structured_content, dict) and "ok" in result.structured_content:
        return result.structured_content
    text = next(c for c in result.content if isinstance(c, TextContent)).text
    parsed: dict[str, Any] = json.loads(text)
    return parsed


def images(result: CallToolResult) -> list[Image.Image]:
    return [Image.open(io.BytesIO(base64.b64decode(c.data))) for c in result.content if isinstance(c, ImageContent)]


def cli_json(root: Path, *argv: str) -> dict[str, Any]:
    previous = os.getcwd()
    os.chdir(root)
    try:
        buffer = io.StringIO()
        from contextlib import redirect_stdout

        with redirect_stdout(buffer):
            main(["--json", *argv])
    finally:
        os.chdir(previous)
    parsed: dict[str, Any] = json.loads(buffer.getvalue())
    return parsed


@pytest.fixture
def root(tmp_path: Path) -> Path:
    make_project(tmp_path)
    (tmp_path / "BRIEF.md").write_text("# Art brief\n\n## Decisions and feedback log\n\n- 2026-01-01: start\n")
    (tmp_path / "STYLE.md").write_text("# Style bible\n")
    return tmp_path


def test_lists_tools_resources_prompts(root: Path) -> None:
    async def body(client: Client) -> tuple[set[str], set[str], set[str]]:
        tools = {t.name for t in (await client.list_tools()).tools}
        resources = {str(r.uri) for r in (await client.list_resources()).resources}
        prompts = {p.name for p in (await client.list_prompts()).prompts}
        return tools, resources, prompts

    tools, resources, prompts = run(root, body)
    assert {"status", "write_asset", "preview", "build", "palette_adjust", "manifest", "lint"} <= tools
    assert {"pagan://workflow", "pagan://reference", "pagan://brief"} <= resources
    assert prompts == {"setup_new_game", "make_asset", "change_the_look", "review_asset"}


def test_status_matches_cli(root: Path) -> None:
    (root / "sprites" / "gem.sprite.yaml").write_text(SPRITE)
    via_mcp = data(call(root, "status"))
    via_cli = cli_json(root, "status")
    assert via_mcp.keys() == via_cli.keys() and via_mcp["assets"] == via_cli["assets"]


def test_write_asset_lints_and_previews(root: Path) -> None:
    result = call(root, "write_asset", {"kind": "sprite", "name": "gem", "text": SPRITE})
    assert data(result)["ok"] and data(result)["errors"] == 0
    [picture] = images(result)
    assert picture.size == (4 * 16, 4 * 16)  # pagan preview's automatic scale
    broken = call(root, "write_asset", {"kind": "sprite", "name": "gem", "text": SPRITE.replace("1222\n    1222", "12\n    1222")})
    findings = data(broken)["findings"]
    assert not data(broken)["ok"] and findings[0]["rule"] == "E003" and not images(broken)
    assert (root / "sprites" / "gem.sprite.yaml").read_text().count("12\n") == 1  # written as given, for fixing


def test_scaffold_read_and_preview(root: Path) -> None:
    created = data(call(root, "scaffold", {"kind": "sprite", "name": "coin", "size": "8x8", "description": "a coin"}))
    assert created["ok"] and "size: [8, 8]" in created["text"]
    assert "a coin" in data(call(root, "read_asset", {"name": "coin"}))["text"]
    call(root, "write_asset", {"kind": "sprite", "name": "gem", "text": SPRITE})
    shown = call(root, "preview", {"asset": "gem"})
    assert data(shown)["ok"] and len(images(shown)) == 1
    assert data(call(root, "preview", {"asset": "gem", "which": "variants"}))["image_note"].startswith("no variants")


def test_errors_are_results(root: Path) -> None:
    missing = call(root, "read_asset", {"name": "nope"})
    assert not missing.is_error and data(missing)["findings"][0]["rule"] == "E000"
    bad = data(call(root, "config_set", {"key": "camera.elevation", "value": "5"}))
    assert not bad["ok"] and bad["findings"][0]["rule"] == "E001"
    assert data(call(root, "config_set", {"key": "camera.elevation", "value": "60"}))["new"] == 60


def test_paths_stay_inside_the_project(root: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    outside = tmp_path_factory.mktemp("outside") / "x.png"
    Image.new("RGBA", (2, 2)).save(outside)
    for path in (str(outside), "../" * 8 + str(outside).lstrip("/")):
        result = data(call(root, "import_png", {"path": path}))
        assert not result["ok"] and "outside" in result["findings"][0]["message"]
    (root / "link.png").symlink_to(outside)
    assert not data(call(root, "import_png", {"path": "link.png"}))["ok"]
    for name in ("../evil", "a/b", "UP"):
        assert not data(call(root, "write_asset", {"kind": "sprite", "name": name, "text": SPRITE}))["ok"]
        assert not data(call(root, "palette_write", {"name": name, "text": "x"}))["ok"]
    assert not list(root.parent.glob("evil*"))


def test_import_base64(root: Path) -> None:
    image = Image.new("RGBA", (2, 2), (255, 0, 0, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    result = data(call(root, "import_png", {"png_base64": base64.b64encode(buffer.getvalue()).decode(), "name": "dot"}))
    assert result["ok"] and (root / "sprites" / "dot.sprite.yaml").is_file()


def test_verify_godot_needs_permission(root: Path) -> None:
    refused = data(call(root, "build", {"verify_godot": True}))
    assert not refused["ok"] and "--allow-godot" in refused["findings"][0]["message"]


def test_build_and_manifest(root: Path) -> None:
    call(root, "write_asset", {"kind": "sprite", "name": "gem", "text": SPRITE})
    assert not data(call(root, "manifest"))["ok"]
    built = data(call(root, "build"))
    assert built["ok"] and built["assets"] == 1
    entry = data(call(root, "manifest", {"asset": "gem"}))
    assert entry["ok"] and entry["entry"]["frames"]["a"] == [0, 0, 4, 4]


def test_palettes(root: Path) -> None:
    listed = data(call(root, "palette_list"))
    assert listed["palettes"]["test"]["ramps"]["red"] == ["1", "2"]
    shown = call(root, "palette_show", {"name": "test"})
    assert data(shown)["ok"] and len(images(shown)) == 1
    dry = call(root, "palette_adjust", {"palette": "test", "lightness": -0.05})
    assert data(dry)["ok"] and data(dry)["written"] is False and not images(dry)
    done = call(root, "palette_adjust", {"palette": "test", "lightness": -0.05, "dry_run": False})
    assert data(done)["written"] is True and len(images(done)) == 1
    bad = data(call(root, "palette_write", {"name": "bad", "text": "name: bad\ncolors: 3\n"}))
    assert not bad["ok"] and bad["findings"]


def test_docs_and_feedback(root: Path) -> None:
    assert data(call(root, "log_feedback", {"note": "owner: darker"}))["ok"]
    docs = data(call(root, "read_docs"))
    assert "owner: darker" in docs["BRIEF.md"] and docs["STYLE.md"] == "# Style bible\n"

    async def body(client: Client) -> str:
        result = await client.read_resource("pagan://workflow")
        text: str = result.contents[0].text  # type: ignore[union-attr]
        return text

    workflow = run(root, body)
    assert workflow.startswith("# PAGAN") and "name: pagan" not in workflow


def test_cli_entry_without_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["--json", "mcp"]) == 1
    assert "pagan init" in capsys.readouterr().out
