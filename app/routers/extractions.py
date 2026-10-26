"""Extraction endpoints.

Routes here are the FE-facing product layer:
  - POST /extractions        → start an extraction
  - GET  /extractions/{id}   → full result (with per-field confidence)
  - GET  /extractions        → paginated history, filtered

Extraction lifecycle:
    pending → ocr_running → extracting → completed | needs_review | failed
    (blurry short-circuits before ocr_running)

The actual work is delegated to a Celery task, same pattern as documents
and images.
"""

import uuid

import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, current_user
from app.models import (
    Extraction,
    ExtractionJobType,
    ExtractionStatus,
    Template,
)
from app.schemas.common import PaginatedResponse
from app.schemas.extraction import (
    ExtractionAccepted,
    ExtractionCreateRequest,
    ExtractionListItem,
    ExtractionOut,
    ExtractionResultField, ExtractionPatchRequest,
)
from app.services.extraction_edit import apply_field_edits
from app.services.extraction_export import export_extraction
from app.tasks.extraction_tasks import run_extraction
from app.utils.pagination import DEFAULT_PAGE_SIZE, build_meta, parse_page
from fastapi.responses import Response
from app.models import Template as TemplateModel

router = APIRouter(prefix="/extractions", tags=["Extractions"])

# =========================================================
# CONSTANTS
# =========================================================

# File types that route through the image pipeline (vision model).
IMAGE_FILE_TYPES = {"jpg", "jpeg", "png", "webp"}

# File types that route through the document pipeline (extract + structure).
DOCUMENT_FILE_TYPES = {"pdf", "docx", "txt", "doc"}


# =========================================================
# CREATE
# =========================================================

@router.post(
    "",
    response_model=ExtractionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_extraction(
        data: ExtractionCreateRequest,
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> ExtractionAccepted:
    # --- validate template ---------------------------------------
    template = await db.scalar(
        select(Template).where(
            Template.id == data.template_id,
            Template.is_active.is_(True),
        )
    )
    if not template:
        raise HTTPException(400, f"Unknown template_id: {data.template_id}")

    # --- validate file_type --------------------------------------
    file_type = data.file_type.lower().lstrip(".")
    if file_type in IMAGE_FILE_TYPES:
        ocr_job_type = ExtractionJobType.IMAGE
    elif file_type in DOCUMENT_FILE_TYPES:
        ocr_job_type = ExtractionJobType.DOCUMENT
    else:
        raise HTTPException(
            400,
            f"Unsupported file_type: {data.file_type}. "
            f"Allowed: {sorted(IMAGE_FILE_TYPES | DOCUMENT_FILE_TYPES)}",
        )

    # --- create the row ------------------------------------------
    extraction = Extraction(
        id=str(uuid.uuid4()),
        batch_id=data.batch_id,
        admin_id=user.admin_id,
        user_id=user.id,
        template_id=template.id,
        template_version="v1",
        file_name=data.file_name,
        file_url=data.file_url,
        file_type=file_type,
        ocr_job_type=ocr_job_type,
        status=ExtractionStatus.PENDING,
        review_needed=False,
    )
    db.add(extraction)
    await db.flush()

    # --- dispatch ------------------------------------------------
    run_extraction.apply_async(args=[extraction.id])

    return ExtractionAccepted(
        extraction_id=extraction.id,
        extraction_status=extraction.status.value,
    )


# =========================================================
# GET ONE
# =========================================================

@router.get("/{extraction_id}", response_model=ExtractionOut)
async def get_extraction(
        extraction_id: str,
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> ExtractionOut:
    extraction = await _get_scoped(db, extraction_id, user)
    return _to_out(extraction)


# =========================================================
# LIST
# =========================================================

@router.get("", response_model=PaginatedResponse[ExtractionListItem])
async def list_extractions(
        page: int = Query(1, ge=1),
        items: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=200),
        batch_id: str | None = Query(None, description="Filter to one batch"),
        template_id: str | None = Query(None, description="Filter by template"),
        extraction_status: str | None = Query(
            None, alias="status",
            description="pending | ocr_running | extracting | completed | needs_review | blurry | failed",
        ),
        review_only: bool = Query(
            False,
            description="Only extractions where review_needed is true",
        ),
        query: str | None = Query(None, description="Search by file_name"),
        created_since: str | None = Query(
            None,
            description="Inclusive lower bound for created_at (ISO date or datetime)",
        ),
        created_before: str | None = Query(
            None,
            description="Exclusive upper bound for created_at (ISO date or datetime)",
        ),
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ExtractionListItem]:
    p = parse_page(page, items)

    base = select(Extraction)
    if user.role != "SUPER_ADMIN":
        base = base.where(Extraction.admin_id == user.admin_id)

    if batch_id:
        base = base.where(Extraction.batch_id == batch_id)

    if template_id:
        base = base.where(Extraction.template_id == template_id)

    if extraction_status:
        try:
            status_enum = ExtractionStatus(extraction_status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {extraction_status}")
        base = base.where(Extraction.status == status_enum)

    if review_only:
        base = base.where(Extraction.review_needed.is_(True))

    if query:
        pattern = f"%{query}%"
        base = base.where(Extraction.file_name.ilike(pattern))

    if created_since:
        try:
            dt = _parse_datetime(created_since)
        except ValueError:
            raise HTTPException(400, f"Invalid created_since: {created_since}")
        base = base.where(Extraction.created_at >= dt)

    if created_before:
        try:
            dt = _parse_datetime(created_before)
        except ValueError:
            raise HTTPException(400, f"Invalid created_before: {created_before}")
        base = base.where(Extraction.created_at < dt)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.scalar(count_stmt)) or 0

    stmt = (
        base.order_by(Extraction.created_at.desc())
        .limit(p.limit)
        .offset(p.offset)
    )
    rows = list((await db.scalars(stmt)).all())

    return PaginatedResponse[ExtractionListItem](
        data=[ExtractionListItem.model_validate(r) for r in rows],
        pagination=build_meta(total, p),
    )


# =========================================================
# HELPERS
# =========================================================

async def _get_scoped(
        db: AsyncSession, extraction_id: str, user: CurrentUser,
) -> Extraction:
    stmt = select(Extraction).where(Extraction.id == extraction_id)
    if user.role != "SUPER_ADMIN":
        stmt = stmt.where(Extraction.admin_id == user.admin_id)
    extraction = await db.scalar(stmt)
    if not extraction:
        raise HTTPException(404, "Extraction not found.")
    return extraction


def _to_out(extraction: Extraction) -> ExtractionOut:
    """Convert the DB row to the detail schema.

    Handles the `result` JSONB conversion from raw dict to typed
    ExtractionResultField models so the OpenAPI schema reflects the
    true per-field shape.
    """
    result = None
    if extraction.result:
        try:
            result = {
                k: ExtractionResultField.model_validate(v)
                for k, v in extraction.result.items()
                if isinstance(v, dict)
            }
        except Exception:
            # If any field in result is malformed, return raw dict
            result = extraction.result

    return ExtractionOut(
        id=extraction.id,
        batch_id=extraction.batch_id,
        admin_id=extraction.admin_id,
        user_id=extraction.user_id,
        template_id=extraction.template_id,
        template_version=extraction.template_version,
        file_name=extraction.file_name,
        file_url=extraction.file_url,
        file_type=extraction.file_type,
        file_size_bytes=extraction.file_size_bytes,
        ocr_job_type=extraction.ocr_job_type.value,
        ocr_job_id=extraction.ocr_job_id,
        ocr_status=extraction.ocr_status,
        status=extraction.status.value,
        result=result,
        min_confidence=extraction.min_confidence,
        review_needed=extraction.review_needed,
        error=extraction.error,
        ai_calls=extraction.ai_calls,
        ai_tokens_in=extraction.ai_tokens_in,
        ai_tokens_out=extraction.ai_tokens_out,
        cost_estimate=extraction.cost_estimate,
        created_at=extraction.created_at,
        started_at=extraction.started_at,
        completed_at=extraction.completed_at,
        updated_at=extraction.updated_at,
    )


def _parse_datetime(value: str) -> datetime:
    """Parse either a date ('2026-10-19') or ISO datetime ('2026-10-19T10:00:00Z')."""
    from datetime import datetime, timezone

    value = value.strip()
    # Try full datetime first
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass
    # Try date only
    try:
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        raise


# =========================================================
# PATCH — edit field values
# =========================================================

@router.patch("/{extraction_id}", response_model=ExtractionOut)
async def patch_extraction(
        extraction_id: str,
        data: ExtractionPatchRequest,
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> ExtractionOut:
    extraction = await _get_scoped(db, extraction_id, user)

    # --- only completed or needs_review can be edited -----------
    if extraction.status not in (
            ExtractionStatus.COMPLETED,
            ExtractionStatus.NEEDS_REVIEW,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot edit extraction in status '{extraction.status.value}'. "
            f"Only completed or needs_review extractions can be edited.",
        )

    if not extraction.result:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Extraction has no result to edit.",
        )

    # --- permissions --------------------------------------------
    # Agents can edit only extractions they created.
    # Admins can edit any extraction in their tenant.
    # SUPER_ADMIN unrestricted.
    if user.role == "AGENT" and extraction.user_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Agents can only edit extractions they created.",
        )

    updated = await apply_field_edits(db, user, extraction, data.fields)
    return _to_out(updated)


# =========================================================
# EXPORT
# =========================================================

@router.get("/{extraction_id}/export")
async def export_extraction_endpoint(
        extraction_id: str,
        format: str = Query(
            "json",
            description="json | csv | vcard",
        ),
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> Response:
    extraction = await _get_scoped(db, extraction_id, user)

    # --- only completed / needs_review can be exported ----------------
    if extraction.status not in (
            ExtractionStatus.COMPLETED,
            ExtractionStatus.NEEDS_REVIEW,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot export extraction in status '{extraction.status.value}'. "
            f"Only completed or needs_review extractions can be exported.",
        )

    if not extraction.result:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Extraction has no result to export.",
        )

    template = await db.get(TemplateModel, extraction.template_id)
    if not template:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Template {extraction.template_id} is missing from the catalog.",
        )

    try:
        content, filename, media_type = export_extraction(
            extraction=extraction,
            template=template,
            format=format,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(content)),
        },
    )
