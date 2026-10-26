from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, current_user
from app.schemas.common import PaginatedResponse
from app.schemas.event import EventCreate, EventOut, EventUpdate
from app.services import event_service
from app.utils.pagination import DEFAULT_PAGE_SIZE, build_meta, parse_page


router = APIRouter(prefix="/events", tags=["Events"])


@router.post(
    "",
    response_model=EventOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_event(
    data: EventCreate,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> EventOut:
    event = await event_service.create_event(db, user, data)
    return EventOut.model_validate(event)


@router.get("", response_model=PaginatedResponse[EventOut])
async def list_events(
    page: int = Query(1, ge=1),
    items: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=200),
    query: str | None = Query(None, description="Search by event name / venue"),
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[EventOut]:
    p = parse_page(page, items)
    rows, total = await event_service.list_events(db, user, p, query)
    return PaginatedResponse[EventOut](
        data=[EventOut.model_validate(r) for r in rows],
        pagination=build_meta(total, p),
    )


@router.get("/{event_id}", response_model=EventOut)
async def get_event(
    event_id: int,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> EventOut:
    event = await event_service.get_event(db, user, event_id)
    return EventOut.model_validate(event)


@router.patch("/{event_id}", response_model=EventOut)
async def update_event(
    event_id: int,
    data: EventUpdate,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> EventOut:
    event = await event_service.update_event(db, user, event_id, data)
    return EventOut.model_validate(event)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: int,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await event_service.delete_event(db, user, event_id)
    return None