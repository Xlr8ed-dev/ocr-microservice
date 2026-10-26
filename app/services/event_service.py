from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUser
from app.models import Event, Visitor
from app.schemas.event import EventCreate, EventUpdate
from app.utils.hierarchy import apply_event_hierarchy
from app.utils.pagination import Page


# =========================================================
# CREATE
# =========================================================

async def create_event(
    db: AsyncSession, user: CurrentUser, data: EventCreate,
) -> Event:
    if user.role not in ("ADMIN", "SUPER_ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create events.",
        )

    event = Event(
        event_name=data.event_name,
        start_date=data.start_date,
        end_date=data.end_date,
        venue=data.venue,
        admin_id=user.admin_id,
        campaign_id=data.campaign_id,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)
    return event


# =========================================================
# READ — single
# =========================================================

async def get_event(
    db: AsyncSession, user: CurrentUser, event_id: int,
) -> Event:
    stmt = select(Event).where(Event.id == event_id)
    stmt = apply_event_hierarchy(stmt, user)

    event = await db.scalar(stmt)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found.",
        )
    return event


# =========================================================
# READ — list
# =========================================================

async def list_events(
    db: AsyncSession,
    user: CurrentUser,
    page: Page,
    query: str | None = None,
) -> tuple[list[Event], int]:
    base = select(Event)
    base = apply_event_hierarchy(base, user)

    if query:
        pattern = f"%{query}%"
        base = base.where(
            or_(
                Event.event_name.ilike(pattern),
                Event.venue.ilike(pattern),
            )
        )

    # count
    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.scalar(count_stmt)) or 0

    # page
    stmt = (
        base.order_by(Event.created_at.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    rows = (await db.scalars(stmt)).all()

    return list(rows), total


# =========================================================
# UPDATE
# =========================================================

async def update_event(
    db: AsyncSession, user: CurrentUser, event_id: int, data: EventUpdate,
) -> Event:
    if user.role not in ("ADMIN", "SUPER_ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can update events.",
        )

    event = await get_event(db, user, event_id)

    payload = data.model_dump(exclude_unset=True)
    for field, value in payload.items():
        setattr(event, field, value)

    await db.flush()
    await db.refresh(event)
    return event


# =========================================================
# DELETE
# =========================================================

async def delete_event(
    db: AsyncSession, user: CurrentUser, event_id: int,
) -> None:
    if user.role not in ("ADMIN", "SUPER_ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete events.",
        )

    event = await get_event(db, user, event_id)

    # Refuse if visitors exist — CASCADE would wipe them silently.
    # If the user really wants to delete, they must delete visitors first.
    visitor_count = await db.scalar(
        select(func.count()).select_from(Visitor).where(Visitor.event_id == event.id)
    )
    if visitor_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot delete event: {visitor_count} visitor(s) are attached. "
                "Delete those visitors first, or archive the event instead."
            ),
        )

    await db.delete(event)
    await db.flush()