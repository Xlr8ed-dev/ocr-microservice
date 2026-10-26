from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, current_user
from app.flows.registry import get_flow
from app.schemas.common import PaginatedResponse
from app.schemas.visitor import (
    DuplicateInfo,
    VisitorAccepted,
    VisitorCreate,
    VisitorListOut,
    VisitorOut,
    VisitorUpdate,
)
from app.schemas.workflow import WorkflowRunOut
from app.services import visitor_service
from app.utils.pagination import DEFAULT_PAGE_SIZE, build_meta, parse_page


router = APIRouter(prefix="/visitors", tags=["Visitors"])


@router.post(
    "",
    response_model=VisitorAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_visitor(
    data: VisitorCreate,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> VisitorAccepted:
    # Resolve flow (silent fallback inside get_flow)
    flow_def = get_flow(data.flow.name if data.flow else None)

    visitor, run = await visitor_service.create_visitor(
        db, user, data, flow_def,
    )

    return VisitorAccepted(
        txn_Id=visitor.txn_Id,
        ocr_status="pending" if not visitor.ocr_status else "ready",
        workflow_run_id=run.run_id if run else None,
    )


@router.get("", response_model=PaginatedResponse[VisitorListOut])
async def list_visitors(
    page: int = Query(1, ge=1),
    items: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=200),
    event_id: int | None = Query(None),
    agent_id: int | None = Query(None),
    query: str | None = Query(None, description="Search name / phone / email / company"),
    include_deleted: bool = Query(False),
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[VisitorListOut]:
    p = parse_page(page, items)
    rows, total = await visitor_service.list_visitors(
        db, user, p,
        event_id=event_id,
        agent_id=agent_id,
        query=query,
        include_deleted=include_deleted,
    )
    return PaginatedResponse[VisitorListOut](
        data=[VisitorListOut.model_validate(r) for r in rows],
        pagination=build_meta(total, p),
    )


@router.get("/{txn_id}", response_model=VisitorOut)
async def get_visitor(
    txn_id: str,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> VisitorOut:
    visitor = await visitor_service.get_visitor(db, user, txn_id)
    return VisitorOut.model_validate(visitor)


@router.patch("/{txn_id}", response_model=VisitorOut)
async def update_visitor(
    txn_id: str,
    data: VisitorUpdate,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> VisitorOut:
    visitor = await visitor_service.update_visitor(db, user, txn_id, data)
    return VisitorOut.model_validate(visitor)


@router.delete("/{txn_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_visitor(
    txn_id: str,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await visitor_service.delete_visitor(db, user, txn_id)
    return None


@router.get("/{txn_id}/duplicates", response_model=DuplicateInfo)
async def get_duplicates(
    txn_id: str,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> DuplicateInfo:
    return await visitor_service.get_duplicates(db, user, txn_id)


@router.get("/{txn_id}/workflow", response_model=WorkflowRunOut | None)
async def get_visitor_workflow(
    txn_id: str,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunOut | None:
    run = await visitor_service.get_visitor_workflow(db, user, txn_id)
    if run is None:
        return None
    return WorkflowRunOut.model_validate(run)