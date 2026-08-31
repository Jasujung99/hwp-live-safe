from __future__ import annotations

import json
from pathlib import Path

import pytest

from hwp_live.foreground import FakeForegroundHwpBackend, ForegroundTypingService
from hwp_live.profile import ProfileStore
from hwp_live.service import HwpLiveError


PRIVATE_VALUE = "로컬-개인정보"


def write_profile(directory: Path, value: str = PRIVATE_VALUE) -> None:
    payload = {
        "version": 1,
        "label": "기본 프로필",
        "fields": {
            "full_name": {
                "label": "성명",
                "sensitivity": "personal",
                "value": value,
            }
        },
    }
    (directory / "default.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def selected_service(tmp_path: Path) -> tuple[ForegroundTypingService, FakeForegroundHwpBackend]:
    backend = FakeForegroundHwpBackend()
    service = ForegroundTypingService(backend, profile_store=ProfileStore(tmp_path))
    listed = service.list_windows()
    service.select_window(listed["windows"][0]["candidate_id"])
    return service, backend


def test_foreground_mode_requires_explicit_collapsed_caret_confirmation(tmp_path: Path) -> None:
    service, backend = selected_service(tmp_path)

    with pytest.raises(HwpLiveError) as caught:
        service.preview_text(
            "입력할 문장",
            expected_revision=1,
            user_confirms_collapsed_caret=False,
        )

    assert caught.value.code == "CARET_NOT_CONFIRMED"
    assert backend.typed == []


def test_foreground_mode_types_exactly_one_reviewed_text(tmp_path: Path) -> None:
    service, backend = selected_service(tmp_path)
    preview = service.preview_text(
        "입력할 문장",
        expected_revision=1,
        user_confirms_collapsed_caret=True,
    )

    receipt = service.apply_preview(preview["plan_id"])

    assert backend.typed[0][1] == "입력할 문장"
    assert receipt["revision"] == 2
    assert receipt["undo_available"] is False


def test_foreground_mode_fails_closed_when_selected_window_disappears(tmp_path: Path) -> None:
    service, backend = selected_service(tmp_path)
    preview = service.preview_text(
        "입력할 문장",
        expected_revision=1,
        user_confirms_collapsed_caret=True,
    )
    backend.windows.clear()

    with pytest.raises(HwpLiveError) as caught:
        service.apply_preview(preview["plan_id"])

    assert caught.value.code == "FOREGROUND_INPUT_FAILED"
    assert backend.typed == []


def test_foreground_profile_preview_is_redacted_and_profile_change_blocks_apply(tmp_path: Path) -> None:
    write_profile(tmp_path)
    service, backend = selected_service(tmp_path)
    preview = service.preview_profile_insert(
        "default",
        "full_name",
        expected_revision=1,
        user_confirms_collapsed_caret=True,
    )

    assert PRIVATE_VALUE not in json.dumps(preview, ensure_ascii=False)
    write_profile(tmp_path, "changed-after-preview")
    with pytest.raises(HwpLiveError) as caught:
        service.apply_preview(preview["plan_id"])

    assert caught.value.code == "PROFILE_CHANGED"
    assert backend.typed == []
