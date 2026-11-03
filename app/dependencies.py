from dataclasses import dataclass
import hashlib
import uuid

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.services.auth_service import (
    AuthServiceError,
    AuthServiceUnauthorized,
    get_current_user as fetch_auth_user,
)
from app.utils.jwt import decode_jwt


@dataclass
class CurrentUser:
    id: int
    role: str  # SUPER_ADMIN | ADMIN | AGENT
    admin_id: int
    agent_id: int | None
    company_name: str | None
    # Useful for display/debugging; never used for authorisation.
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    organization_slug: str | None = None


_bearer = HTTPBearer(auto_error=False)

DEVICE_FINGERPRINT_HEADER = "X-Device-Fingerprint"

# Organization roles from nexby-auth-service mapped onto this service's three
# levels. owner and admin are both workspace administrators here; member is the
# least-privileged AGENT. Anything unrecognised fails closed to AGENT.
_ROLE_MAP = {
    "owner": "ADMIN",
    "admin": "ADMIN",
    "member": "AGENT",
}


# =========================================================
# AUTH MODE: "auth_service" (recommended) | "jwt" (legacy) | "mock"
# =========================================================

def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _uuid_to_int(value: uuid.UUID | str) -> int:
    """Map an auth-service UUID to a stable positive 31-bit integer.

    The OCR tables use INTEGER owner columns, while the auth service issues
    UUIDs. A salted hash of the full UUID is taken and truncated to 31 bits so
    the result fits a signed Postgres INTEGER and never changes for the same
    identity. The salt must be identical on every instance.

    Collision note: this is a compatibility bridge, not an identity system.
    At ~10,000 organizations the birthday bound gives a small but non-zero
    chance of two organizations sharing an admin_id. If this service is to
    outgrow that scale, replace this with a persistent UUID -> integer mapping
    table (or widen the columns to UUID/BIGINT).
    """
    if isinstance(value, uuid.UUID):
        raw = value.hex
    else:
        try:
            raw = uuid.UUID(str(value)).hex
        except (ValueError, AttributeError):
            raw = str(value)
    digest = hashlib.sha256(
        f"{settings.AUTH_ID_HASH_SALT}:{raw}".encode()
    ).digest()
    # First 31 bits; 0 is not a useful owner id, so shift it to 1.
    mapped = int.from_bytes(digest[:4], "big") & 0x7FFFFFFF
    return mapped or 1


def _current_user_from_profile(profile) -> CurrentUser:
    """Build this service's CurrentUser from an auth-service profile."""
    user_int = _uuid_to_int(profile.id)
    org_int = (
        _uuid_to_int(profile.organization_id)
        if profile.organization_id is not None
        else user_int
    )

    email = (profile.email or "").lower()
    if email and email in settings.super_admin_emails:
        role = "SUPER_ADMIN"
        admin_id = user_int
    else:
        role = _ROLE_MAP.get((profile.role or "").lower(), "AGENT")
        admin_id = org_int

    return CurrentUser(
        id=user_int,
        role=role,
        admin_id=admin_id,
        agent_id=user_int if role == "AGENT" else None,
        company_name=profile.organization_name,
        email=profile.email,
        first_name=profile.first_name,
        last_name=profile.last_name,
        full_name=profile.full_name,
        organization_slug=profile.organization_slug,
    )


async def _user_from_auth_service(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    x_device_fingerprint: str | None = Header(
        None, alias=DEVICE_FINGERPRINT_HEADER
    ),
) -> CurrentUser:
    """Validate the request via nexby-auth-service.

    Declaring the bearer credential through HTTPBearer (rather than reading the
    raw header) puts the Authorize button and a padlock on every protected
    route in Swagger/OpenAPI. Declaring the fingerprint as a Header does the
    same for that input, so both can be exercised from /docs without special
    tooling.
    """
    if creds is None or not creds.credentials.strip():
        raise _unauthorized("Missing or malformed Authorization header")

    if not x_device_fingerprint or not x_device_fingerprint.strip():
        raise _unauthorized(f"{DEVICE_FINGERPRINT_HEADER} header is required")

    token = creds.credentials.strip()
    fingerprint = x_device_fingerprint.strip()

    try:
        profile = await fetch_auth_user(token=token, device_fingerprint=fingerprint)
    except AuthServiceUnauthorized as exc:
        raise _unauthorized(str(exc)) from exc
    except AuthServiceError as exc:
        # Never fall back to headers or an unauthenticated user when the auth
        # service is down: failing closed is the only safe answer.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        ) from exc

    user = _current_user_from_profile(profile)

    # Same convenience the auth service exposes for its rate limiter; nothing
    # in this service authorises off request.state.
    request.state.user_id = user.id
    request.state.auth_user_id = str(profile.id)
    return user


async def _user_from_jwt(
        creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    """Legacy path: decode an SSO-issued token directly. Kept for deployments
    that still use the old SSO issuer. New deployments use AUTH_MODE=auth_service.
    """
    if creds is None:
        raise _unauthorized("Missing bearer token")
    try:
        claims = decode_jwt(creds.credentials)
    except Exception as exc:
        raise _unauthorized(f"Invalid token: {exc}") from exc

    return CurrentUser(
        id=int(claims["sub"]),
        role=claims["role"],
        admin_id=int(claims["admin_id"]),
        agent_id=claims.get("agent_id"),
        company_name=claims.get("company"),
        email=claims.get("email"),
        first_name=claims.get("first_name"),
        last_name=claims.get("last_name"),
        full_name=claims.get("name"),
        organization_slug=claims.get("org"),
    )


async def _user_from_headers(
        x_user_id: int = Header(..., alias="X-User-Id"),
        x_user_role: str = Header(..., alias="X-User-Role"),
        x_admin_id: int | None = Header(None, alias="X-Admin-Id"),
        x_agent_id: int | None = Header(None, alias="X-Agent-Id"),
        x_company_name: str | None = Header(None, alias="X-Company-Name"),
        x_user_email: str | None = Header(None, alias="X-User-Email"),
        x_user_name: str | None = Header(None, alias="X-User-Name"),
        x_org_slug: str | None = Header(None, alias="X-Organization"),
) -> CurrentUser:
    """DEV ONLY. Reads identity from plain HTTP headers.

    Used while the auth service is not wired into an environment.
    Should NEVER be enabled when AUTH_MODE != 'mock'.
    """
    return CurrentUser(
        id=x_user_id,
        role=x_user_role,
        admin_id=x_admin_id if x_admin_id is not None else x_user_id,
        agent_id=x_agent_id,
        company_name=x_company_name,
        email=x_user_email,
        full_name=x_user_name,
        organization_slug=x_org_slug,
    )


# =========================================================
# The dependency everything depends on
# =========================================================

def _pick_auth():
    if settings.AUTH_MODE == "mock":
        return _user_from_headers
    if settings.AUTH_MODE == "auth_service":
        return _user_from_auth_service
    return _user_from_jwt


current_user = _pick_auth()


# =========================================================
# Service-to-service token (unchanged)
# =========================================================

async def require_service_token(
        x_service_token: str = Header(..., alias="X-Service-Token"),
) -> None:
    if x_service_token != settings.SERVICE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service token",
        )
