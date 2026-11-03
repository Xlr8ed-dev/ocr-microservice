import uuid

from pydantic import BaseModel


class CurrentUserOut(BaseModel):
    """Shape of the current user after token verification.
    The internal `dependencies.CurrentUser` dataclass mirrors this."""

    id: int
    role: str                       # SUPER_ADMIN | ADMIN | AGENT
    admin_id: int
    agent_id: int | None = None
    company_name: str | None = None
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    organization_slug: str | None = None


class AuthUserProfile(BaseModel):
    """Response of `GET /api/v1/users/me` on nexby-auth-service.

    Only the fields this service consumes are declared; extra fields the auth
    service may add later are ignored (Pydantic's default).
    """

    id: uuid.UUID
    email: str
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    is_email_verified: bool = False
    is_mobile_verified: bool = False

    organization_id: uuid.UUID | None = None
    organization_slug: str | None = None
    organization_name: str | None = None
    organization_account_type: str | None = None
    organization_type: str | None = None
    role: str | None = None
