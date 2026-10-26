import os
import json
from typing import Any

import httpx

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://192.168.1.34:8000/")
AI_SERVICE_TIMEOUT = float(os.getenv("AI_SERVICE_TIMEOUT", "120"))
AI_SERVICE_API_KEY = os.getenv("AI_SERVICE_API_KEY", "c65a00b89feb8b8e04d0226271994703ebb16b05")

OCR_RESPONSE_SCHEMA = {
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
    "required": ["name", "designation", "company", "emails", "phones", "address", "websites"],
}


class AIServiceError(Exception):
    """Raised when the AI service request fails."""


def build_vision_payload(
        prompt: str,
        image_url: str,
        image_side: str | None = None,
) -> dict:
    full_prompt = prompt

    if image_side:
        full_prompt += f"\n[Image side: {image_side}]"

    return {
        "messages": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": full_prompt,
                    }
                ]
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "url": image_url,
                        "detail": "auto",
                    }
                ],
            },
        ],
        "provider": "openai",
        "model": "gpt-4o-mini",
        "service": "OCR Engine Test",
        "use_rag": False,
        "temperature": 0,
        "max_tokens": 2000,
        "response_schema": OCR_RESPONSE_SCHEMA,
    }


async def process_image(
        image_url: str,
        prompt: str,
        txn_id: str,
        user_details: dict[str, Any],
        package_details: dict[str, Any],
        image_side: str | None = None,
) -> dict[str, Any]:
    if not image_url:
        raise AIServiceError("Image URL is empty")

    payload = build_vision_payload(prompt, image_url, image_side)
    url = f"{AI_SERVICE_URL}api/v1/chat/vision"
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": AI_SERVICE_API_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=AI_SERVICE_TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=headers)

        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise AIServiceError("Invalid response received from AI service")
        return result

    except httpx.TimeoutException as exc:
        raise AIServiceError("AI service request timed out") from exc
    except httpx.HTTPStatusError as exc:
        raise AIServiceError(f"AI service returned status {exc.response.status_code}: {exc.response.text}") from exc
    except httpx.RequestError as exc:
        raise AIServiceError("Unable to connect to AI service") from exc
    except ValueError as exc:
        raise AIServiceError("AI service returned invalid JSON") from exc
