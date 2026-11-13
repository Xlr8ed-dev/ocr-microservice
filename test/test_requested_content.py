from app.services.document_prompts import build_ai_payload
from app.services.requested_content import (
    build_requested_response_schema,
    merge_requested_outputs,
    normalize_requested_keys,
    sanitize_requested_output,
)


def test_normalize_requested_keys_trims_and_dedupes():
    assert normalize_requested_keys([" Invoice No ", "", "invoice no", "Total"]) == [
        "Invoice No",
        "Total",
    ]
    assert normalize_requested_keys([]) is None


def test_merge_requested_outputs_prefers_first_non_empty_value():
    merged = merge_requested_outputs(
        [
            {"keys": {"invoice_no": None, "total": 0}},
            {
                "keys": {"invoice_no": "INV-1", "total": 120},
                "prompt_result": "",
            },
            {"prompt_result": "answer"},
        ],
        keys=["invoice_no", "total"],
        prompt="What is the answer?",
    )

    assert merged == {
        "keys": {"invoice_no": "INV-1", "total": 0},
        "prompt_result": "answer",
    }


def test_sanitize_requested_output_keeps_requested_shape():
    assert sanitize_requested_output(
        {"keys": {"a": "1"}},
        keys=["a", "b"],
        prompt=None,
    ) == {"keys": {"a": "1", "b": None}}


def test_document_payload_has_no_requested_when_not_sent():
    payload = build_ai_payload(
        chunk_index=0,
        chunk_total=1,
        start_page=1,
        end_page=1,
        heading_context=None,
        previous_last_block=None,
        chunk_text="hello",
    )

    assert "requested" not in payload["response_schema"]["properties"]
    assert "USER-REQUESTED" not in payload["messages"][1]["content"]


def test_document_payload_injects_requested_keys_and_prompt():
    payload = build_ai_payload(
        chunk_index=0,
        chunk_total=1,
        start_page=1,
        end_page=1,
        heading_context=None,
        previous_last_block=None,
        chunk_text="hello",
        requested_keys=["invoice_no"],
        requested_prompt="Find the total.",
    )

    requested = payload["response_schema"]["properties"]["requested"]
    assert requested["properties"]["keys"]["properties"]["invoice_no"]
    assert requested["properties"]["prompt_result"]
    user_prompt = payload["messages"][1]["content"]
    assert '"invoice_no"' in user_prompt
    assert "Find the total." in user_prompt


def test_requested_response_schema_is_none_without_request():
    assert build_requested_response_schema(keys=None, prompt=None) is None
