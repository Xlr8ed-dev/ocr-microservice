"""Celery task for the document OCR pipeline.

Flow:
  1. Load DocumentOCRJob row (PENDING → EXTRACTING)
  2. Download + extract text + structural hints (document_extract)
  3. Detect headings from those hints (heading_detect)
  4. Chunk the text for AI processing (document_chunk)
  5. For each chunk, call AI to structure (document_structure)
  6. Merge chunk results into one output (document_merge)
  7. Persist output, mark COMPLETED, set cost_estimate

Progress reporting:
  - 5   → after DB load / status flip
  - 25  → after extraction (page_count known)
  - 35  → after chunking (chunk_count known)
  - 35–95 → while processing chunks (per chunk)
  - 100 → after final DB write

Any stage raising an exception flips status to FAILED, records the error,
and stops. No partial output is written.

Every status change also calls `refresh_batch_counters` so the parent
Batch's aggregate counts stay accurate for the FE progress screen.
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.clients.ai import AIServiceError
from app.clients.http import clients
from app.database import AsyncSessionLocal
from app.models import (
    DocumentFileType,
    DocumentOCRJob,
    DocumentOCRStatus,
)
from app.services.batch_service import refresh_batch_counters
from app.services.document_chunk import chunk_document
from app.services.document_extract import (
    DocumentExtractionError,
    extract_document,
)
from app.services.document_merge import merge_chunk_results
from app.services.document_structure import (
    ChunkResult,
    extract_last_block_text,
    structure_chunk,
)
from app.services.heading_detect import detect_headings
from app.tasks._helpers import run_async_safely
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# =========================================================
# CONSTANTS
# =========================================================

COST_PER_PAGE_INR = 1.0  # placeholder billing rate


# =========================================================
# CELERY TASK ENTRY
# =========================================================

@celery_app.task(
    bind=True,
    name="document.run_ocr",
    autoretry_for=(AIServiceError,),
    retry_backoff=True,
    retry_backoff_max=180,
    retry_jitter=True,
    max_retries=2,
)
def run_document_ocr(self, job_id: str) -> dict:
    return run_async_safely(_do_run_document_ocr, job_id)


# =========================================================
# MAIN PIPELINE
# =========================================================

async def _do_run_document_ocr(job_id: str) -> dict:
    await clients.startup()
    started = time.monotonic()
    try:
        # --- 1. Load job, flip to EXTRACTING ----------------------------
        async with AsyncSessionLocal() as db:
            job = await db.scalar(
                select(DocumentOCRJob).where(DocumentOCRJob.job_id == job_id)
            )
            if not job:
                logger.error("Document job not found: %s", job_id)
                return {"status": "not_found", "job_id": job_id}

            job.status = DocumentOCRStatus.EXTRACTING
            job.started_at = datetime.now(timezone.utc)
            job.progress = 5
            await db.commit()

            # Capture for later use outside the session
            source_url = job.source_url
            admin_id = job.admin_id
            batch_id = job.batch_id

            await refresh_batch_counters(db, batch_id)
            await db.commit()

        logger.info("document task start job=%s url=%s", job_id, source_url)

        # --- 2. Extract text + structural hints -------------------------
        try:
            extracted = await extract_document(source_url)
        except DocumentExtractionError as exc:
            await _fail(job_id, f"Extraction failed: {exc}")
            raise

        file_type = _map_extraction_method_to_file_type(extracted.extraction_method)

        async with AsyncSessionLocal() as db:
            job = await db.scalar(
                select(DocumentOCRJob).where(DocumentOCRJob.job_id == job_id)
            )
            job.file_type = file_type
            job.page_count = extracted.page_count
            job.progress = 25
            await db.commit()

            await refresh_batch_counters(db, batch_id)
            await db.commit()

        # --- 3. Detect headings ----------------------------------------
        headings = detect_headings(extracted)

        # --- 4. Chunk ---------------------------------------------------
        chunks = chunk_document(extracted, headings)

        if not chunks:
            await _complete_with_empty(job_id, page_count=extracted.page_count, batch_id=batch_id)
            return {"status": "completed_empty", "job_id": job_id}

        async with AsyncSessionLocal() as db:
            job = await db.scalar(
                select(DocumentOCRJob).where(DocumentOCRJob.job_id == job_id)
            )
            job.chunk_count = len(chunks)
            job.status = DocumentOCRStatus.STRUCTURING
            job.progress = 35
            await db.commit()

            await refresh_batch_counters(db, batch_id)
            await db.commit()

        # --- 5. Per-chunk AI structuring --------------------------------
        results: list[ChunkResult] = []
        previous_last_block: str | None = None
        ai_calls = 0
        ai_tokens_in = 0
        ai_tokens_out = 0

        progress_step = 60 / max(len(chunks), 1)  # 35 → 95

        for chunk in chunks:
            logger.info(
                "document task chunk=%d/%d job=%s",
                chunk.chunk_index + 1, chunk.chunk_total, job_id,
            )
            result = await structure_chunk(
                chunk,
                previous_last_block=previous_last_block,
            )
            results.append(result)

            # Accumulate usage (may all be zero if AI omits usage)
            ai_calls += 1
            usage = result.usage or {}
            ai_tokens_in += int(usage.get("prompt_tokens", 0) or 0)
            ai_tokens_out += int(usage.get("completion_tokens", 0) or 0)

            # Context for next chunk
            previous_last_block = extract_last_block_text(result.blocks)

            # Progress update (no status change — batch counters stay same)
            async with AsyncSessionLocal() as db:
                job = await db.scalar(
                    select(DocumentOCRJob).where(DocumentOCRJob.job_id == job_id)
                )
                job.progress = min(95, int(35 + progress_step * (chunk.chunk_index + 1)))
                job.ai_calls = ai_calls
                job.ai_tokens_in = ai_tokens_in
                job.ai_tokens_out = ai_tokens_out
                await db.commit()

        # --- 6. Merge ---------------------------------------------------
        merged = merge_chunk_results(results)

        # --- 7. Persist output + complete -------------------------------
        elapsed_ms = int((time.monotonic() - started) * 1000)
        metadata = merged.get("metadata") or {}
        metadata.update({
            "page_count": extracted.page_count,
            "extraction_method": extracted.extraction_method,
            "char_count": len(extracted.text),
            "processing_time_ms": elapsed_ms,
        })

        output = {
            "title": merged.get("title"),
            "blocks": merged.get("blocks") or [],
            "metadata": metadata,
        }

        cost_estimate = (
            float(extracted.page_count) * COST_PER_PAGE_INR
            if extracted.page_count
            else None
        )

        async with AsyncSessionLocal() as db:
            job = await db.scalar(
                select(DocumentOCRJob).where(DocumentOCRJob.job_id == job_id)
            )
            job.output = output
            job.progress = 100
            job.status = DocumentOCRStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            job.cost_estimate = cost_estimate
            job.ai_calls = ai_calls
            job.ai_tokens_in = ai_tokens_in
            job.ai_tokens_out = ai_tokens_out
            await db.commit()

            await refresh_batch_counters(db, batch_id)
            await db.commit()

        logger.info(
            "document task complete job=%s pages=%d chunks=%d blocks=%d ms=%d",
            job_id, extracted.page_count, len(chunks),
            len(output["blocks"]), elapsed_ms,
        )
        return {
            "status": "completed",
            "job_id": job_id,
            "blocks": len(output["blocks"]),
            "chunks": len(chunks),
        }

    finally:
        await clients.shutdown()


# =========================================================
# FAILURE / EMPTY PATHS
# =========================================================

async def _fail(job_id: str, error: str) -> None:
    """Mark job FAILED with a truncated error message."""
    try:
        async with AsyncSessionLocal() as db:
            job = await db.scalar(
                select(DocumentOCRJob).where(DocumentOCRJob.job_id == job_id)
            )
            if job:
                job.status = DocumentOCRStatus.FAILED
                job.error = error[:2000]
                job.completed_at = datetime.now(timezone.utc)
                batch_id = job.batch_id
                await db.commit()

                await refresh_batch_counters(db, batch_id)
                await db.commit()
        logger.warning("document job FAILED job=%s error=%s", job_id, error[:200])
    except Exception:
        # Do not mask the original error
        logger.exception("failed to mark document job as failed job=%s", job_id)


async def _complete_with_empty(job_id: str, page_count: int | None, batch_id: str) -> None:
    """Mark the job completed with no blocks — happens for empty documents."""
    async with AsyncSessionLocal() as db:
        job = await db.scalar(
            select(DocumentOCRJob).where(DocumentOCRJob.job_id == job_id)
        )
        if not job:
            return
        job.output = {
            "title": None,
            "blocks": [],
            "metadata": {"page_count": page_count, "char_count": 0},
        }
        job.status = DocumentOCRStatus.COMPLETED
        job.progress = 100
        job.completed_at = datetime.now(timezone.utc)
        await db.commit()

        await refresh_batch_counters(db, batch_id)
        await db.commit()


# =========================================================
# HELPERS
# =========================================================

def _map_extraction_method_to_file_type(method: str) -> DocumentFileType:
    """Map the extraction module's `extraction_method` string to our enum."""
    if method == "pdf_text":
        return DocumentFileType.PDF_TEXT
    if method == "pdf_scan":
        return DocumentFileType.PDF_SCAN
    if method == "docx":
        return DocumentFileType.DOCX
    if method == "txt":
        return DocumentFileType.TXT
    # Fallback — shouldn't happen
    return DocumentFileType.TXT


# =========================================================
# Task registration — expose the job uuid helper if needed by routers
# =========================================================

def new_job_id() -> str:
    return str(uuid.uuid4())
