from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AddressOCR(BaseModel):
    id: int = 0
    address: str = ""
    state: str = ""
    country: str = ""


class OCRResult(BaseModel):
    """The merged OCR output. Matches monolith merged_ocr shape."""

    name: str = ""
    designation: str = ""
    company: str = ""
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    address: list[AddressOCR] = Field(default_factory=list)
    websites: list[str] = Field(default_factory=list)


class OCRJobAccepted(BaseModel):
    job_id: str
    status: str
    txn_id: str


class OCRJobDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    txn_id: str
    job_type: str
    status: str
    result: dict | None = None
    error: str | None = None
    webhook_status: str
    created_at: datetime
    completed_at: datetime | None = None


class OCRCallbackPayload(BaseModel):
    """Payload sent by the OCR worker → this service.

    Matches the callback body defined in the OCR service design."""

    job_id: str
    txn_id: str
    job_type: str                 # ocr_primary | ocr_secondary
    status: str                   # completed | failed
    result: dict | None = None
    error: str | None = None