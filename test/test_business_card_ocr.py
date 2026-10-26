import json
import tempfile

import pytest

from app.models import BusinessCardOCRRequest
from app.services.ai_service import build_ai_request_payload
from app.services import ocr_service


@pytest.mark.asyncio
async def test_process_card_image_forwards_prompt_and_context(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
        temp_file.write(b"test")
        image_path = temp_file.name

    async def fake_download_file(url: str) -> str:
        assert url == "https://example.com/card.jpg"
        return image_path

    captured = {}

    async def fake_process_image(
        *,
        image_path: str,
        prompt: str,
        txn_id: str,
        user_details: dict,
        package_details: dict,
        image_side: str | None = None,
    ) -> dict:
        captured["image_path"] = image_path
        captured["prompt"] = prompt
        captured["txn_id"] = txn_id
        captured["user_details"] = user_details
        captured["package_details"] = package_details
        captured["image_side"] = image_side
        return {
            "data": {
                "name": "Jane Doe",
                "emails": ["jane@example.com"],
            }
        }

    deleted = []

    def fake_delete_file(path: str) -> None:
        deleted.append(path)

    monkeypatch.setattr(ocr_service, "download_file", fake_download_file)
    monkeypatch.setattr(ocr_service, "process_image", fake_process_image)
    monkeypatch.setattr(ocr_service, "delete_file", fake_delete_file)

    result = await ocr_service.process_card_image(
        image_url="https://example.com/card.jpg",
        prompt="Extract business card data",
        txn_id="txn-123",
        user_details={"user_id": "u-1"},
        package_details={"package_name": "pro"},
        image_side="front",
    )

    assert captured["image_path"] == image_path
    assert captured["prompt"] == "Extract business card data"
    assert captured["txn_id"] == "txn-123"
    assert captured["user_details"] == {"user_id": "u-1"}
    assert captured["package_details"] == {"package_name": "pro"}
    assert captured["image_side"] == "front"
    assert result == {
        "name": "Jane Doe",
        "designation": "",
        "company": "",
        "emails": ["jane@example.com"],
        "phones": [],
        "address": [],
        "websites": [],
    }
    assert deleted == [image_path]


def test_business_card_prompt_is_manually_maintained():
    assert (
        ocr_service.get_business_card_prompt(
            {"settings": {"prompt": "Ignore package prompt"}}
        )
        == ocr_service.BUSINESS_CARD_OCR_PROMPT
    )


def test_build_ai_request_payload_serializes_context():
    payload = build_ai_request_payload(
        prompt="Extract card",
        txn_id="txn-1",
        user_details={"user_id": "u-1"},
        package_details={"package_name": "basic"},
        image_side="back",
    )

    assert payload["prompt"] == "Extract card"
    assert payload["txn_id"] == "txn-1"
    assert payload["image_side"] == "back"
    assert json.loads(payload["user_details"]) == {"user_id": "u-1"}
    assert json.loads(payload["package_details"]) == {"package_name": "basic"}


@pytest.mark.asyncio
async def test_business_card_endpoint_uses_sso_package_and_ai_prompt(monkeypatch):
    async def fake_get_user_package(user_id: str) -> dict:
        assert user_id == "user-9"
        return {
            "package_name": "pro",
            "settings": {"business_card_prompt": "Ignored package prompt"},
        }

    async def fake_process_card_image(**kwargs):
        if kwargs["image_side"] == "front":
            assert kwargs["prompt"] == ocr_service.BUSINESS_CARD_OCR_PROMPT
        return {
            "name": "Jane Doe",
            "designation": "CEO",
            "company": "Acme",
            "emails": ["jane@example.com"],
            "phones": ["123"],
            "address": [],
            "websites": [],
        }

    monkeypatch.setattr(ocr_service, "get_user_package", fake_get_user_package)
    monkeypatch.setattr(ocr_service, "process_card_image", fake_process_card_image)

    response = await ocr_service.process_business_card(
        BusinessCardOCRRequest(
            txn_id="txn-77",
            user_id="user-9",
            front_url="https://example.com/front.jpg",
            back_url="https://example.com/back.jpg",
        )
    )

    assert response.success is True
    assert response.txn_id == "txn-77"
    assert response.front_ocr is not None
    assert response.front_ocr.name == "Jane Doe"
    assert response.merged_ocr is not None
    assert response.merged_ocr.company == "Acme"
