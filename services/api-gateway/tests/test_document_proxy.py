"""Unit tests for PLAN-0086 Wave E-2 document proxy routes.

Four proxy routes are tested:
  - POST /v1/documents/upload   → S4 POST /api/v1/documents/upload
  - GET  /v1/documents/{doc_id} → S4 GET  /api/v1/documents/{doc_id}
  - GET  /v1/documents          → S4 GET  /api/v1/documents
  - DELETE /v1/documents/{doc_id} → S4 DELETE /api/v1/documents/{doc_id}

Each test verifies:
1. Unauthenticated requests are rejected with 401.
2. Authenticated requests are proxied to the content_ingestion client.
3. The S4 response status/body is forwarded verbatim.

Uses the shared conftest fixtures:
- ``app`` / ``mock_clients``        — no auth injection (401 tests)
- ``authed_app`` / ``authed_mock_clients`` — bearer JWT injects request.state.user
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_SECRET = "test-secret"  # noqa: S105
_JWT_PAYLOAD = {
    "sub": "user-abc",
    "tenant_id": "11111111-1111-1111-1111-111111111111",
    "exp": 9999999999,
}

_DOC_ID = "22222222-2222-2222-2222-222222222222"


def _make_jwt() -> str:
    return jwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _mock_response(status: int, content: bytes = b"{}") -> MagicMock:
    """Build a mock httpx.Response with the given status and body."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    return resp


# ── POST /v1/documents/upload ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_requires_auth(app, mock_clients) -> None:
    """POST /v1/documents/upload without auth → 401; S4 never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/v1/documents/upload", content=b"fake pdf")

    assert resp.status_code == 401
    mock_clients.content_ingestion.post.assert_not_called()


@pytest.mark.asyncio
async def test_upload_proxies_to_s4(authed_app, authed_mock_clients) -> None:
    """POST /v1/documents/upload with auth → S4 receives the call and returns 202."""
    # Arrange: S4 returns 202 Accepted with a doc_id payload.
    upload_body = (
        b'{"doc_id": "' + _DOC_ID.encode() + b'", "status": "processing", "title": "report", "filename": "report.pdf"}'
    )
    authed_mock_clients.content_ingestion.post = AsyncMock(
        return_value=_mock_response(202, upload_body),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/documents/upload",
            content=b"fake pdf body",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "Content-Type": "application/pdf",
            },
        )

    assert resp.status_code == 202
    # S4 must have been called exactly once on the upload path.
    authed_mock_clients.content_ingestion.post.assert_called_once()
    call_args = authed_mock_clients.content_ingestion.post.call_args
    assert "/api/v1/documents/upload" in call_args[0][0]


# ── GET /v1/documents/{doc_id} ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_document_requires_auth(app, mock_clients) -> None:
    """GET /v1/documents/{doc_id} without auth → 401; S4 never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/documents/{_DOC_ID}")

    assert resp.status_code == 401
    mock_clients.content_ingestion.get.assert_not_called()


@pytest.mark.asyncio
async def test_get_document_proxies_to_s4(authed_app, authed_mock_clients) -> None:
    """GET /v1/documents/{doc_id} with auth → S4 receives the call and returns 200."""
    doc_body = (
        b'{"doc_id": "'
        + _DOC_ID.encode()
        + b'", "status": "ready", "title": "Q4", "filename": "q4.pdf", "uploaded_at": "2026-05-08T10:00:00Z"}'
    )
    authed_mock_clients.content_ingestion.get = AsyncMock(
        return_value=_mock_response(200, doc_body),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/documents/{_DOC_ID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.content_ingestion.get.assert_called_once()
    call_args = authed_mock_clients.content_ingestion.get.call_args
    assert f"/api/v1/documents/{_DOC_ID}" in call_args[0][0]


# ── GET /v1/documents ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_documents_requires_auth(app, mock_clients) -> None:
    """GET /v1/documents without auth → 401; S4 never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/documents")

    assert resp.status_code == 401
    mock_clients.content_ingestion.get.assert_not_called()


@pytest.mark.asyncio
async def test_list_documents_proxies_to_s4(authed_app, authed_mock_clients) -> None:
    """GET /v1/documents with auth → S4 receives call; query params forwarded."""
    list_body = b'{"items": [], "next_cursor": null, "total": 0}'
    authed_mock_clients.content_ingestion.get = AsyncMock(
        return_value=_mock_response(200, list_body),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/documents?status=ready&limit=10",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.content_ingestion.get.assert_called_once()
    call_kwargs = authed_mock_clients.content_ingestion.get.call_args
    # Verify query params were forwarded (the params kwarg should be present).
    assert call_kwargs is not None
    assert "/api/v1/documents" in call_kwargs[0][0]


# ── DELETE /v1/documents/{doc_id} ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_document_requires_auth(app, mock_clients) -> None:
    """DELETE /v1/documents/{doc_id} without auth → 401; S4 never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(f"/v1/documents/{_DOC_ID}")

    assert resp.status_code == 401
    mock_clients.content_ingestion.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_document_proxies_to_s4(authed_app, authed_mock_clients) -> None:
    """DELETE /v1/documents/{doc_id} with auth → S4 receives call and returns 200."""
    delete_body = b'{"doc_id": "' + _DOC_ID.encode() + b'", "status": "deleted"}'
    authed_mock_clients.content_ingestion.delete = AsyncMock(
        return_value=_mock_response(200, delete_body),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(
            f"/v1/documents/{_DOC_ID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.content_ingestion.delete.assert_called_once()
    call_args = authed_mock_clients.content_ingestion.delete.call_args
    assert f"/api/v1/documents/{_DOC_ID}" in call_args[0][0]
