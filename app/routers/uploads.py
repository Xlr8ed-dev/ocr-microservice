"""Endpoints for direct-to-S3 uploads."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import CurrentUser, current_user
from app.schemas.upload import (
    PresignRequest,
    PresignResponse,
    PresignedUploadOut,
)
from app.services import s3_service

router = APIRouter(prefix="/uploads", tags=["Uploads"])


@router.post(
    "/presign",
    response_model=PresignResponse,
    status_code=status.HTTP_200_OK,
)
async def create_presigned_uploads(
        data: PresignRequest,
        user: CurrentUser = Depends(current_user),
) -> PresignResponse:
    """Generate presigned POST URLs for N files.

    The FE uploads each file directly to S3 using the returned
    `presigned_url` + `presigned_fields`. Then calls POST /documents
    (or /images, /extractions) with the resulting `file_url`.
    """
    uploads: list[PresignedUploadOut] = []
    max_bytes = s3_service.settings.S3_UPLOAD_MAX_MB * 1024 * 1024

    for f in data.files:
        if f.size_bytes > max_bytes:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"File '{f.file_name}' exceeds the {s3_service.settings.S3_UPLOAD_MAX_MB} MB limit.",
            )

        try:
            presigned_url, fields, file_key = s3_service.generate_presigned_post(
                admin_id=user.admin_id,
                file_name=f.file_name,
                content_type=f.content_type,
            )
        except RuntimeError as exc:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))

        uploads.append(PresignedUploadOut(
            file_name=f.file_name,
            file_key=file_key,
            file_url=s3_service.build_file_url(file_key),
            presigned_url=presigned_url,
            presigned_fields=fields,
        ))

    return PresignResponse(uploads=uploads)
