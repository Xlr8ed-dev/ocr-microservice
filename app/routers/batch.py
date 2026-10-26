"""Batch endpoints.

The single polling surface for every upload (documents, images, or
extractions). The FE polls GET /batch/{id} to render the progress
screen — it works the same regardless of what kind of files are in
the batch.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, current_user
from app.models import (
    Batch,
    BatchKind,
    BatchStatus,
    DocumentOCRJob,
    Extraction,
    ImageOCRJob,
)
from app.schemas.batch import (
    BatchJobStatusItem,
    BatchListItem,
    BatchOut,
)
from app.schemas.common import PaginatedResponse
from app.utils.pagination import DEFAULT_PAGE_SIZE, build_meta, parse_page

router = APIRouter(prefix="/batch", tags=["Batches"])


# =========================================================
# GET ONE BATCH
# =========================================================

@router.get("/{batch_id}", response_model=BatchOut)
async def get_batch(
        batch_id: str,
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> BatchOut:
    batch = await _get_scoped(db, batch_id, user)
    jobs = await _load_jobs(db, batch)

    return BatchOut(
        batch_id=batch.id,
        kind=batch.kind.value,
        template_id=batch.template_id,
        label=batch.label,
        total_files=batch.total_files,
        pending_files=batch.pending_files,
        in_progress_files=batch.in_progress_files,
        completed_files=batch.completed_files,
        failed_files=batch.failed_files,
        status=batch.status.value,
        created_at=batch.created_at,
        started_at=batch.started_at,
        completed_at=batch.completed_at,
        jobs=jobs,
    )


# =========================================================
# LIST BATCHES
# =========================================================

@router.get("", response_model=PaginatedResponse[BatchListItem])
async def list_batches(
        page: int = Query(1, ge=1),
        items: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=200),
        kind: str | None = Query(
            None,
            description="Filter by kind: document | image | extraction",
        ),
        batch_status: str | None = Query(None, alias="status"),
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[BatchListItem]:
    p = parse_page(page, items)

    base = select(Batch)
    if user.role == "ADMIN":
        base = base.where(Batch.admin_id == user.admin_id)
    elif user.role == "AGENT":
        base = base.where(Batch.user_id == user.id)
    # SUPER_ADMIN: no filter

    if kind:
        try:
            kind_enum = BatchKind(kind)
        except ValueError:
            raise HTTPException(400, f"Invalid kind: {kind}")
        base = base.where(Batch.kind == kind_enum)

    if batch_status:
        try:
            status_enum = BatchStatus(batch_status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {batch_status}")
        base = base.where(Batch.status == status_enum)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.scalar(count_stmt)) or 0

    stmt = (
        base.order_by(Batch.created_at.desc())
        .limit(p.limit)
        .offset(p.offset)
    )
    rows = list((await db.scalars(stmt)).all())

    return PaginatedResponse[BatchListItem](
        data=[
            BatchListItem(
                batch_id=b.id,
                kind=b.kind.value,
                template_id=b.template_id,
                label=b.label,
                total_files=b.total_files,
                completed_files=b.completed_files,
                failed_files=b.failed_files,
                status=b.status.value,
                created_at=b.created_at,
                completed_at=b.completed_at,
            )
            for b in rows
        ],
        pagination=build_meta(total, p),
    )


# =========================================================
# CANCEL
# =========================================================

@router.delete("/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_batch(
        batch_id: str,
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> None:
    if user.role not in ("ADMIN", "SUPER_ADMIN"):
        raise HTTPException(403, "Only admins can cancel batches.")

    batch = await _get_scoped(db, batch_id, user)

    if batch.status in (
            BatchStatus.COMPLETED,
            BatchStatus.PARTIALLY_FAILED,
            BatchStatus.FAILED,
            BatchStatus.CANCELLED,
    ):
        raise HTTPException(
            409,
            f"Batch is already in terminal state: {batch.status.value}",
        )

    # Mark cancelled. We don't revoke Celery tasks — those already in flight
    # will finish; those still queued will be picked up by a worker and
    # finish too. But the batch status will read `cancelled` from now on.
    # If we want hard cancellation, we'd need to track Celery task IDs and
    # call revoke() — deferring that for v2.
    batch.status = BatchStatus.CANCELLED
    batch.completed_at = datetime.now(timezone.utc)
    await db.flush()


# =========================================================
# HELPERS
# =========================================================

async def _get_scoped(
        db: AsyncSession, batch_id: str, user: CurrentUser,
) -> Batch:
    stmt = select(Batch).where(Batch.id == batch_id)
    if user.role == "ADMIN":
        stmt = stmt.where(Batch.admin_id == user.admin_id)
    elif user.role == "AGENT":
        stmt = stmt.where(Batch.user_id == user.id)
    batch = await db.scalar(stmt)
    if not batch:
        raise HTTPException(404, "Batch not found.")
    return batch


async def _load_jobs(db: AsyncSession, batch: Batch) -> list[BatchJobStatusItem]:
    """Load child jobs for this batch, sorted by creation order."""
    if batch.kind == BatchKind.DOCUMENT:
        stmt = (
            select(DocumentOCRJob)
            .where(DocumentOCRJob.batch_id == batch.id)
            .order_by(DocumentOCRJob.created_at, DocumentOCRJob.id)
        )
        rows = list((await db.scalars(stmt)).all())
        return [
            BatchJobStatusItem(
                id=r.job_id,
                file_name=r.file_name or "",
                status=r.status.value,
                error=r.error,
                page_count=r.page_count,
            )
            for r in rows
        ]

    if batch.kind == BatchKind.IMAGE:
        stmt = (
            select(ImageOCRJob)
            .where(ImageOCRJob.batch_id == batch.id)
            .order_by(ImageOCRJob.created_at, ImageOCRJob.id)
        )
        rows = list((await db.scalars(stmt)).all())
        return [
            BatchJobStatusItem(
                id=r.job_id,
                file_name="",  # image jobs don't store file_name in v1
                status=r.status.value,
                error=r.error,
                page_count=1,
            )
            for r in rows
        ]

    if batch.kind == BatchKind.EXTRACTION:
        stmt = (
            select(Extraction)
            .where(Extraction.batch_id == batch.id)
            .order_by(Extraction.created_at, Extraction.id)
        )
        rows = list((await db.scalars(stmt)).all())
        return [
            BatchJobStatusItem(
                id=r.id,
                file_name=r.file_name,
                status=r.status.value,
                error=r.error,
                page_count=None,
            )
            for r in rows
        ]

    return []
