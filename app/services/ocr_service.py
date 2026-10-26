import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import OCRJob, JobStatus, JobType, WebhookStatus, Visitor
from app.tasks.ocr_tasks import run_ocr_primary, run_ocr_secondary


logger = logging.getLogger(__name__)


# =========================================================
# DISPATCH HELPERS
# =========================================================

async def enqueue_primary_ocr(
    db: AsyncSession,
    visitor: Visitor,
    *,
    front_url: str | None,
    back_url: str | None,
    admin_id: int,
    user_id: int,
) -> OCRJob | None:
    """Insert an OCRJob row and dispatch the Celery task.

    Returns None if neither URL is provided.
    """
    if not front_url and not back_url:
        return None

    job = OCRJob(
        job_id=str(uuid.uuid4()),
        txn_id=visitor.txn_Id,
        idempotency_key=f"{visitor.txn_Id}:ocr_primary",
        admin_id=admin_id,
        user_id=user_id,
        job_type=JobType.OCR_PRIMARY,
        payload={"front": front_url, "back": back_url},
        callback_url=settings.OCR_CALLBACK_URL,
        status=JobStatus.PENDING,
        webhook_status=WebhookStatus.NOT_REQUIRED,   # direct DB write for v1
    )
    db.add(job)
    await db.flush()

    # dispatch after flush — Celery might run inline in eager mode,
    # in which case it needs the row to already exist.
    run_ocr_primary.apply_async(args=[job.job_id])

    return job


async def enqueue_secondary_ocr(
    db: AsyncSession,
    visitor: Visitor,
    *,
    cards: list[tuple[str | None, str | None]],
    admin_id: int,
    user_id: int,
) -> OCRJob | None:
    """Insert an OCRJob for secondary cards and dispatch."""
    valid_cards = [
        [f, b] for (f, b) in cards if f or b
    ]
    if not valid_cards:
        return None

    job = OCRJob(
        job_id=str(uuid.uuid4()),
        txn_id=visitor.txn_Id,
        idempotency_key=f"{visitor.txn_Id}:ocr_secondary",
        admin_id=admin_id,
        user_id=user_id,
        job_type=JobType.OCR_SECONDARY,
        payload={"cards": valid_cards},
        callback_url=settings.OCR_CALLBACK_URL,
        status=JobStatus.PENDING,
        webhook_status=WebhookStatus.NOT_REQUIRED,
    )
    db.add(job)
    await db.flush()

    run_ocr_secondary.apply_async(args=[job.job_id])
    return job


# =========================================================
# CALLBACK HANDLER (kept for future use — currently unused)
# =========================================================

async def handle_ocr_callback(db: AsyncSession, payload) -> None:
    """Unused in v1 (worker writes to DB directly).
    Kept so the /internal/ocr/callback endpoint has a target.
    """
    logger.warning("handle_ocr_callback called but not implemented in v1")
    raise NotImplementedError("HTTP callbacks not used in v1; worker writes DB directly.")