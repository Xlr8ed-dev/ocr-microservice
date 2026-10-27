import asyncio
import json
import logging

from sqlalchemy import select

from app.clients.ai import AIServiceError, vision_ocr
from app.clients.http import clients
from app.database import AsyncSessionLocal
from app.models import (
    JobStatus,
    OCRJob,
    OpenAIUsageLog,
    Visitor,
    WorkflowRun,
    WorkflowStatus,
)
from app.services import duplicate_service
from app.services.business_card_service import (
    BUSINESS_CARD_PROMPT,
    merge_ocr_results,
    parse_ai_response_to_ocr_result,
)
from app.tasks._helpers import run_async_safely
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


# =========================================================
# PROMPT (same as monolith)
# =========================================================

# BUSINESS_CARD_PROMPT lives in app/services/business_card_service.py
# (imported above) so both the OCR worker and any preview endpoint share it.


# =========================================================
# HELPERS
# =========================================================

def _run(coro):
    """Run an async coroutine from a sync Celery task.
    Each task owns its own event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


async def _write_usage_log(
        db,
        *,
        job_id: str,
        txn_id: str,
        admin_id: int,
        task_name: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
) -> None:
    db.add(OpenAIUsageLog(
        job_id=job_id,
        txn_id=txn_id,
        admin_id=admin_id,
        task_name=task_name,
        api_call_type="chat_completion",
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    ))
    await db.flush()


# =========================================================
# PRIMARY CARD TASK
# =========================================================

@celery_app.task(
    bind=True,
    name="ocr.run_primary",
    autoretry_for=(AIServiceError,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=3,
)
def run_ocr_primary(self, job_id: str) -> dict:
    return run_async_safely(_do_run_ocr_primary, job_id)


async def _do_run_ocr_primary(job_id: str) -> dict:
    await clients.startup()
    try:
        async with AsyncSessionLocal() as db:
            job = await db.scalar(
                select(OCRJob).where(OCRJob.job_id == job_id)
            )
            if not job:
                logger.error("OCR job not found: %s", job_id)
                return {"status": "not_found", "job_id": job_id}

            job.status = JobStatus.PROCESSING
            job.attempts += 1
            await db.flush()

            front_url = job.payload.get("front")
            back_url = job.payload.get("back")

            try:
                front_ocr = None
                back_ocr = None

                if front_url:
                    raw = await vision_ocr(
                        image_url=front_url,
                        prompt=BUSINESS_CARD_PROMPT,
                        image_side="front",
                    )
                    front_ocr = parse_ai_response_to_ocr_result(raw)
                    # usage log — extract from raw if present
                    usage = raw.get("usage") or {}
                    if usage:
                        await _write_usage_log(
                            db,
                            job_id=job.job_id,
                            txn_id=job.txn_id,
                            admin_id=job.admin_id,
                            task_name="primary_front",
                            model=usage.get("model", "gpt-4o-mini"),
                            prompt_tokens=usage.get("prompt_tokens", 0),
                            completion_tokens=usage.get("completion_tokens", 0),
                            total_tokens=usage.get("total_tokens", 0),
                        )

                if back_url:
                    raw = await vision_ocr(
                        image_url=back_url,
                        prompt=BUSINESS_CARD_PROMPT,
                        image_side="back",
                    )
                    back_ocr = parse_ai_response_to_ocr_result(raw)
                    usage = raw.get("usage") or {}
                    if usage:
                        await _write_usage_log(
                            db,
                            job_id=job.job_id,
                            txn_id=job.txn_id,
                            admin_id=job.admin_id,
                            task_name="primary_back",
                            model=usage.get("model", "gpt-4o-mini"),
                            prompt_tokens=usage.get("prompt_tokens", 0),
                            completion_tokens=usage.get("completion_tokens", 0),
                            total_tokens=usage.get("total_tokens", 0),
                        )

                merged = merge_ocr_results(front_ocr, back_ocr)

                # --- write result onto the job ---
                job.result = {
                    "front_ocr": front_ocr.model_dump() if front_ocr else None,
                    "back_ocr": back_ocr.model_dump() if back_ocr else None,
                    "merged_ocr": merged.model_dump(),
                }
                job.status = JobStatus.COMPLETED
                await db.flush()

                # --- apply to the visitor ---
                await _apply_primary_to_visitor(db, job, merged)

                # --- generate summaries from notes (best-effort) ---
                await _generate_and_store_summaries(db, job)

                # --- compute duplicates now that identity is populated ---
                visitor = await db.scalar(
                    select(Visitor).where(Visitor.txn_Id == job.txn_id)
                )
                if visitor:
                    await duplicate_service.compute_duplicate(db, visitor)

                # --- trigger workflow if one is queued ---
                await _maybe_start_workflow(db, job.txn_id)

                await db.commit()
                return {"status": "completed", "job_id": job_id}

            except Exception as exc:
                job.status = JobStatus.FAILED
                job.error = str(exc)[:2000]
                await db.commit()

                # mark workflow failed if it existed
                await _fail_workflow_if_exists(db, job.txn_id, str(exc))
                raise
    finally:
        await clients.shutdown()


async def _apply_primary_to_visitor(db, job: OCRJob, merged) -> None:
    """Write merged OCR result onto the Visitor row."""
    visitor = await db.scalar(
        select(Visitor).where(Visitor.txn_Id == job.txn_id)
    )
    if not visitor:
        return

    primary_card = [{
        "front": job.payload.get("front") or "",
        "back": job.payload.get("back") or "",
    }]

    # only overwrite if the visitor fields are still empty
    # (admin might have typed them manually — don't clobber)
    if not visitor.name and merged.name:
        visitor.name = merged.name[:255]
    if not visitor.company_name and merged.company:
        visitor.company_name = merged.company[:255]
    if not visitor.phone and merged.phones:
        visitor.phone = ", ".join(merged.phones)[:255]
    if not visitor.visitor_email and merged.emails:
        visitor.visitor_email = ", ".join(merged.emails)
    if not visitor.visitor_designation and merged.designation:
        visitor.visitor_designation = merged.designation
    if not visitor.visitor_websites and merged.websites:
        visitor.visitor_websites = ", ".join(merged.websites)
    if not visitor.visitor_address and merged.address:
        visitor.visitor_address = json.dumps([a.model_dump() for a in merged.address])

    visitor.visiting_card_primary = primary_card
    visitor.visiting_card_primary_ocr = json.dumps(job.result or {})
    visitor.ocr_status = True

    from datetime import datetime, timezone
    visitor.sync_updated_at = datetime.now(timezone.utc)

    await db.flush()


# =========================================================
# SUMMARIZE NOTES
# =========================================================

PLACEHOLDER_SUMMARY = "No meeting notes recorded."


async def _generate_and_store_summaries(db, job: OCRJob) -> None:
    """Generate notes_summarize + email_notes_summarize for the visitor.

    Best-effort: any failure is logged and swallowed. OCR results are
    already persisted by the caller; losing the summary is annoying but
    not fatal.
    """
    from app.clients.ai import AIServiceError, summarize_notes

    visitor = await db.scalar(
        select(Visitor).where(Visitor.txn_Id == job.txn_id)
    )
    if not visitor:
        return

    # Idempotent on retry: skip if already populated.
    if visitor.notes_summarize and visitor.email_notes_summarize:
        return

    notes_list = [str(n) for n in (visitor.notes or []) if n]
    notes_text = "\n".join(notes_list).strip()

    # No notes → set placeholder, no AI call needed.
    if not notes_text:
        visitor.notes_summarize = PLACEHOLDER_SUMMARY
        visitor.email_notes_summarize = PLACEHOLDER_SUMMARY
        await db.flush()
        return

    try:
        result = await summarize_notes(
            notes=notes_text,
            context={
                "visitor_name": visitor.name,
                "visitor_designation": visitor.visitor_designation,
                "visitor_company": visitor.company_name,
                "admin_company_name": visitor.admin_company_name,
                "event_name": visitor.event_name,
                "interest": visitor.interest,
            },
        )
    except AIServiceError as exc:
        logger.warning(
            "Summarize failed for txn=%s: %s (OCR result preserved)",
            job.txn_id, exc,
        )
        return

    visitor.notes_summarize = (
            result["notes_summarize"] or PLACEHOLDER_SUMMARY
    )
    visitor.email_notes_summarize = (
            result["email_notes_summarize"] or PLACEHOLDER_SUMMARY
    )

    usage = result.get("usage") or {}
    if usage:
        await _write_usage_log(
            db,
            job_id=job.job_id,
            txn_id=job.txn_id,
            admin_id=job.admin_id,
            task_name="summarize_notes",
            model=usage.get("model", "gpt-4o-mini"),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )

    await db.flush()


async def _maybe_start_workflow(db, txn_id: str) -> None:
    """If a WorkflowRun exists in PENDING for this txn, dispatch it."""
    run = await db.scalar(
        select(WorkflowRun)
        .where(WorkflowRun.txn_id == txn_id)
        .order_by(WorkflowRun.created_at.desc())
        .limit(1)
    )
    if not run:
        return
    if run.status != WorkflowStatus.PENDING:
        return

    # Import here to avoid circular imports
    from app.tasks.workflow_tasks import run_workflow
    run_workflow.apply_async(args=[run.run_id])


async def _fail_workflow_if_exists(db, txn_id: str, error: str) -> None:
    run = await db.scalar(
        select(WorkflowRun)
        .where(WorkflowRun.txn_id == txn_id)
        .order_by(WorkflowRun.created_at.desc())
        .limit(1)
    )
    if run and run.status in (WorkflowStatus.PENDING, WorkflowStatus.RUNNING):
        run.status = WorkflowStatus.FAILED
        run.error = error[:2000]
        await db.commit()


# =========================================================
# SECONDARY CARD TASK
# =========================================================

@celery_app.task(
    bind=True,
    name="ocr.run_secondary",
    autoretry_for=(AIServiceError,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=3,
)
def run_ocr_secondary(self, job_id: str) -> dict:
    return run_async_safely(_do_run_ocr_secondary, job_id)


async def _do_run_ocr_secondary(job_id: str) -> dict:
    await clients.startup()
    try:
        async with AsyncSessionLocal() as db:
            job = await db.scalar(
                select(OCRJob).where(OCRJob.job_id == job_id)
            )
            if not job:
                return {"status": "not_found", "job_id": job_id}

            job.status = JobStatus.PROCESSING
            job.attempts += 1
            await db.flush()

            cards = job.payload.get("cards") or []  # [[front, back], ...]
            secondary_data = []
            secondary_ocr_list = []

            try:
                for idx, (front_url, back_url) in enumerate(cards, start=1):
                    front_ocr = None
                    back_ocr = None

                    if front_url:
                        raw = await vision_ocr(
                            image_url=front_url,
                            prompt=BUSINESS_CARD_PROMPT,
                            image_side=f"secondary_{idx}_front",
                        )
                        front_ocr = parse_ai_response_to_ocr_result(raw)

                    if back_url:
                        raw = await vision_ocr(
                            image_url=back_url,
                            prompt=BUSINESS_CARD_PROMPT,
                            image_side=f"secondary_{idx}_back",
                        )
                        back_ocr = parse_ai_response_to_ocr_result(raw)

                    merged = merge_ocr_results(front_ocr, back_ocr)

                    secondary_data.append({
                        "id": idx,
                        "front": front_url or "",
                        "back": back_url or "",
                    })
                    secondary_ocr_list.append({
                        "id": str(idx),
                        "name": merged.name,
                        "designation": merged.designation,
                        "company": merged.company,
                        "emails": ", ".join(merged.emails),
                        "phones": ", ".join(merged.phones),
                        "address": [a.model_dump() for a in merged.address],
                        "websites": ", ".join(merged.websites),
                    })

                job.result = {
                    "visiting_card_secondary": secondary_data,
                    "visiting_card_secondary_ocr": secondary_ocr_list,
                }
                job.status = JobStatus.COMPLETED
                await db.flush()

                # --- apply to visitor ---
                visitor = await db.scalar(
                    select(Visitor).where(Visitor.txn_Id == job.txn_id)
                )
                if visitor:
                    visitor.visiting_card_secondary = secondary_data
                    visitor.visiting_card_secondary_ocr = json.dumps(secondary_ocr_list)
                    from datetime import datetime, timezone
                    visitor.sync_updated_at = datetime.now(timezone.utc)
                    await db.flush()

                await db.commit()
                return {"status": "completed", "job_id": job_id}

            except Exception as exc:
                job.status = JobStatus.FAILED
                job.error = str(exc)[:2000]
                await db.commit()
                raise
    finally:
        await clients.shutdown()
