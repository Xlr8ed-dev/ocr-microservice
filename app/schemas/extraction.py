"""Schemas for the extraction endpoints.

An extraction is one file + one template + one result. The FE sees this
as a single item in the History list, or the detail view after processing.

Shapes are deliberately different for list vs. detail:
  - list: lightweight (no `result`), just status + metadata
  - detail: full `result` with per-field confidence
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# =========================================================
# RESULT SHAPE (per field)
# =========================================================

class ExtractionResultField(BaseModel):
    """One extracted field's value + confidence.

    `value` is intentionally typed as `Any` — a template field can be a
    string, number, date, list, or nested object, depending on the
    template's field type.
    """

    value: Any = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    edited: bool = False
    edited_by: int | None = None
    edited_at: datetime | None = None


# =========================================================
# CREATE REQUEST
# =========================================================

class ExtractionCreateRequest(BaseModel):
    """Create a single-file extraction.

    The file has already been uploaded to S3 (or equivalent) by the FE.
    We just need the URL and metadata to know how to process it.
    """

    template_id: str = Field(..., description="Template id from GET /templates")
    file_url: str = Field(..., description="S3 (or similar) URL of the uploaded file")
    file_name: str = Field(..., description="Original filename, for display")
    file_type: str = Field(
        ...,
        description="One of: pdf | docx | txt | jpg | jpeg | png | webp",
    )

    # Optional: group multiple files under a batch (Phase C will populate this)
    batch_id: str | None = Field(
        default=None,
        description="Optional batch id, if the FE is uploading multiple files at once",
    )


# =========================================================
# ACCEPTED (202 response)
# =========================================================

class ExtractionAccepted(BaseModel):
    status: str = "success"
    extraction_id: str
    extraction_status: str
    message: str | None = None


# =========================================================
# DETAIL
# =========================================================

class ExtractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    batch_id: str | None = None

    admin_id: int
    user_id: int

    template_id: str
    template_version: str

    file_name: str
    file_url: str
    file_type: str
    file_size_bytes: int | None = None

    ocr_job_type: str
    ocr_job_id: str | None = None
    ocr_status: str | None = None

    status: str
    result: dict[str, ExtractionResultField] | None = None
    min_confidence: float | None = None
    review_needed: bool = False
    error: str | None = None

    ai_calls: int = 0
    ai_tokens_in: int = 0
    ai_tokens_out: int = 0
    cost_estimate: float | None = None

    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class ExtractionFieldEdit(BaseModel):
    """One field being edited."""
    key: str = Field(..., description="Field key from the template, e.g. 'full_name'")
    value: Any = Field(..., description="New value for the field")


class ExtractionPatchRequest(BaseModel):
    """PATCH body — one or more field edits.

    Only fields that exist in the template's `fields` list can be edited.
    Keys not in the template are rejected with 400.
    """
    fields: list[ExtractionFieldEdit] = Field(
        ...,
        min_length=1,
        description="List of {key, value} to apply",
    )


# =========================================================
# LIST ITEM
# =========================================================

class ExtractionListItem(BaseModel):
    """Lightweight shape for the History screen."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    batch_id: str | None = None

    template_id: str
    file_name: str
    file_type: str

    status: str
    review_needed: bool = False
    error: str | None = None

    created_at: datetime
    completed_at: datetime | None = None
