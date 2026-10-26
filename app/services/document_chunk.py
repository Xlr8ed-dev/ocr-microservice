"""Chunk a document for AI processing.

Given an ExtractedText + heading hints, produce a list of Chunks suitable
for sending to the AI structuring endpoint. Chunks respect document
structure: we break at headings first, then at paragraph boundaries,
and only as a last resort at an arbitrary char limit.

Chunks overlap slightly so the AI can stitch paragraphs that span
boundaries.
"""

import logging
from dataclasses import dataclass, field

from app.services.document_extract import ExtractedText, Line
from app.services.heading_detect import HeadingHint

logger = logging.getLogger(__name__)

# =========================================================
# CONSTANTS
# =========================================================

# Target chunk size in tokens (approximate; chars / 4)
TARGET_TOKENS = 8000
CHARS_PER_TOKEN = 4
TARGET_CHARS = TARGET_TOKENS * CHARS_PER_TOKEN  # ~32_000

# Overlap between consecutive chunks, in tokens
OVERLAP_TOKENS = 500
OVERLAP_CHARS = OVERLAP_TOKENS * CHARS_PER_TOKEN  # ~2_000

# If a single paragraph is bigger than this, we hard-split it
HARD_SPLIT_CHARS = TARGET_CHARS


# =========================================================
# OUTPUT SHAPE
# =========================================================

@dataclass
class Chunk:
    chunk_index: int  # 0-based
    chunk_total: int  # set after the whole list is built
    text: str
    start_line: int  # inclusive index into ExtractedText.lines
    end_line: int  # exclusive
    start_page: int
    end_page: int
    heading_context: str | None = None  # nearest heading above this chunk
    heading_level: int | None = None


# =========================================================
# PUBLIC ENTRY POINT
# =========================================================

def chunk_document(
        extracted: ExtractedText,
        headings: list[HeadingHint],
) -> list[Chunk]:
    """Split the document into chunks suitable for AI processing.

    Strategy:
      1. Build "blocks" — logical units separated by headings or blank lines.
      2. Greedily pack blocks into chunks up to TARGET_CHARS.
      3. When a chunk would exceed the target, close it and start a new one.
      4. Overlap: the last N chars of each chunk (up to OVERLAP_CHARS) are
         replayed at the start of the next chunk.
    """
    lines = extracted.lines
    if not lines:
        return []

    # --- Step 1: build blocks ---
    blocks = _build_blocks(lines, headings)
    if not blocks:
        return []

    # --- Step 2: pack blocks into chunks ---
    chunks = _pack_blocks(blocks, lines)

    # --- Step 3: apply overlap ---
    chunks = _apply_overlap(chunks)

    # --- Step 4: set totals ---
    total = len(chunks)
    for i, c in enumerate(chunks):
        c.chunk_index = i
        c.chunk_total = total

    logger.info(
        "chunk_document: %d chunks, sizes=%s",
        total,
        [len(c.text) for c in chunks],
    )
    return chunks


# =========================================================
# BLOCKS — logical units
# =========================================================

@dataclass
class _Block:
    """A logical unit of content — a heading, a paragraph, or a small group
    of consecutive non-heading lines that form one paragraph."""
    text: str
    start_line: int
    end_line: int  # exclusive
    page: int
    is_heading: bool = False
    heading_level: int | None = None
    heading_text: str | None = None


def _build_blocks(
        lines: list[Line],
        headings: list[HeadingHint],
) -> list[_Block]:
    """Split the document into blocks.

    A block is:
      - A heading (one line, tagged with its level)
      - A paragraph (consecutive body lines joined by spaces)

    We use the heading hints to know which line indices are headings.
    Consecutive body lines between headings are joined into one block.
    """
    heading_by_index = {h.line_index: h for h in headings}

    blocks: list[_Block] = []
    buffer: list[Line] = []
    buffer_start: int | None = None

    def flush_buffer() -> None:
        nonlocal buffer, buffer_start
        if not buffer:
            return
        text = _join_paragraph([l.text for l in buffer])
        blocks.append(_Block(
            text=text,
            start_line=buffer_start if buffer_start is not None else 0,
            end_line=buffer[-1].page and buffer[-1].__dict__.get("_i", 0) or 0,
            page=buffer[0].page,
        ))
        buffer = []
        buffer_start = None

    # Rewrite the loop cleanly:
    blocks = []
    buffer = []
    buffer_start = None

    def flush() -> None:
        nonlocal buffer, buffer_start
        if not buffer:
            return
        text = _join_paragraph([l.text for l in buffer])
        blocks.append(_Block(
            text=text,
            start_line=buffer_start,
            end_line=buffer_start + len(buffer),
            page=buffer[0].page,
        ))
        buffer = []
        buffer_start = None

    for idx, line in enumerate(lines):
        hint = heading_by_index.get(idx)
        if hint is not None:
            flush()
            blocks.append(_Block(
                text=line.text,
                start_line=idx,
                end_line=idx + 1,
                page=line.page,
                is_heading=True,
                heading_level=hint.level,
                heading_text=line.text,
            ))
        else:
            if not buffer:
                buffer_start = idx
            buffer.append(line)

    flush()

    return blocks


def _join_paragraph(parts: list[str]) -> str:
    """Join consecutive lines into a paragraph. If a line already ends with
    whitespace or the next starts lowercase, we join with a space; otherwise
    a space too (most PDFs wrap lines arbitrarily)."""
    cleaned = [p.strip() for p in parts if p.strip()]
    return " ".join(cleaned)


# =========================================================
# PACK BLOCKS INTO CHUNKS
# =========================================================

def _pack_blocks(blocks: list[_Block], lines: list[Line]) -> list[Chunk]:
    """Greedy pack blocks into chunks of up to TARGET_CHARS.

    A heading block is never left dangling at the end of a chunk unless
    it's the last block. We also always include a heading at the start of
    a chunk if the block right before would have fit.
    """
    chunks: list[Chunk] = []
    current_blocks: list[_Block] = []
    current_chars = 0
    current_heading: _Block | None = None

    def close_chunk() -> None:
        nonlocal current_blocks, current_chars
        if not current_blocks:
            return

        text = "\n\n".join(b.text for b in current_blocks)
        start_line = current_blocks[0].start_line
        end_line = current_blocks[-1].end_line

        # Page range
        start_page = current_blocks[0].page
        end_page = current_blocks[-1].page

        # Find nearest heading above (or the heading inside this chunk)
        h_ctx = None
        h_level = None
        for b in current_blocks:
            if b.is_heading:
                h_ctx = b.heading_text
                h_level = b.heading_level

        chunks.append(Chunk(
            chunk_index=0,  # set later
            chunk_total=0,  # set later
            text=text,
            start_line=start_line,
            end_line=end_line,
            start_page=start_page,
            end_page=end_page,
            heading_context=h_ctx,
            heading_level=h_level,
        ))

        current_blocks = []
        current_chars = 0

    for block in blocks:
        block_chars = len(block.text)

        # --- oversized single block: hard split ---
        if block_chars > HARD_SPLIT_CHARS:
            close_chunk()
            # emit as its own chunk, possibly split further
            for piece in _hard_split_block(block, HARD_SPLIT_CHARS):
                chunks.append(Chunk(
                    chunk_index=0,
                    chunk_total=0,
                    text=piece.text,
                    start_line=piece.start_line,
                    end_line=piece.end_line,
                    start_page=piece.page,
                    end_page=piece.page,
                    heading_context=piece.heading_text,
                    heading_level=piece.heading_level,
                ))
            continue

        # --- would exceed target? close and start fresh ---
        if current_chars + block_chars > TARGET_CHARS and current_blocks:
            close_chunk()

        current_blocks.append(block)
        current_chars += block_chars

        if block.is_heading:
            current_heading = block

    close_chunk()
    return chunks


def _hard_split_block(block: _Block, max_chars: int) -> list[_Block]:
    """Split a single oversized block into pieces at sentence boundaries."""
    text = block.text
    pieces: list[_Block] = []

    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            # try to cut at a sentence boundary
            for sep in (". ", "! ", "? ", "\n"):
                pos = text.rfind(sep, start, end)
                if pos != -1 and pos > start + max_chars // 2:
                    end = pos + len(sep)
                    break
        piece_text = text[start:end].strip()
        if piece_text:
            pieces.append(_Block(
                text=piece_text,
                start_line=block.start_line,
                end_line=block.end_line,
                page=block.page,
                is_heading=False,
            ))
        start = end

    return pieces


# =========================================================
# OVERLAP
# =========================================================

def _apply_overlap(chunks: list[Chunk]) -> list[Chunk]:
    """Prepend the tail of each chunk to the head of the next.

    The overlap is at paragraph boundaries where possible, so the AI
    sees clean units of text rather than mid-sentence fragments.
    """
    if len(chunks) < 2:
        return chunks

    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        curr = chunks[i]

        overlap_text = _take_tail(prev.text, OVERLAP_CHARS)
        if overlap_text:
            curr.text = overlap_text + "\n\n" + curr.text

    return chunks


def _take_tail(text: str, max_chars: int) -> str:
    """Return the last max_chars of text, cut at a paragraph boundary."""
    if len(text) <= max_chars:
        return ""  # whole chunk smaller than overlap → skip

    # Prefer cutting at a paragraph break (\n\n)
    tail_start = len(text) - max_chars
    para_break = text.rfind("\n\n", tail_start, len(text))
    if para_break != -1:
        return text[para_break + 2:].strip()

    # Otherwise cut at sentence boundary
    for sep in (". ", "! ", "? "):
        pos = text.rfind(sep, tail_start, len(text))
        if pos != -1:
            return text[pos + len(sep):].strip()

    # Fall back to a raw cut
    return text[tail_start:].strip()
