import pytest

from app.services.document_prompts import (
    DEFAULT_DOCUMENT_TYPE,
    DOCUMENT_TYPE_META,
    build_ai_payload,
    normalize_document_type,
)


EXPECTED_TYPES = {
    "generic",
    "tender",
    "srs",
    "specification",
    "report",
    "letter",
    "memo",
    "policy",
    "form",
    "proposal",
}


def test_all_requested_document_types_are_registered():
    assert set(DOCUMENT_TYPE_META) == EXPECTED_TYPES


def test_normalize_document_type_accepts_aliases():
    assert normalize_document_type(None) == DEFAULT_DOCUMENT_TYPE
    assert normalize_document_type("Tender Document") == "tender"
    assert normalize_document_type("tender-document") == "tender"
    assert normalize_document_type("specification_card") == "specification"
    assert normalize_document_type("SRS") == "srs"


def test_normalize_document_type_rejects_unknown():
    with pytest.raises(ValueError):
        normalize_document_type("unknown-type")


def test_payload_uses_type_specific_system_prompt():
    generic = build_ai_payload(
        chunk_index=0,
        chunk_total=1,
        start_page=1,
        end_page=1,
        heading_context=None,
        previous_last_block=None,
        chunk_text="text",
    )
    tender = build_ai_payload(
        chunk_index=0,
        chunk_total=1,
        start_page=1,
        end_page=1,
        heading_context=None,
        previous_last_block=None,
        chunk_text="text",
        document_type="tender",
    )

    assert "tender" in tender["messages"][0]["content"].lower()
    assert generic["messages"][0]["content"] != tender["messages"][0]["content"]
