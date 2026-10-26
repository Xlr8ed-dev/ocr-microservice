"""Convert document output blocks into downloadable formats."""

from app.schemas.document import DocumentOutput


# =========================================================
# MARKDOWN
# =========================================================

def render_blocks_as_markdown(output: dict) -> str:
    doc = _parse(output)
    lines: list[str] = []

    if doc.title:
        lines.append(f"# {doc.title}")
        lines.append("")

    for block in doc.blocks:
        lines.append(_block_to_md(block))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _block_to_md(block) -> str:
    t = block.type

    if t == "heading":
        prefix = "#" * max(1, min(block.level, 6))
        return f"{prefix} {block.text}"

    if t == "paragraph":
        return block.text

    if t == "list":
        marker = "1." if block.ordered else "-"
        return "\n".join(f"{marker} {item}" for item in block.items)

    if t == "table":
        if not block.columns:
            return ""
        header = "| " + " | ".join(block.columns) + " |"
        sep = "| " + " | ".join("---" for _ in block.columns) + " |"
        rows = [
            "| " + " | ".join(str(c) for c in row) + " |"
            for row in block.rows
        ]
        out = [header, sep, *rows]
        if block.caption:
            out.append("")
            out.append(f"*{block.caption}*")
        return "\n".join(out)

    if t == "page_break":
        return "\n---\n"

    if t == "image":
        return f"_[Image on page {block.page}: {block.description or 'no description'}]_"

    return ""


# =========================================================
# PLAIN TEXT
# =========================================================

def render_blocks_as_text(output: dict) -> str:
    doc = _parse(output)
    lines: list[str] = []

    if doc.title:
        lines.append(doc.title.upper())
        lines.append("=" * len(doc.title))
        lines.append("")

    for block in doc.blocks:
        lines.append(_block_to_text(block))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _block_to_text(block) -> str:
    t = block.type

    if t == "heading":
        return block.text.upper()

    if t == "paragraph":
        return block.text

    if t == "list":
        marker = "1." if block.ordered else "-"
        return "\n".join(f"{marker} {item}" for item in block.items)

    if t == "table":
        # Tab-separated for readability
        rows: list[str] = []
        if block.columns:
            rows.append("\t".join(block.columns))
        for row in block.rows:
            rows.append("\t".join(str(c) for c in row))
        if block.caption:
            rows.append(f"[{block.caption}]")
        return "\n".join(rows)

    if t == "page_break":
        return "\n----- page break -----\n"

    if t == "image":
        return f"[Image on page {block.page}]"

    return ""


# =========================================================
# HELPERS
# =========================================================

def _parse(output: dict) -> DocumentOutput:
    """Validate + normalize. Falls back to an empty output on error."""
    try:
        return DocumentOutput.model_validate(output)
    except Exception:
        return DocumentOutput()
