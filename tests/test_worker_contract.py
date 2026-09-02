"""Static safety contract for the packaged PowerShell COM worker.

The real COM path still has a manual Hancom gate. These checks prevent the
bounded-Undo, format-restoration, and table-exit guards from silently
disappearing in an ordinary unit-test run.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER = (ROOT / "src" / "hwp_live" / "hwp_com_worker.ps1").read_text(
    encoding="utf-8"
)


def test_worker_undo_is_bounded_by_recorded_native_actions() -> None:
    assert "while ($attempt -lt 256)" not in WORKER
    assert "while ($attempt -lt $NativeUndoCount)" in WORKER
    assert "while ($attempt -lt $actionCount)" in WORKER
    assert "native_undo_count = $actionCount" in WORKER
    assert "No Undo was attempted" in WORKER
    assert "context_verified" in WORKER


def test_worker_restores_text_shapes_and_counts_the_restore_actions() -> None:
    assert "$savedCharShape = $script:hwp.CharShape" in WORKER
    assert "$savedParaShape = $script:hwp.ParaShape" in WORKER
    assert "$script:hwp.CharShape = $savedCharShape" in WORKER
    assert "$script:hwp.ParaShape = $savedParaShape" in WORKER
    assert "$ActionCount.Value++" in WORKER
    assert "did not restore the previous character formatting" in WORKER
    assert "did not restore the previous paragraph alignment" in WORKER


def test_worker_exits_new_table_before_later_body_edits() -> None:
    assert 'HAction.Run("MoveListEnd")' in WORKER
    assert 'HAction.Run("MoveRight")' in WORKER
    assert 'HAction.Run("MoveParentList")' in WORKER
    assert "The caret remained inside the newly created table" in WORKER


def test_worker_validates_a_unique_blank_unsaved_com_instance() -> None:
    assert "HWP_LIVE_SAFE_STRICT_ISOLATION" in WORKER
    assert "Get-HwpWindowHandles" in WORKER
    assert "XHwpDocuments.Count -ne 1" in WORKER
    assert "document.FullName" in WORKER
    assert "document.Modified" in WORKER
    assert "$existingHandles -notcontains $handle" in WORKER
    assert "ownership validation failed" in WORKER


def test_existing_hwp_process_is_only_a_strict_mode_guard() -> None:
    assert "if ((Test-StrictIsolation) -and (Get-HwpProcessRunning))" in WORKER
    assert "is_ready = $registered" in WORKER
