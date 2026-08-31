"""Validated, intentionally small document-editing vocabulary."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class TextStyle(BaseModel):
    """Formatting supported for text inserted by version 0.1."""

    font_size_pt: float | None = Field(default=None, ge=1, le=200)
    bold: bool = False
    align: Literal["left", "center", "right", "justify"] | None = None


class TableStyle(BaseModel):
    """Formatting supported for a newly inserted table."""

    first_row_is_header: bool = True
    header_bold: bool = True
    header_fill: str | None = Field(
        default=None,
        pattern=r"^#[0-9A-Fa-f]{6}$",
        description="Optional RGB color, for example #1F4E78.",
    )


class DocumentEdit(BaseModel):
    """One allowlisted insertion operation."""

    kind: Literal["insert_text", "insert_table"]
    text: str | None = Field(default=None, max_length=20_000)
    new_paragraph_after: bool = True
    style: TextStyle | None = None
    rows: int | None = Field(default=None, ge=1, le=100)
    cols: int | None = Field(default=None, ge=1, le=30)
    cells: list[list[str]] | None = None
    table_style: TableStyle | None = None

    @model_validator(mode="after")
    def validate_edit(self) -> "DocumentEdit":
        if self.kind == "insert_text":
            if not self.text or not self.text.strip():
                raise ValueError("insert_text requires non-empty text.")
            if any(value is not None for value in (self.rows, self.cols, self.cells)):
                raise ValueError("insert_text cannot include table fields.")
            if self.table_style is not None:
                raise ValueError("insert_text cannot include table_style.")
            return self

        if self.rows is None or self.cols is None:
            raise ValueError("insert_table requires rows and cols.")
        if self.rows * self.cols > 200:
            raise ValueError("insert_table supports at most 200 cells in version 0.1.")
        if self.text is not None:
            raise ValueError("insert_table cannot include text.")
        if self.style is not None:
            raise ValueError("insert_table cannot include text style.")
        if self.cells is not None:
            if len(self.cells) > self.rows:
                raise ValueError("cells has more rows than rows.")
            if any(len(row) > self.cols for row in self.cells):
                raise ValueError("cells has more columns than cols.")
            if any(len(cell) > 4_000 for row in self.cells for cell in row):
                raise ValueError("A table cell cannot exceed 4,000 characters.")
        if self.cells is None or not any(
            cell.strip() for row in self.cells for cell in row
        ):
            raise ValueError(
                "insert_table requires at least one non-empty cell in version 0.1."
            )
        return self


class ContextView(BaseModel):
    document_id: str | None
    revision: int
    fingerprint: str | None
    text: str
    context_verified: bool
    unsaved: bool
    note: str | None = None


class PreviewView(BaseModel):
    plan_id: str
    expected_revision: int
    expires_at: str
    summary: str
    effects: list[str]
    warnings: list[str] = Field(default_factory=list)


class ReceiptView(BaseModel):
    receipt_id: str
    revision: int
    summary: str
    undo_available: bool
    warnings: list[str] = Field(default_factory=list)
