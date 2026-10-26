"""Prompts for template-driven extraction.

Two variants:
  - Image: vision model reads the image and returns fields directly.
  - Document: text is already structured; the AI applies the template
    fields to the structured text.

Both use the same field schema from the template.
"""

import json


# =========================================================
# IMAGE EXTRACTION
# =========================================================

def build_image_system_prompt(
    *,
    template_name: str,
    template_description: str,
    fields: list[dict],
) -> str:
    """System prompt for the vision model.

    Instructs it to return {field_key: {value, confidence}}.
    """
    field_lines = "\n".join(
        f'  - "{f["key"]}" ({f["type"]}{", required" if f.get("required") else ""}): '
        f'{f["label"]}'
        + (f' — {f["description"]}' if f.get("description") else "")
        for f in fields
    )

    return f"""You are a data extractor for a document type called "{template_name}".
{template_description}

Read the image and extract the following fields:
{field_lines}

For EACH field, return:
  - "value": the extracted value, or null if not found
  - "confidence": a number between 0.0 and 1.0 reflecting how sure you are

RULES:
- Return values exactly as they appear in the image. Do not normalize unless
  the field type requires it (e.g. phone → E.164, date → ISO 8601).
- Never guess. If a field is not present or illegible, return null with confidence 0.0.
- For "list" type fields, return an array. For "object" type fields, return a JSON object.
- Do not invent fields. Do not omit required fields (return null if missing).
- Output must be a single JSON object mapping field keys to {{value, confidence}}.
"""


def build_image_user_prompt() -> str:
    return "Extract the fields from this image."


def build_image_response_schema(fields: list[dict]) -> dict:
    """JSON schema for the AI response.

    Each field key maps to a {value, confidence} object.
    """
    field_props = {}
    for f in fields:
        field_props[f["key"]] = {
            "type": "object",
            "properties": {
                "value": {"type": ["string", "number", "boolean", "array", "object", "null"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["value", "confidence"],
        }

    return {
        "type": "object",
        "properties": field_props,
        "required": [f["key"] for f in fields if f.get("required")],
    }


# =========================================================
# DOCUMENT EXTRACTION
# =========================================================

def build_document_system_prompt(
    *,
    template_name: str,
    template_description: str,
    fields: list[dict],
) -> str:
    """System prompt for text-based extraction.

    Input is the structured text of a document. Instructs the model
    to return {field_key: {value, confidence}}.
    """
    field_lines = "\n".join(
        f'  - "{f["key"]}" ({f["type"]}{", required" if f.get("required") else ""}): '
        f'{f["label"]}'
        + (f' — {f["description"]}' if f.get("description") else "")
        for f in fields
    )

    return f"""You are a data extractor for a document type called "{template_name}".
{template_description}

You receive the full structured text of the document. Extract the following fields:
{field_lines}

For EACH field, return:
  - "value": the extracted value, or null if not found
  - "confidence": a number between 0.0 and 1.0 reflecting how sure you are

RULES:
- Return values exactly as they appear in the document. Do not paraphrase.
- Never guess. If a field is not present, return null with confidence 0.0.
- For "list" type fields, return an array of objects or strings as appropriate.
- Do not invent fields. Do not omit required fields (return null if missing).
- Preserve original text for names, dates, amounts — do NOT translate or normalize.
- Output must be a single JSON object mapping field keys to {{value, confidence}}.
"""


def build_document_user_prompt(*, document_text: str) -> str:
    return (
        "Document content:\n"
        "---\n"
        f"{document_text}\n"
        "---"
    )


def build_document_response_schema(fields: list[dict]) -> dict:
    """Same shape as the image schema."""
    return build_image_response_schema(fields)


# =========================================================
# PAYLOAD BUILDERS
# =========================================================

def build_image_extraction_payload(
    *,
    image_url: str,
    template_name: str,
    template_description: str,
    fields: list[dict],
    model: str = "gpt-4o-mini",
) -> dict:
    """Assemble the /chat/vision request for image extraction."""
    return {
        "messages": [
            {
                "role": "system",
                "content": [{
                    "type": "text",
                    "text": build_image_system_prompt(
                        template_name=template_name,
                        template_description=template_description,
                        fields=fields,
                    ),
                }],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": build_image_user_prompt(),
                    },
                    {
                        "type": "image_url",
                        "url": image_url,
                        "detail": "auto",
                    },
                ],
            },
        ],
        "provider": "openai",
        "model": model,
        "service": "OCR Visitor Service — Image Extraction",
        "use_rag": False,
        "temperature": 0.1,
        "max_tokens": 4000,
        "response_schema": build_image_response_schema(fields),
    }


def build_document_extraction_payload(
    *,
    document_text: str,
    template_name: str,
    template_description: str,
    fields: list[dict],
    model: str = "gpt-4o-mini",
) -> dict:
    """Assemble the /chat/completion request for document extraction."""
    return {
        "messages": [
            {
                "role": "system",
                "content": build_document_system_prompt(
                    template_name=template_name,
                    template_description=template_description,
                    fields=fields,
                ),
            },
            {
                "role": "user",
                "content": build_document_user_prompt(document_text=document_text),
            },
        ],
        "provider": "openai",
        "model": model,
        "service": "OCR Visitor Service — Document Extraction",
        "use_rag": False,
        "temperature": 0.1,
        "max_tokens": 4000,
        "response_schema": build_document_response_schema(fields),
    }


# =========================================================
# POST-PROCESSING
# =========================================================

def parse_extraction_result(raw_data: dict, fields: list[dict]) -> dict[str, dict]:
    """Normalize the AI response into {key: {value, confidence}}.

    Ensures every template field is present (null if missing) and
    confidence is coerced to [0, 1].
    """
    result: dict[str, dict] = {}
    for f in fields:
        key = f["key"]
        entry = raw_data.get(key) if isinstance(raw_data, dict) else None
        if isinstance(entry, dict):
            value = entry.get("value")
            try:
                confidence = float(entry.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            confidence = max(0.0, min(1.0, confidence))
        else:
            value = None
            confidence = 0.0

        result[key] = {"value": value, "confidence": confidence}
    return result


def compute_min_confidence(
    result: dict[str, dict],
    fields: list[dict],
) -> float:
    """Minimum confidence across REQUIRED fields.

    Optional fields don't drag the score down — a missing optional
    field with low confidence shouldn't force review.
    """
    required_keys = [f["key"] for f in fields if f.get("required")]
    if not required_keys:
        # No required fields — use all fields
        required_keys = [f["key"] for f in fields]

    values = [
        result.get(k, {}).get("confidence", 0.0)
        for k in required_keys
    ]
    return min(values) if values else 0.0