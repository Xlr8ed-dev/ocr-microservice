"""Send a chunk to the AI service and parse the response into blocks.

This is the bridge between document_chunk.py and the AI service. It does
not touch the DB. It is called once per chunk by the document worker.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.clients.ai import AIServiceError
from app.clients.http import clients
from app.services.document_chunk import Chunk
from app.services.document_prompts import build_ai_payload


logger = logging.getLogger(__name__)


# =========================================================
# OUTPUT SHAPE
# =========================================================

@dataclass
class ChunkResult:
    chunk_index: int
    blocks: list[dict] = field(default_factory=list)
    title: str | None = None
    usage: dict = field(default_factory=dict)
    raw_response: dict = field(default_factory=dict)


# =========================================================
# PUBLIC ENTRY POINT
# =========================================================

async def structure_chunk(
    chunk: Chunk,
    *,
    previous_last_block: str | None = None,
) -> ChunkResult:
    """Send one chunk to the AI service and return its structured blocks.

    Raises AIServiceError on failure.
    """
    payload = build_ai_payload(
        chunk_index=chunk.chunk_index,
        chunk_total=chunk.chunk_total,
        start_page=chunk.start_page,
        end_page=chunk.end_page,
        heading_context=chunk.heading_context,
        previous_last_block=previous_last_block,
        chunk_text=chunk.text,
    )

    assert clients.ai is not None, "AI client not initialised"

    try:
        response = await clients.ai.post(
            "api/v1/chat/completion",
            json=payload,
        )
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise AIServiceError(
            f"Chunk {chunk.chunk_index} timed out"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise AIServiceError(
            f"AI returned {exc.response.status_code}: "
            f"{exc.response.text[:300]}"
        ) from exc
    except httpx.RequestError as exc:
        raise AIServiceError(
            "Unable to connect to AI service"
        ) from exc

    try:
        raw = response.json()
    except ValueError as exc:
        raise AIServiceError("AI returned invalid JSON") from exc

    if not isinstance(raw, dict):
        raise AIServiceError("AI response is not an object")

    data = raw.get("data", raw)
    if not isinstance(data, dict):
        raise AIServiceError("AI data field is not an object")

    blocks = data.get("blocks", [])
    if not isinstance(blocks, list):
        raise AIServiceError("AI blocks field is not a list")

    title = data.get("title") if isinstance(data.get("title"), str) else None

    # Attach page numbers from the chunk's page range if the model
    # omitted them. The AI doesn't always know exact pages; we help it.
    blocks = _fill_missing_pages(blocks, chunk.start_page)

    return ChunkResult(
        chunk_index=chunk.chunk_index,
        blocks=blocks,
        title=title,
        usage=raw.get("usage") or {},
        raw_response=raw,
    )


def _fill_missing_pages(blocks: list[dict], fallback_page: int) -> list[dict]:
    """Ensure every block has a `page` field. Uses the chunk's start page
    as a default when the model omits it."""
    out = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        if "page" not in b or b["page"] is None:
            b["page"] = fallback_page
        out.append(b)
    return out


def extract_last_block_text(blocks: list[dict]) -> str | None:
    """Return the text of the last textual block, for the next chunk's context."""
    for b in reversed(blocks):
        if not isinstance(b, dict):
            continue
        text = b.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        items = b.get("items")
        if isinstance(items, list) and items:
            return str(items[-1])[:200]
    return None