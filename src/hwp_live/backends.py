"""Backends for the small, reviewable HWP-editing vocabulary.

The production backend keeps the Hancom COM object in a dedicated Windows
PowerShell worker. A specific compatible runtime can be selected when required
by the host's automation registration.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import queue
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from .models import DocumentEdit


class BackendError(RuntimeError):
    """A lower-level Hancom or worker failure."""

    def __init__(self, message: str, *, code: str = "HWP_BACKEND_ERROR") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BackendContext:
    document_id: str | None
    text: str
    fingerprint: str | None
    context_verified: bool
    unsaved: bool = True


@dataclass(frozen=True)
class BackendApplyResult:
    context: BackendContext
    native_undo_count: int
    warnings: tuple[str, ...] = ()


class HwpBackend(Protocol):
    def status(self) -> dict[str, Any]: ...

    def start_new_document(self) -> BackendContext: ...

    def read_context(self) -> BackendContext: ...

    def apply_edits(self, edits: list[DocumentEdit]) -> BackendApplyResult: ...

    def undo(self, native_undo_count: int) -> BackendContext: ...


def _fingerprint(document_id: str | None, text: str) -> str:
    payload = f"{document_id or ''}\0{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


class FakeHwpBackend:
    """In-memory backend used by tests and by offline development."""

    def __init__(self) -> None:
        self.document_id: str | None = None
        self.text = ""
        self.undo_stack: list[str] = []
        self.save_call_count = 0

    def status(self) -> dict[str, Any]:
        return {
            "backend": "fake",
            "hwp_registered": True,
            "is_ready": True,
            "document_open": self.document_id is not None,
            "unsaved": self.document_id is not None,
        }

    def start_new_document(self) -> BackendContext:
        self.document_id = f"fake-{uuid.uuid4().hex[:12]}"
        self.text = ""
        self.undo_stack.clear()
        return self.read_context()

    def read_context(self) -> BackendContext:
        if self.document_id is None:
            raise BackendError("No automation-owned document is open.")
        return BackendContext(
            document_id=self.document_id,
            text=self.text,
            fingerprint=_fingerprint(self.document_id, self.text),
            context_verified=True,
        )

    def apply_edits(self, edits: list[DocumentEdit]) -> BackendApplyResult:
        if self.document_id is None:
            raise BackendError("No automation-owned document is open.")
        self.undo_stack.append(self.text)
        rendered: list[str] = []
        for edit in edits:
            if edit.kind == "insert_text":
                rendered.append(edit.text or "")
                if edit.new_paragraph_after:
                    rendered.append("")
                continue

            matrix = edit.cells or []
            for index in range(edit.rows or 0):
                row = matrix[index] if index < len(matrix) else []
                values = [row[column] if column < len(row) else "" for column in range(edit.cols or 0)]
                rendered.append(" | ".join(values))
            rendered.append("")

        addition = "\n".join(rendered)
        if self.text and addition:
            self.text += "\n"
        self.text += addition
        return BackendApplyResult(
            context=self.read_context(),
            native_undo_count=1,
        )

    def undo(self, native_undo_count: int) -> BackendContext:
        if self.document_id is None:
            raise BackendError("No automation-owned document is open.")
        if not self.undo_stack:
            raise BackendError("There is no HWP Live change to undo.")
        self.text = self.undo_stack.pop()
        return self.read_context()

    def mutate_externally(self, text: str) -> None:
        """Test helper that simulates a user changing the open document."""

        if self.document_id is None:
            raise BackendError("No automation-owned document is open.")
        self.text += text


class PowerShellHwpBackend:
    """Talk to the Hancom COM worker using line-delimited JSON."""

    DEFAULT_TIMEOUTS = {
        "status": 10.0,
        "read_context": 10.0,
        "start_new_document": 60.0,
        "apply_edits": 60.0,
        "undo": 60.0,
        "shutdown": 3.0,
    }

    def __init__(
        self,
        powershell_path: Path | None = None,
        worker_path: Path | None = None,
        operation_timeouts: Mapping[str, float] | None = None,
    ) -> None:
        configured_path = os.environ.get("HWP_LIVE_POWERSHELL_PATH")
        default_path = Path(r"C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe")
        discovered_path = shutil.which("powershell.exe")
        self.powershell_path = powershell_path or (
            Path(configured_path)
            if configured_path
            else default_path
            if default_path.is_file()
            else Path(discovered_path or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
        )
        self.worker_path = worker_path or Path(__file__).with_name("hwp_com_worker.ps1")
        self.operation_timeouts = dict(self.DEFAULT_TIMEOUTS)
        if operation_timeouts:
            for operation, timeout in operation_timeouts.items():
                if timeout <= 0:
                    raise ValueError(f"Timeout for {operation!r} must be positive.")
                self.operation_timeouts[operation] = float(timeout)
        self._process: subprocess.Popen[str] | None = None
        self._stuck_error: BackendError | None = None
        self._lock = threading.RLock()
        atexit.register(self.shutdown)

    def _ensure_process(self) -> subprocess.Popen[str]:
        if not self.powershell_path.is_file():
            raise BackendError(
                "Windows PowerShell was not found. Hancom automation cannot be started."
            )
        if not self.worker_path.is_file():
            raise BackendError("The HWP COM worker script is missing.")
        if self._process is not None and self._process.poll() is None:
            return self._process

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = subprocess.Popen(
            [
                str(self.powershell_path),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.worker_path),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # The JSON protocol uses stdout only.  Discarding stderr prevents a
            # full, unread pipe from deadlocking the worker.
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        return self._process

    def _call(self, operation: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            if self._stuck_error is not None:
                raise BackendError(str(self._stuck_error), code=self._stuck_error.code)
            process = self._ensure_process()
            if process.stdin is None or process.stdout is None:
                raise BackendError("The HWP worker has no active communication channel.")
            request_id = uuid.uuid4().hex
            request = {
                "id": request_id,
                "operation": operation,
                "params": params or {},
            }
            try:
                process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self.shutdown()
                raise BackendError("The HWP worker unexpectedly stopped.") from exc

            responses: queue.Queue[tuple[str | None, BaseException | None]] = queue.Queue(maxsize=1)

            def read_response() -> None:
                try:
                    responses.put((process.stdout.readline(), None))
                except BaseException as exc:  # pragma: no cover - defensive worker boundary
                    responses.put((None, exc))

            reader = threading.Thread(target=read_response, daemon=True)
            reader.start()
            timeout = self.operation_timeouts.get(operation, 60.0)
            try:
                response_line, read_error = responses.get(timeout=timeout)
            except queue.Empty as exc:
                error = BackendError(
                    f"The HWP worker did not respond to {operation!r} within {timeout:g} seconds. "
                    "Call shutdown before starting a replacement worker.",
                    code="HWP_WORKER_TIMEOUT",
                )
                self._stuck_error = error
                raise error from exc
            if read_error is not None:
                self.shutdown()
                raise BackendError("The HWP worker response could not be read.") from read_error

            if not response_line:
                self.shutdown()
                raise BackendError(
                    "The HWP worker returned no response. Check that Hancom Office 2022 is ready."
                )

            try:
                response = json.loads(response_line)
            except json.JSONDecodeError as exc:
                self.shutdown()
                raise BackendError("The HWP worker returned an invalid response.") from exc
            if response.get("id") != request_id:
                self.shutdown()
                raise BackendError("The HWP worker response did not match its request.")
            if not response.get("ok"):
                error = response.get("error") or {}
                message = error.get("message") or "Unknown HWP worker error."
                raise BackendError(str(message))
            result = response.get("result")
            if not isinstance(result, dict):
                self.shutdown()
                raise BackendError("The HWP worker returned an invalid result.")
            return result

    @staticmethod
    def _context(data: dict[str, Any]) -> BackendContext:
        return BackendContext(
            document_id=data.get("document_id"),
            text=str(data.get("text") or ""),
            fingerprint=data.get("fingerprint"),
            context_verified=bool(data.get("context_verified")),
            unsaved=bool(data.get("unsaved", True)),
        )

    def status(self) -> dict[str, Any]:
        return self._call("status")

    def start_new_document(self) -> BackendContext:
        return self._context(self._call("start_new_document"))

    def read_context(self) -> BackendContext:
        return self._context(self._call("read_context"))

    def apply_edits(self, edits: list[DocumentEdit]) -> BackendApplyResult:
        result = self._call(
            "apply_edits",
            {"edits": [edit.model_dump(mode="json", exclude_none=True) for edit in edits]},
        )
        return BackendApplyResult(
            context=self._context(result.get("context") or {}),
            native_undo_count=int(result.get("native_undo_count") or 1),
            warnings=tuple(str(item) for item in result.get("warnings") or []),
        )

    def undo(self, native_undo_count: int) -> BackendContext:
        return self._context(self._call("undo", {"native_undo_count": native_undo_count}))

    def shutdown(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            self._stuck_error = None
            if process is None:
                return
            if process.poll() is None:
                try:
                    if process.stdin is not None:
                        request = {
                            "id": uuid.uuid4().hex,
                            "operation": "shutdown",
                            "params": {},
                        }
                        process.stdin.write(json.dumps(request) + "\n")
                        process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                try:
                    process.terminate()
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                except OSError:
                    pass
