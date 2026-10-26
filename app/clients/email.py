import uuid
from typing import Any

import httpx

from app.clients.http import clients


class EmailServiceError(Exception):
    """Raised when the Email service request fails."""


class EmailServiceSkipped(Exception):
    """Raised when a call is deliberately skipped (no email, no campaign).
    Callers should mark the workflow step `skipped`, not `failed`."""


def _client() -> httpx.AsyncClient:
    if clients.email is None:
        raise EmailServiceError("Email service URL not configured")
    return clients.email


def _first_email(raw: str | None) -> str:
    """visitor.visitor_email can hold comma-separated emails. Take the first."""
    if not raw:
        return ""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts[0] if parts else ""


def _first_phone(raw: str | None) -> str | None:
    """visitor.phone can hold comma-separated numbers. Take the first, or None."""
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts[0] if parts else None


async def trigger_campaign(
    *,
    campaign_id: str,
    source_event_id: int,
    workflow_run_id: str,
    visitor: Any,
    admin_id: int,
    agent_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Call Email Service's POST /api/v1/campaigns/{campaign_id}/run.

    Returns:
        {"run_id": "...", "status": "active", "started_at": "..."}

    Raises:
        EmailServiceSkipped — visitor has no email, or campaign not found
        EmailServiceError   — any other HTTP / network failure
    """
    visitor_email = _first_email(visitor.visitor_email)
    if not visitor_email:
        raise EmailServiceSkipped("Visitor has no email address")

    if not campaign_id:
        raise EmailServiceSkipped("No campaign configured for this event")

    idempotency_key = (
        f"ocr:{workflow_run_id}:{visitor.txn_Id}:{campaign_id}"
    )

    payload: dict[str, Any] = {
        "source_ref": {
            "type": "event",
            "id": str(source_event_id),
        },
        "visitor": {
            "name": visitor.name or "",
            "number": _first_phone(visitor.phone),
            "email": visitor_email,
            "ai_summary": visitor.notes_summarize or "",
            "email_summary": visitor.email_notes_summarize or "",
        },
        "recipients": {
            "admin_id": admin_id,
            "agent_ids": list(agent_ids or []),
        },
        "idempotency_key": idempotency_key,
    }

    headers = {
        "X-Request-Id": str(uuid.uuid4()),
        "X-Service-Id": "ocr-service",
    }

    url = f"/api/v1/campaigns/{campaign_id}/run"

    try:
        r = await _client().post(url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise EmailServiceError("Email service timed out") from exc
    except httpx.RequestError as exc:
        raise EmailServiceError("Unable to connect to Email service") from exc

    # Strict REST: 2xx success, 4xx/5xx failure.
    if r.status_code >= 400:
        try:
            body = r.json()
            err = body.get("message") or body.get("errors") or r.text[:300]
        except ValueError:
            err = r.text[:300]

        # Campaign doesn't exist → skip the step, don't fail the workflow.
        if r.status_code == 404:
            raise EmailServiceSkipped(f"Campaign not found: {campaign_id}")

        raise EmailServiceError(
            f"Email service returned {r.status_code}: {err}"
        )

    try:
        body = r.json()
    except ValueError as exc:
        raise EmailServiceError("Email service returned invalid JSON") from exc

    if not isinstance(body, dict) or body.get("status") != "success":
        raise EmailServiceError(
            f"Unexpected Email service response: {str(body)[:300]}"
        )

    data = body.get("data") or {}
    return {
        "run_id": data.get("run_id", ""),
        "status": data.get("status", ""),
        "started_at": data.get("started_at", ""),
    }