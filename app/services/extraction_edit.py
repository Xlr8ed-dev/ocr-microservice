"""Edit logic for extraction results.

Applies field edits to an extraction's `result` JSONB, recomputes
min_confidence over untouched required fields, and decides whether
the extraction is now fully resolved.
"""

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUser
from app.models import Extraction, ExtractionStatus, Template
from app.schemas.extraction import ExtractionFieldEdit

logger = logging.getLogger(__name__)

# =========================================================
# CONSTANTS
# =========================================================

REVIEW_THRESHOLD = 0.7


# =========================================================
# PUBLIC ENTRY POINT
# =========================================================

async def apply_field_edits(
        db: AsyncSession,
        user: CurrentUser,
        extraction: Extraction,
        edits: list[ExtractionFieldEdit],
) -> Extraction:
    """Apply field edits to an extraction. Mutates and returns the row.

    Preconditions (checked by the caller):
      - extraction.status in {COMPLETED, NEEDS_REVIEW}
      - extraction.result is not None

    Raises HTTPException(400) on unknown field keys.
    """
    # --- load template to know which keys are valid ------------------
    template = await db.get(Template, extraction.template_id)
    if not template:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Template {extraction.template_id} is missing from the catalog.",
        )

    valid_keys = {f["key"] for f in (template.fields or []) if "key" in f}

    # --- validate every key in the request ---------------------------
    unknown = [e.key for e in edits if e.key not in valid_keys]
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown field key(s): {unknown}. "
            f"Valid keys: {sorted(valid_keys)}",
        )

    # --- apply edits -------------------------------------------------
    result = dict(extraction.result or {})
    now = datetime.now(timezone.utc)

    for edit in edits:
        entry = result.get(edit.key) or {
            "value": None,
            "confidence": 0.0,
        }
        entry = dict(entry)
        entry["value"] = edit.value
        entry["edited"] = True
        entry["edited_by"] = user.id
        entry["edited_at"] = now
        result[edit.key] = entry

    extraction.result = result

    # --- recompute review state --------------------------------------
    extraction.review_needed = _recompute_review_needed(
        result=result,
        template_fields=template.fields or [],
    )
    extraction.min_confidence = _recompute_min_confidence(
        result=result,
        template_fields=template.fields or [],
    )

    # Status transition: needs_review → completed when the last
    # low-confidence un-edited required field is now edited.
    if (
            extraction.status == ExtractionStatus.NEEDS_REVIEW
            and not extraction.review_needed
    ):
        extraction.status = ExtractionStatus.COMPLETED

    await db.flush()
    logger.info(
        "extraction edit id=%s fields=%s review_needed=%s",
        extraction.id, [e.key for e in edits], extraction.review_needed,
    )
    return extraction


# =========================================================
# HELPERS
# =========================================================

def _recompute_review_needed(
        *,
        result: dict,
        template_fields: list[dict],
) -> bool:
    """True if any REQUIRED field is BOTH un-edited AND below threshold.

    Fields the user has verified (`edited=True`) never force review,
    even if their stored confidence is low — the human check supersedes
    the AI confidence.
    """
    for f in template_fields:
        if not f.get("required"):
            continue
        entry = result.get(f["key"])
        if not isinstance(entry, dict):
            return True  # required field missing entirely
        if entry.get("edited"):
            continue  # human verified this field
        if float(entry.get("confidence", 0.0)) < REVIEW_THRESHOLD:
            return True

    return False


def _recompute_min_confidence(
        *,
        result: dict,
        template_fields: list[dict],
) -> float:
    """Min confidence across required fields, treating edited fields
    as 1.0 (human-verified)."""
    values: list[float] = []
    for f in template_fields:
        if not f.get("required"):
            continue
        entry = result.get(f["key"]) or {}
        if entry.get("edited"):
            values.append(1.0)
        else:
            values.append(float(entry.get("confidence", 0.0)))

    if not values:
        return 0.0
    return min(values)
