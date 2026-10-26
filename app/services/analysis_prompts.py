"""Prompts, response schemas, and category defaults for analysis jobs.

Analysis is a combined summarize + classify operation. One AI call returns
both. Documents get a category + confidence; images only get tags because
the image_type already tells us what they are.
"""

# =========================================================
# DEFAULT CATEGORIES (documents)
# =========================================================

DEFAULT_DOCUMENT_CATEGORIES: list[str] = [
    "invoice",
    "receipt",
    "contract",
    "tender",
    "specification",
    "srs",
    "report",
    "letter",
    "memo",
    "policy",
    "form",
    "manual",
    "proposal",
    "other",
]


# =========================================================
# DOCUMENT ANALYSIS — SYSTEM PROMPT
# =========================================================

def build_document_system_prompt(
        *,
        categories: list[str],
        max_words: int,
) -> str:
    """System prompt for the combined document summarize + classify call.

    Categories are injected as a literal list so the model sees exactly
    which one to pick from. max_words caps the summary length.
    """
    category_lines = "\n".join(f"  - {c}" for c in categories)

    return f"""You are a document analyst. You receive structured content from a document and return ONE JSON object containing BOTH a summary and a classification.

CLASSIFICATION
Classify the document into EXACTLY ONE of these categories:
{category_lines}

If none of the categories fit, use "other".

Also choose:
  - subcategory: an optional finer label, or null if none fits naturally
  - tags: up to 5 short descriptive keywords (single words or two-word phrases)

SUMMARY
Write a summary of up to {max_words} words that captures:
  - The document's purpose
  - The main topics covered
  - Any critical information present (dates, amounts, parties, deadlines)

RULES
- Do NOT use markdown in the summary. Plain text only.
- Do NOT invent details not present in the document.
- Preserve names, dates, and numbers exactly as written.
- If the document is very short (under 50 words), summarize it in one line.
- Output must match the response schema exactly.
"""


# =========================================================
# DOCUMENT ANALYSIS — RESPONSE SCHEMA
# =========================================================

DOCUMENT_ANALYSIS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "category": {"type": "string"},
        "subcategory": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "category", "confidence", "tags"],
}


# =========================================================
# IMAGE ANALYSIS — SYSTEM PROMPT
# =========================================================

def build_image_system_prompt(
        *,
        image_type: str,
        max_words: int,
) -> str:
    """System prompt for image summarization.

    No classification — the caller already told us the image_type.
    """
    return f"""You are an image content summarizer. You receive structured JSON extracted from a {image_type} image. Produce:

  - summary: a {max_words}-word (or shorter) plain-English summary of what this image contains.
  - tags: up to 5 short descriptive tags (single words or two-word phrases).

RULES
- No markdown. Plain text only.
- Do not invent details not present in the JSON.
- Preserve names, amounts, and dates exactly as written.
- If the content is trivial (e.g., a single name), keep the summary to one line.
- Output must match the response schema exactly.
"""


# =========================================================
# IMAGE ANALYSIS — RESPONSE SCHEMA
# =========================================================

IMAGE_ANALYSIS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "tags"],
}


# =========================================================
# USER PROMPT BUILDERS
# =========================================================

def build_document_user_prompt(
        *,
        title: str | None,
        digest: str,
) -> str:
    """User prompt for document analysis."""
    safe_title = (title or "Untitled").strip()
    return (
        f"Title: {safe_title}\n\n"
        "Document content:\n"
        "---\n"
        f"{digest}\n"
        "---"
    )


def build_image_user_prompt(
        *,
        image_type: str,
        output_json: dict,
) -> str:
    """User prompt for image analysis."""
    import json
    return (
        f"Image type: {image_type}\n\n"
        "Extracted JSON:\n"
        "---\n"
        f"{json.dumps(output_json, ensure_ascii=False, indent=2)}\n"
        "---"
    )


# =========================================================
# PAYLOAD BUILDERS
# =========================================================

def build_document_analysis_payload(
        *,
        title: str | None,
        digest: str,
        categories: list[str],
        max_words: int,
        model: str = "gpt-4o-mini",
) -> dict:
    """Assemble the /chat/completion request body for a document analysis."""
    return {
        "messages": [
            {
                "role": "system",
                "content": build_document_system_prompt(
                    categories=categories,
                    max_words=max_words,
                ),
            },
            {
                "role": "user",
                "content": build_document_user_prompt(
                    title=title,
                    digest=digest,
                ),
            },
        ],
        "provider": "openai",
        "model": model,
        "service": "OCR Visitor Service — Document Analysis",
        "use_rag": False,
        "temperature": 0.2,
        "max_tokens": 2000,
        "response_schema": DOCUMENT_ANALYSIS_SCHEMA,
    }


def build_image_analysis_payload(
        *,
        image_type: str,
        output_json: dict,
        max_words: int,
        model: str = "gpt-4o-mini",
) -> dict:
    """Assemble the /chat/completion request body for an image analysis."""
    return {
        "messages": [
            {
                "role": "system",
                "content": build_image_system_prompt(
                    image_type=image_type,
                    max_words=max_words,
                ),
            },
            {
                "role": "user",
                "content": build_image_user_prompt(
                    image_type=image_type,
                    output_json=output_json,
                ),
            },
        ],
        "provider": "openai",
        "model": model,
        "service": "OCR Visitor Service — Image Analysis",
        "use_rag": False,
        "temperature": 0.2,
        "max_tokens": 1200,
        "response_schema": IMAGE_ANALYSIS_SCHEMA,
    }


# =========================================================
# PROMPT VERSION (for future A/B testing)
# =========================================================

PROMPT_VERSION = "v1"
