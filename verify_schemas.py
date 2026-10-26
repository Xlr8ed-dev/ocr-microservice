from app.schemas import (
    DocumentOutput,
    HeadingBlock,
    ParagraphBlock,
    TableBlock,
    DocumentJobOut,
    ImageJobOut,
    ImageTypeListOut,
)


def test_round_trip():
    print("--- Test 1: build a document output ---")
    output = DocumentOutput(
        title="Test Tender",
        blocks=[
            HeadingBlock(level=1, text="1. Introduction", page=1),
            ParagraphBlock(text="This is a test.", page=1),
            TableBlock(
                columns=["Item", "Qty"],
                rows=[["Widget", "10"]],
                caption="Table 1",
                page=2,
            ),
        ],
    )
    print("Title:", output.title)
    print("Blocks:", len(output.blocks))
    for b in output.blocks:
        display = getattr(b, "text", None) or getattr(b, "caption", "")
        print(f"  - {b.type}: {display}")


def test_discriminated_union():
    print("\n--- Test 2: discriminated union parsing ---")
    raw = {
        "title": "X",
        "blocks": [
            {"type": "heading", "level": 1, "text": "A"},
            {"type": "paragraph", "text": "B"},
        ],
    }
    parsed = DocumentOutput.model_validate(raw)
    print("Parsed types:", [b.type for b in parsed.blocks])


def test_bad_block_rejected():
    print("\n--- Test 3: malformed block should be rejected ---")
    try:
        DocumentOutput.model_validate({"blocks": [{"type": "heading"}]})
        print("ERROR: should have raised")
    except Exception:
        print("Correctly rejected malformed block")


def test_schema_generation():
    print("\n--- Test 4: JSON schema generation ---")
    schemas = {
        "DocumentJobOut": DocumentJobOut.model_json_schema(),
        "ImageJobOut": ImageJobOut.model_json_schema(),
        "ImageTypeListOut": ImageTypeListOut.model_json_schema(),
    }
    for name, s in schemas.items():
        props = s.get("properties", {})
        print(f"{name}: {len(props)} fields")


if __name__ == "__main__":
    test_round_trip()
    test_discriminated_union()
    test_bad_block_rejected()
    test_schema_generation()
    print("\nAll schema checks passed.")