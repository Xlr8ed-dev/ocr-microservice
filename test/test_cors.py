"""CORS configuration tests.

The FE is served from a different origin than the API, so a missing or wrong
Access-Control-Allow-Origin header breaks every browser call even though the
same request works in curl/Postman. These tests cover both halves of the
feature: parsing the .env value into clean origins, and the middleware that
answers preflight requests.
"""

from fastapi.testclient import TestClient

from app.config import parse_allowed_origins, settings
from app.main import app


# ---------------------------------------------------------
# Parsing CORS_ALLOWED_ORIGINS
# ---------------------------------------------------------

def test_parses_json_array():
    raw = '["https://qa-apis.nexby.ai","http://localhost:3000"]'
    assert parse_allowed_origins(raw) == [
        "https://qa-apis.nexby.ai",
        "http://localhost:3000",
    ]


def test_parses_comma_separated_list():
    raw = "https://qa-apis.nexby.ai,http://localhost:3000"
    assert parse_allowed_origins(raw) == [
        "https://qa-apis.nexby.ai",
        "http://localhost:3000",
    ]


def test_strips_quotes_whitespace_and_trailing_slashes():
    raw = '[" https://qa-apis.nexby.ai/ ", \'http://localhost:3000/\']'
    assert parse_allowed_origins(raw) == [
        "https://qa-apis.nexby.ai",
        "http://localhost:3000",
    ]


def test_deduplicates_while_preserving_order():
    raw = "https://a.example,https://a.example,https://b.example"
    assert parse_allowed_origins(raw) == [
        "https://a.example",
        "https://b.example",
    ]


def test_empty_value_disables_cors():
    assert parse_allowed_origins("") == []
    assert parse_allowed_origins(None) == []
    assert parse_allowed_origins("   ") == []


def test_malformed_json_falls_back_to_comma_split():
    raw = '["https://a.example", https://b.example]'
    assert parse_allowed_origins(raw) == [
        "https://a.example",
        "https://b.example",
    ]


def test_wildcard_is_kept_as_is():
    assert parse_allowed_origins("*") == ["*"]
    assert parse_allowed_origins('["*"]') == ["*"]


def test_settings_reads_env_value():
    # .env ships with the QA and local FE origins; if it is customised in a
    # deployment this only asserts the property mirrors the raw setting.
    assert settings.cors_allowed_origins == parse_allowed_origins(
        settings.CORS_ALLOWED_ORIGINS
    )


# ---------------------------------------------------------
# Middleware behaviour
# ---------------------------------------------------------

def test_preflight_allows_configured_origin_and_credentials():
    origins = settings.cors_allowed_origins
    assert origins, "CORS_ALLOWED_ORIGINS must be set for the middleware to run"
    origin = origins[0]

    client = TestClient(app)
    response = client.options(
        "/documents",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": (
                "authorization,x-user-id,x-device-fingerprint,content-type"
            ),
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"

    allowed_headers = response.headers["access-control-allow-headers"].lower()
    for header in (
        "authorization",
        "x-user-id",
        "x-device-fingerprint",
        "content-type",
    ):
        assert header in allowed_headers

    assert "content-disposition" not in response.headers.get(
        "access-control-expose-headers", ""
    ).lower()  # expose headers are sent on the actual response, not preflight


def test_unconfigured_origin_is_rejected():
    origins = settings.cors_allowed_origins
    assert origins
    origin = origins[0]
    not_allowed = (
        "https://evil.example"
        if origin != "https://evil.example"
        else "https://other.example"
    )

    client = TestClient(app)
    response = client.options(
        "/documents",
        headers={
            "Origin": not_allowed,
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_actual_request_gets_allow_origin_header():
    origins = settings.cors_allowed_origins
    assert origins
    origin = origins[0]

    client = TestClient(app)
    response = client.get("/healthz", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    # Export endpoints return file downloads; the FE needs to read these.
    exposed = response.headers["access-control-expose-headers"].lower()
    assert "content-disposition" in exposed
    assert "content-length" in exposed
