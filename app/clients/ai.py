from typing import Any

import httpx

from app.clients.http import clients
from app.services.s3_service import normalize_download_url

# =========================================================
# RESPONSE SCHEMA (unchanged from your tested version)
# =========================================================

OCR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "designation": {"type": "string"},
        "company": {"type": "string"},
        "emails": {"type": "array", "items": {"type": "string"}},
        "phones": {"type": "array", "items": {"type": "string"}},
        "address": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "address": {"type": "string"},
                    "state": {"type": "string"},
                    "country": {"type": "string"},
                },
                "required": ["id", "address"],
            },
        },
        "websites": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "name", "designation", "company",
        "emails", "phones", "address", "websites",
    ],
}

VISION_MODEL = "gpt-4o-mini"


class AIServiceError(Exception):
    """Raised when the AI service request fails."""


# =========================================================
# PAYLOAD BUILDER (unchanged behaviour)
# =========================================================

def build_vision_payload(
        *,
        prompt: str,
        image_url: str,
        image_side: str | None = None,
) -> dict[str, Any]:
    full_prompt = prompt
    if image_side:
        full_prompt += f"\n[Image side: {image_side}]"

    return {
        "messages": [
            {
                "role": "system",
                "content": [{"type": "text", "text": full_prompt}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "url": image_url, "detail": "auto"},
                ],
            },
        ],
        "provider": "openai",
        "model": VISION_MODEL,
        "service": "OCR Engine",
        "use_rag": False,
        "temperature": 0,
        "max_tokens": 2000,
        "response_schema": OCR_RESPONSE_SCHEMA,
    }


# =========================================================
# VISION OCR
# =========================================================

async def vision_ocr(
        *,
        image_url: str,
        prompt: str,
        image_side: str | None = None,
) -> dict[str, Any]:
    """Call the AI service's vision endpoint and return the raw dict.

    Raises `AIServiceError` on any failure. The caller (services layer)
    is responsible for parsing the response into `OCRResult`.
    """
    if not image_url:
        raise AIServiceError("Image URL is empty")

    assert clients.ai is not None, "AI client not initialised"

    image_url = normalize_download_url(image_url)

    payload = build_vision_payload(
        prompt=prompt,
        image_url=image_url,
        image_side=image_side,
    )

    try:
        response = await clients.ai.post("api/v1/chat/vision", json=payload)
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise AIServiceError("AI service request timed out") from exc
    except httpx.HTTPStatusError as exc:
        raise AIServiceError(
            f"AI service returned {exc.response.status_code}: "
            f"{exc.response.text[:300]}"
        ) from exc
    except httpx.RequestError as exc:
        raise AIServiceError("Unable to connect to AI service") from exc

    try:
        result = response.json()
    except ValueError as exc:
        raise AIServiceError("AI service returned invalid JSON") from exc

    if not isinstance(result, dict):
        raise AIServiceError("Invalid response received from AI service")

    return result


# =========================================================
# STT — stub (contract TBD with AI service)
# =========================================================

async def transcribe_audio(
        *,
        audio_url: str,
        txn_id: str,
) -> dict[str, Any]:
    """Placeholder. Wire up once the AI service exposes an STT endpoint."""
    raise AIServiceError("STT not yet implemented in AI client")


# =========================================================
# SUMMARIZE — stub (contract TBD with AI service)
# =========================================================

async def summarize(
        *,
        text: str,
        context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Placeholder. Wire up once the AI service exposes a summarize endpoint."""
    raise AIServiceError("Summarize not yet implemented in AI client")


# =========================================================
# SUMMARIZE NOTES (text completion)
# =========================================================

SUMMARY_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "notes_summarize": {"type": "string"},
        "email_notes_summarize": {"type": "string"},
    },
    "required": ["notes_summarize", "email_notes_summarize"],
}

SUMMARY_SYSTEM_PROMPT = """You are a business meeting summarizer. You receive raw notes written by a
salesperson after meeting a visitor at an exhibition or event. The notes may
be in ANY language and may be unstructured, fragmented, or contain typos.

Your job is to produce TWO summaries, both in English:

1. notes_summarize:
   - A clear, professional 2-3 sentence summary of the meeting.
   - Objective tone.
   - No bullet points. No markdown. No headings.
   - Plain paragraph.

2. email_notes_summarize:
   - A one-paragraph summary suitable for inclusion in a follow-up email
     sent to the visitor.
   - First-person plural ("we discussed", "you mentioned", "we spoke about").
   - Warm but professional.
   - No bullet points, no markdown, no salutation, no sign-off — just the
     paragraph body.
   - Plain text only.

RULES:
- Never invent facts not present in the notes.
- If the notes mention a product, mention it.
- If the notes mention an interest level, describe it in words, not a number
  (e.g., "very interested" not "interest 4").
- Keep both summaries under 100 words.
- Output must be a single JSON object with exactly two keys:
  "notes_summarize" and "email_notes_summarize".
"""


def build_summary_user_prompt(
        *,
        notes: str,
        context: dict[str, Any],
) -> str:
    interest = context.get("interest")
    interest_line = (
        f"{interest} (0=lowest, 5=highest)" if interest is not None else "not specified"
    )

    return (
        "Meeting context:\n"
        f"- Visitor: {context.get('visitor_name') or '—'} "
        f"({context.get('visitor_designation') or '—'}) "
        f"from {context.get('visitor_company') or '—'}\n"
        f"- Exhibitor: {context.get('admin_company_name') or '—'}\n"
        f"- Event: {context.get('event_name') or '—'}\n"
        f"- Interest level: {interest_line}\n"
        "\n"
        "Raw notes:\n"
        f"{notes}\n"
    )


def build_summary_payload(*, notes: str, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "messages": [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": build_summary_user_prompt(notes=notes, context=context)},
        ],
        "provider": "openai",
        "model": "gpt-4o-mini",
        "service": "OCR Visitor Service",
        "use_rag": False,
        "temperature": 0.2,
        "max_tokens": 500,
        "response_schema": SUMMARY_RESPONSE_SCHEMA,
    }


async def summarize_notes(
        *,
        notes: str,
        context: dict[str, Any],
) -> dict[str, Any]:
    """Call the AI service's text completion endpoint to produce
    notes_summarize and email_notes_summarize.

    Returns:
        {
            "notes_summarize": "...",
            "email_notes_summarize": "...",
            "usage": {model, prompt_tokens, completion_tokens, total_tokens},
        }

    Raises AIServiceError on failure.
    """
    assert clients.ai is not None, "AI client not initialised"

    payload = build_summary_payload(notes=notes, context=context)

    try:
        response = await clients.ai.post("api/v1/chat/completion", json=payload)
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise AIServiceError("Summarize request timed out") from exc
    except httpx.HTTPStatusError as exc:
        raise AIServiceError(
            f"Summarize returned {exc.response.status_code}: "
            f"{exc.response.text[:300]}"
        ) from exc
    except httpx.RequestError as exc:
        raise AIServiceError("Unable to connect to AI service") from exc

    try:
        result = response.json()
    except ValueError as exc:
        raise AIServiceError("Summarize returned invalid JSON") from exc

    if not isinstance(result, dict):
        raise AIServiceError("Invalid response from AI service")

    data = result.get("data", result)
    if not isinstance(data, dict):
        raise AIServiceError("Invalid summarize response shape")

    return {
        "notes_summarize": data.get("notes_summarize") or "",
        "email_notes_summarize": data.get("email_notes_summarize") or "",
        "usage": result.get("usage") or {},
    }
