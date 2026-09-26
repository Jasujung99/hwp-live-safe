"""Optional real Hancom MCP smoke test on a disposable unsaved document."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult


def payload(result: CallToolResult) -> dict[str, Any]:
    assert not result.is_error, result
    assert result.structured_content is not None, result
    return dict(result.structured_content)


async def main() -> None:
    with TemporaryDirectory(prefix="hwp-safe-native-smoke-") as profile_dir:
        await run_smoke(profile_dir)


async def run_smoke(profile_dir: str) -> None:
    project_root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONPATH"] = str(project_root / "src")
    environment["HWP_LIVE_SAFE_PROFILE_DIR"] = profile_dir
    environment["HWP_LIVE_BACKEND"] = "powershell-com"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "hwp_live.server"],
        env=environment,
        cwd=project_root,
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            started = payload(await session.call_tool("hwp_start_new_document", {}))
            document = started["document"]
            assert document["unsaved"] is True and document["context_verified"] is True
            print(f"Owned disposable document ID: {document['document_id']}")
            print("This smoke test leaves its new unsaved window open; do not close another Hancom window.")
            readback = payload(await session.call_tool("hwp_read_context", {}))["document"]
            assert readback["document_id"] == document["document_id"]
            assert readback["context_verified"] is True
            document = readback
            previewed = payload(
                await session.call_tool(
                    "hwp_preview_edits",
                    {
                        "edits": [
                            {
                                "kind": "insert_text",
                                "text": "HWP Live MCP integration test",
                                "new_paragraph_after": False,
                                "style": {
                                    "font_size_pt": 14,
                                    "bold": True,
                                    "align": "center",
                                },
                            }
                        ],
                        "expected_revision": document["revision"],
                    },
                )
            )
            receipt = payload(
                await session.call_tool(
                    "hwp_apply_preview",
                    {"plan_id": previewed["preview"]["plan_id"]},
                )
            )
            verified = payload(await session.call_tool("hwp_read_context", {}))
            assert "HWP Live MCP integration test" in verified["document"]["text"]
            undone = payload(
                await session.call_tool(
                    "hwp_undo_last",
                    {"expected_revision": receipt["receipt"]["revision"]},
                )
            )
            assert "HWP Live MCP integration test" not in undone["document"]["text"]
            table_preview = payload(
                await session.call_tool(
                    "hwp_preview_edits",
                    {
                        "edits": [
                            {
                                "kind": "insert_table",
                                "rows": 2,
                                "cols": 2,
                                "cells": [
                                    ["Field", "Value"],
                                    ["Name", "Example"],
                                ],
                                "table_style": {
                                    "first_row_is_header": False,
                                    "header_bold": False,
                                },
                            }
                        ],
                        "expected_revision": undone["document"]["revision"],
                    },
                )
            )
            table_receipt = payload(
                await session.call_tool(
                    "hwp_apply_preview",
                    {"plan_id": table_preview["preview"]["plan_id"]},
                )
            )
            table_readback = payload(await session.call_tool("hwp_read_context", {}))
            assert "Example" in table_readback["document"]["text"]

            # Regression: a text edit after a table must land in normal body text,
            # not in the bottom-right cell left active by TableCreate.
            continuation_preview = payload(
                await session.call_tool(
                    "hwp_preview_edits",
                    {
                        "edits": [
                            {
                                "kind": "insert_text",
                                "text": "Text after table",
                                "new_paragraph_after": False,
                            }
                        ],
                        "expected_revision": table_readback["document"]["revision"],
                    },
                )
            )
            continuation_receipt = payload(
                await session.call_tool(
                    "hwp_apply_preview",
                    {"plan_id": continuation_preview["preview"]["plan_id"]},
                )
            )
            continuation_readback = payload(await session.call_tool("hwp_read_context", {}))
            rendered = continuation_readback["document"]["text"]
            assert "Example" in rendered
            assert "Text after table" in rendered
            assert "ExampleText after table" not in rendered
            final = payload(
                await session.call_tool(
                    "hwp_undo_last",
                    {"expected_revision": continuation_receipt["receipt"]["revision"]},
                )
            )
            assert "Text after table" not in final["document"]["text"]
            print("Live Hancom MCP smoke test passed")
            print("Identify the window by the 2 by 2 Field/Value and Name/Example table, then close only it without saving.")


if __name__ == "__main__":
    asyncio.run(main())
