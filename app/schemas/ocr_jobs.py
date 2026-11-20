"""Schemas for the unified OCR read API.

The FE shows one "All OCR" screen covering both document and image jobs. This
is the light list shape for that screen; the detail endpoint returns the full,
family-specific shape instead (`DocumentJobOut` or `ImageJobOut`), so no data is
lost or flattened.

Named `ocr_jobs` rather than `ocr` because `app.schemas.ocr` already holds the
Vision OCR request/response models.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class OcrJobListItem(BaseModel):
    id: str = Field(..., description="Document job_id or image job_id")
    kind: str = Field(..., description="document | image")
    file_name: str | None = Field(
        default=None,
        description=(
            "Document filename, or the image filename derived from its URL."
        ),
    )
    file_type: str | None = Field(
        default=None,
        description="Document only: pdf_text | pdf_scan | docx | txt",
    )
    image_type: str | None = Field(
        default=None,
        description="Image only: invoice | receipt | visiting_card | ...",
    )
    status: str = Field(..., description="Job status")
    progress: int | None = Field(
        default=None, description="Document only: 0-100"
    )
    page_count: int | None = Field(
        default=None, description="Document only: pages detected"
    )
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
