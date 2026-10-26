"""Renderers for extraction export.

Three formats:
  - JSON: the raw per-field {value, confidence} result
  - CSV:  one row, one column per template field
  - vCard: a single .vcf contact (business_card_extraction only)

All formats respect the template's field order so exports are stable
across runs.
"""

import csv
import io
import json
from datetime import datetime
from typing import Any

from app.models import Extraction, Template


# =========================================================
# PUBLIC ENTRY POINT
# =========================================================

def export_extraction(
    *,
    extraction: Extraction,
    template: Template,
    format: str,
) -> tuple[bytes, str, str]:
    """Render the extraction in the requested format.

    Returns:
        (content_bytes, filename, media_type)
    """
    fmt = format.lower()
    base_name = _safe_filename(extraction.file_name or extraction.id)

    if fmt == "json":
        content = _render_json(extraction, template)
        return content.encode("utf-8"), f"{base_name}.json", "application/json"

    if fmt == "csv":
        content = _render_csv(extraction, template)
        return content.encode("utf-8"), f"{base_name}.csv", "text/csv"

    if fmt == "vcard":
        if template.id != "business_card_extraction":
            raise ValueError(
                f"vCard export is only available for the "
                f"'business_card_extraction' template, not '{template.id}'."
            )
        content = _render_vcard(extraction, template)
        return content.encode("utf-8"), f"{base_name}.vcf", "text/vcard"

    raise ValueError(
        f"Unsupported format: {format}. Supported: json, csv, vcard."
    )


# =========================================================
# JSON
# =========================================================

def _render_json(extraction: Extraction, template: Template) -> str:
    """Pretty-printed JSON of the extraction result.

    Includes per-field confidence so exports preserve the same data the
    API returns. Metadata (file_name, template, timestamps) is added
    outside `result` so consumers can distinguish the fields from the
    context.
    """
    payload = {
        "extraction_id": extraction.id,
        "template_id": template.id,
        "template_name": template.name,
        "file_name": extraction.file_name,
        "status": extraction.status.value,
        "min_confidence": extraction.min_confidence,
        "review_needed": extraction.review_needed,
        "created_at": _iso(extraction.created_at),
        "completed_at": _iso(extraction.completed_at),
        "result": _ordered_result(extraction, template),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# =========================================================
# CSV
# =========================================================

def _render_csv(extraction: Extraction, template: Template) -> str:
    """One header row + one data row.

    Lists and objects are serialized as JSON strings in their cell.
    Column order matches template field order.
    """
    fields = [f for f in (template.fields or []) if "key" in f]
    result = extraction.result or {}

    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)

    # header
    writer.writerow([f["key"] for f in fields])

    # data row
    row: list[str] = []
    for f in fields:
        entry = result.get(f["key"]) or {}
        value = entry.get("value")
        row.append(_cell_value(value))
    writer.writerow(row)

    return buf.getvalue()


def _cell_value(value: Any) -> str:
    """Flatten a value into a CSV-safe string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    # lists, dicts, etc.
    return json.dumps(value, ensure_ascii=False)


# =========================================================
# VCARD
# =========================================================

def _render_vcard(extraction: Extraction, template: Template) -> str:
    """Render a single vCard 3.0 entry for a business card extraction.

    Maps template fields to vCard properties:
      full_name → FN (formatted name)
      job_title → TITLE
      company → ORG
      phone → TEL;TYPE=WORK
      email → EMAIL;TYPE=WORK
      website → URL
      address → ADR;TYPE=WORK
      social → URL (each entry)
    """
    result = extraction.result or {}

    def get(key: str) -> str:
        v = (result.get(key) or {}).get("value")
        return str(v).strip() if v else ""

    lines: list[str] = ["BEGIN:VCARD", "VERSION:3.0"]

    full_name = get("full_name")
    if full_name:
        # FN is required by vCard spec; split into N (last;first) if possible
        lines.append(f"FN:{_vcard_escape(full_name)}")
        lines.append(f"N:{_vcard_escape(full_name)};;;;")

    job_title = get("job_title")
    if job_title:
        lines.append(f"TITLE:{_vcard_escape(job_title)}")

    company = get("company")
    if company:
        lines.append(f"ORG:{_vcard_escape(company)}")

    phone = get("phone")
    if phone:
        lines.append(f"TEL;TYPE=WORK:{_vcard_escape(phone)}")

    email = get("email")
    if email:
        lines.append(f"EMAIL;TYPE=WORK:{_vcard_escape(email)}")

    website = get("website")
    if website:
        lines.append(f"URL:{_vcard_escape(website)}")

    address = get("address")
    if address:
        # ADR format: ;;street;city;state;zip;country
        # We don't try to split the address — put it all in the "street" slot.
        lines.append(f"ADR;TYPE=WORK:;;{_vcard_escape(address)};;;;")

    social_raw = (result.get("social") or {}).get("value") or []
    if isinstance(social_raw, list):
        for handle in social_raw:
            if handle:
                lines.append(f"URL:{_vcard_escape(str(handle))}")

    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"


def _vcard_escape(s: str) -> str:
    """Escape commas, semicolons, backslashes, newlines for vCard."""
    return (
        s.replace("\\", "\\\\")
         .replace(",", "\\,")
         .replace(";", "\\;")
         .replace("\n", "\\n")
    )


# =========================================================
# HELPERS
# =========================================================

def _ordered_result(extraction: Extraction, template: Template) -> dict:
    """Return result ordered by template field order, so JSON export
    reads top-to-bottom like the template."""
    result = extraction.result or {}
    ordered: dict = {}
    for f in template.fields or []:
        key = f.get("key")
        if key:
            ordered[key] = result.get(key) or {
                "value": None, "confidence": 0.0,
            }
    return ordered


def _safe_filename(name: str) -> str:
    safe = "".join(
        c for c in name if c.isalnum() or c in "-_. "
    ).strip()
    return (safe or "extraction")[:100]


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None