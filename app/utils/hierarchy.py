from sqlalchemy import Select

from app.dependencies import CurrentUser
from app.models import Event, Visitor


def apply_event_hierarchy(stmt: Select, user: CurrentUser) -> Select:
    """Filter events by role.
       SUPER_ADMIN → all
       ADMIN       → events where admin_id == user.admin_id
       AGENT       → events where admin_id == user.admin_id
                    (agents see events their admin created; they cannot create events)
    """
    if user.role == "SUPER_ADMIN":
        return stmt
    return stmt.where(Event.admin_id == user.admin_id)


def apply_visitor_hierarchy(stmt: Select, user: CurrentUser) -> Select:
    """Filter visitors by role.
       SUPER_ADMIN → all
       ADMIN       → visitors where admin_id == user.admin_id
       AGENT       → visitors where agent_id == user.id
    """
    if user.role == "SUPER_ADMIN":
        return stmt
    if user.role == "ADMIN":
        return stmt.where(Visitor.admin_id == user.admin_id)
    if user.role == "AGENT":
        return stmt.where(Visitor.agent_id == user.id)
    # Unknown role → fail closed
    return stmt.where(False)