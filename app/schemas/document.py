"""Schemas for the document OCR API.

Two sections:
  - Job lifecycle: create request, job detail, list item
  - Block types: the shape of `output.blocks[]`

Block types use a discriminated union so Pydantic validates each block
against its own model based on the `type` field.
"""

from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)

from app.schemas.batch import FileInput

RequestedKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]


# =========================================================
# SUPPORTED DOCUMENT TYPES — used by GET /documents/types
# =========================================================

class DocumentTypeInfo(BaseModel):
    key: str
    label: str
    description: str


class DocumentTypeListOut(BaseModel):
    status: str = "success"
    data: list[DocumentTypeInfo]


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
    document_type: str | None = None       # generic | tender | srs | ...
    chunk_count: int | None = None
    char_count: int | None = None
    processing_time_ms: int | None = None


class DocumentOutput(BaseModel):
    title: str | None = None
    blocks: list[Block] = Field(default_factory=list)
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    # Populated only when the FE sent requested keys / a custom prompt.
    requested: dict[str, Any] | None = None


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
    document_type: str | None = Field(
        default=None,
        description=(
            "Document profile: generic | tender | srs | specification | "
            "report | letter | memo | policy | form | proposal. "
            "Omit or send null for generic."
        ),
    )
    label: str | None = Field(
        default=None,
        max_length=255,
        description="Optional user-facing label for the batch",
    )

    # --- optional user-requested content -------------------------
    keys: list[RequestedKey] | None = Field(
        default=None,
        max_length=50,
        description=(
            "Optional field keys the FE wants extracted as well as normal "
            "OCR (e.g. ['invoice_number', 'total_amount']). The service does "
            "not manage this vocabulary — it only consumes it. Omit for "
            "normal OCR."
        ),
    )
    prompt: str | None = Field(
        default=None,
        max_length=4000,
        validation_alias=AliasChoices("prompt", "custom_prompt"),
        description=(
            "Optional custom extraction instruction to run on top of normal "
            "OCR. Result is stored under output.requested.prompt_result. "
            "`custom_prompt` is accepted as an alias."
        ),
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

    requested_keys: list[str] | None = None
    requested_prompt: str | None = None
    document_type: str | None = None

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