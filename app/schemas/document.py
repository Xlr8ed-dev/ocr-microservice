"""Schemas for the document OCR API.

Two sections:
  - Job lifecycle: create request, job detail, list item
  - Block types: the shape of `output.blocks[]`

Block types use a discriminated union so Pydantic validates each block
against its own model based on the `type` field.
"""

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.batch import FileInput


# =========================================================
# BLOCK TYPES
# =========================================================

class HeadingBlock(BaseModel):
    type: Literal["heading"] = "heading"
    level: int = Field(..., ge=1, le=6)
    text: str
    page: int | None = None


class ParagraphBlock(BaseModel):
    type: Literal["paragraph"] = "paragraph"
    text: str
    page: int | None = None


class ListBlock(BaseModel):
    type: Literal["list"] = "list"
    ordered: bool = False
    items: list[str] = Field(default_factory=list)
    page: int | None = None


class TableBlock(BaseModel):
    type: Literal["table"] = "table"
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    caption: str | None = None
    page: int | None = None


class PageBreakBlock(BaseModel):
    type: Literal["page_break"] = "page_break"
    page: int


class ImageBlock(BaseModel):
    """An embedded image we detected but did not OCR."""
    type: Literal["image"] = "image"
    page: int
    description: str | None = None


Block = Annotated[
    Union[
        HeadingBlock,
        ParagraphBlock,
        ListBlock,
        TableBlock,
        PageBreakBlock,
        ImageBlock,
    ],
    Field(discriminator="type"),
]


# =========================================================
# OUTPUT ENVELOPE
# =========================================================

class DocumentMetadata(BaseModel):
    page_count: int | None = None
    language: str | None = None
    extraction_method: str | None = None   # pdf_text | pdf_scan | docx | doc | txt
    chunk_count: int | None = None
    char_count: int | None = None
    processing_time_ms: int | None = None


class DocumentOutput(BaseModel):
    title: str | None = None
    blocks: list[Block] = Field(default_factory=list)
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)


# =========================================================
# REQUEST / RESPONSE
# =========================================================

class DocumentBatchCreateRequest(BaseModel):
    """Create a batch of document OCR jobs. 1 to 30 files.

    Accepted file_type values: pdf | docx | txt.
    """
    files: list[FileInput] = Field(
        ...,
        min_length=1,
        max_length=30,
        description="1 to 30 files. All must be document types.",
    )
    label: str | None = Field(
        default=None,
        max_length=255,
        description="Optional user-facing label for the batch",
    )


# class DocumentAccepted(BaseModel):
#     status: str = "success"
#     job_id: str
#     job_status: str
#     message: str | None = None


class DocumentJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    admin_id: int
    user_id: int

    source_url: str
    file_name: str | None = None
    file_type: str
    file_size_bytes: int | None = None

    status: str
    progress: int = 0
    page_count: int | None = None
    chunk_count: int | None = None
    ai_calls: int = 0
    ai_tokens_in: int = 0
    ai_tokens_out: int = 0

    output: DocumentOutput | None = None
    error: str | None = None

    cost_estimate: float | None = None

    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class DocumentListOut(BaseModel):
    """Lighter shape for list endpoints — no `output`, no `raw_chunks`."""

    model_config = ConfigDict(from_attributes=True)

    job_id: str
    file_name: str | None = None
    file_type: str
    status: str
    progress: int = 0
    page_count: int | None = None
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None