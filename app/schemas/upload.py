"""Schemas for the presign upload flow."""

from pydantic import BaseModel, Field


class FilePresignRequest(BaseModel):
    file_name: str = Field(..., description="Original filename for display and extension inference")
    content_type: str = Field(..., description="MIME type, e.g. 'application/pdf' or 'image/jpeg'")
    size_bytes: int = Field(..., gt=0, description="File size in bytes (informational, enforced by S3)")


class PresignRequest(BaseModel):
    files: list[FilePresignRequest] = Field(..., min_length=1, max_length=30)


class PresignedUploadOut(BaseModel):
    file_name: str
    file_key: str
    file_url: str
    presigned_url: str
    presigned_fields: dict


class PresignResponse(BaseModel):
    status: str = "success"
    uploads: list[PresignedUploadOut]
