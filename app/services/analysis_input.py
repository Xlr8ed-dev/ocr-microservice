"""Build AI input digests from OCR output.

For documents, we don't send the raw blocks JSON — we render them as a
compact text form (headings + paragraphs + tables) which is smaller and
reads better to the model. If the digest exceeds a hard cap, we sample:
first ~60% + last ~20% + all headings, in that order.
"""

import json
import logging

logger = logging.getLogger(__name__)

# =========================================================
# CONSTANTS
# =========================================================

# Hard cap on digest size. 32000 chars ≈ 8000 tokens. Well within any
# model we use, leaves headroom for the summary itself.
MAX_DIGEST_CHARS = 32_000

# When sampling, proportions of the cap to allocate.
SAMPLE_HEAD_CHARS = int(MAX_DIGEST_CHARS * 0.60)  # 19_200
SAMPLE_TAIL_CHARS = int(MAX_DIGEST_CHARS * 0.20)  # 6_400


# Remaining 20% (~6_400) reserved for headings that appear anywhere.


# =========================================================
# DOCUMENT DIGEST
# =========================================================

def blocks_to_digest(output: dict) -> str:
    """Convert `output.blocks[]` into a compact text digest.

    Preserves structure lightly: headings get their number/caps, paragraphs
    keep their text, tables stay as pipe-separated rows, page breaks become
    section separators. No JSON overhead.
    """
    blocks = output.get("blocks") or []
    if not blocks:
        return ""

    full = _render_blocks(blocks)

    if len(full) <= MAX_DIGEST_CHARS:
        return full

    logger.info(
        "analysis_input: digest over cap (%d > %d), sampling",
        len(full), MAX_DIGEST_CHARS,
    )
    return _sample_digest(blocks)


def _render_blocks(blocks: list[dict]) -> str:
    """Full render, no truncation. Used when under cap and as the base
    for sampling."""
    parts: list[str] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        text = _render_block(b)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _render_block(b: dict) -> str:
    t = b.get("type")

    if t == "heading":
        level = b.get("level") or 1
        prefix = "#" * max(1, min(level, 6))
        return f"{prefix} {b.get('text', '').strip()}"

    if t == "paragraph":
        return b.get("text", "").strip()

    if t == "list":
        marker = "1." if b.get("ordered") else "-"
        items = b.get("items") or []
        return "\n".join(f"{marker} {str(i).strip()}" for i in items if i)

    if t == "table":
        cols = b.get("columns") or []
        rows = b.get("rows") or []
        lines: list[str] = []
        if cols:
            lines.append("| " + " | ".join(str(c) for c in cols) + " |")
            lines.append("| " + " | ".join("---" for _ in cols) + " |")
        for row in rows:
            lines.append("| " + " | ".join(str(c) for c in row) + " |")
        if b.get("caption"):
            lines.append(f"[{b['caption']}]")
        return "\n".join(lines)

    if t == "page_break":
        return "\n---\n"

    if t == "image":
        return f"[image on page {b.get('page', '?')}]"

    return ""


def _sample_digest(blocks: list[dict]) -> str:
    """Sample the blocks when the full digest exceeds the cap.

    Layout of the sampled digest:
      1. HEAD:    first SAMPLE_HEAD_CHARS worth of rendered blocks
      2. HEADINGS: all headings NOT already in HEAD or TAIL
      3. TAIL:    last SAMPLE_TAIL_CHARS worth of rendered blocks

    Rationale: head captures purpose/introduction, headings capture the
    outline, tail captures conclusions/deadlines. Middle body text is
    usually the least important for both summarization and classification.
    """
    rendered = [(_render_block(b), b) for b in blocks if isinstance(b, dict)]
    rendered = [(t, b) for t, b in rendered if t]

    if not rendered:
        return ""

    # --- split into head and tail ---
    head_parts: list[str] = []
    head_len = 0
    tail_parts: list[str] = []
    tail_len = 0

    # Greedily pick from the front until HEAD is full
    head_end_idx = 0
    for i, (text, _b) in enumerate(rendered):
        if head_len + len(text) + 2 > SAMPLE_HEAD_CHARS:
            break
        head_parts.append(text)
        head_len += len(text) + 2
        head_end_idx = i + 1

    # Greedily pick from the back until TAIL is full
    tail_start_idx = len(rendered)
    for i in range(len(rendered) - 1, head_end_idx - 1, -1):
        text, _b = rendered[i]
        if tail_len + len(text) + 2 > SAMPLE_TAIL_CHARS:
            break
        tail_parts.insert(0, text)
        tail_len += len(text) + 2
        tail_start_idx = i

    # --- collect headings not already in head or tail ---
    heading_parts: list[str] = []
    for i in range(head_end_idx, tail_start_idx):
        text, b = rendered[i]
        if b.get("type") == "heading":
            heading_parts.append(text)

    # --- assemble with clear markers so the model knows we elided ---
    parts: list[str] = []
    if head_parts:
        parts.append("\n\n".join(head_parts))
    if heading_parts:
        parts.append(
            "[... sections omitted; headings of the omitted portion follow ...]\n\n"
            + "\n".join(heading_parts)
        )
    if tail_parts:
        parts.append(
            "[... end of document ...]\n\n" + "\n\n".join(tail_parts)
        )

    return "\n\n".join(parts)


# =========================================================
# IMAGE DIGEST
# =========================================================

def image_output_to_digest(output: dict | None) -> str:
    """Render image OCR output as compact JSON text.

    Images have small, structured output already — no need for fancy
    rendering. Just ensure it's readable and bounded.
    """
    if not output:
        return "{}"

    text = json.dumps(output, ensure_ascii=False, indent=2)
    if len(text) > MAX_DIGEST_CHARS:
        text = text[:MAX_DIGEST_CHARS] + "\n... [truncated]"
    return text
