from typing import Any

import httpx

from app.clients.http import clients


class WhatsAppServiceError(Exception):
    """Raised when the WhatsApp service request fails."""


def _client() -> httpx.AsyncClient:
    if clients.whatsapp is None:
        raise WhatsAppServiceError("WhatsApp service URL not configured")
    return clients.whatsapp


async def send_whatsapp(
    *,
    txn_id: str,
    phone: str,
    template: str | None = None,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send WhatsApp message. Contract TBD with WhatsApp team.
    Expected return: {message_id: str, status: str}"""
    raise WhatsAppServiceError("WhatsApp service not integrated yet")