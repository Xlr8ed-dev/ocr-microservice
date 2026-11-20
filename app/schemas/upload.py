"""Schemas for the presign upload flow.

The canonical body is:

    {"files": [{"file_name": ..., "content_type": ..., "size_bytes": ...}]}

Two lenient forms are also accepted so an older FE build keeps working:

  * a single bare file object instead of a `files` array, and
  * `file_size` (or `size`) instead of `size_bytes`.

The stored/returned shape is always the canonical one, so nothing downstream
has to know about the aliases.
"""

from typing import Any

from pydantic import AliasChoices, BaseModel, Field, model_validator


class FilePresignRequest(BaseModel):
    file_name: str = Field(
        ...,
        description="Original filename for display and extension inference",
    )
    content_type: str = Field(
        ...,
        description="MIME type, e.g. 'application/pdf' or 'image/jpeg'",
    )
    size_bytes: int = Field(
        ...,
        gt=0,
        validation_alias=AliasChoices("size_bytes", "file_size", "size"),
        description=(
            "File size in bytes (informational, enforced by S3). "
            "`file_size` and `size` are accepted as aliases."
        ),
    )


class PresignRequest(BaseModel):
    files: list[FilePresignRequest] = Field(
        ...,
        min_length=1,
        max_length=30,
        description="1 to 30 files to upload",
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_single_file(cls, data: Any) -> Any:
        """Wrap a single file object into the canonical `files` array.

        Covers both mistakes in one place:
          * `{"file_name": ...}`          -> `{"files": [{...}]}`
          * `{"files": {...}}`            -> `{"files": [{...}]}`
        """
        if not isinstance(data, dict):
            return data

        files = data.get("files")

        if isinstance(files, dict):
            return {**data, "files": [files]}

        if files is None and (
            "file_name" in data or "content_type" in data or "url" in data
        ):
            return {"files": [data]}

        return data


class PresignedUploadOut(BaseModel):
    file_name: str
    file_key: str
    file_url: str
    presigned_url: str
    presigned_fields: dict


class PresignResponse(BaseModel):
    status: str = "success"
    uploads: list[PresignedUploadOut]
