"""Contract tests for the AI service integration.

Regression cover for the 404 that broke document OCR: the service exposes
`/api/v1/chat/completions` (plural) and nests schema output under
`data.structured_output`. Every caller must use the plural path and read the
nested output, otherwise document structuring silently produces zero blocks.
"""

import asyncio

import httpx
import pytest

from app.clients.ai import AIServiceError, summarize_notes, unwrap_ai_response
from app.clients.http import clients
from app.config import settings
from app.services.document_chunk import Chunk
from app.services.document_structure import structure_chunk


def _envelope(structured: dict, *, usage: dict | None = None) -> dict:
    """The shape the AI service actually returns."""
    return {
        "success": True,
        "error": None,
        "data": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "content": "",
            "token_usage": usage
            or {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
            "structured_output": structured,
            "tool_calls": [],
            "rag_used": False,
            "rag_chunks": 0,
        },
    }


def _swap_client(handler):
    previous = clients.ai
    clients.ai = httpx.AsyncClient(
        base_url=settings.AI_SERVICE_URL,
        transport=httpx.MockTransport(handler),
    )
    return previous


def _close_client(previous):
    asyncio.run(clients.ai.aclose())
    clients.ai = previous


# ---------------------------------------------------------
# Envelope helper
# ---------------------------------------------------------

def test_unwrap_reads_nested_structured_output_and_token_usage():
    raw = _envelope({"blocks": [{"type": "paragraph", "text": "hi"}]})

    envelope, structured, usage = unwrap_ai_response(raw)

    assert envelope["model"] == "gpt-4o-mini"
    assert structured == {"blocks": [{"type": "paragraph", "text": "hi"}]}
    assert usage["prompt_tokens"] == 120


def test_unwrap_accepts_bare_envelope():
    raw = {
        "model": "gpt-4o-mini",
        "blocks": [{"type": "paragraph", "text": "hi"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2},
    }

    envelope, structured, usage = unwrap_ai_response(raw)

    assert structured is None
    assert envelope["blocks"][0]["text"] == "hi"
    assert usage == {"prompt_tokens": 1, "completion_tokens": 2}


def test_unwrap_raises_when_service_reports_failure():
    with pytest.raises(AIServiceError):
        unwrap_ai_response({"success": False, "data": None, "error": "boom"})


# ---------------------------------------------------------
# Document structuring
# ---------------------------------------------------------

def test_structure_chunk_calls_plural_endpoint_and_reads_structured_output():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json=_envelope(
                {
                    "title": "Sample",
                    "blocks": [
                        {"type": "heading", "level": 1, "text": "Invoice"},
                        {"type": "paragraph", "text": "Hello world."},
                    ],
                }
            ),
        )

    chunk = Chunk(
        chunk_index=0,
        chunk_total=1,
        text="Invoice\nHello world.",
        start_line=0,
        end_line=2,
        start_page=3,
        end_page=3,
    )

    previous = _swap_client(handler)
    try:
        result = asyncio.run(structure_chunk(chunk))
    finally:
        _close_client(previous)

    assert captured["url"].endswith("/api/v1/chat/completions")
    assert result.title == "Sample"
    assert [b["text"] for b in result.blocks] == ["Invoice", "Hello world."]
    # Page numbers are filled from the chunk when the model omits them.
    assert {b["page"] for b in result.blocks} == {3}
    assert result.usage["prompt_tokens"] == 120


def test_structure_chunk_reads_requested_from_structured_output():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope(
                {
                    "blocks": [{"type": "paragraph", "text": "x"}],
                    "requested": {"keys": {"invoice_number": "INV-42"}},
                }
            ),
        )

    chunk = Chunk(
        chunk_index=0,
        chunk_total=1,
        text="x",
        start_line=0,
        end_line=1,
        start_page=1,
        end_page=1,
    )

    previous = _swap_client(handler)
    try:
        result = asyncio.run(
            structure_chunk(chunk, requested_keys=["invoice_number"])
        )
    finally:
        _close_client(previous)

    assert result.requested["keys"]["invoice_number"] == "INV-42"


def test_structure_chunk_raises_on_http_404():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Not Found"})

    chunk = Chunk(
        chunk_index=0,
        chunk_total=1,
        text="x",
        start_line=0,
        end_line=1,
        start_page=1,
        end_page=1,
    )

    previous = _swap_client(handler)
    try:
        with pytest.raises(AIServiceError) as excinfo:
            asyncio.run(structure_chunk(chunk))
    finally:
        _close_client(previous)

    assert "404" in str(excinfo.value)


# ---------------------------------------------------------
# Every completion caller uses the plural path
# ---------------------------------------------------------

def test_extraction_post_ai_uses_plural_path():
    from app.tasks import extraction_tasks

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_envelope({}))

    previous = _swap_client(handler)
    try:
        asyncio.run(extraction_tasks._post_ai("api/v1/chat/completions", {}))
    finally:
        _close_client(previous)

    assert captured["url"].endswith("/api/v1/chat/completions")


def test_analysis_post_ai_uses_plural_path():
    from app.tasks import analysis_tasks

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_envelope({}))

    previous = _swap_client(handler)
    try:
        asyncio.run(analysis_tasks._post_ai({}))
    finally:
        _close_client(previous)

    assert captured["url"].endswith("/api/v1/chat/completions")


def test_summarize_notes_uses_plural_path_and_structured_output():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json=_envelope(
                {
                    "notes_summarize": "We discussed OCR.",
                    "email_notes_summarize": "Thanks for the chat.",
                }
            ),
        )

    previous = _swap_client(handler)
    try:
        result = asyncio.run(
            summarize_notes(notes="talked about OCR", context={"interest": 3})
        )
    finally:
        _close_client(previous)

    assert captured["url"].endswith("/api/v1/chat/completions")
    assert result["notes_summarize"] == "We discussed OCR."
    assert result["email_notes_summarize"] == "Thanks for the chat."
    assert result["usage"]["prompt_tokens"] == 120


# ---------------------------------------------------------
# Extraction result parsing reads structured fields
# ---------------------------------------------------------

def test_parse_extraction_result_on_structured_output():
    from app.services.extraction_prompts import parse_extraction_result

    structured = {
        "full_name": {"value": "Omkar", "confidence": 0.92},
        "company": {"value": "Nexby", "confidence": 0.71},
    }
    fields = [
        {"key": "full_name", "required": True},
        {"key": "company", "required": False},
    ]

    result = parse_extraction_result(structured, fields)

    assert result["full_name"] == {"value": "Omkar", "confidence": 0.92}
    assert result["company"]["confidence"] == 0.71
