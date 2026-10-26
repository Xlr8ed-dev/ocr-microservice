"""Verify the merge logic with synthetic chunks.

Run:  python verify_merge.py
"""

from app.services.document_structure import ChunkResult
from app.services.document_merge import merge_chunk_results


def test_heading_dedup():
    print("--- Test 1: overlap dedup on headings ---")
    r1 = ChunkResult(
        chunk_index=0,
        blocks=[
            {"type": "heading", "level": 1, "text": "1. Introduction", "page": 1},
            {"type": "paragraph", "text": "The purpose of this tender is to invite suppliers.",
             "page": 1},
            {"type": "heading", "level": 2, "text": "1.1 Scope", "page": 1},
        ],
        title="Tender for Supply of Industrial Equipment",
    )
    r2 = ChunkResult(
        chunk_index=1,
        blocks=[
            # This heading appears at the tail of chunk 1's overlap
            {"type": "heading", "level": 2, "text": "1.1 Scope", "page": 1},
            {"type": "paragraph", "text": "The scope includes supply, installation.", "page": 1},
            {"type": "heading", "level": 1, "text": "2. Eligibility", "page": 1},
        ],
    )
    merged = merge_chunk_results([r1, r2])
    print("Title:", merged["title"])
    print("Blocks:", len(merged["blocks"]))
    for b in merged["blocks"]:
        print(f"  [{b['type']}] {b.get('text', '')[:60]}")
    assert len(merged["blocks"]) == 5, f"expected 5, got {len(merged['blocks'])}"
    print("PASS: duplicate heading removed")


def test_single_chunk():
    print("\n--- Test 2: single chunk ---")
    r = ChunkResult(
        chunk_index=0,
        blocks=[
            {"type": "heading", "level": 1, "text": "Introduction", "page": 1},
            {"type": "paragraph", "text": "Some body text.", "page": 1},
        ],
    )
    merged = merge_chunk_results([r])
    print("Title:", merged["title"])
    print("Blocks:", len(merged["blocks"]))
    assert merged["title"] == "Introduction"
    assert len(merged["blocks"]) == 2
    print("PASS: title inferred from first heading")


def test_no_title_no_heading():
    print("\n--- Test 3: no title, no heading ---")
    r = ChunkResult(
        chunk_index=0,
        blocks=[
            {"type": "paragraph", "text": "Just body text.", "page": 1},
        ],
    )
    merged = merge_chunk_results([r])
    print("Title:", merged["title"])
    assert merged["title"] is None
    print("PASS")


if __name__ == "__main__":
    test_heading_dedup()
    test_single_chunk()
    test_no_title_no_heading()
    print("\nAll merge tests passed.")