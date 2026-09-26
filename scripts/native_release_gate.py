"""Opt-in interactive gate promoted from a local release probe.

Only a new native document. No profile values, foreground selection, arbitrary
actions, open/save/close tools, hardcoded interpreter, or personal paths.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Awaitable, Callable

Call = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def confirm(message: str) -> None:
    if input(message + " [type YES to continue]: ").strip() != "YES":
        raise RuntimeError("Gate cancelled; the disposable document is left for manual inspection")


def checked(result: dict[str, Any], key: str) -> dict[str, Any]:
    if result.get("ok") is not True or key not in result:
        raise RuntimeError("Gate operation failed: " + str(result.get("error", {}).get("code", "INVALID_RESULT")))
    return result[key]


async def run_gate(call: Call, checkpoint: Callable[[str], None] = confirm) -> dict[str, Any]:
    checkpoint("Create one NEW disposable unsaved Hancom document; existing documents are not targets")
    started = checked(await call("hwp_start_new_document", {}), "document")
    document_id = started.get("document_id")
    if not isinstance(document_id, str) or not document_id:
        raise RuntimeError("New document has no verifiable identity")
    print(f"Owned disposable document ID: {document_id}")
    print("Identify its window by the synthetic markers inserted during this gate; never close another window.")
    if started.get("unsaved") is not True or started.get("context_verified") is not True:
        raise RuntimeError("New document is not an unsaved, verified document")
    if started["text"].strip():
        raise RuntimeError("New document is not empty")
    checkpoint("Confirm the NEW blank document is visible")

    async def read_document() -> dict[str, Any]:
        document = checked(await call("hwp_read_context", {}), "document")
        if document.get("document_id") != document_id:
            raise RuntimeError("The active document is no longer the new test document")
        if document.get("unsaved") is not True or document.get("context_verified") is not True:
            raise RuntimeError("The test document is no longer unsaved and verifiably readable")
        return document

    async def preview(edit: dict[str, Any]) -> dict[str, Any]:
        context = await read_document()
        plan = checked(await call("hwp_preview_edits", {
            "edits": [edit], "expected_revision": context["revision"],
        }), "preview")
        if plan.get("expected_revision") != context["revision"]:
            raise RuntimeError("Preview revision does not match the verified document")
        return plan

    async def apply(edit: dict[str, Any], label: str) -> dict[str, Any]:
        plan = await preview(edit)
        checkpoint(label)
        receipt = checked(await call("hwp_apply_preview", {"plan_id": plan["plan_id"]}), "receipt")
        if receipt.get("revision") != plan["expected_revision"] + 1:
            raise RuntimeError("Apply did not advance the preview revision exactly once")
        return receipt

    for edit, marker, label in [
        ({"kind": "insert_text", "text": "SYNTHETIC GATE", "new_paragraph_after": False,
          "style": {"font_size_pt": 16, "bold": True, "align": "center"}},
         "SYNTHETIC GATE", "Approve the synthetic centered 16pt bold heading"),
        ({"kind": "insert_table", "rows": 2, "cols": 2,
          "cells": [["Field", "Value"], ["Sample", "GATE CELL"]],
          "table_style": {"first_row_is_header": False, "header_bold": False}},
         "GATE CELL", "Approve the synthetic 2 by 2 table"),
    ]:
        receipt = await apply(edit, label)
        context = await read_document()
        if marker not in context["text"]:
            raise RuntimeError("Inserted text is missing")
        checkpoint("Verify visible formatting/table and confirm immediate Undo; do not edit manually yet")
        undone = checked(await call("hwp_undo_last", {"expected_revision": receipt["revision"]}), "document")
        if undone.get("document_id") != document_id or undone.get("context_verified") is not True:
            raise RuntimeError("Undo did not return the verified test document")
        if undone.get("revision") != receipt["revision"] + 1:
            raise RuntimeError("Undo did not advance the document revision exactly once")
        if marker in undone["text"]:
            raise RuntimeError("Undo did not remove the synthetic edit")

    stale = await preview({"kind": "insert_text", "text": "MUST-NOT-APPEAR", "new_paragraph_after": False})
    checkpoint("In the NEW document manually type MANUAL-STALE, then confirm to test stale-preview rejection")
    rejected = await call("hwp_apply_preview", {"plan_id": stale["plan_id"]})
    if rejected.get("ok") is not False or rejected.get("error", {}).get("code") != "DOCUMENT_CHANGED":
        raise RuntimeError("Stale preview was not rejected")
    context = await read_document()
    if "MUST-NOT-APPEAR" in context["text"] or "MANUAL-STALE" not in context["text"]:
        raise RuntimeError("Stale-preview readback failed")

    receipt = await apply({"kind": "insert_text", "text": "UNDO-GATE", "new_paragraph_after": False},
                          "Approve UNDO-GATE insertion to test guarded Undo")
    checkpoint("In the NEW document manually type MANUAL-UNDO, then confirm to test Undo rejection")
    rejected = await call("hwp_undo_last", {"expected_revision": receipt["revision"]})
    if rejected.get("ok") is not False or rejected.get("error", {}).get("code") != "DOCUMENT_CHANGED":
        raise RuntimeError("Unsafe Undo was not rejected")
    context = await read_document()
    if not all(marker in context["text"] for marker in ("UNDO-GATE", "MANUAL-UNDO")):
        raise RuntimeError("Guarded Undo did not preserve manual edits")
    return {"contract_sequence_passed": True, "owned_document_id": document_id,
            "profile_tested": False, "foreground_tested": False}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="explicitly enable the interactive native gate")
    args = parser.parse_args()
    if not args.live or sys.platform != "win32":
        parser.error("Requires Windows and --live; no Hancom session was started")
    # Import only after opt-in. Use the caller's MCP 2.x environment, not hwpctl's.
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="hwp-safe-gate-") as profiles:
        environment = dict(os.environ)
        environment.update(PYTHONUTF8="1", PYTHONPATH=str(root / "src"),
                           HWP_LIVE_BACKEND="powershell-com", HWP_LIVE_SAFE_PROFILE_DIR=profiles)
        params = StdioServerParameters(command=sys.executable, args=["-m", "hwp_live.server"],
                                       env=environment, cwd=root)
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()

                async def call(name, arguments):
                    result = await session.call_tool(name, arguments)
                    if result.is_error or result.structured_content is None:
                        raise RuntimeError("MCP transport result failed")
                    return dict(result.structured_content)

                try:
                    result = await run_gate(call)
                    print({**result, "native_contract_passed": True,
                           "visual_checkpoints_acknowledged": True})
                finally:
                    print("If the gate created a document, leave this terminal open and inspect the new unsaved Hancom window.")
                    print("On a completed gate, match MANUAL-STALE, UNDO-GATE, and MANUAL-UNDO in that window before closing it without saving.")
                    print("The earlier SYNTHETIC GATE heading and GATE CELL table are undone by the gate.")
                    print("If the window cannot be identified confidently, leave it open; no cleanup tool is invoked.")


if __name__ == "__main__":
    asyncio.run(main())
