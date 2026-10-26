"""Celery task for generic image OCR.

One vision call per job. No chunking, no merging.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select

from app.clients.ai import AIServiceError, vision_ocr
from app.clients.http import clients
from app.database import AsyncSessionLocal
from app.models import ImageOCRJob, ImageOCRStatus
from app.services.image_prompts import IMAGE_TYPE_META
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="image.run_ocr",
    autoretry_for=(AIServiceError,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=3,
)
def run_image_ocr(self, job_id: str) -> dict:
    return asyncio.run(_do_run_image_ocr(job_id))


async def _do_run_image_ocr(job_id: str) -> dict:
    await clients.startup()
    started = time.monotonic()
    try:
        async with AsyncSessionLocal() as db:
            job = await db.scalar(
                select(ImageOCRJob).where(ImageOCRJob.job_id == job_id)
            )
            if not job:
                logger.error("Image job not found: %s", job_id)
                return {"status": "not_found", "job_id": job_id}

            job.status = ImageOCRStatus.PROCESSING
            job.started_at = datetime.now(timezone.utc)
            await db.commit()

            source_url = job.source_url
            image_type = job.image_type

        meta = IMAGE_TYPE_META.get(image_type)
        if not meta:
            await _fail(job_id, f"Unknown image type: {image_type}")
            return {"status": "failed", "job_id": job_id}

        try:
            raw = await vision_ocr(
                image_url=source_url,
                prompt=meta["system_prompt"],
            )
        except AIServiceError as exc:
            await _fail(job_id, str(exc)[:2000])
            raise

        # Extract output — support both {data: {...}} and bare {..}
        data = raw.get("data", raw) if isinstance(raw, dict) else {}
        usage = raw.get("usage") or {} if isinstance(raw, dict) else {}

        async with AsyncSessionLocal() as db:
            job = await db.scalar(
                select(ImageOCRJob).where(ImageOCRJob.job_id == job_id)
            )
            job.output = data if isinstance(data, dict) else {"raw": data}
            job.raw_response = raw if isinstance(raw, dict) else None
            job.status = ImageOCRStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            job.ai_calls = 1
            job.ai_tokens_in = int(usage.get("prompt_tokens", 0) or 0)
            job.ai_tokens_out = int(usage.get("completion_tokens", 0) or 0)
            # Image cost placeholder — flat ₹1 per image for now
            job.cost_estimate = 1.0
            await db.commit()

        logger.info(
            "image task complete job=%s type=%s ms=%d",
            job_id, image_type.value, int((time.monotonic() - started) * 1000),
        )
        return {"status": "completed", "job_id": job_id}

    finally:
        await clients.shutdown()


async def _fail(job_id: str, error: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            job = await db.scalar(
                select(ImageOCRJob).where(ImageOCRJob.job_id == job_id)
            )
            if job:
                job.status = ImageOCRStatus.FAILED
                job.error = error[:2000]
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()
    except Exception:
        logger.exception("failed to mark image job as failed job=%s", job_id)
