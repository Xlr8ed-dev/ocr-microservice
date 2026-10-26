import logging

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Visitor

logger = logging.getLogger(__name__)


# =========================================================
# INTERNAL HELPERS
# =========================================================

def _normalise_email(raw: str | None) -> str:
    """Lowercase, strip. Empty string if nothing."""
    return (raw or "").strip().lower()


def _normalise_phone(raw: str | None) -> str:
    """Remove spaces, strip. Empty string if nothing."""
    return (raw or "").replace(" ", "").strip()


def _identity_clause(email: str, phone: str):
    """SQL predicate matching other visitors by email OR phone substring.

    Uses LIKE '%value%' because phone/email fields can hold comma-separated
    lists (e.g. "a@x.com, b@x.com"). We accept the small false-positive
    risk for the simpler query; if it becomes a problem, swap to
    regexp_split_to_array.
    """
    clauses = []
    if email:
        clauses.append(func.lower(Visitor.visitor_email).contains(email))
    if phone:
        clauses.append(func.replace(Visitor.phone, " ", "").contains(phone))
    if not clauses:
        return None
    return or_(*clauses)


async def _find_matches(
        db: AsyncSession,
        visitor: Visitor,
        email: str,
        phone: str,
) -> list[Visitor]:
    """Return all other non-deleted visitors in the same admin scope
    that share email or phone with `visitor`."""
    clause = _identity_clause(email, phone)
    if clause is None:
        return []

    stmt = select(Visitor).where(
        Visitor.admin_id == visitor.admin_id,
        Visitor.txn_Id != visitor.txn_Id,
        Visitor.deleted_at.is_(None),
        clause,
    )
    return list((await db.scalars(stmt)).all())


async def release_original_if_alone(
        db: AsyncSession,
        original_txn_id: str,
) -> None:
    """If no other non-deleted visitor points at this original, clear its flag."""
    remaining = await db.scalar(
        select(func.count()).select_from(Visitor).where(
            Visitor.duplicate_of == original_txn_id,
            Visitor.deleted_at.is_(None),
        )
    )
    if remaining:
        return

    original = await db.scalar(
        select(Visitor).where(Visitor.txn_Id == original_txn_id)
    )
    if original and original.is_duplicate and original.duplicate_of is None:
        original.is_duplicate = False
        await db.flush()


# =========================================================
# MAIN ENTRY POINT
# =========================================================

async def compute_duplicate(
        db: AsyncSession,
        visitor: Visitor,
) -> None:
    """Compute and store duplicate flags for `visitor`.

    Side effects on `visitor`:
      - is_duplicate: True if any same-event match exists, else False
      - duplicate_of: txn_Id of the earliest same-event match, or None
      - related_event_ids: list of event ids of matches in OTHER events

    Side effect on the matched original:
      - is_duplicate = True (its duplicate_of stays None)

    Idempotent. Safe to run multiple times.
    """

    email = _normalise_email(visitor.visitor_email)
    phone = _normalise_phone(visitor.phone)

    # --- 1. if identity is empty, clear flags and release any old original ---
    if not email and not phone:
        await _clear_flags(db, visitor)
        return

    # --- 2. find candidates --------------------------------------------
    matches = await _find_matches(db, visitor, email, phone)

    # --- 3. split by event ---------------------------------------------
    same_event = [m for m in matches if m.event_id == visitor.event_id]
    other_events = [m for m in matches if m.event_id != visitor.event_id]

    # --- 4. if no matches at all, clear flags and release any old original ---
    if not same_event:
        await _clear_flags(db, visitor)
        # related_event_ids can still be populated for other events
        new_related = sorted({m.event_id for m in other_events})
        if visitor.related_event_ids != new_related:
            visitor.related_event_ids = new_related
            await db.flush()
        return

    # --- 5. we have same-event matches → this visitor is a duplicate ----
    # The "original" is the earliest by sync_at among same-event matches
    # PLUS the visitor itself considered as a candidate.
    candidates = same_event + [visitor]
    candidates.sort(key=lambda v: (v.sync_at, v.txn_Id))
    original = candidates[0]

    if original.txn_Id == visitor.txn_Id:
        # This visitor IS the original.
        visitor.duplicate_of = None
        visitor.is_duplicate = True  # still part of a duplicate set

        # Mark each same-event match as pointing to this original.
        for m in same_event:
            if not m.is_duplicate or m.duplicate_of is None:
                m.is_duplicate = True
                m.duplicate_of = visitor.txn_Id
                await db.flush()
    else:
        # This visitor is a duplicate of `original`.
        visitor.is_duplicate = True
        visitor.duplicate_of = original.txn_Id

        # Mark the original so the FE badges it too.
        if not original.is_duplicate:
            original.is_duplicate = True
            await db.flush()

    # --- 6. related_event_ids ------------------------------------------
    new_related = sorted({m.event_id for m in other_events})
    if visitor.related_event_ids != new_related:
        visitor.related_event_ids = new_related

    await db.flush()
    logger.info(
        "compute_duplicate txn=%s is_duplicate=%s duplicate_of=%s related=%s",
        visitor.txn_Id, visitor.is_duplicate, visitor.duplicate_of, new_related,
    )


# =========================================================
# CLEAR FLAGS (helper)
# =========================================================

async def _clear_flags(db: AsyncSession, visitor: Visitor) -> None:
    """If the visitor was a duplicate, clear its flag and release the original."""
    previous_original_txn = visitor.duplicate_of

    changed = False
    if visitor.is_duplicate:
        visitor.is_duplicate = False
        changed = True
    if visitor.duplicate_of is not None:
        visitor.duplicate_of = None
        changed = True
    if visitor.related_event_ids:
        visitor.related_event_ids = []
        changed = True

    if changed:
        await db.flush()

    if previous_original_txn:
        await release_original_if_alone(db, previous_original_txn)
