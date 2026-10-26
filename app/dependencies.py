from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.utils.jwt import decode_jwt


@dataclass
class CurrentUser:
    id: int
    role: str  # SUPER_ADMIN | ADMIN | AGENT
    admin_id: int
    agent_id: int | None
    company_name: str | None


_bearer = HTTPBearer(auto_error=False)


# =========================================================
# AUTH MODE: "jwt" (real) | "mock" (dev only)
# =========================================================

async def _user_from_jwt(
        creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_jwt(creds.credentials)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return CurrentUser(
        id=int(claims["sub"]),
        role=claims["role"],
        admin_id=int(claims["admin_id"]),
        agent_id=claims.get("agent_id"),
        company_name=claims.get("company"),
    )


async def _user_from_headers(
        x_user_id: int = Header(..., alias="X-User-Id"),
        x_user_role: str = Header(..., alias="X-User-Role"),
        x_admin_id: int | None = Header(None, alias="X-Admin-Id"),
        x_agent_id: int | None = Header(None, alias="X-Agent-Id"),
        x_company_name: str | None = Header(None, alias="X-Company-Name"),
) -> CurrentUser:
    """DEV ONLY. Reads identity from plain HTTP headers.

    Used while SSO is not yet issuing tokens.
    Should NEVER be enabled when AUTH_MODE != 'mock'.
    """
    return CurrentUser(
        id=x_user_id,
        role=x_user_role,
        admin_id=x_admin_id if x_admin_id is not None else x_user_id,
        agent_id=x_agent_id,
        company_name=x_company_name,
    )


# =========================================================
# The dependency everything depends on
# =========================================================

def _pick_auth():
    if settings.AUTH_MODE == "mock":
        return _user_from_headers
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
