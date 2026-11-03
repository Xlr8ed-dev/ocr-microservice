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


def _with_mock_transport(handler):
    previous = clients.auth
    clients.auth = httpx.AsyncClient(
        base_url=settings.auth_service_base_url,
        transport=httpx.MockTransport(handler),
    )
    return previous


def test_client_returns_profile_for_valid_token(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["fingerprint"] = request.headers.get("X-Device-Fingerprint")
        return httpx.Response(200, json=_profile().model_dump(mode="json"))

    previous = _with_mock_transport(handler)
    try:
        profile = asyncio.run(
            get_current_user(token="abc", device_fingerprint="device-1")
        )
    finally:
        asyncio.run(clients.auth.aclose())
        clients.auth = previous

    assert profile.id == USER_ID
    assert captured["authorization"] == "Bearer abc"
    assert captured["fingerprint"] == "device-1"
    assert captured["url"].endswith("/api/v1/users/me")


def test_client_maps_401_to_unauthorized():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "nope"})

    previous = _with_mock_transport(handler)
    try:
        with pytest.raises(AuthServiceUnauthorized):
            asyncio.run(get_current_user(token="bad", device_fingerprint="d"))
    finally:
        asyncio.run(clients.auth.aclose())
        clients.auth = previous


def test_client_maps_5xx_to_service_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    previous = _with_mock_transport(handler)
    try:
        with pytest.raises(AuthServiceError):
            asyncio.run(get_current_user(token="abc", device_fingerprint="d"))
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
            "/auth/me", headers={"Authorization": "Bearer token"}
        )
    finally:
        clients.auth = previous

    assert response.status_code == 401
    assert "X-Device-Fingerprint" in response.json()["detail"]


def test_auth_me_returns_mapped_user(client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_profile(role="admin").model_dump(mode="json"))

    previous = _swap_auth_client(handler)
    try:
        response = client.get(
            "/auth/me",
            headers={
                "Authorization": "Bearer token",
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


def test_auth_me_propagates_auth_service_401(client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "revoked"})

    previous = _swap_auth_client(handler)
    try:
        response = client.get(
            "/auth/me",
            headers={
                "Authorization": "Bearer token",
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
                "X-Device-Fingerprint": "device-1",
            },
        )
    finally:
        clients.auth = previous

    assert response.status_code == 503
