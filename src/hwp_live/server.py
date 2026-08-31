"""stdio MCP server exposing a small, approval-friendly HWP Live toolset."""

from __future__ import annotations

import os
from typing import Any, Callable, TypeVar

from mcp.server import MCPServer
from pydantic import BaseModel

from . import __version__
from .backends import FakeHwpBackend, PowerShellHwpBackend
from .foreground import (
    ForegroundBackendError,
    ForegroundTypingService,
    UnavailableForegroundHwpBackend,
    WindowsForegroundHwpBackend,
)
from .models import ContextView, DocumentEdit, PreviewView, ReceiptView, TextStyle
from .profile import ProfileStore
from .service import HwpLiveError, HwpLiveService

T = TypeVar("T")


def create_service(profile_store: ProfileStore | None = None) -> HwpLiveService:
    """Create the production backend unless an explicit test backend is selected."""

    backend_name = os.environ.get("HWP_LIVE_BACKEND", "powershell-com").lower()
    if backend_name == "fake":
        return HwpLiveService(FakeHwpBackend(), profile_store=profile_store)
    if backend_name != "powershell-com":
        raise RuntimeError(
            "HWP_LIVE_BACKEND must be 'powershell-com' or 'fake'; "
            f"got {backend_name!r}."
        )
    return HwpLiveService(PowerShellHwpBackend(), profile_store=profile_store)


profile_store = ProfileStore()
service = create_service(profile_store)
try:
    foreground_backend = WindowsForegroundHwpBackend()
except ForegroundBackendError as exc:
    foreground_backend = UnavailableForegroundHwpBackend(str(exc))
foreground_service = ForegroundTypingService(foreground_backend, profile_store=profile_store)

mcp = MCPServer(
    name="hwp-live-safe",
    version=__version__,
    instructions=(
        "The native COM tools control only a new, automation-owned Hancom Office 2022 document. "
        "Never open, save, close, or overwrite a user file. "
        "For a native-document edit, always call hwp_read_context, then hwp_preview_edits before editing. "
        "For a short, explicit, structured request, preview and apply in the "
        "same turn, then report the receipt. For long-form, ambiguous, or "
        "replacement text, show the preview and wait for the user's approval. "
        "If the user asks to revise the immediately preceding change, use "
        "hwp_undo_last only when its revision matches. Local profile values must never be repeated "
        "in chat or tool output; use hwp_profile_list and hwp_preview_profile_insert instead. "
        "The hwp_foreground_* tools are experimental UI typing, not document attachment: use them only "
        "after the user explicitly selects a listed Hancom window and confirms a collapsed caret. "
        "Never use foreground mode for replacement text, tables, batch edits, or automatic undo."
    ),
)


def _result(label: str, value: T) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        payload: Any = value.model_dump(mode="json")
    else:
        payload = value
    return {"ok": True, label: payload}


def _run(label: str, operation: Callable[[], T]) -> dict[str, Any]:
    try:
        return _result(label, operation())
    except HwpLiveError as exc:
        return exc.as_dict()
    except Exception as exc:  # Keep unexpected worker details out of the document.
        return {
            "ok": False,
            "error": {
                "code": "UNEXPECTED_ERROR",
                "message": (
                    "HWP Live Safe could not complete that request because the local "
                    "automation bridge returned an unexpected error."
                ),
            },
        }


@mcp.tool()
def hwp_status() -> dict[str, Any]:
    """Check whether the local Hancom 2022 automation bridge is ready.

    This does not launch Hancom, edit a document, or access a user file.
    """

    return service.status()


@mcp.tool()
def hwp_start_new_document() -> dict[str, Any]:
    """Launch Hancom and create a brand-new unsaved document owned by HWP Live.

    It never attaches to or changes an already-open user document.
    """

    return _run("document", service.start_new_document)


@mcp.tool()
def hwp_read_context() -> dict[str, Any]:
    """Read text from HWP Live's current unsaved document and return its revision."""

    return _run("document", service.read_context)


@mcp.tool()
def hwp_profile_list() -> dict[str, Any]:
    """List configured local profile keys without returning any profile value.

    This does not open Hancom, read a document, or write a profile. It only
    exposes profile/key labels and whether each value is configured.
    """

    return _run("profiles", service.profile_list)


@mcp.tool()
def hwp_preview_profile_insert(
    profile_id: str,
    key: str,
    expected_revision: int,
    new_paragraph_after: bool = False,
    style: TextStyle | None = None,
) -> dict[str, Any]:
    """Preview inserting one local profile value at the current HWP Live caret.

    Values stay inside the local server and are not returned in the preview.
    First call hwp_read_context, place or confirm the visible caret, then ask
    for approval before applying the returned plan.
    """

    return _run(
        "preview",
        lambda: service.preview_profile_insert(
            profile_id,
            key,
            expected_revision,
            new_paragraph_after=new_paragraph_after,
            style=style,
        ),
    )


@mcp.tool()
def hwp_preview_edits(
    edits: list[DocumentEdit],
    expected_revision: int,
) -> dict[str, Any]:
    """Create a 60-second, non-mutating preview for text or table insertions.

    Call hwp_read_context first and pass its revision. Show the preview and obtain
    the user's approval before calling hwp_apply_preview.
    """

    return _run("preview", lambda: service.preview_edits(edits, expected_revision))


@mcp.tool()
def hwp_apply_preview(plan_id: str) -> dict[str, Any]:
    """Apply exactly one fresh preview to the visible, automation-owned document."""

    return _run("receipt", lambda: service.apply_preview(plan_id))


@mcp.tool()
def hwp_undo_last(expected_revision: int) -> dict[str, Any]:
    """Undo HWP Live's immediately preceding change if the document is unchanged."""

    return _run("document", lambda: service.undo_last(expected_revision))


@mcp.tool()
def hwp_foreground_status() -> dict[str, Any]:
    """Show the experimental foreground-typing session state without touching Hancom."""

    return foreground_service.status()


@mcp.tool()
def hwp_foreground_list_windows() -> dict[str, Any]:
    """List visible Hancom window titles for an explicit experimental typing choice.

    This does not read document text or edit anything. Window titles can reveal
    file names, so call it only when the user asks to target an already-open
    Hancom window and is comfortable identifying it.
    """

    return _run("windows", foreground_service.list_windows)


@mcp.tool()
def hwp_foreground_select_window(candidate_id: str) -> dict[str, Any]:
    """Select one short-lived Hancom-window candidate for foreground typing.

    This does not activate or edit the window. The user must explicitly identify
    the desired listed window and active tab before it is selected.
    """

    return _run("session", lambda: foreground_service.select_window(candidate_id))


@mcp.tool()
def hwp_foreground_preview_text(
    text: str,
    expected_revision: int,
    user_confirms_collapsed_caret: bool,
) -> dict[str, Any]:
    """Preview literal text typed at a user-confirmed caret in the selected window.

    The mode cannot read the document or verify selection state. Set
    user_confirms_collapsed_caret true only after the user explicitly confirms
    that the intended Hancom tab has one collapsed caret, not selected text.
    """

    return _run(
        "preview",
        lambda: foreground_service.preview_text(
            text,
            expected_revision,
            user_confirms_collapsed_caret=user_confirms_collapsed_caret,
        ),
    )


@mcp.tool()
def hwp_foreground_preview_profile_insert(
    profile_id: str,
    key: str,
    expected_revision: int,
    user_confirms_collapsed_caret: bool,
) -> dict[str, Any]:
    """Preview a local profile value typed at a user-confirmed foreground caret.

    The profile value is resolved only inside the local server and is never
    included in the MCP response. This is experimental and has no automatic
    document read-back or Undo.
    """

    return _run(
        "preview",
        lambda: foreground_service.preview_profile_insert(
            profile_id,
            key,
            expected_revision,
            user_confirms_collapsed_caret=user_confirms_collapsed_caret,
        ),
    )


@mcp.tool()
def hwp_foreground_apply_preview(plan_id: str) -> dict[str, Any]:
    """Activate the selected Hancom window and type exactly one fresh foreground preview.

    This never saves or closes a document. It has no read-back or automatic
    Undo, so use it only after the user has approved the preview.
    """

    return _run("receipt", lambda: foreground_service.apply_preview(plan_id))


@mcp.tool()
def hwp_foreground_disconnect() -> dict[str, Any]:
    """Forget the selected foreground window without changing Hancom."""

    return _run("session", foreground_service.disconnect)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
