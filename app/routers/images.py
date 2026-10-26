"""Image OCR endpoints.

Fixed set of image types, each with its own prompt. Same job model as
documents: insert a row, enqueue the task, poll for the result.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, current_user
from app.models import ImageOCRJob, ImageOCRStatus, ImageOCRType
from app.schemas.common import PaginatedResponse
from app.schemas.image import (
    ImageAccepted,
    ImageCreateRequest,
    ImageJobOut,
    ImageListOut,
    ImageTypeInfo,
    ImageTypeListOut,
)
from app.services.image_prompts import IMAGE_TYPE_META
from app.tasks.image_tasks import run_image_ocr
from app.utils.pagination import DEFAULT_PAGE_SIZE, build_meta, parse_page

router = APIRouter(prefix="/images", tags=["Images"])


# =========================================================
# TYPES CATALOG (for the FE dropdown)
# =========================================================

@router.get("/types", response_model=ImageTypeListOut)
async def list_image_types() -> ImageTypeListOut:
    """Supported image types with labels and descriptions."""
    return ImageTypeListOut(
        data=[
            ImageTypeInfo(
                key=t.value,
                label=meta["label"],
                description=meta["description"],
            )
            for t, meta in IMAGE_TYPE_META.items()
        ],
    )


# =========================================================
# CREATE
# =========================================================

@router.post(
    "",
    response_model=ImageAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_image_job(
        data: ImageCreateRequest,
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> ImageAccepted:
    try:
        image_type = ImageOCRType(data.image_type)
    except ValueError:
        raise HTTPException(
            400,
            f"Unsupported image_type: {data.image_type}. "
            f"Call GET /images/types for the list.",
        )

    job = ImageOCRJob(
        job_id=str(uuid.uuid4()),
        admin_id=user.admin_id,
        user_id=user.id,
        source_url=data.source_url,
        image_type=image_type,
        status=ImageOCRStatus.PENDING,
    )
    db.add(job)
    await db.flush()

    run_image_ocr.apply_async(args=[job.job_id])

    return ImageAccepted(
        job_id=job.job_id,
        job_status=job.status.value,
    )


# =========================================================
# GET ONE
# =========================================================

@router.get("/{job_id}", response_model=ImageJobOut)
async def get_image_job(
        job_id: str,
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> ImageJobOut:
    job = await _get_job_scoped(db, job_id, user)
    return _job_to_out(job)


# =========================================================
# LIST
# =========================================================

@router.get("", response_model=PaginatedResponse[ImageListOut])
async def list_image_jobs(
        page: int = Query(1, ge=1),
        items: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=200),
        job_status: str | None = Query(None, alias="status"),
        image_type: str | None = Query(None),
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ImageListOut]:
    p = parse_page(page, items)

    base = select(ImageOCRJob)
    if user.role != "SUPER_ADMIN":
        base = base.where(ImageOCRJob.admin_id == user.admin_id)

    if job_status:
        try:
            status_enum = ImageOCRStatus(job_status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {job_status}")
        base = base.where(ImageOCRJob.status == status_enum)

    if image_type:
        try:
            type_enum = ImageOCRType(image_type)
        except ValueError:
            raise HTTPException(400, f"Invalid image_type: {image_type}")
        base = base.where(ImageOCRJob.image_type == type_enum)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.scalar(count_stmt)) or 0

    stmt = (
        base.order_by(ImageOCRJob.created_at.desc())
        .limit(p.limit)
        .offset(p.offset)
    )
    rows = list((await db.scalars(stmt)).all())

    return PaginatedResponse[ImageListOut](
        data=[ImageListOut.model_validate(r) for r in rows],
        pagination=build_meta(total, p),
    )


# =========================================================
# DELETE
# =========================================================

@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_image_job(
        job_id: str,
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> None:
    if user.role not in ("ADMIN", "SUPER_ADMIN"):
        raise HTTPException(403, "Only admins can delete image jobs.")

    job = await _get_job_scoped(db, job_id, user)
    await db.delete(job)
    await db.flush()


# =========================================================
# HELPERS
# =========================================================

async def _get_job_scoped(
        db: AsyncSession, job_id: str, user: CurrentUser,
) -> ImageOCRJob:
    stmt = select(ImageOCRJob).where(ImageOCRJob.job_id == job_id)
    if user.role != "SUPER_ADMIN":
        stmt = stmt.where(ImageOCRJob.admin_id == user.admin_id)
    job = await db.scalar(stmt)
    if not job:
        raise HTTPException(404, "Image job not found.")
    return job


def _job_to_out(job: ImageOCRJob) -> ImageJobOut:
    return ImageJobOut(
        job_id=job.job_id,
        admin_id=job.admin_id,
        user_id=job.user_id,
        source_url=job.source_url,
        image_type=job.image_type.value if hasattr(job.image_type, "value") else job.image_type,
        status=job.status.value if hasattr(job.status, "value") else job.status,
        output=job.output,
        error=job.error,
        cost_estimate=job.cost_estimate,
        ai_calls=job.ai_calls,
        ai_tokens_in=job.ai_tokens_in,
        ai_tokens_out=job.ai_tokens_out,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )
