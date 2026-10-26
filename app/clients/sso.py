from typing import Any

import httpx

from app.clients.http import clients


class SSOServiceError(Exception):
    """Raised when the SSO service request fails."""


def _client() -> httpx.AsyncClient:
    assert clients.sso is not None, "SSO client not initialised"
    return clients.sso


async def _post(path: str, body: dict) -> dict[str, Any]:
    try:
        r = await _client().post(path, json=body)
        r.raise_for_status()
    except httpx.TimeoutException as exc:
        raise SSOServiceError("SSO request timed out") from exc
    except httpx.HTTPStatusError as exc:
        raise SSOServiceError(
            f"SSO returned {exc.response.status_code}: "
            f"{exc.response.text[:300]}"
        ) from exc
    except httpx.RequestError as exc:
        raise SSOServiceError("Unable to connect to SSO service") from exc

    data = r.json()
    if not isinstance(data, dict):
        raise SSOServiceError("Invalid response from SSO service")
    return data


# =========================================================
# USER LOOKUP — needed today for agent_name resolution
# =========================================================

async def get_user(user_id: int) -> dict[str, Any]:
    """Return {id, first_name, last_name, role, admin_id, company_name, is_active}.
    Shape TBD by SSO team — this is the assumed contract.
    """
    return await _post("/internal/users/get", {"user_id": user_id})


async def get_users_bulk(user_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Batch lookup for list endpoints.
    Returns {user_id: user_dict}.
    """
    if not user_ids:
        return {}
    data = await _post("/internal/users/bulk", {"user_ids": list(set(user_ids))})
    users = data.get("users", [])
    return {int(u["id"]): u for u in users}


# =========================================================
# USER + PACKAGE (one call, no quota consumption)
# =========================================================

async def get_user_and_package(user_id: int) -> dict[str, Any]:
    """One-shot fetch of user + active package.
    Shape: {user: {...}, package: {...} | null}
    """
    return await _post("/internal/users/package", {"user_id": user_id})


# =========================================================
# QUOTA — Phase 2+ (kept here so the shape is defined)
# =========================================================

async def check_quota(admin_id: int, kind: str = "ocr") -> dict[str, Any]:
    """Returns {allowed: bool, remaining: int, reason: str | None}."""
    return await _post(
        "/internal/packages/check-quota",
        {"admin_id": admin_id, "kind": kind},
    )


async def consume_quota(
    admin_id: int,
    *,
    idempotency_key: str,
    kind: str = "ocr",
) -> dict[str, Any]:
    """Idempotent on `idempotency_key`.
    Returns {ok: bool, remaining: int | None, reason: str | None}."""
    return await _post(
        "/internal/packages/consume-quota",
        {
            "admin_id": admin_id,
            "kind": kind,
            "idempotency_key": idempotency_key,
        },
    )