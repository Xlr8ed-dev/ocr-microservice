"""Stats endpoint for the Home screen.

Read-only aggregates over the caller's extractions. Cheap queries,
not cached in v1 (they're fast enough).

Scope:
  - ADMIN → own admin_id's extractions
  - AGENT → only their own
  - SUPER_ADMIN → all
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, current_user
from app.models import Extraction, ExtractionStatus, Template
from app.schemas.stats import (
    StatsOverviewOut,
    StatusCountItem,
    TemplateUsageItem, NeedsReviewCountOut,
)

router = APIRouter(prefix="/stats", tags=["Stats"])


# =========================================================
# OVERVIEW
# =========================================================

@router.get("/overview", response_model=StatsOverviewOut)
async def get_overview(
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> StatsOverviewOut:
    # --- base scope ---
    base = select(Extraction)
    if user.role == "ADMIN":
        base = base.where(Extraction.admin_id == user.admin_id)
    elif user.role == "AGENT":
        base = base.where(Extraction.user_id == user.id)
    # SUPER_ADMIN → no filter

    # --- total ---
    total = (await db.scalar(
        select(func.count()).select_from(base.subquery())
    )) or 0

    # --- this month ---
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    )
    this_month = (await db.scalar(
        select(func.count())
        .select_from(base.subquery())
        .where(Extraction.created_at >= month_start)
    )) or 0

    # --- per-status counts ---
    status_stmt = (
        select(Extraction.status, func.count().label("count"))
        .group_by(Extraction.status)
    )
    if user.role == "ADMIN":
        status_stmt = status_stmt.where(Extraction.admin_id == user.admin_id)
    elif user.role == "AGENT":
        status_stmt = status_stmt.where(Extraction.user_id == user.id)

    status_rows = (await db.execute(status_stmt)).all()
    status_counts = {s.value: 0 for s in ExtractionStatus}
    for status_enum, count in status_rows:
        status_counts[status_enum.value] = count

    by_status = [
        StatusCountItem(status=s, count=c)
        for s, c in sorted(status_counts.items())
    ]

    needs_review = status_counts.get("needs_review", 0)
    failed = status_counts.get("failed", 0)
    in_progress = (
            status_counts.get("pending", 0)
            + status_counts.get("ocr_running", 0)
            + status_counts.get("extracting", 0)
    )

    # --- per-template counts (top 10) ---
    template_stmt = (
        select(
            Extraction.template_id,
            func.count().label("count"),
        )
        .group_by(Extraction.template_id)
        .order_by(func.count().desc())
        .limit(10)
    )
    if user.role == "ADMIN":
        template_stmt = template_stmt.where(Extraction.admin_id == user.admin_id)
    elif user.role == "AGENT":
        template_stmt = template_stmt.where(Extraction.user_id == user.id)

    template_rows = (await db.execute(template_stmt)).all()
    template_ids = [tid for tid, _ in template_rows]

    template_meta: dict[str, Template] = {}
    if template_ids:
        meta_rows = (await db.scalars(
            select(Template).where(Template.id.in_(template_ids))
        )).all()
        template_meta = {t.id: t for t in meta_rows}

    by_template = [
        TemplateUsageItem(
            template_id=tid,
            template_name=template_meta[tid].name if tid in template_meta else tid,
            category=template_meta[tid].category if tid in template_meta else "Unknown",
            count=count,
        )
        for tid, count in template_rows
    ]

    return StatsOverviewOut(
        total_extractions=total,
        total_this_month=this_month,
        needs_review_count=needs_review,
        failed_count=failed,
        in_progress_count=in_progress,
        by_status=by_status,
        by_template=by_template,
    )


@router.get("/needs-review", response_model=NeedsReviewCountOut)
async def get_needs_review_count(
        user: CurrentUser = Depends(current_user),
        db: AsyncSession = Depends(get_db),
) -> NeedsReviewCountOut:
    stmt = select(func.count()).select_from(Extraction).where(
        Extraction.review_needed.is_(True),
        Extraction.status == ExtractionStatus.NEEDS_REVIEW,
    )
    if user.role == "ADMIN":
        stmt = stmt.where(Extraction.admin_id == user.admin_id)
    elif user.role == "AGENT":
        stmt = stmt.where(Extraction.user_id == user.id)

    count = (await db.scalar(stmt)) or 0
    return NeedsReviewCountOut(count=count)
