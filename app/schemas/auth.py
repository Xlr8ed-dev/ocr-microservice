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
    # The auth-service user UUID. FE sends it back as the X-User-Id header on
    # every protected request (it appears in the /docs Authorize dialog).
    auth_user_id: str | None = None


class AuthUserProfile(BaseModel):
    """The flat identity OCR builds from the auth service's /me response.

    This is the shape every consumer inside OCR sees, regardless of how the
    auth service nests the data, so dependency code never touches envelopes.
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


# =========================================================
# /users/me ENVELOPE (nexby-auth-service)
# =========================================================

class AuthMeUser(BaseModel):
    id: uuid.UUID
    email: str
    is_email_verified: bool = False
    is_mobile_verified: bool = False


class AuthMeProfile(BaseModel):
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    profile_completion_percentage: int | None = None


class AuthMeOrganization(BaseModel):
    """The workspace the token is scoped to (or the caller's first one).

    `role` carries the caller's OrganizationRole there (owner/admin/member).
    Fields the auth service has not added yet simply stay None; unknown
    fields are ignored, so new server-side additions cannot break parsing.
    """

    id: uuid.UUID | None = None
    slug: str | None = None
    name: str | None = None
    account_type: str | None = None
    type_of_organization: str | None = None
    role: str | None = None


class AuthUserMeResponse(BaseModel):
    """The /users/me envelope: {"user": ..., "profile": ..., "organization": ...}.

    `organization` is null for a user-scoped token whose caller belongs to no
    workspace yet; every downstream mapping then falls back to the user as
    their own admin scope.
    """

    user: AuthMeUser
    profile: AuthMeProfile
    organization: AuthMeOrganization | None = None


def auth_me_to_profile(me: AuthUserMeResponse) -> AuthUserProfile:
    """Flatten the /me envelope into the shape OCR's dependency consumes."""
    org = me.organization
    return AuthUserProfile(
        id=me.user.id,
        email=me.user.email,
        first_name=me.profile.first_name,
        middle_name=me.profile.middle_name,
        last_name=me.profile.last_name,
        full_name=me.profile.full_name,
        is_email_verified=me.user.is_email_verified,
        is_mobile_verified=me.user.is_mobile_verified,
        organization_id=org.id if org else None,
        organization_slug=org.slug if org else None,
        organization_name=org.name if org else None,
        organization_account_type=org.account_type if org else None,
        organization_type=org.type_of_organization if org else None,
        role=org.role if org else None,
    )
