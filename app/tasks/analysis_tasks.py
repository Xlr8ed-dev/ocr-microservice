"""Celery tasks for document and image analysis.

Each task:
  1. Loads the Analysis row, sets PROCESSING
  2. Loads the parent job (must be COMPLETED)
  3. Builds a digest from the job's output
  4. Calls the AI /chat/completion endpoint
  5. Writes summary / classification / tags
  6. Marks COMPLETED, records tokens and cost_estimate
  7. On error: marks FAILED, records error
"""

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.clients.ai import AIServiceError
from app.clients.http import clients
from app.database import AsyncSessionLocal
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
from app.services.analysis_input import (
    blocks_to_digest,
    image_output_to_digest,
)
from app.services.analysis_prompts import (
    DEFAULT_DOCUMENT_CATEGORIES,
    PROMPT_VERSION,
    build_document_analysis_payload,
    build_image_analysis_payload,
)
from app.tasks._helpers import run_async_safely
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# =========================================================
# CONSTANTS
# =========================================================

COST_PER_DOC_ANALYSIS_INR = 3.0
COST_PER_IMAGE_ANALYSIS_INR = 1.0


# =========================================================
# DOCUMENT ANALYSIS TASK
# =========================================================

@celery_app.task(
    bind=True,
    name="analysis.run_document",
    autoretry_for=(AIServiceError,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=3,
)
def run_document_analysis(self, analysis_id: str) -> dict:
    return run_async_safely(_do_run_document_analysis, analysis_id)


async def _do_run_document_analysis(analysis_id: str) -> dict:
    await clients.startup()
    try:
        # --- 1. Load analysis row ---
        async with AsyncSessionLocal() as db:
            analysis = await db.scalar(
                select(DocumentAnalysis).where(
                    DocumentAnalysis.analysis_id == analysis_id
                )
            )
            if not analysis:
                logger.error("Document analysis not found: %s", analysis_id)
                return {"status": "not_found", "analysis_id": analysis_id}

            analysis.status = AnalysisStatus.PROCESSING
            analysis.started_at = datetime.now(timezone.utc)
            await db.commit()

            job_id = analysis.job_id
            max_words = analysis.max_words_used or 250
            categories = analysis.categories_used or DEFAULT_DOCUMENT_CATEGORIES

        # --- 2. Load parent job ---
        async with AsyncSessionLocal() as db:
            job = await db.scalar(
                select(DocumentOCRJob).where(DocumentOCRJob.job_id == job_id)
            )
            if not job:
                await _fail_document(analysis_id, "Parent document job not found")
                return {"status": "failed", "analysis_id": analysis_id}
            if job.status != DocumentOCRStatus.COMPLETED or not job.output:
                await _fail_document(
                    analysis_id,
                    f"Parent job not completed (status={job.status.value})",
                )
                return {"status": "failed", "analysis_id": analysis_id}

            output = job.output

        # --- 3. Build digest ---
        digest = blocks_to_digest(output)
        if not digest.strip():
            await _fail_document(analysis_id, "Document has no content to analyze")
            return {"status": "failed", "analysis_id": analysis_id}

        # --- 4. Call AI ---
        payload = build_document_analysis_payload(
            title=output.get("title"),
            digest=digest,
            categories=categories,
            max_words=max_words,
        )

        try:
            raw = await _post_ai(payload)
        except AIServiceError as exc:
            await _fail_document(analysis_id, str(exc)[:2000])
            raise

        data = raw.get("data", raw) if isinstance(raw, dict) else {}
        usage = raw.get("usage") or {} if isinstance(raw, dict) else {}

        if not isinstance(data, dict):
            await _fail_document(analysis_id, "AI returned unexpected shape")
            return {"status": "failed", "analysis_id": analysis_id}

        summary = str(data.get("summary") or "").strip()
        category = str(data.get("category") or "other").strip().lower()
        subcategory = data.get("subcategory")
        if subcategory is not None:
            subcategory = str(subcategory).strip() or None
        confidence = _coerce_float(data.get("confidence"), default=0.0)
        tags = _coerce_tags(data.get("tags"))

        # --- 5. Persist ---
        async with AsyncSessionLocal() as db:
            analysis = await db.scalar(
                select(DocumentAnalysis).where(
                    DocumentAnalysis.analysis_id == analysis_id
                )
            )
            if not analysis:
                logger.warning("Analysis disappeared: %s", analysis_id)
                return {"status": "not_found", "analysis_id": analysis_id}

            analysis.summary = summary
            analysis.category = category[:64] if category else None
            analysis.subcategory = subcategory[:64] if subcategory else None
            analysis.confidence = confidence
            analysis.tags = tags
            analysis.status = AnalysisStatus.COMPLETED
            analysis.completed_at = datetime.now(timezone.utc)
            analysis.ai_calls = 1
            analysis.ai_tokens_in = int(usage.get("prompt_tokens", 0) or 0)
            analysis.ai_tokens_out = int(usage.get("completion_tokens", 0) or 0)
            analysis.cost_estimate = COST_PER_DOC_ANALYSIS_INR
            analysis.prompt_version = PROMPT_VERSION
            await db.commit()

        logger.info(
            "document analysis complete id=%s job=%s category=%s",
            analysis_id, job_id, category,
        )
        return {"status": "completed", "analysis_id": analysis_id}

    finally:
        await clients.shutdown()


# =========================================================
# IMAGE ANALYSIS TASK
# =========================================================

@celery_app.task(
    bind=True,
    name="analysis.run_image",
    autoretry_for=(AIServiceError,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=3,
)
def run_image_analysis(self, analysis_id: str) -> dict:
    return run_async_safely(_do_run_image_analysis, analysis_id)


async def _do_run_image_analysis(analysis_id: str) -> dict:
    await clients.startup()
    try:
        # --- 1. Load analysis row ---
        async with AsyncSessionLocal() as db:
            analysis = await db.scalar(
                select(ImageAnalysis).where(
                    ImageAnalysis.analysis_id == analysis_id
                )
            )
            if not analysis:
                logger.error("Image analysis not found: %s", analysis_id)
                return {"status": "not_found", "analysis_id": analysis_id}

            analysis.status = ImageAnalysisStatus.PROCESSING
            analysis.started_at = datetime.now(timezone.utc)
            await db.commit()

            job_id = analysis.job_id
            max_words = analysis.max_words_used or 100

        # --- 2. Load parent job ---
        async with AsyncSessionLocal() as db:
            job = await db.scalar(
                select(ImageOCRJob).where(ImageOCRJob.job_id == job_id)
            )
            if not job:
                await _fail_image(analysis_id, "Parent image job not found")
                return {"status": "failed", "analysis_id": analysis_id}
            if job.status != ImageOCRStatus.COMPLETED or not job.output:
                await _fail_image(
                    analysis_id,
                    f"Parent job not completed (status={job.status.value})",
                )
                return {"status": "failed", "analysis_id": analysis_id}

            image_type = job.image_type.value
            output = job.output

        # --- 3. Build digest ---
        digest = image_output_to_digest(output)
        if not digest.strip():
            await _fail_image(analysis_id, "Image has no content to analyze")
            return {"status": "failed", "analysis_id": analysis_id}

        # --- 4. Call AI ---
        payload = build_image_analysis_payload(
            image_type=image_type,
            output_json=output,
            max_words=max_words,
        )

        try:
            raw = await _post_ai(payload)
        except AIServiceError as exc:
            await _fail_image(analysis_id, str(exc)[:2000])
            raise

        data = raw.get("data", raw) if isinstance(raw, dict) else {}
        usage = raw.get("usage") or {} if isinstance(raw, dict) else {}

        if not isinstance(data, dict):
            await _fail_image(analysis_id, "AI returned unexpected shape")
            return {"status": "failed", "analysis_id": analysis_id}

        summary = str(data.get("summary") or "").strip()
        tags = _coerce_tags(data.get("tags"))

        # --- 5. Persist ---
        async with AsyncSessionLocal() as db:
            analysis = await db.scalar(
                select(ImageAnalysis).where(
                    ImageAnalysis.analysis_id == analysis_id
                )
            )
            if not analysis:
                logger.warning("Analysis disappeared: %s", analysis_id)
                return {"status": "not_found", "analysis_id": analysis_id}

            analysis.summary = summary
            analysis.tags = tags
            analysis.status = ImageAnalysisStatus.COMPLETED
            analysis.completed_at = datetime.now(timezone.utc)
            analysis.ai_calls = 1
            analysis.ai_tokens_in = int(usage.get("prompt_tokens", 0) or 0)
            analysis.ai_tokens_out = int(usage.get("completion_tokens", 0) or 0)
            analysis.cost_estimate = COST_PER_IMAGE_ANALYSIS_INR
            analysis.prompt_version = PROMPT_VERSION
            await db.commit()

        logger.info(
            "image analysis complete id=%s job=%s type=%s",
            analysis_id, job_id, image_type,
        )
        return {"status": "completed", "analysis_id": analysis_id}

    finally:
        await clients.shutdown()


# =========================================================
# SHARED HELPERS
# =========================================================

async def _post_ai(payload: dict) -> dict:
    """Post to /api/v1/chat/completion and return the parsed JSON."""
    assert clients.ai is not None, "AI client not initialised"
    try:
        response = await clients.ai.post(
            "api/v1/chat/completion",
            json=payload,
        )
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise AIServiceError("Analysis request timed out") from exc
    except httpx.HTTPStatusError as exc:
        raise AIServiceError(
            f"AI returned {exc.response.status_code}: "
            f"{exc.response.text[:300]}"
        ) from exc
    except httpx.RequestError as exc:
        raise AIServiceError("Unable to connect to AI service") from exc

    try:
        raw = response.json()
    except ValueError as exc:
        raise AIServiceError("AI returned invalid JSON") from exc

    if not isinstance(raw, dict):
        raise AIServiceError("AI response is not an object")
    return raw


def _coerce_float(value, *, default: float = 0.0) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def _coerce_tags(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if item is None:
            continue
        s = str(item).strip()
        if s and s not in out:
            out.append(s)
        if len(out) >= 10:
            break
    return out


async def _fail_document(analysis_id: str, error: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            analysis = await db.scalar(
                select(DocumentAnalysis).where(
                    DocumentAnalysis.analysis_id == analysis_id
                )
            )
            if analysis:
                analysis.status = AnalysisStatus.FAILED
                analysis.error = error[:2000]
                analysis.completed_at = datetime.now(timezone.utc)
                await db.commit()
    except Exception:
        logger.exception("failed to mark doc analysis failed: %s", analysis_id)


async def _fail_image(analysis_id: str, error: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            analysis = await db.scalar(
                select(ImageAnalysis).where(
                    ImageAnalysis.analysis_id == analysis_id
                )
            )
            if analysis:
                analysis.status = ImageAnalysisStatus.FAILED
                analysis.error = error[:2000]
                analysis.completed_at = datetime.now(timezone.utc)
                await db.commit()
    except Exception:
        logger.exception("failed to mark image analysis failed: %s", analysis_id)
