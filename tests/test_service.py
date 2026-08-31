from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from hwp_live.backends import FakeHwpBackend
from hwp_live.models import DocumentEdit, TableStyle, TextStyle
from hwp_live.service import HwpLiveError, HwpLiveService


def text_edit(text: str = "안녕하세요") -> DocumentEdit:
    return DocumentEdit(
        kind="insert_text",
        text=text,
        style=TextStyle(font_size_pt=14, bold=True, align="center"),
    )


def started_service() -> tuple[HwpLiveService, FakeHwpBackend]:
    backend = FakeHwpBackend()
    service = HwpLiveService(backend)
    service.start_new_document()
    return service, backend


def test_preview_does_not_mutate_and_apply_is_single_use() -> None:
    service, backend = started_service()

    preview = service.preview_edits([text_edit()], expected_revision=1)

    assert backend.text == ""
    assert preview.expected_revision == 1
    assert "text insertion" in preview.summary

    receipt = service.apply_preview(preview.plan_id)

    assert receipt.revision == 2
    assert "안녕하세요" in backend.text
    assert backend.save_call_count == 0
    with pytest.raises(HwpLiveError, match="preview is unavailable"):
        service.apply_preview(preview.plan_id)


def test_stale_revision_is_rejected() -> None:
    service, _ = started_service()
    preview = service.preview_edits([text_edit()], expected_revision=1)
    service.apply_preview(preview.plan_id)

    with pytest.raises(HwpLiveError) as caught:
        service.preview_edits([text_edit("두 번째")], expected_revision=1)

    assert caught.value.code == "REVISION_MISMATCH"


def test_version_one_rejects_edit_batches() -> None:
    service, _ = started_service()

    with pytest.raises(HwpLiveError) as caught:
        service.preview_edits([text_edit("첫째"), text_edit("둘째")], expected_revision=1)

    assert caught.value.code == "EDIT_BATCH_UNSUPPORTED"


def test_external_change_invalidates_pending_preview() -> None:
    service, backend = started_service()
    preview = service.preview_edits([text_edit()], expected_revision=1)
    backend.mutate_externally("사용자 입력")

    with pytest.raises(HwpLiveError) as caught:
        service.apply_preview(preview.plan_id)

    assert caught.value.code == "DOCUMENT_CHANGED"
    assert "사용자 입력" in backend.text


def test_undo_is_limited_to_the_unchanged_last_edit() -> None:
    service, backend = started_service()
    preview = service.preview_edits([text_edit()], expected_revision=1)
    receipt = service.apply_preview(preview.plan_id)

    context = service.undo_last(receipt.revision)

    assert context.revision == 3
    assert backend.text == ""


def test_undo_refuses_after_manual_change() -> None:
    service, backend = started_service()
    preview = service.preview_edits([text_edit()], expected_revision=1)
    receipt = service.apply_preview(preview.plan_id)
    backend.mutate_externally("수동 수정")

    with pytest.raises(HwpLiveError) as caught:
        service.undo_last(receipt.revision)

    assert caught.value.code == "DOCUMENT_CHANGED"


def test_table_preview_describes_header_and_requires_content() -> None:
    service, _ = started_service()
    edit = DocumentEdit(
        kind="insert_table",
        rows=2,
        cols=2,
        cells=[["항목", "내용"], ["이름", "홍길동"]],
        table_style=TableStyle(header_fill="#1F4E78"),
    )

    preview = service.preview_edits([edit], expected_revision=1)

    assert "2 × 2 table" in preview.effects[0]
    assert preview.warnings
    with pytest.raises(ValidationError, match="non-empty cell"):
        DocumentEdit(kind="insert_table", rows=2, cols=2)
    with pytest.raises(ValidationError, match="at most 200 cells"):
        DocumentEdit(
            kind="insert_table",
            rows=10,
            cols=21,
            cells=[["x"]],
        )


def test_preview_expires() -> None:
    current = datetime(2026, 9, 1, tzinfo=UTC)
    backend = FakeHwpBackend()
    service = HwpLiveService(backend, now=lambda: current)
    service.start_new_document()
    preview = service.preview_edits([text_edit()], expected_revision=1)
    current += timedelta(seconds=61)

    with pytest.raises(HwpLiveError) as caught:
        service.apply_preview(preview.plan_id)

    assert caught.value.code == "PREVIEW_EXPIRED"
