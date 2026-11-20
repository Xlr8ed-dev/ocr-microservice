"""Unified OCR read API tests.

The FE's "All OCR" screen needs one list across documents and images, and one
detail lookup by id alone. These tests cover the merge/filter logic and the two
routes' wiring, without a real database.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.database import get_db
from app.dependencies import CurrentUser, current_user
from app.main import app
from app.models import (
    DocumentFileType,
    DocumentOCRStatus,
    ImageOCRStatus,
    ImageOCRType,
)
from app.routers.ocr import (
    document_list_item,
    image_list_item,
    merge_page,
    resolve_filters,
)
from app.schemas.ocr_jobs import OcrJobListItem

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def _document(
    *,
    job_id: str = "doc-1",
    created_at: datetime = NOW,
    status: DocumentOCRStatus = DocumentOCRStatus.COMPLETED,
):
    return SimpleNamespace(
        job_id=job_id,
        admin_id=1,
        user_id=1,
        source_url="https://bucket/doc.pdf",
        file_name="doc.pdf",
        file_type=DocumentFileType.PDF_TEXT,
        file_size_bytes=100,
        status=status,
        progress=100,
        page_count=2,
        chunk_count=1,
        output=None,
        error=None,
        requested_keys=None,
        requested_prompt=None,
        cost_estimate=None,
        ai_calls=1,
        ai_tokens_in=10,
        ai_tokens_out=5,
        created_at=created_at,
        started_at=created_at,
        completed_at=created_at,
    )


def _image(
    *,
    job_id: str = "img-1",
    created_at: datetime = NOW,
    status: ImageOCRStatus = ImageOCRStatus.COMPLETED,
):

    return SimpleNamespace(
        job_id=job_id,
        admin_id=1,
        user_id=1,
        source_url=(
            "https://bucket/ocr-uploads/1/card.jpg"
            "?X-Amz-Signature=abc"
        ),
        image_type=ImageOCRType.VISITING_CARD,
        status=status,
        output={"structured_output": {"name": "Omkar"}},
        error=None,
        requested_keys=None,
        requested_prompt=None,
        cost_estimate=1.0,
        ai_calls=1,
        ai_tokens_in=10,
        ai_tokens_out=5,
        created_at=created_at,
        started_at=created_at,
        completed_at=created_at,
    )


# ---------------------------------------------------------
# Filter resolution
# ---------------------------------------------------------

def test_no_filters_includes_both_families():
    assert resolve_filters(None, None) == (True, True, None, None)


def test_kind_narrows_to_one_family():
    assert resolve_filters("document", None) == (True, False, None, None)
    assert resolve_filters("image", None) == (False, True, None, None)


def test_unknown_kind_is_rejected():
    with pytest.raises(HTTPException) as excinfo:
        resolve_filters("video", None)

    assert excinfo.value.status_code == 400


def test_shared_status_applies_to_both_families():
    include_docs, include_images, doc_status, img_status = resolve_filters(
        None, "completed"
    )

    assert include_docs and include_images
    assert doc_status is DocumentOCRStatus.COMPLETED
    assert img_status is ImageOCRStatus.COMPLETED


def test_document_only_status_excludes_images():
    include_docs, include_images, doc_status, img_status = resolve_filters(
        None, "structuring"
    )

    assert include_docs is True
    assert include_images is False
    assert doc_status is DocumentOCRStatus.STRUCTURING
    assert img_status is None


def test_image_only_status_excludes_documents():
    include_docs, include_images, doc_status, img_status = resolve_filters(
        None, "processing"
    )

    assert include_docs is False
    assert include_images is True
    assert doc_status is None
    assert img_status is ImageOCRStatus.PROCESSING


def test_status_incompatible_with_kind_is_rejected():
    with pytest.raises(HTTPException):
        resolve_filters("image", "structuring")


def test_unknown_status_is_rejected():
    with pytest.raises(HTTPException):
        resolve_filters(None, "exploded")


# ---------------------------------------------------------
# Row mapping and merge
# ---------------------------------------------------------

def test_document_list_item_is_light_and_typed():
    item = document_list_item(_document())

    assert isinstance(item, OcrJobListItem)
    assert item.kind == "document"
    assert item.file_name == "doc.pdf"
    assert item.file_type == "pdf_text"
    assert item.status == "completed"
    assert item.page_count == 2
    assert item.image_type is None


def test_image_list_item_derives_filename_from_url():
    item = image_list_item(_image())

    assert item.kind == "image"
    assert item.file_name == "card.jpg"
    assert item.image_type == "visiting_card"
    assert item.status == "completed"
    assert item.file_type is None


def test_merge_orders_across_families_and_paginates_globally():
    documents = [
        _document(job_id="doc-new", created_at=NOW),
        _document(job_id="doc-old", created_at=NOW - timedelta(minutes=10)),
    ]
    images = [
        _image(job_id="img-mid", created_at=NOW - timedelta(minutes=5)),
        _image(job_id="img-oldest", created_at=NOW - timedelta(minutes=20)),
    ]

    first_page = merge_page(documents, images, offset=0, limit=2)
    second_page = merge_page(documents, images, offset=2, limit=2)

    assert [item.id for item in first_page] == ["doc-new", "img-mid"]
    assert [item.id for item in second_page] == ["doc-old", "img-oldest"]
    assert {item.kind for item in first_page} == {"document", "image"}


# ---------------------------------------------------------
# Routes
# ---------------------------------------------------------

class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDB:
    """Feeds queued scalars() results in call order."""

    def __init__(self, *, scalars=None, scalars_rows=None):
        self._scalars = list(scalars or [])
        self._scalars_rows = list(scalars_rows or [])

    async def scalar(self, statement):
        return self._scalars.pop(0)

    async def scalars(self, statement):
        return _FakeResult(self._scalars_rows.pop(0))


@pytest.fixture
def client():
    app.dependency_overrides[current_user] = lambda: CurrentUser(
        id=1, role="ADMIN", admin_id=1, agent_id=None, company_name=None
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_db, None)


def test_list_route_merges_and_paginates(client):
    db = _FakeDB(
        scalars=[2, 2],  # document count, image count
        scalars_rows=[
            [
                _document(job_id="doc-new", created_at=NOW),
                _document(job_id="doc-old", created_at=NOW - timedelta(minutes=10)),
            ],
            [
                _image(job_id="img-mid", created_at=NOW - timedelta(minutes=5)),
                _image(job_id="img-oldest", created_at=NOW - timedelta(minutes=20)),
            ],
        ],
    )
    app.dependency_overrides[get_db] = lambda: db

    response = client.get("/ocr/jobs?page=1&items=2")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["id"] for item in body["data"]] == ["doc-new", "img-mid"]
    assert body["pagination"]["total_entries"] == 4


def test_detail_route_returns_document_shape(client):
    db = _FakeDB(scalars=[_document()])
    app.dependency_overrides[get_db] = lambda: db

    response = client.get("/ocr/jobs/doc-1")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job_id"] == "doc-1"
    assert body["file_name"] == "doc.pdf"
    assert "image_type" not in body


def test_detail_route_falls_back_to_image_shape(client):
    db = _FakeDB(scalars=[None, _image()])
    app.dependency_overrides[get_db] = lambda: db

    response = client.get("/ocr/jobs/img-1")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job_id"] == "img-1"
    assert body["image_type"] == "visiting_card"
    assert "file_name" not in body


def test_detail_route_returns_404_for_unknown_id(client):
    db = _FakeDB(scalars=[None, None])
    app.dependency_overrides[get_db] = lambda: db

    response = client.get("/ocr/jobs/nope")

    assert response.status_code == 404


def test_ocr_routes_require_authentication():
    # No dependency override: the real auth dependency must reject the call
    # before any database work happens.
    response = TestClient(app).get("/ocr/jobs")

    assert response.status_code == 401
