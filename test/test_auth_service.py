import asyncio
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.clients.http import clients
from app.config import settings
from app.dependencies import (
    CurrentUser,
    _current_user_from_profile,
    _uuid_to_int,
)
from app.schemas.auth import AuthUserProfile
from app.main import app
from app.services.auth_service import (
    AuthServiceError,
    AuthServiceUnauthorized,
    get_current_user,
)

USER_ID = uuid.UUID("018f0000-0000-7000-8000-000000000001")
ORG_ID = uuid.UUID("018f0000-0000-7000-8000-0000000000aa")


def _profile(**overrides) -> AuthUserProfile:
    data = {
        "id": USER_ID,
        "email": "person@example.com",
        "first_name": "Test",
        "last_name": "User",
        "organization_id": ORG_ID,
        "organization_slug": "acme",
        "organization_name": "Acme",
        "role": "owner",
    }
    data.update(overrides)
    return AuthUserProfile.model_validate(data)


def test_uuid_mapping_is_stable_and_fits_integer():
    first = _uuid_to_int(USER_ID)
    second = _uuid_to_int(str(USER_ID))

    assert first == second
    assert 0 < first <= 0x7FFFFFFF


def test_uuid_mapping_differs_for_different_uuids():
    assert _uuid_to_int(USER_ID) != _uuid_to_int(ORG_ID)


@pytest.mark.parametrize(
    ("org_role", "expected"),
    [("owner", "ADMIN"), ("admin", "ADMIN"), ("member", "AGENT")],
)
def test_org_roles_map_to_local_roles(org_role, expected):
    user = _current_user_from_profile(_profile(role=org_role))

    assert user.role == expected
    assert user.admin_id == _uuid_to_int(ORG_ID)
    assert user.agent_id == (_uuid_to_int(USER_ID) if expected == "AGENT" else None)


def test_unknown_role_fails_closed_to_agent():
    user = _current_user_from_profile(_profile(role="something-new"))

    assert user.role == "AGENT"


def test_no_organization_uses_user_as_admin_scope():
    user = _current_user_from_profile(
        _profile(organization_id=None, organization_slug=None, role=None)
    )

    assert user.admin_id == _uuid_to_int(USER_ID)
    assert user.role == "AGENT"


def test_super_admin_email_overrides_org_role(monkeypatch):
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", "owner@example.com")

    user = _current_user_from_profile(_profile(email="Owner@Example.com"))

    assert user.role == "SUPER_ADMIN"
    assert user.admin_id == _uuid_to_int(USER_ID)


def _me_payload(
    *,
    user_id: uuid.UUID = USER_ID,
    email: str = "person@example.com",
    first: str = "Test",
    last: str = "User",
    role: str = "owner",
    organization=...,
) -> dict:
    """The nexby-auth-service /users/me envelope, as a plain dict.

    `organization=...` (default sentinel) builds the acme workspace;
    pass None for a user-scoped token with no workspace.
    """
    if organization is ...:
        organization = {
            "id": str(ORG_ID),
            "slug": "acme",
            "name": "Acme",
            "role": role,
        }
    return {
        "user": {
            "id": str(user_id),
            "email": email,
            "is_email_verified": False,
            "is_mobile_verified": False,
        },
        "profile": {
            "first_name": first,
            "middle_name": "Test",
            "last_name": last,
            "full_name": f"{first} Test {last}",
            "profile_completion_percentage": 25,
        },
        "organization": organization,
    }


def _with_mock_transport(handler):
    previous = clients.auth
    clients.auth = httpx.AsyncClient(
        base_url=settings.auth_service_base_url,
        transport=httpx.MockTransport(handler),
    )
    return previous


def test_client_returns_profile_for_valid_token():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["authorization"] = request.headers.get("Authorization")
        captured["user_id"] = request.headers.get("X-User-Id")
        captured["fingerprint"] = request.headers.get("X-Device-Fingerprint")
        captured["body"] = request.read().decode()
        return httpx.Response(200, json=_me_payload())

    previous = _with_mock_transport(handler)
    try:
        profile = asyncio.run(
            get_current_user(
                token="abc",
                user_id=str(USER_ID),
                device_fingerprint="device-1",
            )
        )
    finally:
        asyncio.run(clients.auth.aclose())
        clients.auth = previous

    assert profile.id == USER_ID
    assert profile.first_name == "Test"
    assert profile.full_name == "Test Test User"
    assert profile.organization_slug == "acme"
    assert profile.role == "owner"
    assert captured["authorization"] == "Bearer abc"
    assert captured["user_id"] == str(USER_ID)
    assert captured["fingerprint"] == "device-1"
    assert captured["url"].endswith("/api/v1/users/me")
    assert captured["method"] == "GET"
    assert captured["body"] == ""


def test_client_parses_null_organization():
    """A user-scoped token with no workspace: org fields stay None."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_me_payload(organization=None))

    previous = _with_mock_transport(handler)
    try:
        profile = asyncio.run(
            get_current_user(
                token="abc",
                user_id=str(USER_ID),
                device_fingerprint="device-1",
            )
        )
    finally:
        asyncio.run(clients.auth.aclose())
        clients.auth = previous

    assert profile.id == USER_ID
    assert profile.organization_id is None
    assert profile.organization_slug is None
    assert profile.role is None


def test_client_accepts_flat_response_too():
    """Backwards compatibility: a flat profile shape still parses."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_profile().model_dump(mode="json"))

    previous = _with_mock_transport(handler)
    try:
        profile = asyncio.run(
            get_current_user(
                token="abc",
                user_id=str(USER_ID),
                device_fingerprint="device-1",
            )
        )
    finally:
        asyncio.run(clients.auth.aclose())
        clients.auth = previous

    assert profile.id == USER_ID
    assert profile.role == "owner"


def test_client_maps_401_to_unauthorized():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "nope"})

    previous = _with_mock_transport(handler)
    try:
        with pytest.raises(AuthServiceUnauthorized):
            asyncio.run(
                get_current_user(
                    token="bad", user_id=str(USER_ID), device_fingerprint="d"
                )
            )
    finally:
        asyncio.run(clients.auth.aclose())
        clients.auth = previous


def test_client_maps_5xx_to_service_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    previous = _with_mock_transport(handler)
    try:
        with pytest.raises(AuthServiceError):
            asyncio.run(
                get_current_user(
                    token="abc", user_id=str(USER_ID), device_fingerprint="d"
                )
            )
    finally:
        asyncio.run(clients.auth.aclose())
        clients.auth = previous


def test_current_user_dataclass_defaults_keep_legacy_calls_working():
    user = CurrentUser(id=1, role="ADMIN", admin_id=1, agent_id=None, company_name=None)

    assert user.email is None
    assert user.organization_slug is None


@pytest.fixture
def client():
    """TestClient over the real app, without lifespan startup.

    The auth client is swapped for a MockTransport so the dependency and the
    /auth/me route are exercised end to end, including header checks.
    """
    return TestClient(app)


def _swap_auth_client(handler):
    previous = clients.auth
    clients.auth = httpx.AsyncClient(
        base_url=settings.auth_service_base_url,
        transport=httpx.MockTransport(handler),
    )
    return previous


def test_auth_me_requires_bearer_token(client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("auth service must not be called without a token")

    previous = _swap_auth_client(handler)
    try:
        response = client.get(
            "/auth/me", headers={"X-Device-Fingerprint": "device-1"}
        )
    finally:
        clients.auth = previous

    assert response.status_code == 401


def test_auth_me_requires_device_fingerprint(client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("auth service must not be called without a fingerprint")

    previous = _swap_auth_client(handler)
    try:
        response = client.get(
            "/auth/me",
            headers={"Authorization": "Bearer token", "X-User-Id": str(USER_ID)},
        )
    finally:
        clients.auth = previous

    assert response.status_code == 401
    assert "X-Device-Fingerprint" in response.json()["detail"]


def test_auth_me_requires_user_id(client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("auth service must not be called without a user id")

    previous = _swap_auth_client(handler)
    try:
        response = client.get(
            "/auth/me",
            headers={"Authorization": "Bearer token", "X-Device-Fingerprint": "device-1"},
        )
    finally:
        clients.auth = previous

    assert response.status_code == 401
    assert "X-User-Id" in response.json()["detail"]


def test_auth_me_rejects_non_uuid_user_id(client):
    previous = _swap_auth_client(
        lambda request: httpx.Response(200, json=_profile().model_dump(mode="json"))
    )
    try:
        response = client.get(
            "/auth/me",
            headers={
                "Authorization": "Bearer token",
                "X-User-Id": "not-a-uuid",
                "X-Device-Fingerprint": "device-1",
            },
        )
    finally:
        clients.auth = previous

    assert response.status_code == 401


def test_auth_me_forwards_user_id_header(client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["user_id"] = request.headers.get("X-User-Id")
        return httpx.Response(200, json=_me_payload(role="admin"))

    previous = _swap_auth_client(handler)
    try:
        response = client.get(
            "/auth/me",
            headers={
                "Authorization": "Bearer token",
                "X-User-Id": str(USER_ID),
                "X-Device-Fingerprint": "device-1",
            },
        )
    finally:
        clients.auth = previous

    assert response.status_code == 200
    assert captured["method"] == "GET"
    assert captured["user_id"] == str(USER_ID)


def test_auth_me_rejects_profile_user_mismatch(client):
    """If the auth service ever answers with a DIFFERENT user than claimed,
    treat it as an authentication failure rather than resolving the identity."""
    other_user = uuid.UUID("018f0000-0000-7000-8000-0000000000ff")

    previous = _swap_auth_client(
        lambda request: httpx.Response(200, json=_me_payload(user_id=other_user))
    )
    try:
        response = client.get(
            "/auth/me",
            headers={
                "Authorization": "Bearer token",
                "X-User-Id": str(USER_ID),
                "X-Device-Fingerprint": "device-1",
            },
        )
    finally:
        clients.auth = previous

    assert response.status_code == 401


def test_auth_me_returns_mapped_user(client):
    previous = _swap_auth_client(
        lambda request: httpx.Response(200, json=_me_payload(role="admin"))
    )
    try:
        response = client.get(
            "/auth/me",
            headers={
                "Authorization": "Bearer token",
                "X-User-Id": str(USER_ID),
                "X-Device-Fingerprint": "device-1",
            },
        )
    finally:
        clients.auth = previous

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "ADMIN"
    assert body["email"] == "person@example.com"
    assert body["organization_slug"] == "acme"
    assert body["admin_id"] == _uuid_to_int(ORG_ID)
    assert body["auth_user_id"] == str(USER_ID)


def test_auth_me_propagates_auth_service_401(client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "revoked"})

    previous = _swap_auth_client(handler)
    try:
        response = client.get(
            "/auth/me",
            headers={
                "Authorization": "Bearer token",
                "X-User-Id": str(USER_ID),
                "X-Device-Fingerprint": "device-1",
            },
        )
    finally:
        clients.auth = previous

    assert response.status_code == 401


def test_auth_me_fails_closed_when_auth_service_is_down(client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    previous = _swap_auth_client(handler)
    try:
        response = client.get(
            "/auth/me",
            headers={
                "Authorization": "Bearer token",
                "X-User-Id": str(USER_ID),
                "X-Device-Fingerprint": "device-1",
            },
        )
    finally:
        clients.auth = previous

    assert response.status_code == 503


def test_openapi_authorize_dialog_includes_user_id_and_fingerprint():
    """The /docs Authorize dialog must collect all three credentials."""
    schema = app.openapi()

    schemes = schema["components"]["securitySchemes"]
    assert schemes["XUserId"]["in"] == "header"
    assert schemes["XUserId"]["name"] == "X-User-Id"
    assert schemes["XDeviceFingerprint"]["name"] == "X-Device-Fingerprint"

    operation = schema["paths"]["/auth/me"]["get"]
    requirement = operation["security"][0]
    assert set(requirement) == {"HTTPBearer", "XUserId", "XDeviceFingerprint"}

    # The header inputs are provided through the Authorize dialog, so the
    # per-endpoint parameter list must not duplicate them.
    header_names = {
        parameter["name"]
        for parameter in operation.get("parameters", [])
        if parameter.get("in") == "header"
    }
    assert "X-User-Id" not in header_names
    assert "X-Device-Fingerprint" not in header_names


def test_openapi_public_routes_are_not_protected_in_schema():
    schema = app.openapi()

    for path in ("/healthz", "/readyz", "/documents/types", "/images/types"):
        for method, operation in schema["paths"][path].items():
            assert not operation.get("security"), f"{method.upper()} {path}"
