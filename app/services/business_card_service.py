"""Business-card OCR helpers.

Pure functions only:
  - BUSINESS_CARD_PROMPT       — system prompt for the AI service
  - parse_ai_response_to_ocr_result — AI response → OCRResult
  - merge_ocr_results          — front + back OCRResult → merged OCRResult

No I/O, no DB, no HTTP. The Celery worker in app/tasks/ocr_tasks.py
owns the AI call and the persistence.
"""

from typing import Any

from app.schemas.ocr import AddressOCR, OCRResult


# =========================================================
# SYSTEM PROMPT
# =========================================================

BUSINESS_CARD_PROMPT = """You are an OCR-to-JSON extractor for visiting cards. Read ONLY the text present in the 
            image and return ONE JSON object. Never guess, correct, or invent data beyond the transformations below. 
            Output must be a single JSON object only, with keys: name, designation, company, emails, phones, address, 
            websites.

            RULES:
            1) NAME: Extract exactly as printed. If more than one name, separate with comma.
            2) DESIGNATION and COMPANY: Extract exactly as printed (do not add or remove words).
            3) EMAILS: Extract exactly as shown. Remove spaces inside the email only. Return as an array; if none, return an empty array.
            4) WEBSITES: Extract exactly as shown. Remove spaces inside the URL only. Return as an array; if none, return an empty array.
            5) PHONES (strict algorithm):
               a. Capture ALL numbers present on the card, including those labeled or implied as Tel, Telephone, T, Phone, Ph, Office, Landline, Mob, Mobile, Cell, or a phone icon, as well as unlabeled numbers that appear to be phone numbers.
               b. Use high accuracy to capture all digits exactly as printed, avoiding OCR misreads.
               c. Normalize to E.164-like form: a single optional leading '+', then digits only. Remove spaces, hyphens, dots, and parentheses. Keep extensions as 'x<digits>' (e.g., +14151234567x89).
               d. Country code (safe inference): If a number lacks a country code, infer the country ONLY when it is unambiguous, using this order of cues from the printed content:
                  1) Country explicitly present in the address.
                  2) State/province or city in the address that uniquely maps to a country (e.g., Maharashtra/Mumbai -> India; California/NY -> USA; Ontario -> Canada; NSW/VIC -> Australia; London (UK) when paired with UK context, etc.). Use standard lists of well-known states/provinces and major cities.
                  3) Country-code top-level domain of the website/email (ccTLD): .in, .us, .uk, .ca, .au, .sg, .ae, .de, .fr, etc. Ignore path segments like '/in'.
                  4) Clear domestic numbering pattern plus area/STD code that uniquely indicates a country when combined with the address context (e.g., Indian STD pattern 0xx/0xxx/0xxxx such as 022, 040, 080 in an Indian city).
                  If multiple cues conflict or none are decisive, do NOT add any country code.
               e. Trunk prefix: When adding a country code, drop a single domestic trunk '0' directly before the area/STD code (e.g., 022 -> +91 22 ...). Do not drop other zeros.
               f. Area/STD propagation on the same line: If the first landline on a line includes an area/STD code and subsequent numbers on that line omit it, apply the same area/STD code to them. Example: '022 4002 9978 • 2262 3405' -> '022 40029978' and '022 22623405'.
               g. Slash-notation expansion: If a complete base number is followed by '/suffix' parts, create full numbers by replacing the last L digits of the base with each suffix of length L. Example: '+91 22 2209 4675 /58/70' -> '+912222094675', '+912222094658', '+912222094670'. If no valid base exists or lengths do not match, treat tokens as separate numbers without expansion.
               h. Convert '00' international prefix to '+'.
               i. Deduplicate. Keep numbers that have at least 6 subscriber digits after area code. Never invent missing digits.
            6) ADDRESS: Return exactly as printed, preserving line order, as an array of objects: [{"id": 0, "address": "<full address lines joined with commas>", "state": "<state if present>", "country": "<country if present>"}]. If multiple addresses, increment id starting from 0 and id's will be incremental according to the address available. Only fill state/country if unambiguously identified from the printed text.
            7) LANGUAGE: Keep each field in the same language as printed. If a field is in a regional language and others are in English, keep the regional text and add its English in parentheses. Example: 'अर्चित जैन (Converted in English)'.
            8) OUTPUT FORMAT: Return exactly one JSON object with keys: name (string), designation (string), company (string), emails (array), phones (array), address (array of objects as specified), websites (array). No extra text before or after the JSON.

            IMPORTANT:
            - Use enhanced OCR accuracy to capture all email ids, phone numbers and digits exactly as printed.
            - Do NOT omit any phone numbers and email id present on the card.
            - Do NOT guess or alter digits; if unclear, omit that number.
            - Ensure no phone number is missed or partially captured.
            """


# =========================================================
# PARSE AI RESPONSE → OCRResult
# =========================================================

def parse_ai_response_to_ocr_result(
    ai_response: dict[str, Any] | None,
) -> OCRResult | None:
    """Parse the AI service response into an OCRResult.

    The AI service may return either:
        {"success": true, "data": {...}}
    or the bare object:
        {"name": "...", "designation": "...", ...}

    Returns None if the response is missing or malformed.
    """
    if not ai_response:
        return None

    data = ai_response.get("data", ai_response)
    if not isinstance(data, dict):
        return None

    address_data = data.get("address", [])
    addresses: list[AddressOCR] = []

    if isinstance(address_data, list):
        for index, address in enumerate(address_data):
            if not isinstance(address, dict):
                continue
            addresses.append(AddressOCR(
                id=address.get("id", index),
                address=address.get("address", ""),
                state=address.get("state", ""),
                country=address.get("country", ""),
            ))

    return OCRResult(
        name=data.get("name", ""),
        designation=data.get("designation", ""),
        company=data.get("company", ""),
        emails=_string_list(data.get("emails")),
        phones=_string_list(data.get("phones")),
        address=addresses,
        websites=_string_list(data.get("websites")),
    )


# =========================================================
# MERGE FRONT + BACK
# =========================================================

def merge_ocr_results(
    front: OCRResult | None,
    back: OCRResult | None,
) -> OCRResult:
    front = front or OCRResult()
    back = back or OCRResult()

    return OCRResult(
        name=front.name or back.name,
        designation=front.designation or back.designation,
        company=front.company or back.company,
        emails=_merge_lists(front.emails, back.emails),
        phones=_merge_lists(front.phones, back.phones),
        websites=_merge_lists(front.websites, back.websites),
        address=_merge_addresses(front.address, back.address),
    )


# =========================================================
# HELPERS
# =========================================================

def _merge_lists(first: list[str], second: list[str]) -> list[str]:
    result: list[str] = []
    for value in first + second:
        if not value:
            continue
        if value not in result:
            result.append(value)
    return result


def _merge_addresses(
    front: list[AddressOCR],
    back: list[AddressOCR],
) -> list[AddressOCR]:
    result: list[AddressOCR] = []
    seen: set[tuple[str, str, str]] = set()

    for address in front + back:
        key = (
            address.address.strip().lower(),
            address.state.strip().lower(),
            address.country.strip().lower(),
        )
        if not address.address.strip():
            continue
        if key in seen:
            continue
        seen.add(key)
        result.append(AddressOCR(
            id=len(result),
            address=address.address,
            state=address.state,
            country=address.country,
        ))

    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        str(item)
        for item in value
        if item is not None and str(item).strip()
    ]