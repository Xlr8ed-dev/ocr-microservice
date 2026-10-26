"""Template catalog endpoints.

Read-only. Templates are seed-only in v1; no create/update/delete
routes exist. Admin can add templates by editing the seed script and
re-running it (upsert by ID).

All routes require an authenticated user. Templates are global (not
scoped by admin_id) — every user sees the same catalog.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, current_user
from app.models import Template
from app.schemas.template import (
    TemplateCategoryListOut,
    TemplateCategoryOut,
    TemplateField,
    TemplateListItem,
    TemplateOut,
)
from app.schemas.common import PaginatedResponse
from app.utils.pagination import DEFAULT_PAGE_SIZE, build_meta, parse_page


router = APIRouter(prefix="/templates", tags=["Templates"])


# =========================================================
# LIST
# =========================================================

@router.get("", response_model=PaginatedResponse[TemplateListItem])
async def list_templates(
    page: int = Query(1, ge=1),
    items: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=200),
    category: str | None = Query(None, description="Filter by category"),
    query: str | None = Query(None, description="Search by name or description"),
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[TemplateListItem]:
    p = parse_page(page, items)

    base = select(Template).where(Template.is_active.is_(True))

    if category:
        base = base.where(Template.category == category)

    if query:
        pattern = f"%{query}%"
        base = base.where(
            Template.name.ilike(pattern) | Template.description.ilike(pattern)
        )

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.scalar(count_stmt)) or 0

    stmt = (
        base.order_by(Template.category, Template.name)
        .limit(p.limit)
        .offset(p.offset)
    )
    rows = list((await db.scalars(stmt)).all())

    data = [
        TemplateListItem(
            id=r.id,
            name=r.name,
            category=r.category,
            description=r.description,
            field_count=len(r.fields or []),
            sample_doc_url=r.sample_doc_url,
        )
        for r in rows
    ]

    return PaginatedResponse[TemplateListItem](
        data=data,
        pagination=build_meta(total, p),
    )


# =========================================================
# CATEGORIES (for the tabs above the list)
# =========================================================

@router.get("/categories", response_model=TemplateCategoryListOut)
async def list_categories(
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> TemplateCategoryListOut:
    stmt = (
        select(Template.category, func.count().label("count"))
        .where(Template.is_active.is_(True))
        .group_by(Template.category)
        .order_by(Template.category)
    )
    rows = (await db.execute(stmt)).all()

    return TemplateCategoryListOut(
        data=[
            TemplateCategoryOut(
                key=category,
                label=category,
                count=count,
            )
            for category, count in rows
        ],
    )


# =========================================================
# DETAIL
# =========================================================

@router.get("/{template_id}", response_model=TemplateOut)
async def get_template(
    template_id: str,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> TemplateOut:
    template = await db.scalar(
        select(Template).where(
            Template.id == template_id,
            Template.is_active.is_(True),
        )
    )
    if not template:
        raise HTTPException(404, "Template not found.")

    # Validate fields against the schema so a corrupt row doesn't crash the FE.
    # If a template's `fields` JSON is malformed, we still return it (with
    # best-effort parsing) rather than 500ing the whole catalog.
    try:
        fields = [TemplateField.model_validate(f) for f in (template.fields or [])]
    except Exception:
        fields = []

    return TemplateOut(
        id=template.id,
        name=template.name,
        category=template.category,
        description=template.description,
        fields=fields,
        sample_doc_url=template.sample_doc_url,
        is_active=template.is_active,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )