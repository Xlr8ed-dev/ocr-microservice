from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.batch import FileInput


# =========================================================
# SUPPORTED TYPES — used by GET /images/types
# =========================================================

class ImageTypeInfo(BaseModel):
    key: str
    label: str
    description: str


class ImageTypeListOut(BaseModel):
    status: str = "success"
    data: list[ImageTypeInfo]


# =========================================================
# REQUEST / RESPONSE
# =========================================================

class ImageBatchCreateRequest(BaseModel):
    """Create a batch of image OCR jobs. 1 to 30 files.

    Accepted file_type values: jpg | jpeg | png | webp.
    All files in the batch share the same image_type.
    """
    image_type: str = Field(
        ...,
        description="One of: invoice | receipt | visiting_card | "
                    "hotel_menu | id_card | handwritten | generic",
    )
    files: list[FileInput] = Field(
        ...,
        min_length=1,
        max_length=30,
    )
    label: str | None = Field(default=None, max_length=255)


# class ImageAccepted(BaseModel):
#     status: str = "success"
#     job_id: str
#     job_status: str
#     message: str | None = None


class ImageJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    admin_id: int
    user_id: int

    source_url: str
    image_type: str
    status: str

    # output shape depends on image_type — see app/services/image_prompts.py
    output: dict | None = None
    error: str | None = None

    cost_estimate: float | None = None
    ai_calls: int = 0
    ai_tokens_in: int = 0
    ai_tokens_out: int = 0

    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ImageListOut(BaseModel):
    """Lighter shape for list endpoints — no `output`, no `raw_response`."""

    model_config = ConfigDict(from_attributes=True)

    job_id: str
    image_type: str
    status: str
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
