"""Celery task for the extraction pipeline.

Two paths depending on file type:
  - Image (jpg/png/webp): pre-flight blurry check → single vision call.
  - Document (pdf/docx/txt): extract text → structure → single AI call.

Both converge on: {field_key: {value, confidence}}, then a min-confidence
check decides between `completed` and `needs_review`.

Every status transition also refreshes the parent Batch counters so the
FE batch progress screen reflects the change on the next poll.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.clients.ai import AIServiceError
from app.clients.http import clients
from app.database import AsyncSessionLocal
from app.models import (
    DocumentFileType,
    DocumentOCRJob,
    DocumentOCRStatus,
    Extraction,
    ExtractionJobType,
    ExtractionStatus,
    ImageOCRJob,
    ImageOCRStatus,
    Template,
)
from app.services.batch_service import refresh_batch_counters
from app.services.blurry_check import is_blurry
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
from app.services.extraction_prompts import (
    build_document_extraction_payload,
    build_image_extraction_payload,
    compute_min_confidence,
    parse_extraction_result,
)
from app.services.heading_detect import detect_headings
from app.tasks._helpers import run_async_safely
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# =========================================================
# CONSTANTS
# =========================================================

REVIEW_THRESHOLD = 0.7
COST_PER_EXTRACTION_INR = 3.0


# =========================================================
# CELERY TASK
# =========================================================

@celery_app.task(
    bind=True,
    name="extraction.run",
    autoretry_for=(AIServiceError,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=2,
)
def run_extraction(self, extraction_id: str) -> dict:
    return run_async_safely(_do_run_extraction, extraction_id)


# =========================================================
# MAIN LOGIC
# =========================================================

async def _do_run_extraction(extraction_id: str) -> dict:
    await clients.startup()
    try:
        # --- 1. Load extraction + template --------------------------
        async with AsyncSessionLocal() as db:
            extraction = await db.scalar(
                select(Extraction).where(Extraction.id == extraction_id)
            )
            if not extraction:
                logger.error("Extraction not found: %s", extraction_id)
                return {"status": "not_found", "extraction_id": extraction_id}

            extraction.status = (
                ExtractionStatus.OCR_RUNNING
                if extraction.ocr_job_type == ExtractionJobType.DOCUMENT
                else ExtractionStatus.EXTRACTING
            )
            extraction.started_at = datetime.now(timezone.utc)
            await db.commit()

            template = await db.scalar(
                select(Template).where(Template.id == extraction.template_id)
            )
            if not template:
                await _fail(extraction_id, f"Template not found: {extraction.template_id}")
                return {"status": "failed", "extraction_id": extraction_id}

            # Snapshot data we need outside the session
            job_type = extraction.ocr_job_type
            file_url = extraction.file_url
            template_name = template.name
            template_desc = template.description
            fields = template.fields or []
            batch_id = extraction.batch_id

            await refresh_batch_counters(db, batch_id)
            await db.commit()

        # --- 2. Dispatch by file type -------------------------------
        if job_type == ExtractionJobType.IMAGE:
            return await _run_image_path(
                extraction_id, batch_id, file_url, template_name, template_desc, fields,
            )
        elif job_type == ExtractionJobType.DOCUMENT:
            return await _run_document_path(
                extraction_id, batch_id, file_url, template_name, template_desc, fields,
            )
        else:
            await _fail(extraction_id, f"Unknown ocr_job_type: {job_type}")
            return {"status": "failed", "extraction_id": extraction_id}

    finally:
        await clients.shutdown()


# =========================================================
# IMAGE PATH
# =========================================================

async def _run_image_path(
        extraction_id: str,
        batch_id: str,
        file_url: str,
        template_name: str,
        template_desc: str,
        fields: list[dict],
) -> dict:
    # --- pre-flight blurry check ---
    try:
        blurry, avg_conf = await is_blurry(file_url)
    except Exception as exc:
        logger.warning("blurry check failed (proceeding): %s", exc)
        blurry, avg_conf = False, 1.0

    if blurry:
        async with AsyncSessionLocal() as db:
            extraction = await db.scalar(
                select(Extraction).where(Extraction.id == extraction_id)
            )
            if extraction:
                extraction.status = ExtractionStatus.BLURRY
                extraction.error = f"Image appears blurry (avg confidence {avg_conf:.2f})"
                extraction.completed_at = datetime.now(timezone.utc)
                await db.commit()

                await refresh_batch_counters(db, batch_id)
                await db.commit()
        logger.info("extraction %s marked blurry (conf=%.2f)", extraction_id, avg_conf)
        return {"status": "blurry", "extraction_id": extraction_id}

    # --- vision call ---
    payload = build_image_extraction_payload(
        image_url=file_url,
        template_name=template_name,
        template_description=template_desc,
        fields=fields,
    )

    try:
        raw = await _post_ai("api/v1/chat/vision", payload)
    except AIServiceError as exc:
        await _fail(extraction_id, str(exc)[:2000])
        raise

    data = raw.get("data", raw) if isinstance(raw, dict) else {}
    usage = raw.get("usage") or {} if isinstance(raw, dict) else {}

    result = parse_extraction_result(data, fields)
    await _finalize(extraction_id, batch_id, result, fields, usage)

    return {"status": "completed", "extraction_id": extraction_id}


# =========================================================
# DOCUMENT PATH
# =========================================================

async def _run_document_path(
        extraction_id: str,
        batch_id: str,
        file_url: str,
        template_name: str,
        template_desc: str,
        fields: list[dict],
) -> dict:
    # --- 1. text extraction ---
    try:
        extracted = await extract_document(file_url)
    except DocumentExtractionError as exc:
        await _fail(extraction_id, f"Extraction failed: {exc}")
        return {"status": "failed", "extraction_id": extraction_id}

    # --- 2. heading detection ---
    headings = detect_headings(extracted)

    # --- 3. chunking ---
    chunks = chunk_document(extracted, headings)

    if not chunks:
        await _fail(extraction_id, "Document has no extractable content")
        return {"status": "failed", "extraction_id": extraction_id}

    # --- 4. per-chunk structure (existing pipeline) ---
    async with AsyncSessionLocal() as db:
        extraction = await db.scalar(
            select(Extraction).where(Extraction.id == extraction_id)
        )
        if extraction:
            extraction.status = ExtractionStatus.EXTRACTING
            await db.commit()

            await refresh_batch_counters(db, batch_id)
            await db.commit()

    results: list[ChunkResult] = []
    previous_last_block: str | None = None
    ai_calls = 0
    ai_tokens_in = 0
    ai_tokens_out = 0

    for chunk in chunks:
        chunk_result = await structure_chunk(
            chunk,
            previous_last_block=previous_last_block,
        )
        results.append(chunk_result)

        ai_calls += 1
        usage = chunk_result.usage or {}
        ai_tokens_in += int(usage.get("prompt_tokens", 0) or 0)
        ai_tokens_out += int(usage.get("completion_tokens", 0) or 0)

        previous_last_block = extract_last_block_text(chunk_result.blocks)

    # --- 5. merge to text digest ---
    merged = merge_chunk_results(results)
    document_text = _blocks_to_text(merged.get("blocks") or [])
    if not document_text.strip():
        await _fail(extraction_id, "Structured document is empty")
        return {"status": "failed", "extraction_id": extraction_id}

    # --- 6. field extraction (template applied to text) ---
    payload = build_document_extraction_payload(
        document_text=document_text,
        template_name=template_name,
        template_description=template_desc,
        fields=fields,
    )

    try:
        raw = await _post_ai("api/v1/chat/completion", payload)
    except AIServiceError as exc:
        await _fail(extraction_id, str(exc)[:2000])
        raise

    data = raw.get("data", raw) if isinstance(raw, dict) else {}
    usage = raw.get("usage") or {} if isinstance(raw, dict) else {}

    ai_calls += 1
    ai_tokens_in += int(usage.get("prompt_tokens", 0) or 0)
    ai_tokens_out += int(usage.get("completion_tokens", 0) or 0)

    result = parse_extraction_result(data, fields)
    await _finalize(extraction_id, batch_id, result, fields, usage, ai_calls=ai_calls,
                    ai_tokens_in=ai_tokens_in, ai_tokens_out=ai_tokens_out)

    return {"status": "completed", "extraction_id": extraction_id}


# =========================================================
# FINALIZATION
# =========================================================

async def _finalize(
        extraction_id: str,
        batch_id: str,
        result: dict,
        fields: list[dict],
        usage: dict,
        *,
        ai_calls: int = 1,
        ai_tokens_in: int | None = None,
        ai_tokens_out: int | None = None,
) -> None:
    """Write the extraction result and set the final status."""
    min_conf = compute_min_confidence(result, fields)
    review_needed = min_conf < REVIEW_THRESHOLD
    final_status = (
        ExtractionStatus.NEEDS_REVIEW if review_needed
        else ExtractionStatus.COMPLETED
    )

    # Use provided totals for multi-stage (documents); derive from usage
    # otherwise (images = 1 AI call).
    tokens_in = ai_tokens_in if ai_tokens_in is not None else int(usage.get("prompt_tokens", 0) or 0)
    tokens_out = ai_tokens_out if ai_tokens_out is not None else int(usage.get("completion_tokens", 0) or 0)

    async with AsyncSessionLocal() as db:
        extraction = await db.scalar(
            select(Extraction).where(Extraction.id == extraction_id)
        )
        if not extraction:
            logger.warning("Extraction disappeared: %s", extraction_id)
            return

        extraction.result = result
        extraction.min_confidence = min_conf
        extraction.review_needed = review_needed
        extraction.status = final_status
        extraction.completed_at = datetime.now(timezone.utc)
        extraction.ai_calls = ai_calls
        extraction.ai_tokens_in = tokens_in
        extraction.ai_tokens_out = tokens_out
        extraction.cost_estimate = COST_PER_EXTRACTION_INR
        extraction.error = None
        await db.commit()

        await refresh_batch_counters(db, batch_id)
        await db.commit()

    logger.info(
        "extraction complete id=%s status=%s min_conf=%.2f",
        extraction_id, final_status.value, min_conf,
    )


async def _fail(extraction_id: str, error: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            extraction = await db.scalar(
                select(Extraction).where(Extraction.id == extraction_id)
            )
            if extraction:
                extraction.status = ExtractionStatus.FAILED
                extraction.error = error[:2000]
                extraction.completed_at = datetime.now(timezone.utc)
                batch_id = extraction.batch_id
                await db.commit()

                await refresh_batch_counters(db, batch_id)
                await db.commit()
        logger.warning("extraction FAILED id=%s err=%s", extraction_id, error[:200])
    except Exception:
        logger.exception("failed to mark extraction failed: %s", extraction_id)


# =========================================================
# AI CALL HELPERS
# =========================================================

async def _post_ai(path: str, payload: dict) -> dict:
    """POST to the AI service and return parsed JSON. Raises AIServiceError."""
    import httpx
    assert clients.ai is not None, "AI client not initialised"
    try:
        response = await clients.ai.post(path, json=payload)
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise AIServiceError("Extraction request timed out") from exc
    except httpx.HTTPStatusError as exc:
        raise AIServiceError(
            f"AI returned {exc.response.status_code}: {exc.response.text[:300]}"
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


# =========================================================
# TEXT RENDERING FOR DOCUMENT PATH
# =========================================================

def _blocks_to_text(blocks: list[dict], max_chars: int = 32000) -> str:
    """Render blocks to a compact text digest for the extraction call.

    Truncates to max_chars if needed (same approach as analysis_input).
    """
    parts: list[str] = []
    total = 0

    for b in blocks:
        if not isinstance(b, dict):
            continue
        rendered = _render_block(b)
        if not rendered:
            continue
        if total + len(rendered) + 2 > max_chars:
            parts.append("[... truncated ...]")
            break
        parts.append(rendered)
        total += len(rendered) + 2

    return "\n\n".join(parts)


def _render_block(b: dict) -> str:
    t = b.get("type")
    if t == "heading":
        level = b.get("level") or 1
        return f"{'#' * max(1, min(level, 6))} {b.get('text', '').strip()}"
    if t == "paragraph":
        return b.get("text", "").strip()
    if t == "list":
        marker = "1." if b.get("ordered") else "-"
        return "\n".join(f"{marker} {str(i).strip()}" for i in (b.get("items") or []) if i)
    if t == "table":
        cols = b.get("columns") or []
        rows = b.get("rows") or []
        lines: list[str] = []
        if cols:
            lines.append("| " + " | ".join(str(c) for c in cols) + " |")
            lines.append("| " + " | ".join("---" for _ in cols) + " |")
        for row in rows:
            lines.append("| " + " | ".join(str(c) for c in row) + " |")
        return "\n".join(lines)
    if t == "page_break":
        return "\n---\n"
    if t == "image":
        return f"[image on page {b.get('page', '?')}]"
    return ""
