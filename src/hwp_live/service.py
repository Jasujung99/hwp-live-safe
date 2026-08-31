"""Safety layer between an AI client and a live Hancom document."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from uuid import uuid4

from .backends import BackendContext, BackendError, HwpBackend
from .models import ContextView, DocumentEdit, PreviewView, ReceiptView, TextStyle
from .profile import ProfileError, ProfileStore


class HwpLiveError(RuntimeError):
    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": str(self),
                **({"detail": self.detail} if self.detail else {}),
            },
        }


@dataclass(frozen=True)
class ProfileRequirement:
    profile_id: str
    key: str
    value_hash: str


@dataclass(frozen=True)
class PreviewPlan:
    plan_id: str
    expected_revision: int
    before_fingerprint: str
    edits: tuple[DocumentEdit, ...]
    expires_at: datetime
    summary: str
    effects: tuple[str, ...]
    warnings: tuple[str, ...]
    profile_requirements: tuple[ProfileRequirement, ...] = ()


@dataclass(frozen=True)
class ApplyReceipt:
    receipt_id: str
    revision: int
    before_fingerprint: str
    after_fingerprint: str
    native_undo_count: int
    summary: str
    warnings: tuple[str, ...]


class HwpLiveService:
    """Preview-first document mutations with external-change protection."""

    max_context_chars = 12_000

    def __init__(
        self,
        backend: HwpBackend,
        *,
        plan_ttl_seconds: int = 60,
        now: Callable[[], datetime] | None = None,
        profile_store: ProfileStore | None = None,
    ) -> None:
        self.backend = backend
        self.plan_ttl_seconds = plan_ttl_seconds
        self._now = now or (lambda: datetime.now(UTC))
        self.profile_store = profile_store or ProfileStore()
        self._session_id: str | None = None
        self._revision = 0
        self._context: BackendContext | None = None
        self._plans: dict[str, PreviewPlan] = {}
        self._last_receipt: ApplyReceipt | None = None

    def status(self) -> dict[str, Any]:
        try:
            status = dict(self.backend.status())
        except BackendError as exc:
            return {
                "ok": False,
                "error": {"code": "HWP_NOT_READY", "message": str(exc)},
                "backend": "powershell-com",
            }
        status.update(
            {
                "ok": True,
                "session_id": self._session_id,
                "revision": self._revision,
                "active_document_id": self._context.document_id if self._context else None,
                "pending_previews": len(self._plans),
                "last_change_can_be_undone": self._last_receipt is not None,
                "safety": {
                    "opens_existing_files": False,
                    "saves_files": False,
                    "closes_documents": False,
                    "mutations_require_preview": True,
                },
            }
        )
        return status

    def start_new_document(self) -> ContextView:
        try:
            context = self.backend.start_new_document()
        except BackendError as exc:
            raise HwpLiveError("HWP_START_FAILED", str(exc)) from exc
        self._session_id = uuid4().hex
        self._revision = 1
        self._context = context
        self._plans.clear()
        self._last_receipt = None
        return self._context_view(context)

    def read_context(self) -> ContextView:
        context, changed = self._refresh_context()
        note = None
        if changed:
            note = (
                "The open document changed outside HWP Live. "
                "Pending previews and the previous undo receipt were discarded."
            )
        return self._context_view(context, note=note)

    def preview_edits(
        self,
        edits: list[DocumentEdit],
        expected_revision: int,
    ) -> PreviewView:
        return self._preview_edits(edits, expected_revision)

    def profile_list(self) -> dict[str, Any]:
        """Return profile metadata only; values never leave the local store."""

        try:
            keys = self.profile_store.list_keys()
        except ProfileError as exc:
            raise HwpLiveError("PROFILE_UNAVAILABLE", str(exc)) from exc
        return {
            "profiles": [
                {
                    "profile_id": item.profile_id,
                    "profile_label": item.profile_label,
                    "key": item.key,
                    "label": item.label,
                    "sensitivity": item.sensitivity,
                    "configured": item.configured,
                }
                for item in keys
            ],
            "note": (
                "Profile values are intentionally not returned. Copy profile.example.json "
                "to the configured local profile folder and fill it there."
                if not keys
                else "Profile values are intentionally not returned."
            ),
        }

    def preview_profile_insert(
        self,
        profile_id: str,
        key: str,
        expected_revision: int,
        *,
        new_paragraph_after: bool = False,
        style: TextStyle | None = None,
    ) -> PreviewView:
        """Create a private text plan from a local profile value.

        The resolved value remains inside this service and its PowerShell pipe;
        only the field label is returned in the public preview.
        """

        try:
            value = self.profile_store.resolve(profile_id, key)
        except ProfileError as exc:
            raise HwpLiveError("PROFILE_UNAVAILABLE", str(exc)) from exc
        edit = DocumentEdit(
            kind="insert_text",
            text=value.value,
            new_paragraph_after=new_paragraph_after,
            style=style,
        )
        return self._preview_edits(
            [edit],
            expected_revision,
            summary_override="local profile insertion",
            effects_override=[
                f"Insert the locally stored “{value.label}” field from profile “{value.profile_label}”."
            ],
            warnings_override=[
                "The profile value is not included in this preview or MCP response. "
                "Confirm that the visible caret is in the intended form cell."
            ],
            profile_requirements=(
                ProfileRequirement(
                    profile_id=value.profile_id,
                    key=value.key,
                    value_hash=value.value_hash,
                ),
            ),
        )

    def _preview_edits(
        self,
        edits: list[DocumentEdit],
        expected_revision: int,
        *,
        summary_override: str | None = None,
        effects_override: list[str] | None = None,
        warnings_override: list[str] | None = None,
        profile_requirements: tuple[ProfileRequirement, ...] = (),
    ) -> PreviewView:
        if not edits:
            raise HwpLiveError("EMPTY_EDIT", "At least one document edit is required.")
        if len(edits) > 1:
            raise HwpLiveError(
                "EDIT_BATCH_UNSUPPORTED",
                "Version 0.2 applies one text block or one table per preview. "
                "Create the next preview after the read-back.",
            )
        context, changed = self._refresh_context()
        if changed:
            raise HwpLiveError(
                "DOCUMENT_CHANGED",
                "The open document changed outside HWP Live. Read it again before creating a preview.",
                {"current_revision": self._revision},
            )
        if not context.context_verified:
            raise HwpLiveError(
                "CONTEXT_UNVERIFIED",
                "HWP Live could not reliably read the visible document text. "
                "No edit was previewed; verify the Hancom window and try again.",
            )
        self._require_revision(expected_revision)
        if not context.fingerprint:
            raise HwpLiveError("CONTEXT_UNAVAILABLE", "A document fingerprint could not be read.")

        summary, effects, warnings = self._describe(edits)
        if summary_override is not None:
            summary = summary_override
        if effects_override is not None:
            effects = effects_override
        if warnings_override is not None:
            warnings = warnings_override
        now = self._now()
        plan = PreviewPlan(
            plan_id=uuid4().hex,
            expected_revision=self._revision,
            before_fingerprint=context.fingerprint,
            edits=tuple(edit.model_copy(deep=True) for edit in edits),
            expires_at=now + timedelta(seconds=self.plan_ttl_seconds),
            summary=summary,
            effects=tuple(effects),
            warnings=tuple(warnings),
            profile_requirements=profile_requirements,
        )
        self._plans[plan.plan_id] = plan
        return PreviewView(
            plan_id=plan.plan_id,
            expected_revision=plan.expected_revision,
            expires_at=plan.expires_at.isoformat(),
            summary=plan.summary,
            effects=list(plan.effects),
            warnings=list(plan.warnings),
        )

    def apply_preview(self, plan_id: str) -> ReceiptView:
        plan = self._plans.get(plan_id)
        if plan is None:
            raise HwpLiveError(
                "PREVIEW_NOT_FOUND",
                "That preview is unavailable. Create a new preview before editing.",
            )
        if self._now() > plan.expires_at:
            self._plans.pop(plan_id, None)
            raise HwpLiveError(
                "PREVIEW_EXPIRED",
                "That preview expired after 60 seconds. Read the document and create a new one.",
            )

        context, changed = self._refresh_context()
        if changed or context.fingerprint != plan.before_fingerprint:
            self._plans.clear()
            self._last_receipt = None
            raise HwpLiveError(
                "DOCUMENT_CHANGED",
                "The document no longer matches the preview. No change was applied.",
                {"current_revision": self._revision},
            )
        if not context.context_verified:
            raise HwpLiveError(
                "CONTEXT_UNVERIFIED",
                "HWP Live could not verify the document just before applying the preview.",
            )
        self._require_revision(plan.expected_revision)
        self._require_profile_values_unchanged(plan)

        try:
            result = self.backend.apply_edits(list(plan.edits))
        except BackendError as exc:
            raise HwpLiveError("HWP_APPLY_FAILED", str(exc)) from exc
        if not result.context.fingerprint:
            raise HwpLiveError(
                "READBACK_FAILED",
                "Hancom applied the change but HWP Live could not read back a document fingerprint.",
            )

        self._context = result.context
        self._revision += 1
        self._plans.clear()
        receipt = ApplyReceipt(
            receipt_id=uuid4().hex,
            revision=self._revision,
            before_fingerprint=plan.before_fingerprint,
            after_fingerprint=result.context.fingerprint,
            native_undo_count=result.native_undo_count,
            summary=plan.summary,
            warnings=result.warnings,
        )
        self._last_receipt = receipt
        return ReceiptView(
            receipt_id=receipt.receipt_id,
            revision=receipt.revision,
            summary=receipt.summary,
            undo_available=True,
            warnings=list(receipt.warnings),
        )

    def undo_last(self, expected_revision: int) -> ContextView:
        self._require_revision(expected_revision)
        receipt = self._last_receipt
        if receipt is None:
            raise HwpLiveError("NOTHING_TO_UNDO", "There is no unchanged HWP Live edit to undo.")

        context, changed = self._refresh_context()
        if changed or context.fingerprint != receipt.after_fingerprint:
            self._last_receipt = None
            raise HwpLiveError(
                "DOCUMENT_CHANGED",
                "The document changed after HWP Live's last edit, so it will not undo it automatically.",
            )
        try:
            undone = self.backend.undo(receipt.native_undo_count)
        except BackendError as exc:
            raise HwpLiveError("HWP_UNDO_FAILED", str(exc)) from exc
        self._context = undone
        self._revision += 1
        self._plans.clear()
        self._last_receipt = None
        return self._context_view(undone, note="The last HWP Live edit was undone.")

    def _refresh_context(self) -> tuple[BackendContext, bool]:
        try:
            context = self.backend.read_context()
        except BackendError as exc:
            raise HwpLiveError("NO_DOCUMENT", str(exc)) from exc
        if self._context is None:
            self._context = context
            return context, False
        if context.fingerprint != self._context.fingerprint:
            self._context = context
            self._revision += 1
            self._plans.clear()
            self._last_receipt = None
            return context, True
        self._context = context
        return context, False

    def _require_revision(self, expected_revision: int) -> None:
        if self._context is None:
            raise HwpLiveError("NO_DOCUMENT", "Start a new automation-owned document first.")
        if expected_revision != self._revision:
            raise HwpLiveError(
                "REVISION_MISMATCH",
                "The preview was based on an older document state. Read it and create a new preview.",
                {"expected_revision": expected_revision, "current_revision": self._revision},
            )

    def _require_profile_values_unchanged(self, plan: PreviewPlan) -> None:
        for requirement in plan.profile_requirements:
            try:
                current = self.profile_store.resolve(requirement.profile_id, requirement.key)
            except ProfileError as exc:
                self._plans.pop(plan.plan_id, None)
                raise HwpLiveError(
                    "PROFILE_CHANGED",
                    "The local profile changed or became unavailable after this preview. "
                    "No document change was applied.",
                ) from exc
            if current.value_hash != requirement.value_hash:
                self._plans.pop(plan.plan_id, None)
                raise HwpLiveError(
                    "PROFILE_CHANGED",
                    "The local profile changed after this preview. No document change was applied.",
                )

    def _context_view(self, context: BackendContext, note: str | None = None) -> ContextView:
        text = context.text
        if len(text) > self.max_context_chars:
            text = text[: self.max_context_chars]
            suffix = f"Read-back text was truncated to {self.max_context_chars:,} characters."
            note = f"{note} {suffix}".strip() if note else suffix
        if not context.context_verified:
            suffix = "Read-back fell back to HWP Live's local insertion log; verify visually in Hancom."
            note = f"{note} {suffix}".strip() if note else suffix
        return ContextView(
            document_id=context.document_id,
            revision=self._revision,
            fingerprint=context.fingerprint,
            text=text,
            context_verified=context.context_verified,
            unsaved=context.unsaved,
            note=note,
        )

    @staticmethod
    def _describe(edits: list[DocumentEdit]) -> tuple[str, list[str], list[str]]:
        text_count = sum(1 for edit in edits if edit.kind == "insert_text")
        table_count = sum(1 for edit in edits if edit.kind == "insert_table")
        chunks: list[str] = []
        if text_count:
            chunks.append(f"text insertion × {text_count}")
        if table_count:
            chunks.append(f"table insertion × {table_count}")
        effects: list[str] = []
        warnings: list[str] = []

        for edit in edits:
            if edit.kind == "insert_text":
                formatting: list[str] = []
                if edit.style and edit.style.font_size_pt:
                    formatting.append(f"{edit.style.font_size_pt:g} pt")
                if edit.style and edit.style.bold:
                    formatting.append("bold")
                if edit.style and edit.style.align:
                    formatting.append(f"{edit.style.align} aligned")
                detail = f" ({', '.join(formatting)})" if formatting else ""
                effects.append(f'Insert “{(edit.text or "")[:80]}”{detail}.')
                continue

            effect = f"Insert a {edit.rows} × {edit.cols} table."
            if edit.table_style and edit.table_style.first_row_is_header:
                effect += " The first row is treated as a header."
            effects.append(effect)
            if edit.table_style and (
                edit.table_style.header_bold or edit.table_style.header_fill
            ):
                warnings.append(
                    "Header bold/fill is requested; verify or style that row visually after the native edit."
                )

        summary = ", ".join(chunks) if chunks else "No document change"
        return summary, effects, warnings
