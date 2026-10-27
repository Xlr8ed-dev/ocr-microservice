"""Shared helpers for creating and updating batches.

Called by the routers (create) and the workers (counter updates).
Every batch operation funnels through here so the counting logic
stays in one place.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Batch,
    BatchKind,
    BatchStatus,
    DocumentOCRJob,
    DocumentOCRStatus,
    Extraction,
    ExtractionStatus,
    ImageOCRJob,
    ImageOCRStatus,
)

logger = logging.getLogger(__name__)


# =========================================================
# CREATE
# =========================================================

async def create_batch(
        db: AsyncSession,
        *,
        admin_id: int,
        user_id: int,
        kind: BatchKind,
        template_id: str | None,
        total_files: int,
        label: str | None = None,
) -> Batch:
    """Insert a batch row with initial counters.

    Sets `pending_files = total_files` so the FE sees correct state
    immediately, before any child job has been dispatched.
    """
    batch = Batch(
        id=_new_id(),
        admin_id=admin_id,
        user_id=user_id,
        kind=kind,
        template_id=template_id,
        label=label,
        total_files=total_files,
        pending_files=total_files,
        in_progress_files=0,
        completed_files=0,
        failed_files=0,
        status=BatchStatus.PENDING,
    )
    db.add(batch)
    await db.flush()
    return batch


# =========================================================
# RECOMPUTE
# =========================================================

async def refresh_batch_counters(db: AsyncSession, batch_id: str) -> None:
    """Recompute counters + status from the child rows.

    Called by each worker whenever a child transitions state. Uses a
    full recount (cheap for realistic batch sizes; no drift possible).

    Idempotent. Safe to call multiple times.
    """
    batch = await db.get(Batch, batch_id)
    if not batch:
        logger.warning("refresh_batch_counters: batch not found: %s", batch_id)
        return

    if batch.kind == BatchKind.DOCUMENT:
        counts = await _count_documents(db, batch_id)
    elif batch.kind == BatchKind.IMAGE:
        counts = await _count_images(db, batch_id)
    elif batch.kind == BatchKind.EXTRACTION:
        counts = await _count_extractions(db, batch_id)
    else:
        logger.error("refresh_batch_counters: unknown kind %s", batch.kind)
        return

    batch.pending_files = counts["pending"]
    batch.in_progress_files = counts["in_progress"]
    batch.completed_files = counts["completed"]
    batch.failed_files = counts["failed"]

    # --- derive overall status ---
    batch.status = _derive_status(batch, counts)

    # --- started_at: first time we see in_progress or completed ---
    if batch.started_at is None and (
            counts["in_progress"] > 0 or counts["completed"] > 0
    ):
        batch.started_at = datetime.now(timezone.utc)

    # --- completed_at: when fully terminal ---
    if batch.status in (
            BatchStatus.COMPLETED,
            BatchStatus.PARTIALLY_FAILED,
            BatchStatus.FAILED,
            BatchStatus.CANCELLED,
    ):
        if batch.completed_at is None:
            batch.completed_at = datetime.now(timezone.utc)

    await db.flush()


def _derive_status(batch: Batch, counts: dict) -> BatchStatus:
    if batch.status == BatchStatus.CANCELLED:
        return BatchStatus.CANCELLED

    total_terminal = counts["completed"] + counts["failed"]
    if counts["pending"] == 0 and counts["in_progress"] == 0:
        if total_terminal == 0:
            return BatchStatus.PENDING
        if counts["failed"] == 0:
            return BatchStatus.COMPLETED
        if counts["completed"] == 0:
            return BatchStatus.FAILED
        return BatchStatus.PARTIALLY_FAILED

    return BatchStatus.PROCESSING


# =========================================================
# PER-KIND COUNTERS
# =========================================================

async def _count_documents(db: AsyncSession, batch_id: str) -> dict:
    stmt = select(DocumentOCRJob.status).where(
        DocumentOCRJob.batch_id == batch_id
    )
    rows = (await db.scalars(stmt)).all()
    return _tally(rows, {
        "pending": {DocumentOCRStatus.PENDING},
        "in_progress": {DocumentOCRStatus.EXTRACTING, DocumentOCRStatus.STRUCTURING},
        "completed": {DocumentOCRStatus.COMPLETED},
        "failed": {DocumentOCRStatus.FAILED},
    })


async def _count_images(db: AsyncSession, batch_id: str) -> dict:
    stmt = select(ImageOCRJob.status).where(
        ImageOCRJob.batch_id == batch_id
    )
    rows = (await db.scalars(stmt)).all()
    return _tally(rows, {
        "pending": {ImageOCRStatus.PENDING},
        "in_progress": {ImageOCRStatus.PROCESSING},
        "completed": {ImageOCRStatus.COMPLETED},
        "failed": {ImageOCRStatus.FAILED},
    })


async def _count_extractions(db: AsyncSession, batch_id: str) -> dict:
    stmt = select(Extraction.status).where(Extraction.batch_id == batch_id)
    rows = (await db.scalars(stmt)).all()
    return _tally(rows, {
        "pending": {ExtractionStatus.PENDING},
        "in_progress": {
            ExtractionStatus.OCR_RUNNING,
            ExtractionStatus.EXTRACTING,
        },
        # needs_review and completed both count as "done" from a batch
        # progress perspective. The batch is not "failed" just because
        # some fields need review.
        "completed": {
            ExtractionStatus.COMPLETED,
            ExtractionStatus.NEEDS_REVIEW,
        },
        "failed": {
            ExtractionStatus.FAILED,
            ExtractionStatus.BLURRY,
        },
    })


def _tally(statuses, groups: dict) -> dict:
    counts = {k: 0 for k in groups}
    for s in statuses:
        for group, values in groups.items():
            if s in values:
                counts[group] += 1
                break
    return counts


def _new_id() -> str:
    import uuid
    return str(uuid.uuid4())
