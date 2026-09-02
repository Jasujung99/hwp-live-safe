"""Experimental, foreground-only typing for a user-selected Hancom window.

This mode intentionally does not attach through COM or enumerate the Running
Object Table. It can only activate a window the user selected, inject literal
text at the current visible caret, and report that no read-back is available.
It never opens, saves, closes, replaces a selection, or uses an arbitrary
window handle supplied by an MCP client.
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol
from uuid import uuid4

from .profile import ProfileError, ProfileStore
from .service import HwpLiveError, ProfileRequirement


class ForegroundBackendError(RuntimeError):
    """A foreground window could not be verified or text input was uncertain."""

    def __init__(self, message: str, *, outcome_unknown: bool = False) -> None:
        super().__init__(message)
        self.outcome_unknown = outcome_unknown


@dataclass(frozen=True)
class ForegroundWindow:
    handle: int
    process_id: int
    process_started: int
    title: str


class ForegroundHwpBackend(Protocol):
    def list_windows(self) -> list[ForegroundWindow]: ...

    def validate_target(self, target: ForegroundWindow) -> None: ...

    def type_text(self, target: ForegroundWindow, text: str) -> None: ...


class FakeForegroundHwpBackend:
    """A no-UI foreground backend for tests."""

    def __init__(self, windows: list[ForegroundWindow] | None = None) -> None:
        self.windows = windows or [
            ForegroundWindow(handle=101, process_id=202, process_started=303, title="resume.hwp")
        ]
        self.typed: list[tuple[ForegroundWindow, str]] = []

    def list_windows(self) -> list[ForegroundWindow]:
        return list(self.windows)

    def validate_target(self, target: ForegroundWindow) -> None:
        if target not in self.windows:
            raise ForegroundBackendError("The selected Hancom window is no longer available.")

    def type_text(self, target: ForegroundWindow, text: str) -> None:
        self.validate_target(target)
        self.typed.append((target, text))


class UnavailableForegroundHwpBackend:
    """Keeps the MCP server importable on a host without Windows UI access."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def list_windows(self) -> list[ForegroundWindow]:
        raise ForegroundBackendError(self.reason)

    def validate_target(self, target: ForegroundWindow) -> None:
        raise ForegroundBackendError(self.reason)

    def type_text(self, target: ForegroundWindow, text: str) -> None:
        raise ForegroundBackendError(self.reason)


class _KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _MouseInput(ctypes.Structure):
    """The largest native INPUT union member on Windows."""

    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _InputUnion(ctypes.Union):
    # INPUT is sized for every union member even when SendInput carries only
    # keyboard events.  Keeping the full union matters: a 64-bit process
    # otherwise passes 32 instead of the required 40-byte cbSize and Windows
    # rejects the entire batch with ERROR_INVALID_PARAMETER.
    _fields_ = [
        ("mi", _MouseInput),
        ("ki", _KeyBdInput),
        ("hi", _HardwareInput),
    ]


class _Input(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", _InputUnion)]


class WindowsForegroundHwpBackend:
    """Use Win32 only after an explicit user-chosen candidate is selected."""

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _INPUT_KEYBOARD = 1
    _KEYEVENTF_KEYUP = 0x0002
    _KEYEVENTF_UNICODE = 0x0004
    _VK_RETURN = 0x0D

    def __init__(self) -> None:
        if os.name != "nt":
            raise ForegroundBackendError("Foreground Hancom typing is available only on Windows.")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_functions()

    def _configure_functions(self) -> None:
        self._enum_windows_proc = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HWND,
            wintypes.LPARAM,
        )
        self._user32.EnumWindows.argtypes = [
            self._enum_windows_proc,
            wintypes.LPARAM,
        ]
        self._user32.EnumWindows.restype = wintypes.BOOL
        self._user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self._user32.IsWindowVisible.restype = wintypes.BOOL
        self._user32.IsWindow.argtypes = [wintypes.HWND]
        self._user32.IsWindow.restype = wintypes.BOOL
        self._user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self._user32.GetWindowTextLengthW.restype = ctypes.c_int
        self._user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self._user32.GetWindowTextW.restype = ctypes.c_int
        self._user32.GetForegroundWindow.argtypes = []
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.SetForegroundWindow.restype = wintypes.BOOL
        self._user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int]
        self._user32.SendInput.restype = wintypes.UINT

        self._kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self._kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        self._kernel32.GetProcessTimes.restype = wintypes.BOOL

    def list_windows(self) -> list[ForegroundWindow]:
        windows: list[ForegroundWindow] = []

        @self._enum_windows_proc
        def collect(handle: int, _: int) -> bool:
            try:
                window = self._window_from_handle(handle)
            except Exception:
                # A protected/elevated unrelated process must never prevent
                # discovery of the user's visible Hancom windows.
                window = None
            if window is not None:
                windows.append(window)
            return True

        ctypes.set_last_error(0)
        completed = self._user32.EnumWindows(collect, 0)
        if not completed and ctypes.get_last_error():
            raise ForegroundBackendError("Windows could not enumerate visible application windows.")
        return sorted(windows, key=lambda item: (item.title.casefold(), item.handle))

    def validate_target(self, target: ForegroundWindow) -> None:
        current = self._window_from_handle(target.handle)
        if current is None:
            raise ForegroundBackendError("The selected Hancom window is no longer visible.")
        if (
            current.process_id != target.process_id
            or current.process_started != target.process_started
        ):
            raise ForegroundBackendError("The selected Hancom window no longer belongs to the same process.")

    def type_text(self, target: ForegroundWindow, text: str) -> None:
        self.validate_target(target)
        handle = wintypes.HWND(target.handle)
        if not self._is_foreground(target.handle):
            self._user32.SetForegroundWindow(handle)
            time.sleep(0.12)
        if not self._is_foreground(target.handle):
            raise ForegroundBackendError(
                "Windows did not activate the selected Hancom window, so no text was typed."
            )

        inputs = self._build_inputs(text)
        for offset in range(0, len(inputs), 128):
            if not self._is_foreground(target.handle):
                raise ForegroundBackendError(
                    "Foreground changed while typing. The document may contain a partial insertion; "
                    "verify it visually before continuing.",
                    outcome_unknown=True,
                )
            batch = inputs[offset : offset + 128]
            array = (_Input * len(batch))(*batch)
            sent = self._user32.SendInput(len(batch), array, ctypes.sizeof(_Input))
            if sent != len(batch):
                raise ForegroundBackendError(
                    "Windows could not send all keystrokes. The document may contain a partial insertion; "
                    "verify it visually before continuing.",
                    outcome_unknown=True,
                )

    @staticmethod
    def _hwnd_value(handle: int | wintypes.HWND | None) -> int:
        """Normalize ctypes HWND wrappers before comparing their numeric handles.

        Python 3.12's ``c_void_p`` wrappers compare by object identity, so two
        separately returned ``HWND(101)`` objects are not equal even though they
        represent the same native window.
        """

        if handle is None:
            return 0
        if isinstance(handle, int):
            return handle
        return int(handle.value or 0)

    def _is_foreground(self, target_handle: int) -> bool:
        return self._hwnd_value(self._user32.GetForegroundWindow()) == target_handle

    def _window_from_handle(self, handle: int) -> ForegroundWindow | None:
        native_handle = wintypes.HWND(handle)
        if not self._user32.IsWindow(native_handle) or not self._user32.IsWindowVisible(native_handle):
            return None
        process_id = wintypes.DWORD()
        if not self._user32.GetWindowThreadProcessId(native_handle, ctypes.byref(process_id)):
            return None
        path, process_started = self._process_details(process_id.value)
        if PathName(path).casefold() != "hwp.exe":
            return None
        length = self._user32.GetWindowTextLengthW(native_handle)
        buffer = ctypes.create_unicode_buffer(max(1, length + 1))
        self._user32.GetWindowTextW(native_handle, buffer, len(buffer))
        return ForegroundWindow(
            handle=int(handle),
            process_id=int(process_id.value),
            process_started=process_started,
            title=buffer.value,
        )

    def _process_details(self, process_id: int) -> tuple[str, int]:
        process = self._kernel32.OpenProcess(
            self._PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            wintypes.DWORD(process_id),
        )
        if not process:
            raise ForegroundBackendError("Windows could not inspect a candidate process.")
        try:
            capacity = 32_768
            path_buffer = ctypes.create_unicode_buffer(capacity)
            path_size = wintypes.DWORD(capacity)
            if not self._kernel32.QueryFullProcessImageNameW(
                process,
                0,
                path_buffer,
                ctypes.byref(path_size),
            ):
                raise ForegroundBackendError("Windows could not verify a candidate process image.")
            created = wintypes.FILETIME()
            exited = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            if not self._kernel32.GetProcessTimes(
                process,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                raise ForegroundBackendError("Windows could not verify a candidate process lifetime.")
            started = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
            return path_buffer.value, started
        finally:
            self._kernel32.CloseHandle(process)

    def _build_inputs(self, text: str) -> list[_Input]:
        inputs: list[_Input] = []
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        for character in normalized:
            if character == "\n":
                inputs.extend(
                    (
                        _Input(
                            type=self._INPUT_KEYBOARD,
                            ki=_KeyBdInput(wVk=self._VK_RETURN, wScan=0, dwFlags=0, time=0, dwExtraInfo=0),
                        ),
                        _Input(
                            type=self._INPUT_KEYBOARD,
                            ki=_KeyBdInput(
                                wVk=self._VK_RETURN,
                                wScan=0,
                                dwFlags=self._KEYEVENTF_KEYUP,
                                time=0,
                                dwExtraInfo=0,
                            ),
                        ),
                    )
                )
                continue
            encoded = character.encode("utf-16-le")
            for offset in range(0, len(encoded), 2):
                code_unit = int.from_bytes(encoded[offset : offset + 2], "little")
                inputs.extend(
                    (
                        _Input(
                            type=self._INPUT_KEYBOARD,
                            ki=_KeyBdInput(
                                wVk=0,
                                wScan=code_unit,
                                dwFlags=self._KEYEVENTF_UNICODE,
                                time=0,
                                dwExtraInfo=0,
                            ),
                        ),
                        _Input(
                            type=self._INPUT_KEYBOARD,
                            ki=_KeyBdInput(
                                wVk=0,
                                wScan=code_unit,
                                dwFlags=self._KEYEVENTF_UNICODE | self._KEYEVENTF_KEYUP,
                                time=0,
                                dwExtraInfo=0,
                            ),
                        ),
                    )
                )
        return inputs


def PathName(path: str) -> str:
    """Return a Windows file name without importing pathlib into the hot path."""

    return path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]


@dataclass(frozen=True)
class _WindowCandidate:
    candidate_id: str
    target: ForegroundWindow
    expires_at: datetime


@dataclass(frozen=True)
class _ForegroundPlan:
    plan_id: str
    session_id: str
    expected_revision: int
    target: ForegroundWindow
    text: str
    expires_at: datetime
    summary: str
    effects: tuple[str, ...]
    warnings: tuple[str, ...]
    profile_requirements: tuple[ProfileRequirement, ...] = ()


class ForegroundTypingService:
    """Preview-first literal typing into a user-selected visible HWP window."""

    max_text_chars = 4_000

    def __init__(
        self,
        backend: ForegroundHwpBackend,
        *,
        profile_store: ProfileStore | None = None,
        candidate_ttl_seconds: int = 120,
        plan_ttl_seconds: int = 60,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.backend = backend
        self.profile_store = profile_store or ProfileStore()
        self.candidate_ttl_seconds = candidate_ttl_seconds
        self.plan_ttl_seconds = plan_ttl_seconds
        self._now = now or (lambda: datetime.now(UTC))
        self._candidates: dict[str, _WindowCandidate] = {}
        self._target: ForegroundWindow | None = None
        self._session_id: str | None = None
        self._revision = 0
        self._plans: dict[str, _ForegroundPlan] = {}

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "experimental": True,
            "selected_window": self._target is not None,
            "session_id": self._session_id,
            "revision": self._revision,
            "pending_previews": len(self._plans),
            "safety": {
                "opens_existing_files": False,
                "saves_files": False,
                "closes_documents": False,
                "reads_document_text": False,
                "replaces_selection": False,
                "automatic_undo": False,
                "mutations_require_preview": True,
            },
        }

    def list_windows(self) -> dict[str, Any]:
        try:
            windows = self.backend.list_windows()
        except ForegroundBackendError as exc:
            raise HwpLiveError("FOREGROUND_UNAVAILABLE", str(exc)) from exc
        now = self._now()
        self._candidates.clear()
        public: list[dict[str, Any]] = []
        for window in windows:
            candidate = _WindowCandidate(
                candidate_id=uuid4().hex,
                target=window,
                expires_at=now + timedelta(seconds=self.candidate_ttl_seconds),
            )
            self._candidates[candidate.candidate_id] = candidate
            public.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "title": window.title or "(untitled Hancom window)",
                    "expires_at": candidate.expires_at.isoformat(),
                }
            )
        return {
            "windows": public,
            "note": (
                "This lists window titles only, not document text. Select a window only after the user "
                "has explicitly identified the desired Hancom window and active tab."
            ),
        }

    def select_window(self, candidate_id: str) -> dict[str, Any]:
        candidate = self._candidates.get(candidate_id)
        if candidate is None:
            raise HwpLiveError("WINDOW_CANDIDATE_NOT_FOUND", "List visible Hancom windows again first.")
        if self._now() > candidate.expires_at:
            self._candidates.pop(candidate_id, None)
            raise HwpLiveError("WINDOW_CANDIDATE_EXPIRED", "That Hancom-window choice expired. List again.")
        try:
            self.backend.validate_target(candidate.target)
        except ForegroundBackendError as exc:
            raise HwpLiveError("WINDOW_CHANGED", str(exc)) from exc
        self._target = candidate.target
        self._session_id = uuid4().hex
        self._revision = 1
        self._plans.clear()
        return {
            "session_id": self._session_id,
            "revision": self._revision,
            "note": (
                "Experimental foreground mode is ready. Before any preview, the user must confirm that "
                "the chosen Hancom tab has a single collapsed caret at the intended insertion point."
            ),
        }

    def disconnect(self) -> dict[str, Any]:
        self._target = None
        self._session_id = None
        self._revision = 0
        self._plans.clear()
        return {"disconnected": True, "note": "Only the local foreground session was cleared; Hancom was not changed."}

    def preview_text(
        self,
        text: str,
        expected_revision: int,
        *,
        user_confirms_collapsed_caret: bool,
    ) -> dict[str, Any]:
        self._validate_text(text)
        self._require_caret_confirmation(user_confirms_collapsed_caret)
        return self._create_preview(
            text=text,
            expected_revision=expected_revision,
            summary="foreground text insertion",
            effects=(f"Type “{text[:80]}” at the current Hancom caret.",),
            warnings=self._foreground_warnings(),
        )

    def preview_profile_insert(
        self,
        profile_id: str,
        key: str,
        expected_revision: int,
        *,
        user_confirms_collapsed_caret: bool,
    ) -> dict[str, Any]:
        self._require_caret_confirmation(user_confirms_collapsed_caret)
        try:
            value = self.profile_store.resolve(profile_id, key)
        except ProfileError as exc:
            raise HwpLiveError("PROFILE_UNAVAILABLE", str(exc)) from exc
        return self._create_preview(
            text=value.value,
            expected_revision=expected_revision,
            summary="foreground local profile insertion",
            effects=(
                f"Type the locally stored “{value.label}” field from profile “{value.profile_label}” "
                "at the current Hancom caret.",
            ),
            warnings=(
                *self._foreground_warnings(),
                "The profile value is not included in this preview or MCP response.",
            ),
            profile_requirements=(
                ProfileRequirement(
                    profile_id=value.profile_id,
                    key=value.key,
                    value_hash=value.value_hash,
                ),
            ),
        )

    def apply_preview(self, plan_id: str) -> dict[str, Any]:
        plan = self._plans.get(plan_id)
        if plan is None:
            raise HwpLiveError("PREVIEW_NOT_FOUND", "That foreground preview is unavailable. Create a new one.")
        if self._now() > plan.expires_at:
            self._plans.pop(plan_id, None)
            raise HwpLiveError("PREVIEW_EXPIRED", "That foreground preview expired. Create a new one.")
        if self._session_id != plan.session_id or self._target != plan.target:
            self._plans.clear()
            raise HwpLiveError("WINDOW_CHANGED", "The selected Hancom window changed. No text was typed.")
        self._require_revision(plan.expected_revision)
        self._require_profile_values_unchanged(plan)
        try:
            self.backend.type_text(plan.target, plan.text)
        except ForegroundBackendError as exc:
            code = "FOREGROUND_INPUT_UNKNOWN" if exc.outcome_unknown else "FOREGROUND_INPUT_FAILED"
            raise HwpLiveError(code, str(exc)) from exc
        self._revision += 1
        self._plans.clear()
        return {
            "receipt_id": uuid4().hex,
            "revision": self._revision,
            "summary": plan.summary,
            "undo_available": False,
            "warnings": [
                "No document read-back or automatic Undo is available in foreground mode. "
                "Verify the visible Hancom window; use Hancom's own Undo immediately if needed."
            ],
        }

    def _create_preview(
        self,
        *,
        text: str,
        expected_revision: int,
        summary: str,
        effects: tuple[str, ...],
        warnings: tuple[str, ...],
        profile_requirements: tuple[ProfileRequirement, ...] = (),
    ) -> dict[str, Any]:
        self._require_revision(expected_revision)
        target = self._require_target()
        try:
            self.backend.validate_target(target)
        except ForegroundBackendError as exc:
            self._invalidate_target()
            raise HwpLiveError("WINDOW_CHANGED", str(exc)) from exc
        now = self._now()
        plan = _ForegroundPlan(
            plan_id=uuid4().hex,
            session_id=self._session_id or "",
            expected_revision=self._revision,
            target=target,
            text=text,
            expires_at=now + timedelta(seconds=self.plan_ttl_seconds),
            summary=summary,
            effects=effects,
            warnings=warnings,
            profile_requirements=profile_requirements,
        )
        self._plans[plan.plan_id] = plan
        return {
            "plan_id": plan.plan_id,
            "expected_revision": plan.expected_revision,
            "expires_at": plan.expires_at.isoformat(),
            "summary": plan.summary,
            "effects": list(plan.effects),
            "warnings": list(plan.warnings),
        }

    def _require_target(self) -> ForegroundWindow:
        if self._target is None or self._session_id is None:
            raise HwpLiveError(
                "NO_FOREGROUND_WINDOW",
                "Select a visible Hancom window through the explicit foreground workflow first.",
            )
        return self._target

    def _require_revision(self, expected_revision: int) -> None:
        self._require_target()
        if expected_revision != self._revision:
            raise HwpLiveError(
                "REVISION_MISMATCH",
                "The foreground preview was based on an older session state. Select or preview again.",
                {"expected_revision": expected_revision, "current_revision": self._revision},
            )

    def _require_profile_values_unchanged(self, plan: _ForegroundPlan) -> None:
        for requirement in plan.profile_requirements:
            try:
                current = self.profile_store.resolve(requirement.profile_id, requirement.key)
            except ProfileError as exc:
                self._plans.pop(plan.plan_id, None)
                raise HwpLiveError(
                    "PROFILE_CHANGED",
                    "The local profile changed or became unavailable after this preview. No text was typed.",
                ) from exc
            if current.value_hash != requirement.value_hash:
                self._plans.pop(plan.plan_id, None)
                raise HwpLiveError(
                    "PROFILE_CHANGED",
                    "The local profile changed after this preview. No text was typed.",
                )

    @classmethod
    def _validate_text(cls, text: str) -> None:
        if not isinstance(text, str) or not text.strip():
            raise HwpLiveError("EMPTY_EDIT", "Foreground typing requires non-empty text.")
        if len(text) > cls.max_text_chars:
            raise HwpLiveError(
                "TEXT_TOO_LONG",
                "Foreground mode supports at most 4,000 characters per reviewed insertion.",
            )
        if "\x00" in text or "\x02" in text:
            raise HwpLiveError("UNSAFE_TEXT", "Foreground typing rejects reserved control characters.")

    @staticmethod
    def _require_caret_confirmation(user_confirms_collapsed_caret: bool) -> None:
        if not user_confirms_collapsed_caret:
            raise HwpLiveError(
                "CARET_NOT_CONFIRMED",
                "Do not type until the user explicitly confirms a single collapsed caret in the chosen Hancom tab.",
            )

    @staticmethod
    def _foreground_warnings() -> tuple[str, ...]:
        return (
            "Experimental mode activates the user-selected Hancom window and types literal text at its "
            "current caret. It cannot read the document or verify the caret/selection.",
            "Do not use this mode for replacement text, table creation, batch edits, or anything the user "
            "has not explicitly approved.",
        )

    def _invalidate_target(self) -> None:
        self._target = None
        self._session_id = None
        self._revision = 0
        self._plans.clear()
