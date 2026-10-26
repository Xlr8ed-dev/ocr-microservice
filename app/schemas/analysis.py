"""Schemas for analysis endpoints (summarize + classify).

Documents: combined summary + category + confidence + tags.
Images: summary + tags only (type already known).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# =========================================================
# CREATE REQUESTS
# =========================================================

class DocumentAnalyzeRequest(BaseModel):
    categories: list[str] | None = Field(
        default=None,
        description="Override the default category list. "
                    "If omitted, the service uses its built-in list.",
    )
    max_words: int = Field(
        default=250, ge=50, le=1000,
        description="Target length of the summary in words.",
    )


class ImageAnalyzeRequest(BaseModel):
    max_words: int = Field(
        default=100, ge=30, le=300,
        description="Target length of the summary in words.",
    )


# =========================================================
# ACCEPTED (202 responses)
# =========================================================

class AnalysisAccepted(BaseModel):
    status: str = "success"
    analysis_id: str
    analysis_status: str
    message: str | None = None


# =========================================================
# OUTPUT
# =========================================================

class DocumentAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    job_id: str
    admin_id: int
    user_id: int

    summary: str | None = None
    category: str | None = None
    subcategory: str | None = None
    confidence: float | None = None
    tags: list[str] | None = None

    status: str
    error: str | None = None

    ai_calls: int = 0
    ai_tokens_in: int = 0
    ai_tokens_out: int = 0

    prompt_version: str | None = None
    categories_used: list[str] | None = None
    max_words_used: int | None = None

    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class DocumentAnalysisListItem(BaseModel):
    """Lightweight item for list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    job_id: str
    status: str
    category: str | None = None
    confidence: float | None = None
    created_at: datetime
    completed_at: datetime | None = None


class ImageAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    job_id: str
    admin_id: int
    user_id: int

    summary: str | None = None
    tags: list[str] | None = None

    status: str
    error: str | None = None

    ai_calls: int = 0
    ai_tokens_in: int = 0
    ai_tokens_out: int = 0

    prompt_version: str | None = None
    max_words_used: int | None = None

    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ImageAnalysisListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    job_id: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None