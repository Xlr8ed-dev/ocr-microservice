from pydantic import BaseModel


class CurrentUserOut(BaseModel):
    """Shape of the current user after JWT verification.
    The internal `dependencies.CurrentUser` dataclass mirrors this."""

    id: int
    role: str                       # SUPER_ADMIN | ADMIN | AGENT
    admin_id: int
    agent_id: int | None = None
    company_name: str | None = None