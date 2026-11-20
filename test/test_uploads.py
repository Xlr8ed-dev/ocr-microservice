"""Presign request schema tests.

The FE integration hit two contract mismatches:
  * a single file object instead of a `files` array, and
  * `file_size` instead of `size_bytes`.
Both must be accepted, while the resulting model always uses the canonical
shape so the router never sees the legacy variants.
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.dependencies import CurrentUser, current_user
from app.main import app
from app.schemas.upload import FilePresignRequest, PresignRequest


def test_canonical_body():
    request = PresignRequest.model_validate(
        {
            "files": [
                {
                    "file_name": "tender.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": 245760,
                }
            ]
        }
    )

    assert request.files[0].file_name == "tender.pdf"
    assert request.files[0].size_bytes == 245760


def test_accepts_single_bare_file_object():
    """What the FE actually sent: no 'files' wrapper."""
    request = PresignRequest.model_validate(
        {
            "file_name": "JDPythonDeveloper (1).pdf",
            "content_type": "application/pdf",
            "file_size": 157835,
        }
    )

    assert len(request.files) == 1
    file = request.files[0]
    assert file.file_name == "JDPythonDeveloper (1).pdf"
    assert file.content_type == "application/pdf"
    assert file.size_bytes == 157835


def test_accepts_single_object_under_files_key():
    request = PresignRequest.model_validate(
        {
            "files": {
                "file_name": "scan.png",
                "content_type": "image/png",
                "size_bytes": 1024,
            }
        }
    )

    assert len(request.files) == 1
    assert request.files[0].file_name == "scan.png"


@pytest.mark.parametrize("alias", ["size_bytes", "file_size", "size"])
def test_all_size_aliases_are_accepted(alias):
    file = FilePresignRequest.model_validate(
        {"file_name": "a.pdf", "content_type": "application/pdf", alias: 10}
    )

    assert file.size_bytes == 10


def test_missing_size_is_still_rejected():
    with pytest.raises(ValidationError):
        FilePresignRequest.model_validate(
            {"file_name": "a.pdf", "content_type": "application/pdf"}
        )


def test_zero_and_negative_size_are_rejected():
    for size in (0, -1):
        with pytest.raises(ValidationError):
            FilePresignRequest.model_validate(
                {
                    "file_name": "a.pdf",
                    "content_type": "application/pdf",
                    "file_size": size,
                }
            )


def test_empty_files_list_is_rejected():
    with pytest.raises(ValidationError):
        PresignRequest.model_validate({"files": []})


def test_more_than_thirty_files_is_rejected():
    files = [
        {"file_name": f"{i}.pdf", "content_type": "application/pdf", "size_bytes": 1}
        for i in range(31)
    ]

    with pytest.raises(ValidationError):
        PresignRequest.model_validate({"files": files})


def test_mixed_aliases_in_one_batch():
    request = PresignRequest.model_validate(
        {
            "files": [
                {"file_name": "a.pdf", "content_type": "application/pdf", "file_size": 1},
                {"file_name": "b.pdf", "content_type": "application/pdf", "size": 2},
                {"file_name": "c.pdf", "content_type": "application/pdf", "size_bytes": 3},
            ]
        }
    )

    assert [f.size_bytes for f in request.files] == [1, 2, 3]


def test_presign_endpoint_accepts_the_fe_payload(monkeypatch):
    """End-to-end regression for the reported 422.

    The exact body the FE sent must produce a 200, not a validation error.
    Auth and S3 are replaced so the test only exercises body parsing.
    """
    app.dependency_overrides[current_user] = lambda: CurrentUser(
        id=1, role="ADMIN", admin_id=1, agent_id=None, company_name=None
    )
    monkeypatch.setattr(
        "app.routers.uploads.s3_service.generate_presigned_post",
        lambda **kwargs: (
            "https://bucket.s3.ap-south-1.amazonaws.com/",
            {"key": "ocr-uploads/1/file.pdf", "Content-Type": "application/pdf"},
            "ocr-uploads/1/file.pdf",
        ),
    )

    try:
        client = TestClient(app)
        response = client.post(
            "/uploads/presign",
            json={
                "file_name": "JDPythonDeveloper (1).pdf",
                "content_type": "application/pdf",
                "file_size": 157835,
            },
        )
    finally:
        app.dependency_overrides.pop(current_user, None)

    assert response.status_code == 200, response.text
    upload = response.json()["uploads"][0]
    assert upload["file_name"] == "JDPythonDeveloper (1).pdf"
    assert upload["file_url"].endswith("ocr-uploads/1/file.pdf")
