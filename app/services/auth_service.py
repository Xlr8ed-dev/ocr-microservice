"""Client for nexby-auth-service.

This service never decodes or trusts a token by itself. It forwards the
caller's bearer token (and X-Device-Fingerprint) to the auth service's
`GET /api/v1/users/me`, which verifies the signature, checks revocation and
enforces the device binding, then returns the profile plus workspace context.

That keeps token state in ONE place: rotating the signing key, revoking a
session or changing a role takes effect here on the next request with no
shared secret and no local token table.
"""

from typing import Any

import httpx

from app.clients.http import clients
from app.config import settings
from app.schemas.auth import AuthUserProfile


class AuthServiceError(Exception):
    """The auth service could not be reached or returned an unexpected error."""


class AuthServiceUnauthorized(AuthServiceError):
    """The token is missing, expired, revoked, or bound to another device."""


def _client() -> httpx.AsyncClient:
    if clients.auth is None:
        # Fail closed rather than trusting the caller when startup did not run.
        raise AuthServiceError("Auth client not initialised")
    return clients.auth


async def get_current_user(
    *,
    token: str,
    device_fingerprint: str,
) -> AuthUserProfile:
    """Resolve a request's bearer token to a user profile.

    The auth service owns every decision here: signature, expiry, token type,
    revocation and device binding. A 401/403 from it is a 401 here. A 5xx or a
    network failure is a 503, never an authentication bypass.
    """
    path = f"{settings.auth_service_root}/users/me"

    try:
        response = await _client().get(
            path,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Device-Fingerprint": device_fingerprint,
                "Accept": "application/json",
            },
        )
    except httpx.TimeoutException as exc:
        raise AuthServiceError("Auth service request timed out") from exc
    except httpx.RequestError as exc:
        raise AuthServiceError("Unable to connect to the auth service") from exc

    if response.status_code in (401, 403, 404):
        # Deliberately one message regardless of the real reason: telling a
        # caller whether the token expired, was revoked, or belongs to another
        # device is not useful to them and is useful to an attacker.
        raise AuthServiceUnauthorized("Invalid or expired token")

    if response.status_code >= 500:
        raise AuthServiceError(
            f"Auth service returned {response.status_code}"
        )

    if response.status_code != 200:
        raise AuthServiceError(
            f"Auth service returned {response.status_code}: "
            f"{response.text[:300]}"
        )

    try:
        payload: Any = response.json()
    except ValueError as exc:
        raise AuthServiceError("Invalid JSON from the auth service") from exc

    if not isinstance(payload, dict):
        raise AuthServiceError("Invalid response from the auth service")

    try:
        return AuthUserProfile.model_validate(payload)
    except Exception as exc:  # pydantic ValidationError, kept dependency-free
        raise AuthServiceError(
            "Auth service returned an unexpected user shape"
        ) from exc
