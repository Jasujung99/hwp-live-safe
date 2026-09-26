"""Launch the stdio server with the fake backend and exercise MCP discovery."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment["HWP_LIVE_BACKEND"] = "fake"
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONPATH"] = str(project_root / "src")
    with TemporaryDirectory(prefix="hwp-safe-smoke-") as profile_dir:
        environment["HWP_LIVE_SAFE_PROFILE_DIR"] = profile_dir
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "hwp_live.server"],
            env=environment,
            cwd=project_root,
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                initialized = await session.initialize()
                assert initialized.server_info.name == "hwp-live-safe"
                assert initialized.server_info.version == "0.3.0rc1"
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                expected = {
                    "hwp_status",
                    "hwp_start_new_document",
                    "hwp_read_context",
                    "hwp_preview_edits",
                    "hwp_apply_preview",
                    "hwp_undo_last",
                    "hwp_profile_list",
                    "hwp_preview_profile_insert",
                    "hwp_foreground_status",
                    "hwp_foreground_list_windows",
                    "hwp_foreground_select_window",
                    "hwp_foreground_preview_text",
                    "hwp_foreground_preview_profile_insert",
                    "hwp_foreground_apply_preview",
                    "hwp_foreground_disconnect",
                }
                assert names == expected, names
                result = await session.call_tool("hwp_status", {})
                assert not result.is_error
                assert result.structured_content is not None
                assert result.structured_content["ok"] is True
                profiles = await session.call_tool("hwp_profile_list", {})
                assert not profiles.is_error
                assert profiles.structured_content is not None
                assert profiles.structured_content["ok"] is True
                assert profiles.structured_content["profiles"]["profiles"] == []
                foreground = await session.call_tool("hwp_foreground_status", {})
                assert not foreground.is_error
                assert foreground.structured_content is not None
                assert foreground.structured_content["ok"] is True
                print(f"MCP smoke test passed ({len(names)} tools)")


if __name__ == "__main__":
    asyncio.run(main())
