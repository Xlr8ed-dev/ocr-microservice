"""Helpers for user-requested OCR content.

The FE may send a list of `keys` (fields it wants extracted) and/or a
free-form `prompt`. The OCR service does not own or validate the key list —
it only consumes it, injects it into the AI prompt, and stores whatever the
model returns.

Output shape stored under `output.requested`:

    {
        "keys": {"<requested key>": <value or null>, ...},
        "prompt_result": <value or null>          # only when a prompt was sent
    }
"""

from typing import Any

# Bounds protect the AI prompt/schema from abuse. The FE owns the actual
# key vocabulary; we only cap size.
MAX_REQUESTED_KEYS = 50
MAX_REQUESTED_KEY_LENGTH = 100
MAX_REQUESTED_PROMPT_LENGTH = 4000

# JSON schema for an arbitrary requested value.
REQUESTED_VALUE_SCHEMA: dict[str, Any] = {
    "type": ["string", "number", "boolean", "array", "object", "null"],
}


# =========================================================
# REQUEST NORMALISATION
# =========================================================

def normalize_requested_keys(keys: list[str] | None) -> list[str] | None:
    """Trim, drop blanks, de-duplicate (case-insensitive), preserve order."""
    if not keys:
        return None

    out: list[str] = []
    seen: set[str] = set()
    for raw in keys:
        key = str(raw).strip()
        if not key:
            continue
        if len(key) > MAX_REQUESTED_KEY_LENGTH:
            raise ValueError(
                f"Requested key is too long (max {MAX_REQUESTED_KEY_LENGTH} "
                f"characters): {key[:40]!r}"
            )
        dedupe_key = key.casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        out.append(key)

    if len(out) > MAX_REQUESTED_KEYS:
        raise ValueError(
            f"Too many requested keys (max {MAX_REQUESTED_KEYS})."
        )
    return out or None


def normalize_requested_prompt(prompt: str | None) -> str | None:
    """Trim the custom prompt and reject an over-long one."""
    if prompt is None:
        return None
    clean = prompt.strip()
    if not clean:
        return None
    if len(clean) > MAX_REQUESTED_PROMPT_LENGTH:
        raise ValueError(
            f"Requested prompt is too long "
            f"(max {MAX_REQUESTED_PROMPT_LENGTH} characters)."
        )
    return clean


def has_requested_content(
    keys: list[str] | None,
    prompt: str | None,
) -> bool:
    return bool(keys or prompt)


# =========================================================
# PROMPT INJECTION
# =========================================================

def build_requested_instructions(
    *,
    keys: list[str] | None,
    prompt: str | None,
) -> str:
    """Build the block of instructions appended to the AI user prompt.

    Returns an empty string when the caller did not ask for anything extra.
    """
    if not has_requested_content(keys, prompt):
        return ""

    parts: list[str] = ["USER-REQUESTED EXTRACTION"]

    if keys:
        parts.append(
            "In addition to the normal output, extract the following fields "
            "from the content. Return them in the `requested.keys` object "
            "using these exact keys:"
        )
        parts.extend(f'  - "{key}"' for key in keys)
        parts.append(
            "If a requested field is not present in this content, set its "
            "value to null. Never guess or invent a value."
        )

    if prompt:
        parts.append("")
        parts.append("CUSTOM EXTRACTION INSTRUCTION")
        parts.append(prompt)
        parts.append(
            "Return the result of this instruction in "
            "`requested.prompt_result`. Use null if the instruction cannot "
            "be answered from this content."
        )

    return "\n".join(parts)


# =========================================================
# RESPONSE SCHEMA
# =========================================================

def build_requested_response_schema(
    *,
    keys: list[str] | None,
    prompt: str | None,
) -> dict[str, Any] | None:
    """Return the `requested` schema fragment, or None if nothing was asked."""
    if not has_requested_content(keys, prompt):
        return None

    properties: dict[str, Any] = {}
    required: list[str] = []

    if keys:
        properties["keys"] = {
            "type": "object",
            "properties": {key: REQUESTED_VALUE_SCHEMA for key in keys},
            "required": list(keys),
            "additionalProperties": False,
        }
        required.append("keys")

    if prompt:
        properties["prompt_result"] = REQUESTED_VALUE_SCHEMA
        required.append("prompt_result")

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


# =========================================================
# RESULT NORMALISATION / MERGING
# =========================================================

def sanitize_requested_output(
    raw: Any,
    *,
    keys: list[str] | None,
    prompt: str | None,
) -> dict[str, Any] | None:
    """Normalise a model response into the stored `requested` shape.

    Always returns one entry per requested key (null when the model omitted
    it), so the FE can rely on the shape.
    """
    if not has_requested_content(keys, prompt):
        return None

    data = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}

    if keys:
        raw_keys = data.get("keys")
        if not isinstance(raw_keys, dict):
            raw_keys = {}
        out["keys"] = {key: raw_keys.get(key) for key in keys}

    if prompt:
        out["prompt_result"] = data.get("prompt_result")

    return out


def merge_requested_outputs(
    values: list[Any],
    *,
    keys: list[str] | None,
    prompt: str | None,
) -> dict[str, Any] | None:
    """Merge per-chunk requested values into one result.

    For each key the first non-empty value wins. The same applies to the
    custom-prompt result. Missing keys stay null.
    """
    if not has_requested_content(keys, prompt):
        return None

    merged_keys: dict[str, Any] = {}
    merged_prompt: Any = None

    for raw in values:
        if not isinstance(raw, dict):
            continue

        raw_keys = raw.get("keys")
        if isinstance(raw_keys, dict):
            for key in keys or []:
                if not _is_empty(merged_keys.get(key)):
                    continue
                value = raw_keys.get(key)
                if not _is_empty(value):
                    merged_keys[key] = value

        if prompt and _is_empty(merged_prompt):
            value = raw.get("prompt_result")
            if not _is_empty(value):
                merged_prompt = value

    out: dict[str, Any] = {}
    if keys:
        out["keys"] = {key: merged_keys.get(key) for key in keys}
    if prompt:
        out["prompt_result"] = merged_prompt
    return out


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}
