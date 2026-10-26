"""Prompts and response schema for the AI structuring step.

The AI receives chunks of extracted document text and returns structured
blocks. The system prompt is fixed; the user prompt is per-chunk and
includes light context so the model knows where it is in the document.
"""

# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """You are a document structure extractor. You receive raw text from a page or chunk of a document (tender, contract, SRS, spec, or similar). Your job is to return structured blocks that preserve the document's hierarchy.

Do NOT summarize. Do NOT paraphrase. Preserve the text as-is.
Do NOT translate. If the document is in Hindi, keep it in Hindi.

Detect headings by content and context:
  - Numbered sections: "1. Introduction", "1.1 Scope", "1.1.1 Details"
  - Keyword-led sections: "Chapter X", "Section X", "Article X", "Annexure A", "Appendix B"
  - ALL-CAPS lines that read like titles
  - Bold or larger text (when indicated by the input)

Heading level is inferred from nesting depth:
  - "1. Introduction"      -> level 1
  - "1.1 Scope"            -> level 2
  - "1.1.1 Details"        -> level 3
  - "Chapter X"            -> level 1
  - "Annexure A"           -> level 1

Tables must be preserved as structured columns + rows, not as text.
Lists (bulleted or numbered) become list blocks with items[].
Between pages, insert a page_break block.
Never invent text. If something is unclear, preserve it as-is.

Output must match the provided response_schema exactly:
- blocks: array of block objects
- title: optional document title (only include if you are confident)

Each block has a "type" field:
  - "heading": needs level (1-6), text, optional page
  - "paragraph": needs text, optional page
  - "list": needs ordered (bool), items (string array), optional page
  - "table": needs columns (string array), rows (array of string arrays),
             optional caption, optional page
  - "page_break": needs page
  - "image": needs page, optional description

Only use "page_break" if the input explicitly marks a page boundary.
"""


# =========================================================
# USER PROMPT BUILDER
# =========================================================

def build_user_prompt(
    *,
    chunk_index: int,
    chunk_total: int,
    start_page: int,
    end_page: int,
    heading_context: str | None,
    previous_last_block: str | None,
    chunk_text: str,
) -> str:
    """Build the per-chunk user prompt.

    `previous_last_block` is the tail of the previous chunk's output, so
    the model can continue cleanly across chunk boundaries.
    """
    parts: list[str] = []

    parts.append(f"Chunk {chunk_index + 1} of {chunk_total}.")
    if start_page == end_page:
        parts.append(f"Pages: {start_page}.")
    else:
        parts.append(f"Pages: {start_page}-{end_page}.")

    if heading_context:
        parts.append(f"Nearest heading above this chunk: \"{heading_context}\"")

    if previous_last_block:
        parts.append(
            "The previous chunk ended with this text (for continuity, do NOT repeat it):\n"
            f'"{previous_last_block}"'
        )

    parts.append("")
    parts.append("Raw text of this chunk:")
    parts.append("---")
    parts.append(chunk_text)
    parts.append("---")

    return "\n".join(parts)


# =========================================================
# RESPONSE SCHEMA
# =========================================================

# JSON schema for the AI's structured output. Matches the pydantic block
# models in app/schemas/document.py so validation downstream is a no-op.

RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "heading", "paragraph", "list",
                            "table", "page_break", "image",
                        ],
                    },
                    "level":    {"type": "integer", "minimum": 1, "maximum": 6},
                    "text":     {"type": "string"},
                    "ordered":  {"type": "boolean"},
                    "items":    {"type": "array", "items": {"type": "string"}},
                    "caption":  {"type": "string"},
                    "columns":  {"type": "array", "items": {"type": "string"}},
                    "rows": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "page":        {"type": "integer"},
                    "description": {"type": "string"},
                },
                "required": ["type"],
            },
        },
    },
    "required": ["blocks"],
}


# =========================================================
# PAYLOAD BUILDER
# =========================================================

def build_ai_payload(
    *,
    chunk_index: int,
    chunk_total: int,
    start_page: int,
    end_page: int,
    heading_context: str | None,
    previous_last_block: str | None,
    chunk_text: str,
    model: str = "gpt-4o-mini",
) -> dict:
    """Assemble the /chat/completion request body."""
    user_prompt = build_user_prompt(
        chunk_index=chunk_index,
        chunk_total=chunk_total,
        start_page=start_page,
        end_page=end_page,
        heading_context=heading_context,
        previous_last_block=previous_last_block,
        chunk_text=chunk_text,
    )

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "provider": "openai",
        "model": model,
        "service": "OCR Visitor Service — Document Structuring",
        "use_rag": False,
        "temperature": 0.1,
        "max_tokens": 8000,
        "response_schema": RESPONSE_SCHEMA,
    }