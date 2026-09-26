"""Opt-in native guard check on one new, unsaved Hancom document.

The direct backend edits represent changes outside the preview service. They
are synthetic edits in the same automation-owned document, not manual typing
or a visual check. No existing document or profile is opened, saved, or closed.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

# Use this checkout's backend even when the caller has another installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hwp_live.backends import PowerShellHwpBackend
from hwp_live.models import DocumentEdit
from hwp_live.profile import ProfileStore
from hwp_live.service import HwpLiveError, HwpLiveService


def require_changed(operation) -> None:
    try:
        operation()
    except HwpLiveError as exc:
        if exc.code != "DOCUMENT_CHANGED":
            raise RuntimeError(f"Expected DOCUMENT_CHANGED, got {exc.code}") from exc
    else:
        raise RuntimeError("A stale operation was applied to the changed native document")


def run_gate() -> dict[str, object]:
    with TemporaryDirectory(prefix="hwp-safe-native-profiles-") as profile_dir:
        backend = PowerShellHwpBackend()
        service = HwpLiveService(backend, profile_store=ProfileStore(Path(profile_dir)))
        try:
            started = service.start_new_document()
            if not started.document_id or not started.unsaved or not started.context_verified:
                raise RuntimeError("The new native document was not verified as owned and unsaved")
            print(f"Owned disposable document ID: {started.document_id}", flush=True)
            print("This gate leaves its synthetic document open and unsaved; do not close another window.", flush=True)

            context = service.read_context()
            if context.document_id != started.document_id or context.text.strip():
                raise RuntimeError("The owned native document changed before the first preview")
            plan = service.preview_edits(
                [DocumentEdit(kind="insert_text", text="NATIVE-UNDO-CHECK", new_paragraph_after=False)],
                context.revision,
            )
            receipt = service.apply_preview(plan.plan_id)
            if receipt.revision != context.revision + 1:
                raise RuntimeError("Native apply did not advance revision once")
            if "NATIVE-UNDO-CHECK" not in service.read_context().text:
                raise RuntimeError("Native insertion was not read back")
            undone = service.undo_last(receipt.revision)
            if undone.revision != receipt.revision + 1 or "NATIVE-UNDO-CHECK" in undone.text:
                raise RuntimeError("Native Undo did not restore the document")

            stale = service.preview_edits(
                [DocumentEdit(kind="insert_text", text="MUST-NOT-APPEAR", new_paragraph_after=False)],
                undone.revision,
            )
            backend.apply_edits(
                [DocumentEdit(kind="insert_text", text="EXTERNAL-STAGE", new_paragraph_after=False)]
            )
            require_changed(lambda: service.apply_preview(stale.plan_id))
            after_stale = service.read_context()
            if ("EXTERNAL-STAGE" not in after_stale.text or
                    "MUST-NOT-APPEAR" in after_stale.text):
                raise RuntimeError("Stale preview guard changed the native document")

            fresh = service.preview_edits(
                [DocumentEdit(kind="insert_text", text="SAFE-UNDO-GUARD", new_paragraph_after=False)],
                after_stale.revision,
            )
            safe_receipt = service.apply_preview(fresh.plan_id)
            backend.apply_edits(
                [DocumentEdit(kind="insert_text", text="EXTERNAL-UNDO", new_paragraph_after=False)]
            )
            require_changed(lambda: service.undo_last(safe_receipt.revision))
            final = service.read_context()
            if final.document_id != started.document_id or not final.unsaved or not final.context_verified:
                raise RuntimeError("The owned native document could not be verified after guard checks")
            if not all(marker in final.text for marker in
                       ("EXTERNAL-STAGE", "SAFE-UNDO-GUARD", "EXTERNAL-UNDO")):
                raise RuntimeError("Guarded Undo altered the native document")
            return {
                "native_contract_passed": True,
                "external_change_rejection_passed": True,
                "manual_visual_check_performed": False,
                "owned_document_id": started.document_id,
            }
        finally:
            backend.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="create one new native test document")
    args = parser.parse_args()
    if not args.live or sys.platform != "win32":
        parser.error("Requires Windows and --live; no Hancom session was started")
    if os.environ.get("HWP_LIVE_BACKEND", "powershell-com").lower() == "fake":
        parser.error("The fake backend cannot satisfy this native gate")
    try:
        print(run_gate())
    finally:
        print("If created, match EXTERNAL-STAGE, SAFE-UNDO-GUARD, and EXTERNAL-UNDO in the new unsaved window.")
        print("Close only that window without saving; if unsure which it is, leave it open.")


if __name__ == "__main__":
    main()
