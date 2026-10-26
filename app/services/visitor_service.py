import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUser
from app.flows.registry import FlowDefinition
from app.models import Event, Visitor, WorkflowRun, WorkflowStatus
from app.schemas.visitor import (
    AddressOut,
    EventDetails,
    EventInfo,
    SecondaryOCROut,
    VisitorCreate,
    VisitorUpdate,
    VisitingCardOut,
    VisitingCardPrimary,
    VisitingCardSecondary, DuplicateInfo,
)
from app.services import ocr_service
from app.utils.pagination import Page

logger = logging.getLogger(__name__)


# =========================================================
# HELPERS
# =========================================================
async def _shape_visitor_out(
        db: AsyncSession, visitor: Visitor,
) -> dict:
    """Build the full monolith-shaped response dict for a visitor row."""
    event_details = await _build_event_details(db, visitor)

    agent_name: str | None = None
    if visitor.agent_id:
        # SSO lookup comes in 5.4
        agent_name = None

    secondary_ocr = _parse_secondary_ocr(visitor.visiting_card_secondary_ocr)
    visitor_address = _parse_address(visitor.visitor_address)
    visiting_card = _build_visiting_card_out(visitor)

    return {
        "txn_Id": visitor.txn_Id,
        "name": visitor.name,
        "company_name": visitor.company_name,
        "phone": visitor.phone,
        "visitor_email": visitor.visitor_email,
        "image": visitor.image,
        "interest": visitor.interest,
        "date": visitor.date,
        "meet_time": visitor.meet_time,
        "created_at": visitor.created_at,
        "sync_at": visitor.sync_at,
        "sync_updated_at": visitor.sync_updated_at,
        "admin_id": visitor.admin_id,
        "agent_id": visitor.agent_id,
        "agent_name": agent_name,
        "admin_company_name": visitor.admin_company_name,
        "event": visitor.event_id,
        "event_details": event_details,
        "visitor_address": visitor_address,
        "visitor_designation": visitor.visitor_designation,
        "visitor_websites": visitor.visitor_websites,
        "visitor_category": visitor.visitor_category,
        "visiting_card": visiting_card,
        "visiting_card_secondary_ocr": secondary_ocr,
        "products": visitor.products,
        "notes": visitor.notes or [],
        "voice_notes": visitor.voice_notes or [],
        "notes_summarize": visitor.notes_summarize,
        "is_duplicate": visitor.is_duplicate,
        "duplicate_of": visitor.duplicate_of,
        "related_event_ids": visitor.related_event_ids or [],
        "is_stopped": visitor.is_stopped,
        "is_stopped_at": visitor.is_stopped_at,
        "ocr_status": visitor.ocr_status,
    }


def _resolve_agent_id(user: CurrentUser, requested_agent_id: int | None) -> int | None:
    """Determine which agent_id to attach to the visitor.

    ADMIN       → None (admin created it, no agent attribution)
    AGENT       → user.id (agent created it)
    SUPER_ADMIN → whatever the request asked for (or None)
    """
    if user.role == "AGENT":
        return user.id
    if user.role == "SUPER_ADMIN":
        return requested_agent_id
    return None


def _build_primary_card(
        front: str | None, back: str | None,
) -> list[dict]:
    """Monolith shape: list of one dict {front, back}."""
    if not front and not back:
        return []
    return [{"front": front or "", "back": back or ""}]


def _build_secondary_cards(cards: list) -> list[dict]:
    """Monolith shape: list of {id, front, back}, 1-based ids, skipping fully-empty cards."""
    out: list[dict] = []
    for idx, card in enumerate(cards, start=1):
        front = getattr(card, "front", None) or (
            card.get("front") if isinstance(card, dict) else None
        )
        back = getattr(card, "back", None) or (
            card.get("back") if isinstance(card, dict) else None
        )
        if not front and not back:
            continue
        out.append({"id": idx, "front": front or "", "back": back or ""})
    return out


def _parse_json_list(raw: str | None) -> list:
    """Safely parse a Text column that holds JSON. Returns [] on any failure."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_secondary_ocr(raw: str | None) -> list[SecondaryOCROut]:
    """Monolith's get_visiting_card_secondary_ocr: parse JSON list, coerce to strings."""
    parsed = _parse_json_list(raw)
    out: list[SecondaryOCROut] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue

        def _join(value) -> str:
            if isinstance(value, list):
                return ", ".join(str(v) for v in value)
            return str(value) if value is not None else ""

        out.append(SecondaryOCROut(
            id=str(entry.get("id", "")),
            name=str(entry.get("name", "")),
            designation=str(entry.get("designation", "")),
            company=str(entry.get("company", "")),
            emails=_join(entry.get("emails")),
            phones=_join(entry.get("phones")),
            address=str(entry.get("address", "")),
            websites=_join(entry.get("websites")),
        ))
    return out


def _parse_address(raw: str | None) -> list[AddressOut] | str | None:
    """Monolith supported both a JSON list of dicts and a plain string."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw  # old format: plain string

    if not isinstance(parsed, list):
        return raw if isinstance(parsed, str) else None

    out: list[AddressOut] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        out.append(AddressOut(
            id=int(entry.get("id", 0)),
            address=entry.get("address", "") or "",
            state=entry.get("state", "") or "",
            country=entry.get("country", "") or "",
        ))
    return out if out else None


def _build_visiting_card_out(visitor: Visitor) -> VisitingCardOut:
    """Compose the nested visiting_card block from stored JSON."""
    primary_raw = visitor.visiting_card_primary or []
    primary_dict = primary_raw[0] if primary_raw and isinstance(primary_raw[0], dict) else {}
    primary = VisitingCardPrimary(
        front=primary_dict.get("front") or None,
        back=primary_dict.get("back") or None,
    )

    secondary_raw = visitor.visiting_card_secondary or []
    secondary = [
        VisitingCardSecondary(
            id=int(c.get("id", 0)) if isinstance(c, dict) else 0,
            front=(c.get("front") or None) if isinstance(c, dict) else None,
            back=(c.get("back") or None) if isinstance(c, dict) else None,
        )
        for c in secondary_raw
        if isinstance(c, dict)
    ]

    return VisitingCardOut(primary=primary, secondary=secondary)


async def _build_event_details(
        db: AsyncSession, visitor: Visitor,
) -> list[EventDetails]:
    """Fetch main event + any related events referenced by related_event_ids.
    Returns [] if the visitor has no event (shouldn't happen — event_id is required)."""
    if not visitor.event_id:
        return []

    main = await db.get(Event, visitor.event_id)
    main_info = (
        EventInfo(
            event_name=main.event_name,
            start_date=main.start_date.isoformat() if main.start_date else None,
            end_date=main.end_date.isoformat() if main.end_date else None,
            venue=main.venue,
        )
        if main
        else None
    )

    related_ids = [
        int(eid) for eid in (visitor.related_event_ids or [])
        if isinstance(eid, (int, str)) and str(eid).isdigit()
    ]

    related_events: list[EventInfo] = []
    if related_ids:
        stmt = select(Event).where(Event.id.in_(related_ids), Event.id != visitor.event_id)
        rows = (await db.scalars(stmt)).all()
        related_events = [
            EventInfo(
                event_name=e.event_name,
                start_date=e.start_date.isoformat() if e.start_date else None,
                end_date=e.end_date.isoformat() if e.end_date else None,
                venue=e.venue,
            )
            for e in rows
        ]

    message: str | None = None
    if visitor.is_duplicate:
        message = (
            "Duplicate visitor entries detected for this event; "
            "no additional timeline available."
        )
    elif related_events:
        message = (
            "Visitor has participated in other events. "
            "Additional timeline available."
        )

    return [EventDetails(
        event=main_info,
        related_event_map=related_events,
        message=message,
    )]


# =========================================================
# CREATE
# =========================================================

async def create_visitor(
        db: AsyncSession,
        user: CurrentUser,
        data: VisitorCreate,
        flow_def: FlowDefinition,
) -> tuple[Visitor, WorkflowRun | None]:
    """Insert visitor + optional WorkflowRun. Does NOT dispatch OCR yet (5.4)."""

    # --- 1. resolve event -------------------------------------
    event = await db.get(Event, data.event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {data.event_id} not found.",
        )

    # An admin/agent can only add visitors to their own events.
    if user.role != "SUPER_ADMIN" and event.admin_id != user.admin_id:
        # Return 404, not 403 — don't leak existence.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {data.event_id} not found.",
        )

    # --- 2. guard against duplicate txn_Id ---------------------
    existing = await db.get(Visitor, data.txn_Id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Visitor with txn_Id {data.txn_Id} already exists.",
        )

    # --- 3. build the row --------------------------------------
    primary_raw = data.visiting_card.primary
    secondary_raw = data.visiting_card.secondary

    visitor = Visitor(
        txn_Id=data.txn_Id,
        admin_id=user.admin_id,
        agent_id=_resolve_agent_id(user, data.agent_id),
        created_by_user_id=user.id,
        created_by_role=user.role,

        event_id=event.id,
        event_name=event.event_name,
        admin_company_name=user.company_name,

        name=data.name or "",
        company_name=data.company_name,
        phone=data.phone or "",
        visitor_email=data.visitor_email,
        image=data.image,

        interest=data.interest,
        date=data.date,
        meet_time=data.meet_time,
        created_at=data.created_at,

        visitor_address=data.visitor_address,
        visitor_designation=data.visitor_designation,
        visitor_websites=data.visitor_websites,
        visitor_category=data.visitor_category,

        products=data.products,
        notes=list(data.notes or []),
        voice_notes=list(data.voice_notes or []),

        visiting_card_primary=_build_primary_card(
            primary_raw.front, primary_raw.back,
        ),
        visiting_card_secondary=_build_secondary_cards(secondary_raw),

        ocr_status=False,
        is_duplicate=False,
        duplicate_of=None,
        related_event_ids=[],

        is_stopped=False,
    )

    db.add(visitor)
    await db.flush()

    # --- 4. create WorkflowRun if flow isn't ocr_only ----------
    workflow_run: WorkflowRun | None = None
    if flow_def.name != "ocr_only":
        config = {
            "send_whatsapp": bool(data.flow.send_whatsapp) if data.flow else False,
            "send_email": bool(data.flow.send_email) if data.flow else False,
            "email_template_id": data.flow.email_template_id if data.flow else None,
            "email_sender": data.flow.email_sender if data.flow else None,
        }
        workflow_run = WorkflowRun(
            run_id=str(uuid.uuid4()),
            txn_id=visitor.txn_Id,
            admin_id=user.admin_id,
            user_id=user.id,
            flow_name=flow_def.name,
            steps={"config": config},
            status=WorkflowStatus.PENDING,
            current_step=None,
        )
        db.add(workflow_run)
        await db.flush()

    # --- 5. OCR dispatch happens in 5.4 ------------------------
    primary = data.visiting_card.primary
    await ocr_service.enqueue_primary_ocr(
        db,
        visitor,
        front_url=primary.front,
        back_url=primary.back,
        admin_id=user.admin_id,
        user_id=user.id,
    )

    secondary_cards = [
        (c.front, c.back) for c in (data.visiting_card.secondary or [])
        if c.front or c.back
    ]
    if secondary_cards:
        await ocr_service.enqueue_secondary_ocr(
            db,
            visitor,
            cards=secondary_cards,
            admin_id=user.admin_id,
            user_id=user.id,
        )

    return visitor, workflow_run


# =========================================================
# READ — single visitor (monolith shape)
# =========================================================

async def get_visitor(
        db: AsyncSession, user: CurrentUser, txn_id: str,
) -> dict:
    """Fetch one visitor and return the shaped response dict."""
    stmt = select(Visitor).where(Visitor.txn_Id == txn_id)
    if user.role == "ADMIN":
        stmt = stmt.where(Visitor.admin_id == user.admin_id)
    elif user.role == "AGENT":
        stmt = stmt.where(Visitor.agent_id == user.id)

    visitor = await db.scalar(stmt)
    if not visitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visitor not found.",
        )
    return await _shape_visitor_out(db, visitor)


# =========================================================
# DELETE — soft
# =========================================================

async def delete_visitor(
        db: AsyncSession, user: CurrentUser, txn_id: str,
) -> None:
    if user.role not in ("ADMIN", "SUPER_ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete visitors.",
        )

    stmt = select(Visitor).where(
        Visitor.txn_Id == txn_id,
        Visitor.deleted_at.is_(None),
    )
    if user.role == "ADMIN":
        stmt = stmt.where(Visitor.admin_id == user.admin_id)

    visitor = await db.scalar(stmt)
    if not visitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visitor not found or already deleted.",
        )

    visitor.deleted_at = datetime.now(timezone.utc)
    visitor.sync_updated_at = datetime.now(timezone.utc)
    await db.flush()

    # --- release original's flag if this was the last duplicate ---------
    if visitor.duplicate_of:
        from app.services import duplicate_service
        await duplicate_service.release_original_if_alone(
            db, visitor.duplicate_of,
        )


# =========================================================
# LIST
# =========================================================

async def list_visitors(
        db: AsyncSession,
        user: CurrentUser,
        page: Page,
        *,
        event_id: int | None = None,
        agent_id: int | None = None,
        query: str | None = None,
        include_deleted: bool = False,
) -> tuple[list[Visitor], int]:
    """Hierarchy-filtered list. Returns (rows, total_count)."""

    base = select(Visitor)

    # --- hierarchy --------------------------------------------
    if user.role == "ADMIN":
        base = base.where(Visitor.admin_id == user.admin_id)
    elif user.role == "AGENT":
        base = base.where(Visitor.agent_id == user.id)
    # SUPER_ADMIN → all

    # --- soft-delete filter -----------------------------------
    if not include_deleted:
        base = base.where(Visitor.deleted_at.is_(None))

    # --- optional filters -------------------------------------
    if event_id is not None:
        base = base.where(Visitor.event_id == event_id)

    if agent_id is not None:
        # An agent can never see another agent's visitors.
        # An admin filtering by agent_id must still be scoped to their own admin_id.
        base = base.where(Visitor.agent_id == agent_id)

    # --- search -----------------------------------------------
    if query:
        pattern = f"%{query}%"
        base = base.where(
            or_(
                Visitor.name.ilike(pattern),
                Visitor.phone.ilike(pattern),
                Visitor.visitor_email.ilike(pattern),
                Visitor.company_name.ilike(pattern),
                Visitor.event_name.ilike(pattern),
            )
        )

    # --- count ------------------------------------------------
    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.scalar(count_stmt)) or 0

    # --- page -------------------------------------------------
    stmt = (
        base.order_by(Visitor.sync_at.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    rows = list((await db.scalars(stmt)).all())

    return rows, total


# =========================================================
# UPDATE
# =========================================================

async def update_visitor(
        db: AsyncSession,
        user: CurrentUser,
        txn_id: str,
        data: VisitorUpdate,
) -> Visitor:
    """Partial update. Recomputes duplicates if phone/email changed."""

    stmt = select(Visitor).where(
        Visitor.txn_Id == txn_id,
        Visitor.deleted_at.is_(None),
    )
    if user.role == "ADMIN":
        stmt = stmt.where(Visitor.admin_id == user.admin_id)
    elif user.role == "AGENT":
        stmt = stmt.where(Visitor.agent_id == user.id)

    visitor = await db.scalar(stmt)
    if not visitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visitor not found.",
        )

    payload = data.model_dump(exclude_unset=True)

    # Capture pre-change identity fields for duplicate recompute decision
    old_phone = visitor.phone
    old_email = visitor.visitor_email

    # --- apply changes ----------------------------------------
    for field, value in payload.items():
        if field == "is_stopped":
            visitor.is_stopped = bool(value)
            if value:
                visitor.is_stopped_at = datetime.now(timezone.utc)
            else:
                visitor.is_stopped_at = None
        else:
            setattr(visitor, field, value)

    visitor.sync_updated_at = datetime.now(timezone.utc)

    await db.flush()

    # --- recompute duplicates if identity changed -------------
    identity_changed = (
            visitor.phone != old_phone
            or visitor.visitor_email != old_email
    )
    if identity_changed:
        # Import here to avoid circular imports
        from app.services import duplicate_service
        await duplicate_service.compute_duplicate(db, visitor)
        await db.flush()

    return await _shape_visitor_out(db, visitor)


# =========================================================
# DUPLICATES — on-demand query
# =========================================================

async def get_duplicates(
        db: AsyncSession,
        user: CurrentUser,
        txn_id: str,
) -> DuplicateInfo:
    """Find other visitors that match by email OR phone within the same admin scope.

    Scope rules:
      - Same admin_id as the source visitor (never cross-tenant).
      - Same event_id → these are "duplicates".
      - Different event_id → these are "related" (returned via related_txn_ids).
      - Soft-deleted visitors are excluded.
      - The source visitor itself is excluded.
    """

    # --- load source visitor ----------------------------------
    source = await db.scalar(
        select(Visitor).where(Visitor.txn_Id == txn_id)
    )
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visitor not found.",
        )

    # --- hierarchy check --------------------------------------
    if user.role == "ADMIN" and source.admin_id != user.admin_id:
        raise HTTPException(status_code=404, detail="Visitor not found.")
    if user.role == "AGENT" and source.agent_id != user.id:
        raise HTTPException(status_code=404, detail="Visitor not found.")

    email = (source.visitor_email or "").strip().lower()
    phone = (source.phone or "").strip().replace(" ", "")

    if not email and not phone:
        return DuplicateInfo(
            is_duplicate=False,
            duplicate_of=source.duplicate_of,
            related_txn_ids=[],
        )

    # --- build identity predicate -----------------------------
    identity_clauses = []
    if email:
        identity_clauses.append(
            func.lower(Visitor.visitor_email).contains(email)
        )
    if phone:
        identity_clauses.append(
            func.replace(Visitor.phone, " ", "").contains(phone)
        )

    identity_predicate = or_(*identity_clauses) if identity_clauses else None

    if identity_predicate is None:
        return DuplicateInfo(
            is_duplicate=False,
            duplicate_of=source.duplicate_of,
            related_txn_ids=[],
        )

    # --- find candidates in the same admin scope --------------
    stmt = select(Visitor).where(
        Visitor.admin_id == source.admin_id,
        Visitor.txn_Id != source.txn_Id,
        Visitor.deleted_at.is_(None),
        identity_predicate,
    )
    candidates = list((await db.scalars(stmt)).all())

    # --- split into same-event vs other-event -----------------
    same_event_txns: list[str] = []
    other_event_txns: list[str] = []

    for c in candidates:
        if c.event_id == source.event_id:
            same_event_txns.append(c.txn_Id)
        else:
            other_event_txns.append(c.txn_Id)

    return DuplicateInfo(
        is_duplicate=len(same_event_txns) > 0 or source.is_duplicate,
        duplicate_of=source.duplicate_of,
        related_txn_ids=same_event_txns + other_event_txns,
    )


# =========================================================
# WORKFLOW RUN — latest for a visitor
# =========================================================

async def get_visitor_workflow(
        db: AsyncSession,
        user: CurrentUser,
        txn_id: str,
) -> WorkflowRun | None:
    """Latest workflow run for this visitor, if any.
    Returns None if no workflow was ever started for this visitor."""

    # --- hierarchy check via the visitor row ------------------
    visitor = await db.scalar(
        select(Visitor).where(Visitor.txn_Id == txn_id)
    )
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found.")

    if user.role == "ADMIN" and visitor.admin_id != user.admin_id:
        raise HTTPException(status_code=404, detail="Visitor not found.")
    if user.role == "AGENT" and visitor.agent_id != user.id:
        raise HTTPException(status_code=404, detail="Visitor not found.")

    # --- fetch run --------------------------------------------
    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.txn_id == txn_id)
        .order_by(WorkflowRun.created_at.desc())
        .limit(1)
    )
    return await db.scalar(stmt)
