"""Prompts and response schemas for each supported image OCR type.

Each entry has:
  - label / description (FE dropdown metadata)
  - system_prompt (what the AI is told to do)
  - response_schema (JSON schema the AI must conform to)
"""

from app.models import ImageOCRType

# =========================================================
# INVOICE
# =========================================================

_INVOICE_SYSTEM = """You are an invoice data extractor. Read the invoice image and return ONE JSON object matching the schema exactly.

Rules:
- Never guess. If a field is not visible, return null.
- Numbers must be numeric types, not strings.
- Dates must be ISO 8601 (YYYY-MM-DD).
- Amounts must include currency and be numbers.
- Preserve line item order as printed on the invoice.
"""

_INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "vendor_name": {"type": ["string", "null"]},
        "vendor_address": {"type": ["string", "null"]},
        "invoice_number": {"type": ["string", "null"]},
        "invoice_date": {"type": ["string", "null"]},
        "due_date": {"type": ["string", "null"]},
        "currency": {"type": ["string", "null"]},
        "subtotal": {"type": ["number", "null"]},
        "tax": {"type": ["number", "null"]},
        "total": {"type": ["number", "null"]},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "quantity": {"type": ["number", "null"]},
                    "unit_price": {"type": ["number", "null"]},
                    "total": {"type": ["number", "null"]},
                },
                "required": ["description"],
            },
        },
        "notes": {"type": ["string", "null"]},
    },
    "required": [
        "vendor_name", "invoice_number", "invoice_date",
        "total", "line_items",
    ],
}

# =========================================================
# RECEIPT
# =========================================================

_RECEIPT_SYSTEM = """You are a receipt data extractor. Read the receipt image and return ONE JSON object matching the schema exactly.

Rules:
- Never guess. Missing fields should be null.
- Numbers must be numeric.
- Dates must be ISO 8601.
- Preserve item order.
"""

_RECEIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "merchant_name": {"type": ["string", "null"]},
        "merchant_address": {"type": ["string", "null"]},
        "date": {"type": ["string", "null"]},
        "time": {"type": ["string", "null"]},
        "currency": {"type": ["string", "null"]},
        "subtotal": {"type": ["number", "null"]},
        "tax": {"type": ["number", "null"]},
        "total": {"type": ["number", "null"]},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"type": ["number", "null"]},
                    "price": {"type": ["number", "null"]},
                },
                "required": ["name"],
            },
        },
        "payment_method": {"type": ["string", "null"]},
    },
    "required": ["merchant_name", "date", "total"],
}

# =========================================================
# VISITING CARD
# =========================================================

_VISITING_CARD_SYSTEM = """You are a visiting card OCR extractor. Read ONLY the text present on the card and return ONE JSON object matching the schema exactly.

Rules:
- Extract names, designations, companies exactly as printed.
- Emails and websites: remove spaces inside them.
- Phones: normalize to E.164-like (single leading '+', digits only, drop spaces/hyphens/parens; keep extensions as x123).
- Multiple names / emails / phones / websites → return as arrays.
- Never guess or invent data.
"""

_VISITING_CARD_SCHEMA = {
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
    "required": ["name", "emails", "phones", "websites"],
}

# =========================================================
# HOTEL MENU
# =========================================================

_HOTEL_MENU_SYSTEM = """You are a menu extractor. Read the menu image and return ONE JSON object matching the schema exactly.

Rules:
- Preserve item names exactly as printed.
- Prices should be numbers if possible; otherwise strings with currency.
- Group items by category if the menu has visible category headers.
"""

_HOTEL_MENU_SCHEMA = {
    "type": "object",
    "properties": {
        "restaurant_name": {"type": ["string", "null"]},
        "cuisine": {"type": ["string", "null"]},
        "currency": {"type": ["string", "null"]},
        "categories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "description": {"type": ["string", "null"]},
                                "price": {"type": ["string", "number", "null"]},
                            },
                            "required": ["name"],
                        },
                    },
                },
                "required": ["name", "items"],
            },
        },
    },
    "required": ["categories"],
}

# =========================================================
# ID CARD
# =========================================================

_ID_CARD_SYSTEM = """You are an ID card extractor. Read the ID card image and return ONE JSON object matching the schema exactly.

Rules:
- Never guess. If a field is not clearly visible, return null.
- Dates must be ISO 8601.
- Do NOT extract or return sensitive numbers like full ID/SSN/passport numbers
  beyond what's needed — return the ID number as printed but no verification codes.
"""

_ID_CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": ["string", "null"]},
        "id_number": {"type": ["string", "null"]},
        "dob": {"type": ["string", "null"]},
        "issue_date": {"type": ["string", "null"]},
        "expiry_date": {"type": ["string", "null"]},
        "issuing_authority": {"type": ["string", "null"]},
        "nationality": {"type": ["string", "null"]},
    },
    "required": ["name"],
}

# =========================================================
# HANDWRITTEN
# =========================================================

_HANDWRITTEN_SYSTEM = """You are a handwriting OCR extractor. Read the handwritten text in the image and return ONE JSON object matching the schema exactly.

Rules:
- Transcribe text as-is. Preserve line breaks.
- If the handwriting is illegible, transcribe what you can and omit the rest.
- Never guess at words you cannot read.
"""

_HANDWRITTEN_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "language": {"type": ["string", "null"]},
    },
    "required": ["text"],
}

# =========================================================
# GENERIC
# =========================================================

_GENERIC_SYSTEM = """You are a general OCR extractor. Read ALL visible text in the image and return ONE JSON object matching the schema exactly.

Rules:
- Transcribe all text as-is. Preserve line breaks.
- Do not structure, summarize, or interpret.
"""

_GENERIC_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "language": {"type": ["string", "null"]},
    },
    "required": ["text"],
}

# =========================================================
# REGISTRY
# =========================================================

IMAGE_TYPE_META: dict[ImageOCRType, dict] = {
    ImageOCRType.INVOICE: {
        "label": "Invoice",
        "description": "Extract vendor, line items, totals from an invoice",
        "system_prompt": _INVOICE_SYSTEM,
        "response_schema": _INVOICE_SCHEMA,
    },
    ImageOCRType.RECEIPT: {
        "label": "Receipt",
        "description": "Extract merchant, date, items, total from a receipt",
        "system_prompt": _RECEIPT_SYSTEM,
        "response_schema": _RECEIPT_SCHEMA,
    },
    ImageOCRType.VISITING_CARD: {
        "label": "Visiting Card",
        "description": "Extract contact details from a business card",
        "system_prompt": _VISITING_CARD_SYSTEM,
        "response_schema": _VISITING_CARD_SCHEMA,
    },
    ImageOCRType.HOTEL_MENU: {
        "label": "Hotel Menu",
        "description": "Extract dishes, categories, prices from a menu",
        "system_prompt": _HOTEL_MENU_SYSTEM,
        "response_schema": _HOTEL_MENU_SCHEMA,
    },
    ImageOCRType.ID_CARD: {
        "label": "ID Card",
        "description": "Extract name, ID number, dates from an ID",
        "system_prompt": _ID_CARD_SYSTEM,
        "response_schema": _ID_CARD_SCHEMA,
    },
    ImageOCRType.HANDWRITTEN: {
        "label": "Handwritten",
        "description": "Transcribe handwritten text",
        "system_prompt": _HANDWRITTEN_SYSTEM,
        "response_schema": _HANDWRITTEN_SCHEMA,
    },
    ImageOCRType.GENERIC: {
        "label": "Generic",
        "description": "Extract all visible text",
        "system_prompt": _GENERIC_SYSTEM,
        "response_schema": _GENERIC_SCHEMA,
    },
}
