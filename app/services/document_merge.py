"""Merge per-chunk block lists into a single output.

Because chunks overlap (the tail of chunk N is replayed at the head of
chunk N+1), some blocks appear twice. We deduplicate by exact text match
on headings and by prefix match on paragraphs.

We also decide the document title:
  - If any chunk returned a title, we take the first one.
  - Otherwise, if the first block is a level-1 heading, we use that as
    the title AND keep it as a heading block.
"""

import logging

from app.services.document_structure import ChunkResult

logger = logging.getLogger(__name__)


# =========================================================
# PUBLIC ENTRY POINT
# =========================================================

def merge_chunk_results(results: list[ChunkResult]) -> dict:
    """Merge chunk results into one final output dict.

    Returns:
        {
          "title": str | None,
          "blocks": [ ... ],
          "metadata": { chunk_count: int },
        }
    """
    if not results:
        return {"title": None, "blocks": [], "metadata": {"chunk_count": 0}}

    # Sort by chunk index to be safe
    results = sorted(results, key=lambda r: r.chunk_index)

    merged_blocks: list[dict] = []
    title: str | None = None

    # Track last block's dedup key so we can detect overlap duplicates
    last_key: tuple[str, str] | None = None

    for result in results:
        # First non-None title wins
        if title is None and result.title:
            title = result.title.strip() or None

        for block in result.blocks:
            key = _dedup_key(block)
            if key is not None and key == last_key:
                # Duplicate from overlap — skip
                logger.debug("merge: dropping duplicate block %s", key)
                continue
            merged_blocks.append(block)
            last_key = key

    # If no explicit title, and the very first block is a level-1 heading,
    # treat it as the title (but keep the block so the FE still renders it)
    if not title:
        first_heading = _find_first_heading(merged_blocks)
        if first_heading:
            title = first_heading.get("text", "").strip() or None

    return {
        "title": title,
        "blocks": merged_blocks,
        "metadata": {"chunk_count": len(results)},
    }


# =========================================================
# HELPERS
# =========================================================

def _dedup_key(block: dict) -> tuple[str, str] | None:
    """Return a key we can compare for duplicate detection.

    Headings: (type, text). Two identical heading blocks in a row mean
    overlap duplication.

    Paragraphs: (type, first 80 chars) — reduces false positives from
    paraphrasing by the model between chunks.
    """
    if not isinstance(block, dict):
        return None

    btype = block.get("type")
    if btype == "heading":
        text = (block.get("text") or "").strip()
        return ("heading", text) if text else None
    if btype == "paragraph":
        text = (block.get("text") or "").strip()
        return ("paragraph", text[:80]) if text else None
    if btype == "list":
        items = block.get("items") or []
        first = str(items[0])[:60] if items else ""
        return ("list", first) if first else None
    if btype == "table":
        cols = block.get("columns") or []
        key = ",".join(str(c) for c in cols)[:60]
        return ("table", key) if key else None
    if btype == "page_break":
        return ("page_break", str(block.get("page")))
    return None


def _find_first_heading(blocks: list[dict]) -> dict | None:
    for b in blocks[:3]:  # only look at the first few
        if isinstance(b, dict) and b.get("type") == "heading":
            return b
    return None
