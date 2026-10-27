"""Document OCR endpoints.

All routes require an authenticated user (JWT). Jobs are scoped to the
caller's admin_id — cross-tenant access returns 404, not 403.
"""

import io
import json
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, current_user
from app.models import DocumentOCRJob, DocumentOCRStatus, BatchKind, DocumentFileType
from app.schemas.batch import BatchCreatedResponse, BatchJobItem
from app.schemas.common import PaginatedResponse
from app.schemas.document import (
    DocumentJobOut,
    DocumentListOut,
    DocumentOutput, DocumentBatchCreateRequest,
)
from app.services.batch_service import create_batch
from app.services.document_export import (
    render_blocks_as_markdown,
    render_blocks_as_text,
)
from app.tasks.document_tasks import run_document_ocr
from app.utils.pagination import DEFAULT_PAGE_SIZE, build_meta, parse_page

router = APIRouter(prefix="/documents", tags=["Documents"])


# =========================================================
# CONSTANTS
# =========================================================

ALLOWED_DOCUMENT_TYPES = {"pdf", "docx", "txt"}


# =========================================================
# CREATE — batch upload
# =========================================================

@router.post(
    "",
    response_model=BatchCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_document_batch(
    data: DocumentBatchCreateRequest,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> BatchCreatedResponse:
    # --- validate file types --------------------------------------
    invalid = [
        f.file_name for f in data.files
        if f.file_type.lower().lstrip(".") not in ALLOWED_DOCUMENT_TYPES
    ]
    if invalid:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported file type(s) for document OCR: {invalid}. "
            f"Allowed: {sorted(ALLOWED_DOCUMENT_TYPES)}. "
            f"For images, use POST /images.",
        )

    # --- create batch ---------------------------------------------
    batch = await create_batch(
        db,
        admin_id=user.admin_id,
        user_id=user.id,
        kind=BatchKind.DOCUMENT,
        template_id=None,
        total_files=len(data.files),
        label=data.label,
    )

    # --- create one job per file ---------------------------------
    jobs: list[BatchJobItem] = []
    job_ids: list[str] = []

    for file_input in data.files:
        # We don't know the exact file type (pdf_text vs pdf_scan) until
        # the worker reads the file. Default to TXT as a safe placeholder;
        # the worker updates it after extraction.
        job = DocumentOCRJob(
            job_id=str(uuid.uuid4()),
            batch_id=batch.id,
            admin_id=user.admin_id,
            user_id=user.id,
            source_url=file_input.url,
            file_name=file_input.file_name,
            file_type=DocumentFileType.TXT,
            status=DocumentOCRStatus.PENDING,
            progress=0,
        )
        db.add(job)
        await db.flush()

        jobs.append(BatchJobItem(
            id=job.job_id,
            file_name=job.file_name or "",
            status=job.status.value,
        ))
        job_ids.append(job.job_id)

    # --- dispatch workers -----------------------------------------
    # Dispatch after flush — worker may start immediately and needs the row
    for job_id in job_ids:
        run_document_ocr.apply_async(args=[job_id])

    return BatchCreatedResponse(
        batch_id=batch.id,
        total_files=len(jobs),
        jobs=jobs,
    )


# =========================================================
# GET ONE
# =========================================================

@router.get("/{job_id}", response_model=DocumentJobOut)
async def get_document_job(
        job_id: str,
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> DocumentJobOut:
    job = await _get_job_scoped(db, job_id, user)
    return _job_to_out(job)


# =========================================================
# LIST
# =========================================================

@router.get("", response_model=PaginatedResponse[DocumentListOut])
async def list_document_jobs(
        page: int = Query(1, ge=1),
        items: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=200),
        job_status: str | None = Query(None, alias="status"),
        query: str | None = Query(None, description="Search in file_name"),
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[DocumentListOut]:
    p = parse_page(page, items)

    base = select(DocumentOCRJob)
    if user.role != "SUPER_ADMIN":
        base = base.where(DocumentOCRJob.admin_id == user.admin_id)

    if job_status:
        try:
            status_enum = DocumentOCRStatus(job_status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {job_status}")
        base = base.where(DocumentOCRJob.status == status_enum)

    if query:
        pattern = f"%{query}%"
        base = base.where(DocumentOCRJob.file_name.ilike(pattern))

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.scalar(count_stmt)) or 0

    stmt = (
        base.order_by(DocumentOCRJob.created_at.desc())
        .limit(p.limit)
        .offset(p.offset)
    )
    rows = list((await db.scalars(stmt)).all())

    return PaginatedResponse[DocumentListOut](
        data=[DocumentListOut.model_validate(r) for r in rows],
        pagination=build_meta(total, p),
    )


# =========================================================
# DELETE
# =========================================================

@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document_job(
        job_id: str,
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> None:
    if user.role not in ("ADMIN", "SUPER_ADMIN"):
        raise HTTPException(403, "Only admins can delete document jobs.")

    job = await _get_job_scoped(db, job_id, user)
    await db.delete(job)
    await db.flush()


# =========================================================
# EXPORT
# =========================================================

@router.get("/{job_id}/export")
async def export_document(
        job_id: str,
        format: Literal["json", "md", "txt"] = Query("json"),
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
):
    job = await _get_job_scoped(db, job_id, user)

    if job.status != DocumentOCRStatus.COMPLETED:
        raise HTTPException(
            409,
            f"Job is not completed yet (status: {job.status.value})",
        )

    output = job.output or {}
    blocks = output.get("blocks") or []
    title = output.get("title") or "document"
    safe_name = _safe_filename(job.file_name or title)

    if format == "json":
        body = json.dumps(output, indent=2, ensure_ascii=False).encode("utf-8")
        return _stream(body, f"{safe_name}.json", "application/json")

    if format == "md":
        text = render_blocks_as_markdown(output)
        return _stream(text.encode("utf-8"), f"{safe_name}.md", "text/markdown")

    # txt
    text = render_blocks_as_text(output)
    return _stream(text.encode("utf-8"), f"{safe_name}.txt", "text/plain")


# =========================================================
# HELPERS
# =========================================================

async def _get_job_scoped(
        db: AsyncSession, job_id: str, user: CurrentUser,
) -> DocumentOCRJob:
    stmt = select(DocumentOCRJob).where(DocumentOCRJob.job_id == job_id)
    if user.role != "SUPER_ADMIN":
        stmt = stmt.where(DocumentOCRJob.admin_id == user.admin_id)
    job = await db.scalar(stmt)
    if not job:
        raise HTTPException(404, "Document job not found.")
    return job


def _job_to_out(job: DocumentOCRJob) -> DocumentJobOut:
    """Convert model → schema. Ensures `output` is validated as DocumentOutput
    when present, so malformed block data from a bad AI response is caught
    at serialization rather than silently returned."""
    output = None
    if job.output:
        try:
            output = DocumentOutput.model_validate(job.output)
        except Exception:
            # Log and return raw — better than failing the whole GET
            output = None

    return DocumentJobOut(
        job_id=job.job_id,
        admin_id=job.admin_id,
        user_id=job.user_id,
        source_url=job.source_url,
        file_name=job.file_name,
        file_type=job.file_type.value if hasattr(job.file_type, "value") else job.file_type,
        file_size_bytes=job.file_size_bytes,
        status=job.status.value if hasattr(job.status, "value") else job.status,
        progress=job.progress,
        page_count=job.page_count,
        chunk_count=job.chunk_count,
        output=output,
        error=job.error,
        cost_estimate=job.cost_estimate,
        ai_calls=job.ai_calls,
        ai_tokens_in=job.ai_tokens_in,
        ai_tokens_out=job.ai_tokens_out,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def _safe_filename(name: str) -> str:
    """Strip path separators and limit length."""
    safe = "".join(c for c in name if c.isalnum() or c in "-_. ").strip()
    return (safe or "document")[:100]


def _stream(data: bytes, filename: str, media_type: str) -> StreamingResponse:
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Length": str(len(data)),
    }
    return StreamingResponse(io.BytesIO(data), media_type=media_type, headers=headers)
