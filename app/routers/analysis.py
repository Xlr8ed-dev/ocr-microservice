"""Analysis endpoints: on-demand summarize + classify.

Documents:
  POST /documents/{job_id}/analyze
  GET  /documents/{job_id}/analysis      (latest)
  GET  /documents/{job_id}/analyses      (paginated history)
  GET  /document-analyses/{analysis_id}  (direct lookup)

Images:
  POST /images/{job_id}/analyze
  GET  /images/{job_id}/analysis         (latest)
  GET  /images/{job_id}/analyses         (paginated history)
  GET  /image-analyses/{analysis_id}     (direct lookup)

All routes require an authenticated user. Cross-tenant access returns 404.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, current_user
from app.models import (
    AnalysisStatus,
    DocumentAnalysis,
    DocumentOCRJob,
    DocumentOCRStatus,
    ImageAnalysis,
    ImageAnalysisStatus,
    ImageOCRJob,
    ImageOCRStatus,
)
from app.schemas.analysis import (
    AnalysisAccepted,
    DocumentAnalysisListItem,
    DocumentAnalysisOut,
    DocumentAnalyzeRequest,
    ImageAnalysisListItem,
    ImageAnalysisOut,
    ImageAnalyzeRequest,
)
from app.schemas.common import PaginatedResponse
from app.services.analysis_prompts import DEFAULT_DOCUMENT_CATEGORIES
from app.tasks.analysis_tasks import (
    run_document_analysis,
    run_image_analysis,
)
from app.utils.pagination import DEFAULT_PAGE_SIZE, build_meta, parse_page

router = APIRouter(tags=["Analysis"])


# =========================================================
# DOCUMENT — create
# =========================================================

@router.post(
    "/documents/{job_id}/analyze",
    response_model=AnalysisAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_document_analysis(
        job_id: str,
        data: DocumentAnalyzeRequest,
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> AnalysisAccepted:
    # --- parent job must exist, belong to caller, be completed --------
    job = await _get_document_job_scoped(db, job_id, user)

    if job.status != DocumentOCRStatus.COMPLETED or not job.output:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Document job is not completed yet (status={job.status.value})",
        )

    # --- resolve categories (optional override) ------------------------
    if data.categories:
        cleaned = [c.strip().lower() for c in data.categories if c and c.strip()]
        if not cleaned:
            raise HTTPException(400, "categories list is empty after cleanup")
        categories = cleaned[:50]  # sanity cap
    else:
        categories = list(DEFAULT_DOCUMENT_CATEGORIES)

    analysis = DocumentAnalysis(
        analysis_id=str(uuid.uuid4()),
        job_id=job_id,
        admin_id=job.admin_id,
        user_id=user.id,
        status=AnalysisStatus.PENDING,
        categories_used=categories,
        max_words_used=data.max_words,
    )
    db.add(analysis)
    await db.flush()

    run_document_analysis.apply_async(args=[analysis.analysis_id])

    return AnalysisAccepted(
        analysis_id=analysis.analysis_id,
        analysis_status=analysis.status.value,
    )


# =========================================================
# DOCUMENT — latest analysis
# =========================================================

@router.get(
    "/documents/{job_id}/analysis",
    response_model=DocumentAnalysisOut,
)
async def get_latest_document_analysis(
        job_id: str,
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> DocumentAnalysisOut:
    # scope check via parent job
    await _get_document_job_scoped(db, job_id, user)

    stmt = (
        select(DocumentAnalysis)
        .where(DocumentAnalysis.job_id == job_id)
        .order_by(DocumentAnalysis.created_at.desc())
        .limit(1)
    )
    analysis = await db.scalar(stmt)
    if not analysis:
        raise HTTPException(404, "No analysis exists for this document yet.")
    return DocumentAnalysisOut.model_validate(analysis)


# =========================================================
# DOCUMENT — analysis history
# =========================================================

@router.get(
    "/documents/{job_id}/analyses",
    response_model=PaginatedResponse[DocumentAnalysisListItem],
)
async def list_document_analyses(
        job_id: str,
        page: int = Query(1, ge=1),
        items: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=200),
        analysis_status: str | None = Query(None, alias="status"),
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[DocumentAnalysisListItem]:
    await _get_document_job_scoped(db, job_id, user)

    p = parse_page(page, items)
    base = select(DocumentAnalysis).where(DocumentAnalysis.job_id == job_id)

    if analysis_status:
        try:
            status_enum = AnalysisStatus(analysis_status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {analysis_status}")
        base = base.where(DocumentAnalysis.status == status_enum)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.scalar(count_stmt)) or 0

    stmt = (
        base.order_by(DocumentAnalysis.created_at.desc())
        .limit(p.limit)
        .offset(p.offset)
    )
    rows = list((await db.scalars(stmt)).all())

    return PaginatedResponse[DocumentAnalysisListItem](
        data=[DocumentAnalysisListItem.model_validate(r) for r in rows],
        pagination=build_meta(total, p),
    )


# =========================================================
# DOCUMENT — direct lookup by analysis_id
# =========================================================

@router.get(
    "/document-analyses/{analysis_id}",
    response_model=DocumentAnalysisOut,
)
async def get_document_analysis_by_id(
        analysis_id: str,
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> DocumentAnalysisOut:
    stmt = select(DocumentAnalysis).where(
        DocumentAnalysis.analysis_id == analysis_id
    )
    if user.role != "SUPER_ADMIN":
        stmt = stmt.where(DocumentAnalysis.admin_id == user.admin_id)

    analysis = await db.scalar(stmt)
    if not analysis:
        raise HTTPException(404, "Analysis not found.")
    return DocumentAnalysisOut.model_validate(analysis)


# =========================================================
# IMAGE — create
# =========================================================

@router.post(
    "/images/{job_id}/analyze",
    response_model=AnalysisAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_image_analysis(
        job_id: str,
        data: ImageAnalyzeRequest,
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> AnalysisAccepted:
    job = await _get_image_job_scoped(db, job_id, user)

    if job.status != ImageOCRStatus.COMPLETED or not job.output:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Image job is not completed yet (status={job.status.value})",
        )

    analysis = ImageAnalysis(
        analysis_id=str(uuid.uuid4()),
        job_id=job_id,
        admin_id=job.admin_id,
        user_id=user.id,
        status=ImageAnalysisStatus.PENDING,
        max_words_used=data.max_words,
    )
    db.add(analysis)
    await db.flush()

    run_image_analysis.apply_async(args=[analysis.analysis_id])

    return AnalysisAccepted(
        analysis_id=analysis.analysis_id,
        analysis_status=analysis.status.value,
    )


# =========================================================
# IMAGE — latest analysis
# =========================================================

@router.get(
    "/images/{job_id}/analysis",
    response_model=ImageAnalysisOut,
)
async def get_latest_image_analysis(
        job_id: str,
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> ImageAnalysisOut:
    await _get_image_job_scoped(db, job_id, user)

    stmt = (
        select(ImageAnalysis)
        .where(ImageAnalysis.job_id == job_id)
        .order_by(ImageAnalysis.created_at.desc())
        .limit(1)
    )
    analysis = await db.scalar(stmt)
    if not analysis:
        raise HTTPException(404, "No analysis exists for this image yet.")
    return ImageAnalysisOut.model_validate(analysis)


# =========================================================
# IMAGE — analysis history
# =========================================================

@router.get(
    "/images/{job_id}/analyses",
    response_model=PaginatedResponse[ImageAnalysisListItem],
)
async def list_image_analyses(
        job_id: str,
        page: int = Query(1, ge=1),
        items: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=200),
        analysis_status: str | None = Query(None, alias="status"),
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ImageAnalysisListItem]:
    await _get_image_job_scoped(db, job_id, user)

    p = parse_page(page, items)
    base = select(ImageAnalysis).where(ImageAnalysis.job_id == job_id)

    if analysis_status:
        try:
            status_enum = ImageAnalysisStatus(analysis_status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {analysis_status}")
        base = base.where(ImageAnalysis.status == status_enum)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.scalar(count_stmt)) or 0

    stmt = (
        base.order_by(ImageAnalysis.created_at.desc())
        .limit(p.limit)
        .offset(p.offset)
    )
    rows = list((await db.scalars(stmt)).all())

    return PaginatedResponse[ImageAnalysisListItem](
        data=[ImageAnalysisListItem.model_validate(r) for r in rows],
        pagination=build_meta(total, p),
    )


# =========================================================
# IMAGE — direct lookup by analysis_id
# =========================================================

@router.get(
    "/image-analyses/{analysis_id}",
    response_model=ImageAnalysisOut,
)
async def get_image_analysis_by_id(
        analysis_id: str,
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> ImageAnalysisOut:
    stmt = select(ImageAnalysis).where(
        ImageAnalysis.analysis_id == analysis_id
    )
    if user.role != "SUPER_ADMIN":
        stmt = stmt.where(ImageAnalysis.admin_id == user.admin_id)

    analysis = await db.scalar(stmt)
    if not analysis:
        raise HTTPException(404, "Analysis not found.")
    return ImageAnalysisOut.model_validate(analysis)


# =========================================================
# HELPERS
# =========================================================

async def _get_document_job_scoped(
        db: AsyncSession, job_id: str, user: CurrentUser,
) -> DocumentOCRJob:
    stmt = select(DocumentOCRJob).where(DocumentOCRJob.job_id == job_id)
    if user.role != "SUPER_ADMIN":
        stmt = stmt.where(DocumentOCRJob.admin_id == user.admin_id)
    job = await db.scalar(stmt)
    if not job:
        raise HTTPException(404, "Document job not found.")
    return job


async def _get_image_job_scoped(
        db: AsyncSession, job_id: str, user: CurrentUser,
) -> ImageOCRJob:
    stmt = select(ImageOCRJob).where(ImageOCRJob.job_id == job_id)
    if user.role != "SUPER_ADMIN":
        stmt = stmt.where(ImageOCRJob.admin_id == user.admin_id)
    job = await db.scalar(stmt)
    if not job:
        raise HTTPException(404, "Image job not found.")
    return job
