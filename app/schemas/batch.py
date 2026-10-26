"""Shared schemas for batch-based uploads.

Every upload endpoint (documents, images, extractions) returns the same
BatchCreatedResponse shape. The FE renders the batch progress screen
from this uniform contract, regardless of file type.
"""

from datetime import datetime

from pydantic import BaseModel, Field


# =========================================================
# FILE INPUT
# =========================================================

class FileInput(BaseModel):
    """One file to be uploaded in a batch."""
    url: str = Field(..., description="S3 (or similar) URL of the uploaded file")
    file_name: str = Field(..., description="Original filename, for display")
    file_type: str = Field(
        ...,
        description="File extension without the dot, e.g. 'pdf', 'jpg'",
    )


# =========================================================
# JOB LIST ITEM (returned immediately after create)
# =========================================================

class BatchJobItem(BaseModel):
    """One child job in the create response."""
    id: str = Field(..., description="The child job's id (job_id or extraction_id)")
    file_name: str
    status: str = Field(..., description="Initial status — usually 'pending'")


# =========================================================
# CREATE RESPONSE (202 from all three POSTs)
# =========================================================

class BatchCreatedResponse(BaseModel):
    status: str = "success"
    batch_id: str
    total_files: int
    jobs: list[BatchJobItem]


# =========================================================
# BATCH DETAIL (for GET /batch/{id})
# =========================================================

class BatchJobStatusItem(BaseModel):
    """One child job's current state, shown on the progress screen."""
    id: str
    file_name: str
    status: str
    error: str | None = None
    page_count: int | None = None


class BatchOut(BaseModel):
    """Full batch state — aggregate counters + per-file rows."""
    batch_id: str
    kind: str  # document | image | extraction
    template_id: str | None = None
    label: str | None = None

    total_files: int
    pending_files: int
    in_progress_files: int
    completed_files: int
    failed_files: int

    status: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    jobs: list[BatchJobStatusItem]


class BatchListItem(BaseModel):
    """Lightweight batch for the history / recent uploads list."""
    batch_id: str
    kind: str
    template_id: str | None = None
    label: str | None = None
    total_files: int
    completed_files: int
    failed_files: int
    status: str
    created_at: datetime
    completed_at: datetime | None = None
