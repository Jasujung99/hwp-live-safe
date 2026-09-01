from __future__ import annotations

import json
import ctypes
from ctypes import wintypes
from pathlib import Path

import pytest

import hwp_live.foreground as foreground_module
from hwp_live.foreground import (
    FakeForegroundHwpBackend,
    ForegroundBackendError,
    ForegroundTypingService,
    ForegroundWindow,
    WindowsForegroundHwpBackend,
)
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


class FakeWindowsUser32:
    def __init__(
        self,
        foreground: int,
        *,
        activates: bool = True,
        foreground_after_first_check: int | None = None,
    ) -> None:
        self.foreground = foreground
        self.activates = activates
        self.foreground_after_first_check = foreground_after_first_check
        self.foreground_checks = 0
        self.activation_calls: list[int] = []
        self.sent_counts: list[int] = []
        self.input_sizes: list[int] = []

    def GetForegroundWindow(self):  # noqa: N802 - Win32 spelling
        # Return a fresh ctypes wrapper each time, as the real Win32 binding does.
        self.foreground_checks += 1
        if self.foreground_checks == 3 and self.foreground_after_first_check is not None:
            self.foreground = self.foreground_after_first_check
        return wintypes.HWND(self.foreground)

    def SetForegroundWindow(self, handle):  # noqa: N802 - Win32 spelling
        self.activation_calls.append(int(handle.value or 0))
        if self.activates:
            self.foreground = int(handle.value or 0)
        return 1

    def SendInput(self, count, _array, _size):  # noqa: N802 - Win32 spelling
        self.sent_counts.append(count)
        self.input_sizes.append(_size)
        return count


def native_windows_backend(user32: FakeWindowsUser32) -> WindowsForegroundHwpBackend:
    backend = object.__new__(WindowsForegroundHwpBackend)
    backend._user32 = user32
    backend.validate_target = lambda _target: None
    backend._build_inputs = lambda _text: [foreground_module._Input()]
    return backend


def native_target() -> ForegroundWindow:
    return ForegroundWindow(handle=101, process_id=202, process_started=303, title="gate.hwp")


def test_windows_foreground_comparison_uses_numeric_hwnd_value(monkeypatch) -> None:
    user32 = FakeWindowsUser32(foreground=101)
    backend = native_windows_backend(user32)
    monkeypatch.setattr(foreground_module.time, "sleep", lambda _seconds: None)

    backend.type_text(native_target(), "x")

    assert user32.activation_calls == []
    assert user32.sent_counts == [1]
    assert user32.input_sizes == [ctypes.sizeof(foreground_module._Input)]


def test_native_input_layout_matches_win32_input() -> None:
    expected_size = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28

    assert ctypes.sizeof(foreground_module._Input) == expected_size


def test_windows_foreground_activation_rechecks_numeric_hwnd_value(monkeypatch) -> None:
    user32 = FakeWindowsUser32(foreground=999)
    backend = native_windows_backend(user32)
    monkeypatch.setattr(foreground_module.time, "sleep", lambda _seconds: None)

    backend.type_text(native_target(), "x")

    assert user32.activation_calls == [101]
    assert user32.sent_counts == [1]


def test_windows_foreground_activation_fails_closed(monkeypatch) -> None:
    user32 = FakeWindowsUser32(foreground=999, activates=False)
    backend = native_windows_backend(user32)
    monkeypatch.setattr(foreground_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(ForegroundBackendError) as caught:
        backend.type_text(native_target(), "x")

    assert caught.value.outcome_unknown is False
    assert user32.sent_counts == []


def test_windows_foreground_change_before_input_fails_closed(monkeypatch) -> None:
    user32 = FakeWindowsUser32(foreground=101, foreground_after_first_check=999)
    backend = native_windows_backend(user32)
    monkeypatch.setattr(foreground_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(ForegroundBackendError) as caught:
        backend.type_text(native_target(), "x")

    assert caught.value.outcome_unknown is True
    assert user32.sent_counts == []
