"""Endpoints for accessing files stored in S3."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.dependencies import CurrentUser, current_user
from app.services import s3_service

router = APIRouter(prefix="/files", tags=["Files"])


class SignedUrlResponse(BaseModel):
    status: str = "success"
    signed_url: str
    expires_in: int


@router.get("/signed-url", response_model=SignedUrlResponse)
async def get_signed_url(
        file_key: str = Query(..., description="The S3 key from the presign response"),
        user: CurrentUser = Depends(current_user),
) -> SignedUrlResponse:
    """Generate a short-lived presigned GET URL for viewing/downloading.

    The caller must be the admin who owns the file (based on key prefix),
    or a SUPER_ADMIN.
    """
    if user.role != "SUPER_ADMIN":
        if not s3_service.is_admin_owner_of_key(user.admin_id, file_key):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You do not have permission to access this file.",
            )

    try:
        signed = s3_service.generate_presigned_get(file_key)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))

    return SignedUrlResponse(signed_url=signed, expires_in=900)
