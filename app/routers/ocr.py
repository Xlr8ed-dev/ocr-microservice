"""Unified OCR read API.

Documents and images live in separate tables and have separate routers, which
forced the FE to merge two paginated lists for its "All OCR" screen. This
router provides one read surface over both:

    GET /ocr/jobs          -> merged, paginated list (light rows)
    GET /ocr/jobs/{id}     -> full document or image job, by id alone

Nothing here writes: the family endpoints remain the source of truth for
creation and family-specific behaviour. Scoping matches those routers:
everyone except SUPER_ADMIN sees only their workspace's jobs.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, current_user
from app.models import (
    DocumentOCRJob,
    DocumentOCRStatus,
    ImageOCRJob,
    ImageOCRStatus,
)
from app.routers.documents import job_to_out as document_job_to_out
from app.routers.images import job_to_out as image_job_to_out
from app.schemas.common import PaginatedResponse
from app.schemas.document import DocumentJobOut
from app.schemas.image import ImageJobOut
from app.schemas.ocr_jobs import OcrJobListItem
from app.utils.pagination import DEFAULT_PAGE_SIZE, build_meta, parse_page

router = APIRouter(prefix="/ocr", tags=["OCR"])

DOCUMENT_STATUSES = {item.value for item in DocumentOCRStatus}
IMAGE_STATUSES = {item.value for item in ImageOCRStatus}


# =========================================================
# FILTER RESOLUTION
# =========================================================

def resolve_filters(
    kind: str | None,
    job_status: str | None,
) -> tuple[bool, bool, DocumentOCRStatus | None, ImageOCRStatus | None]:
    """Decide which families and statuses a list request covers.

    `status` is shared by both families, but their vocabularies differ:

        documents: pending | extracting | structuring | completed | failed
        images:    pending | processing | completed | failed

    A status only one family knows (e.g. `structuring`) simply excludes the
    other family instead of being rejected. A status NEITHER knows is a 400.

    Returns:
        (include_documents, include_images, document_status, image_status)
    """
    if kind is not None and kind not in ("document", "image"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Invalid kind: {kind}. Expected 'document' or 'image'.",
        )

    include_documents = kind in (None, "document")
    include_images = kind in (None, "image")
    document_status = None
    image_status = None

    if job_status:
        known_to_documents = job_status in DOCUMENT_STATUSES
        known_to_images = job_status in IMAGE_STATUSES

        if not known_to_documents and not known_to_images:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Invalid status: {job_status}. "
                f"Documents: {sorted(DOCUMENT_STATUSES)}. "
                f"Images: {sorted(IMAGE_STATUSES)}.",
            )

        # Asking for a status the chosen family cannot have is a client error,
        # not an empty page.
        if kind == "document" and not known_to_documents:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Invalid status for documents: {job_status}.",
            )
        if kind == "image" and not known_to_images:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Invalid status for images: {job_status}.",
            )

        if known_to_documents and include_documents:
            document_status = DocumentOCRStatus(job_status)
        else:
            include_documents = False

        if known_to_images and include_images:
            image_status = ImageOCRStatus(job_status)
        else:
            include_images = False

    return include_documents, include_images, document_status, image_status


# =========================================================
# ROW MAPPING
# =========================================================

def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else value


def _image_file_name(source_url: str | None) -> str | None:
    """Image jobs store no filename, so derive one from the URL path."""
    if not source_url:
        return None
    path = source_url.split("?", 1)[0].rstrip("/")
    name = path.rsplit("/", 1)[-1]
    return name or None


def document_list_item(job: DocumentOCRJob) -> OcrJobListItem:
    return OcrJobListItem(
        id=job.job_id,
        kind="document",
        file_name=job.file_name,
        file_type=_enum_value(job.file_type),
        status=_enum_value(job.status),
        progress=job.progress,
        page_count=job.page_count,
        error=job.error,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


def image_list_item(job: ImageOCRJob) -> OcrJobListItem:
    return OcrJobListItem(
        id=job.job_id,
        kind="image",
        file_name=_image_file_name(job.source_url),
        image_type=_enum_value(job.image_type),
        status=_enum_value(job.status),
        error=job.error,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


def merge_page(
    documents: list[DocumentOCRJob],
    images: list[ImageOCRJob],
    *,
    offset: int,
    limit: int,
) -> list[OcrJobListItem]:
    """Merge two already-ordered result sets into one global page.

    Callers fetch `offset + limit` rows from EACH family (not just `limit`), so
    the globally newest rows cannot be missed when one family dominates the
    head of the list.
    """
    rows: list[tuple[str, DocumentOCRJob | ImageOCRJob]] = [
        ("document", row) for row in documents
    ] + [("image", row) for row in images]

    rows.sort(key=lambda pair: pair[1].created_at, reverse=True)
    page = rows[offset: offset + limit]

    return [
        document_list_item(row)
        if kind == "document"
        else image_list_item(row)
        for kind, row in page
    ]


# =========================================================
# LIST
# =========================================================

@router.get("/jobs", response_model=PaginatedResponse[OcrJobListItem])
async def list_ocr_jobs(
    page: int = Query(1, ge=1),
    items: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=200),
    kind: str | None = Query(
        None, description="Filter by family: document | image"
    ),
    job_status: str | None = Query(
        None,
        alias="status",
        description=(
            "pending | extracting | structuring | completed | failed "
            "(documents) or pending | processing | completed | failed (images)"
        ),
    ),
    query: str | None = Query(
        None,
        description=(
            "Search document file_name and image source_url "
            "(case-insensitive)"
        ),
    ),
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[OcrJobListItem]:
    """One page of every OCR job, newest first, across both families.

    Rows are light (no `output`): fetch `GET /ocr/jobs/{id}` for the result.
    This is the endpoint the "All OCR" screen should call instead of merging
    `GET /documents` and `GET /images` itself.
    """
    p = parse_page(page, items)
    include_documents, include_images, document_status, image_status = (
        resolve_filters(kind, job_status)
    )

    document_stmt = select(DocumentOCRJob)
    image_stmt = select(ImageOCRJob)

    if user.role != "SUPER_ADMIN":
        document_stmt = document_stmt.where(
            DocumentOCRJob.admin_id == user.admin_id
        )
        image_stmt = image_stmt.where(ImageOCRJob.admin_id == user.admin_id)

    if document_status is not None:
        document_stmt = document_stmt.where(
            DocumentOCRJob.status == document_status
        )
    if image_status is not None:
        image_stmt = image_stmt.where(ImageOCRJob.status == image_status)

    if query:
        pattern = f"%{query}%"
        document_stmt = document_stmt.where(
            DocumentOCRJob.file_name.ilike(pattern)
        )
        image_stmt = image_stmt.where(ImageOCRJob.source_url.ilike(pattern))

    total = 0
    if include_documents:
        total += (await db.scalar(
            select(func.count()).select_from(document_stmt.subquery())
        )) or 0
    if include_images:
        total += (await db.scalar(
            select(func.count()).select_from(image_stmt.subquery())
        )) or 0

    # Fetch offset+limit from each family so the merge is correct for any page.
    scan = p.offset + p.limit
    documents: list[DocumentOCRJob] = []
    images: list[ImageOCRJob] = []

    if include_documents:
        documents = list((await db.scalars(
            document_stmt.order_by(DocumentOCRJob.created_at.desc()).limit(scan)
        )).all())
    if include_images:
        images = list((await db.scalars(
            image_stmt.order_by(ImageOCRJob.created_at.desc()).limit(scan)
        )).all())

    return PaginatedResponse[OcrJobListItem](
        data=merge_page(
            documents, images, offset=p.offset, limit=p.limit
        ),
        pagination=build_meta(total, p),
    )


# =========================================================
# DETAIL
# =========================================================

@router.get(
    "/jobs/{job_id}",
    response_model=DocumentJobOut | ImageJobOut,
    responses={
        404: {"description": "No document or image job with that id"},
    },
)
async def get_ocr_job(
    job_id: str,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentJobOut | ImageJobOut:
    """Full result of a document OR image job, resolved by id alone.

    The FE keeps one id per row from `GET /ocr/jobs`; it does not need to know
    which family the row belongs to. Document results include `output.blocks`;
    image results include `image_type` and `output.structured_output`.
    """
    document_stmt = select(DocumentOCRJob).where(
        DocumentOCRJob.job_id == job_id
    )
    if user.role != "SUPER_ADMIN":
        document_stmt = document_stmt.where(
            DocumentOCRJob.admin_id == user.admin_id
        )
    document = await db.scalar(document_stmt)
    if document:
        return document_job_to_out(document)

    image_stmt = select(ImageOCRJob).where(ImageOCRJob.job_id == job_id)
    if user.role != "SUPER_ADMIN":
        image_stmt = image_stmt.where(ImageOCRJob.admin_id == user.admin_id)
    image = await db.scalar(image_stmt)
    if image:
        return image_job_to_out(image)

    raise HTTPException(
        status.HTTP_404_NOT_FOUND, "OCR job not found."
    )
