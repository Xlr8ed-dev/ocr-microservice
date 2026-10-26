"""Heading detection.

Takes an ExtractedText (from document_extract.py) and produces a list of
HeadingHint objects — one per line that looks like a heading.

This is a heuristic layer. It uses whatever signals are available per line:
  - text content (numbering, capitalization, keywords)
  - font size (PDF text, scanned)
  - bold flag (PDF text, DOCX)
  - bbox / indent (PDF text, scanned)
  - Word style name (DOCX: "Heading 1", "Heading 2", "Title", ...)

Output is HINTS, not gospel. The AI structuring step later either agrees
or overrides. When this module is unsure, it errs on the side of
"yes, could be a heading" and lets the AI prune.
"""

import logging
import re
import statistics
from dataclasses import dataclass

from app.services.document_extract import ExtractedText, Line

logger = logging.getLogger(__name__)


# =========================================================
# OUTPUT SHAPE
# =========================================================

@dataclass
class HeadingHint:
    """A line that looks like a heading."""
    text: str
    page: int
    level: int  # 1..6
    confidence: float  # 0.0..1.0
    source: str  # which signal fired
    line_index: int  # index into ExtractedText.lines


# =========================================================
# PUBLIC ENTRY POINT
# =========================================================

def detect_headings(extracted: ExtractedText) -> list[HeadingHint]:
    """Detect headings in an extracted document.

    Returns hints sorted by (page, line_index). Levels are kept as
    the numbering-depth or style suggests — we do NOT renormalize,
    because a "1.1.1 Details" line means "third level" even if the
    parent headings aren't present in the file.
    """
    lines = extracted.lines
    if not lines:
        return []

    body_size = _estimate_body_font_size(lines)
    indent_floor = _estimate_indent_floor(lines)

    hints: list[HeadingHint] = []
    for idx, line in enumerate(lines):
        hint = _classify_line(idx, line, body_size, indent_floor)
        if hint is not None:
            hints.append(hint)

    logger.info(
        "detect_headings: %d hints from %d lines (body_size=%s)",
        len(hints), len(lines),
        f"{body_size:.1f}" if body_size else "n/a",
    )
    return hints


# =========================================================
# CLASSIFICATION — one line at a time
# =========================================================

def _classify_line(
        idx: int,
        line: Line,
        body_size: float | None,
        indent_floor: float | None,
) -> HeadingHint | None:
    """Return a HeadingHint if this line looks like a heading, else None."""
    text = line.text.strip()
    if not text:
        return None

    # Too long to be a heading
    if len(text) > 200:
        return None

    # --- signal 1: explicit Word style (highest confidence) ---
    if line.style:
        style_lower = line.style.lower()
        if style_lower.startswith("heading"):
            level = _level_from_style(style_lower)
            return HeadingHint(
                text=text, page=line.page, level=level,
                confidence=0.95, source="style", line_index=idx,
            )
        if style_lower == "title":
            return HeadingHint(
                text=text, page=line.page, level=1,
                confidence=0.95, source="style", line_index=idx,
            )

    # --- signal 2: numbered pattern in the text ---
    numbered_level = _level_from_numbering(text)
    if numbered_level is not None and _looks_like_heading_text(text):
        # Slightly lower confidence if line is longish
        confidence = 0.85 if len(text) < 100 else 0.65
        return HeadingHint(
            text=text, page=line.page, level=numbered_level,
            confidence=confidence, source="regex_numbered", line_index=idx,
        )

    # --- signal 3: keyword patterns ---
    keyword_level = _level_from_keyword(text)
    if keyword_level is not None:
        return HeadingHint(
            text=text, page=line.page, level=keyword_level,
            confidence=0.8, source="regex_keyword", line_index=idx,
        )

    # --- signal 4: font size relative to body ---
    if body_size and line.size and body_size > 0:
        ratio = line.size / body_size
        if ratio >= 1.15 and len(text) < 120:
            if ratio >= 1.6:
                level, confidence = 1, 0.9
            elif ratio >= 1.3:
                level, confidence = 2, 0.8
            else:
                level, confidence = 3, 0.7
            return HeadingHint(
                text=text, page=line.page, level=level,
                confidence=confidence, source="font_size", line_index=idx,
            )

    # --- signal 5: bold + short + no trailing punctuation ---
    if (
            line.bold
            and len(text) < 100
            and not text.endswith((".", "!", "?", ":", ";"))
            and not text.islower()
    ):
        return HeadingHint(
            text=text, page=line.page, level=2,
            confidence=0.6, source="bold_short", line_index=idx,
        )

    # --- signal 6: ALL CAPS line, short, no trailing punctuation ---
    if (
            _is_mostly_caps(text)
            and len(text) < 80
            and not text.endswith((".", "!", "?"))
    ):
        return HeadingHint(
            text=text, page=line.page, level=2,
            confidence=0.55, source="all_caps", line_index=idx,
        )

    # --- signal 7: indented relative to body + short ---
    if (
            indent_floor is not None
            and line.bbox is not None
            and len(text) < 80
            and line.bbox[0] > indent_floor + 10
    ):
        return HeadingHint(
            text=text, page=line.page, level=3,
            confidence=0.5, source="indent", line_index=idx,
        )

    return None


# =========================================================
# REGEX HELPERS
# =========================================================

_RE_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")
_RE_ROMAN = re.compile(r"^([IVX]+)\.\s+\S")
_RE_KEYWORD = re.compile(
    r"^(chapter|section|article|part|annexure|annex|appendix|schedule|"
    r"clause|exhibit|attachment)\s+[A-Z0-9]+",
    re.IGNORECASE,
)


def _level_from_numbering(text: str) -> int | None:
    """Heading level from the numbering depth, or None."""
    m = _RE_NUMBERED.match(text)
    if m:
        depth = m.group(1).count(".") + 1
        return min(depth, 6)
    if _RE_ROMAN.match(text):
        return 1
    return None


def _level_from_keyword(text: str) -> int | None:
    if _RE_KEYWORD.match(text):
        return 1
    return None


def _level_from_style(style_lower: str) -> int:
    """'Heading 3' -> 3. 'Heading' without a number -> 2."""
    m = re.search(r"heading\s*(\d+)", style_lower)
    if m:
        return min(int(m.group(1)), 6)
    return 2


def _is_mostly_caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 3:
        return False
    upper_count = sum(1 for c in letters if c.isupper())
    return upper_count / len(letters) > 0.85


# =========================================================
# NUMBERED-LINE QUALITY CHECK (guards against list items)
# =========================================================

def _looks_like_heading_text(text: str) -> bool:
    """True if a numbered line reads like a heading, not a list item.

    Rules (either is sufficient):
      1. The line is ALL CAPS (or mostly).
      2. The line is in Title Case (every significant word starts
         with a capital).
      3. The line does NOT end with a period (list items often do).
    """
    stripped = text.strip()

    if _is_mostly_caps(stripped):
        return True

    if _is_title_case(stripped):
        return True

    # No trailing sentence-ending punctuation
    if not stripped.endswith((".", "!", "?", ";")):
        return True

    return False


def _is_title_case(text: str) -> bool:
    """True if every significant word (len > 3) starts with a capital letter.

    Numbers and short stop-words (of, and, the, in, for, etc.) are ignored.
    """
    words = re.findall(r"[A-Za-z]+", text)
    significant = [w for w in words if len(w) > 3]
    if len(significant) < 2:
        # Too few words to judge; treat as neutral → reject
        return False

    for word in significant:
        if not word[0].isupper():
            return False
    return True


# =========================================================
# STATISTICAL HELPERS
# =========================================================

def _estimate_body_font_size(lines: list[Line]) -> float | None:
    """Median font size among lines long enough to be body text."""
    long_sizes = [
        line.size for line in lines
        if line.size and len(line.text) > 60
    ]
    if len(long_sizes) >= 5:
        return statistics.median(long_sizes)

    all_sizes = [line.size for line in lines if line.size]
    if all_sizes:
        return statistics.median(all_sizes)
    return None


def _estimate_indent_floor(lines: list[Line]) -> float | None:
    """Leftmost x-coordinate among body lines."""
    lefts = [
        line.bbox[0] for line in lines
        if line.bbox and len(line.text) > 40
    ]
    if not lefts:
        return None
    return min(lefts)
