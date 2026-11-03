"""Prompts and response schema for the AI structuring step.

The AI receives chunks of extracted document text and returns structured
blocks. The system prompt is selected from a document-type registry
(tender, SRS, report, etc.); the user prompt is per-chunk and includes
light context so the model knows where it is in the document.

When the FE requests extra content (a list of keys and/or a custom prompt),
that request is injected into the per-chunk prompt and into the response
schema under an optional `requested` object.
"""

import copy

from app.services.requested_content import (
    build_requested_instructions,
    build_requested_response_schema,
    has_requested_content,
)

# =========================================================
# DOCUMENT TYPES
# =========================================================

DEFAULT_DOCUMENT_TYPE = "generic"

# Shared output contract. Every type-specific prompt ends with this so the
# block schema stays consistent regardless of the selected type.
_COMMON_RULES = """Do NOT summarize. Do NOT paraphrase. Preserve the text as-is.
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

Only use "page_break" if the input explicitly marks a page boundary."""


def _system_prompt(role: str, focus: str) -> str:
    return (
        f"{role}\n\n"
        f"{focus.strip()}\n\n"
        f"{_COMMON_RULES}"
    )


_GENERIC_SYSTEM = _system_prompt(
    "You are a document structure extractor. You receive raw text from a "
    "page or chunk of a document. Your job is to return structured blocks "
    "that preserve the document's hierarchy.",
    "Preserve the document as a faithful structured transcription.",
)

_TENDER_SYSTEM = _system_prompt(
    "You are a tender document OCR extractor. You receive raw text from a "
    "tender, RFP, bid notice, or procurement document.",
    """Preserve and emphasise:
- Tender / RFP / notice number, issuing authority, department, project name
- Publication, pre-bid meeting, bid submission, opening, and validity dates
- Scope of work, eligibility criteria, technical and financial requirements
- EMD / bid security, performance guarantee, tender fees
- Evaluation criteria, submission instructions, contact details
- All tables such as BOQ, price schedules, compliance matrices, and annexures

Keep every clause and condition. Do not summarise eligibility, dates,
amounts, or evaluation rules.""",
)

_SRS_SYSTEM = _system_prompt(
    "You are an SRS / requirements document OCR extractor. You receive raw "
    "text from a software requirements specification or similar document.",
    """Preserve and emphasise:
- Requirement IDs, version, revision history, and approval details
- Functional requirements, non-functional requirements, and constraints
- Actors, use cases, user stories, workflows, and business rules
- Acceptance criteria, assumptions, dependencies, and traceability tables
- Interface, data, security, and performance requirements

Keep requirement IDs attached to their requirement text. Do not merge or
drop requirements.""",
)

_SPECIFICATION_SYSTEM = _system_prompt(
    "You are a technical specification OCR extractor. You receive raw text "
    "from a specification document or specification card.",
    """Preserve and emphasise:
- Product / system / component name, model, part number, and revision
- Parameter names, values, units, tolerances, ratings, and limits
- Standards, compliance references, test conditions, and certifications
- Material, dimension, performance, environmental, and safety specifications
- Specification tables and parameter matrices

Keep parameter/value pairs together. Do not round or convert values unless
the document explicitly does so.""",
)

_REPORT_SYSTEM = _system_prompt(
    "You are a report OCR extractor. You receive raw text from a formal "
    "report or assessment document.",
    """Preserve and emphasise:
- Report title, author / organisation, date, version, and reference number
- Executive summary, background, methodology, findings, observations,
  analysis, recommendations, conclusions, and appendices
- Dates, amounts, metrics, and names exactly as written
- Tables, charts captions, figure captions, and data rows

Keep the report's section hierarchy. Do not turn findings into a summary.""",
)

_LETTER_SYSTEM = _system_prompt(
    "You are a formal letter OCR extractor. You receive raw text from a "
    "letter or official correspondence.",
    """Preserve and emphasise:
- Letterhead / organisation name, reference number, and date
- Sender and recipient names, designations, and addresses
- Subject line, salutation, body paragraphs, and closing
- Enclosures, copies, signatures, and signatory details

Keep addresses and signature blocks as separate paragraphs or list items.
Do not merge the letterhead into the body or omit reference numbers.""",
)

_MEMO_SYSTEM = _system_prompt(
    "You are a memo OCR extractor. You receive raw text from an internal "
    "memorandum or office note.",
    """Preserve and emphasise:
- To, From, CC, Date, Subject, and Reference fields
- Body paragraphs, numbered points, decisions, and action items
- Attachments, approvals, and sign-off details

Keep the memo header fields as distinct lines before the body. Do not drop
recipients, dates, or action items.""",
)

_POLICY_SYSTEM = _system_prompt(
    "You are a policy document OCR extractor. You receive raw text from a "
    "policy, procedure, or governance document.",
    """Preserve and emphasise:
- Policy title, policy number, version, owner, and approval authority
- Effective date, review date, and applicable scope
- Purpose, definitions, policy statements, procedures, responsibilities,
  exceptions, and escalation paths
- Clause numbering, cross-references, and revision history

Keep every clause attached to its number. Do not soften or summarise
obligations such as "must", "shall", or "may".""",
)

_FORM_SYSTEM = _system_prompt(
    "You are a form OCR extractor. You receive raw text from a form, "
    "application, checklist, or data-entry sheet.",
    """Preserve and emphasise:
- Form title, form number, revision, and issuing authority
- Section headings and field labels
- Entered values, typed answers, ticks, selections, and checkbox states
- Tables, rows, declarations, signatures, and dates

Keep every field label together with its value. Represent field/value
pairs as paragraphs or list items. Do not omit blank fields or unchecked
options if they are visible in the input.""",
)

_PROPOSAL_SYSTEM = _system_prompt(
    "You are a proposal OCR extractor. You receive raw text from a business, "
    "technical, or commercial proposal.",
    """Preserve and emphasise:
- Proposal title, client, project, prepared-by, date, and reference number
- Executive summary, background, scope, approach, methodology, and deliverables
- Timelines, milestones, phases, assumptions, and dependencies
- Pricing, commercial terms, payment schedules, and cost tables
- Team, experience, case studies, and contact details

Keep pricing and timeline tables structured. Do not summarise commitments
or commercial terms.""",
)


DOCUMENT_TYPE_META: dict[str, dict] = {
    "generic": {
        "label": "Generic Document",
        "description": "Structure any document into heading, paragraph, list, and table blocks",
        "system_prompt": _GENERIC_SYSTEM,
    },
    "tender": {
        "label": "Tender Document",
        "description": "Extract tender/RFP sections, dates, eligibility, BOQ, and submission details",
        "system_prompt": _TENDER_SYSTEM,
    },
    "srs": {
        "label": "SRS Document",
        "description": "Extract requirements, requirement IDs, use cases, and acceptance criteria",
        "system_prompt": _SRS_SYSTEM,
    },
    "specification": {
        "label": "Specification",
        "description": "Extract technical parameters, values, units, standards, and compliance tables",
        "system_prompt": _SPECIFICATION_SYSTEM,
    },
    "report": {
        "label": "Report",
        "description": "Extract report sections, findings, metrics, conclusions, and appendices",
        "system_prompt": _REPORT_SYSTEM,
    },
    "letter": {
        "label": "Letter",
        "description": "Extract letterhead, reference, addresses, subject, body, and signature",
        "system_prompt": _LETTER_SYSTEM,
    },
    "memo": {
        "label": "Memo",
        "description": "Extract To/From/Date/Subject fields, body, and action items",
        "system_prompt": _MEMO_SYSTEM,
    },
    "policy": {
        "label": "Policy",
        "description": "Extract policy clauses, scope, responsibilities, and revision history",
        "system_prompt": _POLICY_SYSTEM,
    },
    "form": {
        "label": "Form",
        "description": "Extract field labels and their entered values, selections, and declarations",
        "system_prompt": _FORM_SYSTEM,
    },
    "proposal": {
        "label": "Proposal",
        "description": "Extract proposal scope, deliverables, timelines, pricing, and terms",
        "system_prompt": _PROPOSAL_SYSTEM,
    },
}

# FE-friendly aliases. Keys are normalised before lookup.
_DOCUMENT_TYPE_ALIASES = {
    "generic_document": "generic",
    "tender_document": "tender",
    "srs_document": "srs",
    "specification_card": "specification",
    "specification_document": "specification",
    "spec": "specification",
    "report_document": "report",
    "letter_document": "letter",
    "memo_document": "memo",
    "policy_document": "policy",
    "form_document": "form",
    "proposal_document": "proposal",
}

# Backwards-compatible name used by older imports.
SYSTEM_PROMPT = _GENERIC_SYSTEM


def normalize_document_type(value: str | None) -> str:
    """Return a canonical document type key.

    Accepts None (generic), case variations, spaces/hyphens, and the
    FE-friendly aliases above.
    """
    if value is None:
        return DEFAULT_DOCUMENT_TYPE

    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    key = _DOCUMENT_TYPE_ALIASES.get(key, key)
    if key not in DOCUMENT_TYPE_META:
        allowed = ", ".join(sorted(DOCUMENT_TYPE_META))
        raise ValueError(
            f"Unsupported document_type: {value!r}. Allowed: {allowed}."
        )
    return key


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
    requested_keys: list[str] | None = None,
    requested_prompt: str | None = None,
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

    requested = build_requested_instructions(
        keys=requested_keys,
        prompt=requested_prompt,
    )
    if requested:
        parts.append("")
        parts.append(requested)

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
    document_type: str = DEFAULT_DOCUMENT_TYPE,
    requested_keys: list[str] | None = None,
    requested_prompt: str | None = None,
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
        requested_keys=requested_keys,
        requested_prompt=requested_prompt,
    )

    schema = RESPONSE_SCHEMA
    requested_schema = build_requested_response_schema(
        keys=requested_keys,
        prompt=requested_prompt,
    )
    if has_requested_content(requested_keys, requested_prompt):
        schema = copy.deepcopy(RESPONSE_SCHEMA)
        schema["properties"]["requested"] = requested_schema
        schema["required"] = [*schema.get("required", []), "requested"]

    meta = DOCUMENT_TYPE_META.get(
        document_type,
        DOCUMENT_TYPE_META[DEFAULT_DOCUMENT_TYPE],
    )

    return {
        "messages": [
            {"role": "system", "content": meta["system_prompt"]},
            {"role": "user", "content": user_prompt},
        ],
        "provider": "openai",
        "model": model,
        "service": "OCR Visitor Service — Document Structuring",
        "use_rag": False,
        "temperature": 0.1,
        "max_tokens": 8000,
        "response_schema": schema,
    }