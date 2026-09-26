"""Test the promoted gate through the real service with an in-memory backend."""
import asyncio
import importlib.util
from pathlib import Path

import pytest

from hwp_live.backends import FakeHwpBackend
from hwp_live.models import DocumentEdit
from hwp_live.service import HwpLiveError, HwpLiveService

spec = importlib.util.spec_from_file_location("native_release_gate", Path(__file__).resolve().parents[1] / "scripts" / "native_release_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def make_fake_session():
    backend = FakeHwpBackend()
    service = HwpLiveService(backend)
    calls = []

    async def call(name, args):
        calls.append(name)
        try:
            if name == "hwp_start_new_document":
                key, value = "document", service.start_new_document()
            elif name == "hwp_read_context":
                key, value = "document", service.read_context()
            elif name == "hwp_preview_edits":
                key, value = "preview", service.preview_edits([DocumentEdit(**edit) for edit in args["edits"]], args["expected_revision"])
            elif name == "hwp_apply_preview":
                key, value = "receipt", service.apply_preview(args["plan_id"])
            elif name == "hwp_undo_last":
                key, value = "document", service.undo_last(args["expected_revision"])
            else:
                pytest.fail("Unexpected tool " + name)
            return {"ok": True, key: value.model_dump(mode="json")}
        except HwpLiveError as exc:
            return exc.as_dict()

    return backend, calls, call


def test_gate_exercises_contract_sequence_without_claiming_native_or_visual_evidence():
    backend, calls, call = make_fake_session()

    def checkpoint(message):
        if "manually type MANUAL-STALE" in message:
            backend.mutate_externally("MANUAL-STALE")
        if "manually type MANUAL-UNDO" in message:
            backend.mutate_externally("MANUAL-UNDO")

    result = asyncio.run(gate.run_gate(call, checkpoint))
    assert result["contract_sequence_passed"]
    assert result["owned_document_id"] == backend.document_id
    assert "native_contract_passed" not in result
    assert "visual_checkpoints_acknowledged" not in result
    assert not result["profile_tested"] and not result["foreground_tested"]
    assert calls[0] == "hwp_start_new_document"
    assert backend.save_call_count == 0


@pytest.mark.parametrize("changed_field", ["document_id", "context_verified", "unsaved"])
def test_gate_stops_if_owned_document_cannot_be_verified(changed_field):
    _, calls, call = make_fake_session()

    async def invalid_read(name, args):
        response = await call(name, args)
        if name == "hwp_read_context":
            document = response["document"]
            document[changed_field] = (
                "different-document" if changed_field == "document_id" else False
            )
        return response

    with pytest.raises(RuntimeError, match="document|verifiably readable"):
        asyncio.run(gate.run_gate(invalid_read, lambda _: None))
    assert "hwp_preview_edits" not in calls
    assert "hwp_apply_preview" not in calls


def test_gate_refuses_an_apply_receipt_with_an_inconsistent_revision():
    _, calls, call = make_fake_session()

    async def invalid_receipt(name, args):
        response = await call(name, args)
        if name == "hwp_apply_preview":
            response["receipt"]["revision"] += 1
        return response

    with pytest.raises(RuntimeError, match="Apply did not advance"):
        asyncio.run(gate.run_gate(invalid_receipt, lambda _: None))
    assert "hwp_apply_preview" in calls
    assert "hwp_undo_last" not in calls


def test_cancel_before_start_makes_no_calls():
    async def call(*args):
        pytest.fail("Must not call MCP")
    def cancel(_):
        raise RuntimeError("cancelled")
    with pytest.raises(RuntimeError, match="cancelled"):
        asyncio.run(gate.run_gate(call, cancel))


@pytest.mark.parametrize("answer", ["", "yes", "NO"])
def test_confirmation_requires_explicit_yes(monkeypatch, answer):
    monkeypatch.setattr("builtins.input", lambda _: answer)
    with pytest.raises(RuntimeError, match="cancelled"):
        gate.confirm("test")
