from __future__ import annotations

import json
from pathlib import Path

import pytest

from hwp_live.backends import FakeHwpBackend
from hwp_live.profile import ProfileStore
from hwp_live.service import HwpLiveError, HwpLiveService


PRIVATE_VALUE = "비공개-테스트-이름"


def write_profile(directory: Path, value: str | None = PRIVATE_VALUE) -> None:
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


def started_service(profile_dir: Path) -> tuple[HwpLiveService, FakeHwpBackend]:
    backend = FakeHwpBackend()
    service = HwpLiveService(backend, profile_store=ProfileStore(profile_dir))
    service.start_new_document()
    return service, backend


def test_profile_list_and_preview_never_expose_value(tmp_path: Path) -> None:
    write_profile(tmp_path)
    service, backend = started_service(tmp_path)

    profiles = service.profile_list()
    preview = service.preview_profile_insert("default", "full_name", expected_revision=1)

    assert profiles["profiles"] == [
        {
            "profile_id": "default",
            "profile_label": "기본 프로필",
            "key": "full_name",
            "label": "성명",
            "sensitivity": "personal",
            "configured": True,
        }
    ]
    assert PRIVATE_VALUE not in json.dumps(profiles, ensure_ascii=False)
    assert PRIVATE_VALUE not in preview.model_dump_json()
    assert "성명" in preview.effects[0]
    assert backend.text == ""


def test_profile_insert_applies_value_only_after_preview(tmp_path: Path) -> None:
    write_profile(tmp_path)
    service, backend = started_service(tmp_path)

    preview = service.preview_profile_insert("default", "full_name", expected_revision=1)
    receipt = service.apply_preview(preview.plan_id)

    assert receipt.undo_available is True
    assert backend.text == PRIVATE_VALUE


def test_profile_change_after_preview_blocks_apply(tmp_path: Path) -> None:
    write_profile(tmp_path)
    service, backend = started_service(tmp_path)
    preview = service.preview_profile_insert("default", "full_name", expected_revision=1)
    write_profile(tmp_path, "changed-after-preview")

    with pytest.raises(HwpLiveError) as caught:
        service.apply_preview(preview.plan_id)

    assert caught.value.code == "PROFILE_CHANGED"
    assert backend.text == ""


def test_unconfigured_profile_value_is_rejected_without_document_change(tmp_path: Path) -> None:
    write_profile(tmp_path, None)
    service, backend = started_service(tmp_path)

    with pytest.raises(HwpLiveError) as caught:
        service.preview_profile_insert("default", "full_name", expected_revision=1)

    assert caught.value.code == "PROFILE_UNAVAILABLE"
    assert backend.text == ""
