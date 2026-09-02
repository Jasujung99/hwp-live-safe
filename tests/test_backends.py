from __future__ import annotations

import io
import threading
import time

import pytest

from hwp_live.backends import BackendError, PowerShellHwpBackend


class FakeProcess:
    def __init__(self, stdout: object) -> None:
        self.stdin = io.StringIO()
        self.stdout = stdout
        self.terminated = False

    def poll(self) -> int | None:
        return None if not self.terminated else 0

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        self.terminated = True


class BlockingStdout:
    def __init__(self) -> None:
        self.release = threading.Event()

    def readline(self) -> str:
        self.release.wait()
        return ""


def backend_with_process(process: FakeProcess, timeout: float = 0.02) -> PowerShellHwpBackend:
    backend = PowerShellHwpBackend(operation_timeouts={"status": timeout})
    backend._process = process  # type: ignore[assignment]
    return backend


def test_call_times_out_and_does_not_start_a_second_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    stdout = BlockingStdout()
    process = FakeProcess(stdout)
    backend = backend_with_process(process)
    calls = 0

    def ensure_process() -> FakeProcess:
        nonlocal calls
        calls += 1
        return process

    monkeypatch.setattr(backend, "_ensure_process", ensure_process)
    started = time.monotonic()
    with pytest.raises(BackendError) as caught:
        backend.status()
    assert caught.value.code == "HWP_WORKER_TIMEOUT"
    assert time.monotonic() - started < 0.5

    with pytest.raises(BackendError) as repeated:
        backend.status()
    assert repeated.value.code == "HWP_WORKER_TIMEOUT"
    assert calls == 1
    assert process.stdin.getvalue().count("\n") == 1

    stdout.release.set()
    backend.shutdown()


@pytest.mark.parametrize("response", ["not json\n", '{"id":"wrong","ok":true,"result":{}}\n'])
def test_protocol_errors_reset_the_worker(response: str) -> None:
    process = FakeProcess(io.StringIO(response))
    backend = backend_with_process(process)

    with pytest.raises(BackendError):
        backend.status()

    assert backend._process is None
    assert process.terminated


def test_timeout_values_must_be_positive() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        PowerShellHwpBackend(operation_timeouts={"status": 0})
