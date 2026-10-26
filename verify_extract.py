"""Verify extraction + heading detection + chunking.

Run:  python verify_extract.py
"""

from pathlib import Path

from app.services.document_extract import (
    DocumentExtractionError,
    _extract_docx,
    _extract_pdf,
    _extract_txt,
)
from app.services.heading_detect import detect_headings
from app.services.document_chunk import chunk_document


SAMPLES = Path("samples")


def run(name: str, fn, path: Path):
    print(f"\n=== {name} ===")
    if not path.exists():
        print(f"SKIPPED (file not found: {path})")
        return

    try:
        extracted = fn(str(path))
    except DocumentExtractionError as e:
        print(f"EXTRACT FAILED: {e}")
        return
    except Exception as e:
        print(f"UNEXPECTED ERROR: {type(e).__name__}: {e}")
        return

    print(f"Method:      {extracted.extraction_method}")
    print(f"Pages:       {extracted.page_count}")
    print(f"Lines:       {len(extracted.lines)}")
    print(f"Chars:       {len(extracted.text)}")

    hints = detect_headings(extracted)
    print(f"Headings:    {len(hints)}")

    chunks = chunk_document(extracted, hints)
    print(f"Chunks:      {len(chunks)}")
    for c in chunks:
        preview = c.text.replace("\n", " ")[:60]
        hctx = c.heading_context or "-"
        print(
            f"  [chunk {c.chunk_index + 1}/{c.chunk_total} "
            f"chars={len(c.text):5d} p{c.start_page}-{c.end_page} "
            f"head=\"{hctx[:30]}\"]"
        )
        print(f"     └─ {preview}...")


if __name__ == "__main__":
    run("TXT",  _extract_txt,  SAMPLES / "sample.txt")
    run("DOCX", _extract_docx, SAMPLES / "sample.docx")
    run("PDF",  _extract_pdf,  SAMPLES / "sample.pdf")
    run("TXT-SECTIONS", _extract_txt, SAMPLES / "sample_sections.txt")
    run("TXT-LIST",     _extract_txt, SAMPLES / "sample_list.txt")