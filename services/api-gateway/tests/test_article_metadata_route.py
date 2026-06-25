"""Tests for GET /v1/articles/{document_id} (backend-gaps wave 3, 2026-06-11).

WHY this route exists: relation-evidence ``doc_id`` values are content-store
(S5) pipeline articles, but the pre-existing ``GET /v1/documents/{doc_id}``
proxies S4 tenant uploads — every evidence doc_id 500'd, so the Intelligence
tab could not resolve article titles/urls. The new route unwraps a
single-element content-store ``POST /api/v1/documents/batch`` call.

Follows test_bq_quote_routes.py conventions (authed_app fixtures).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_SECRET = "test-secret"  # noqa: S105
_JWT_PAYLOAD = {"sub": "user-1", "tenant_id": "t-1", "exp": 9999999999}

_DOC_UUID = "019eb38c-665a-7663-97e2-f4ab7a2d6142"


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {jwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm='HS256')}"}


def _mock_http_response(status: int, content: bytes = b"{}") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    resp.text = content.decode()
    try:
        resp.json.return_value = json.loads(content)
    except json.JSONDecodeError:
        resp.json.side_effect = ValueError("invalid JSON")
    return resp


@pytest.mark.asyncio
async def test_article_metadata_requires_auth(authed_app) -> None:
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/articles/{_DOC_UUID}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_article_metadata_resolves_via_content_store_batch(authed_app, authed_mock_clients) -> None:
    """A pipeline doc_id resolves to {title, url, source, published_at, ...}."""
    cs_body = json.dumps(
        {
            "documents": [
                {
                    "doc_id": _DOC_UUID,
                    "title": "Apple unveils new chip",
                    "url": "https://news.example.com/apple-chip",
                    "published_at": "2026-06-09T12:00:00Z",
                    "source_name": "Example News",
                    "source_type": "rss",
                    "word_count": 640,
                }
            ]
        }
    ).encode()
    authed_mock_clients.content_store.post = AsyncMock(return_value=_mock_http_response(200, cs_body))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/articles/{_DOC_UUID}", headers=_auth_headers())

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "document_id": _DOC_UUID,
        "title": "Apple unveils new chip",
        "url": "https://news.example.com/apple-chip",
        "source": "Example News",
        "source_type": "rss",
        "published_at": "2026-06-09T12:00:00Z",
        "word_count": 640,
    }
    # Single-element batch against the documents/batch internal endpoint.
    called_path = authed_mock_clients.content_store.post.call_args.args[0]
    assert called_path == "/api/v1/documents/batch"
    assert authed_mock_clients.content_store.post.call_args.kwargs["json"] == {"doc_ids": [_DOC_UUID]}


@pytest.mark.asyncio
async def test_article_metadata_404_when_doc_unknown(authed_app, authed_mock_clients) -> None:
    """Batch contract omits missing doc_ids → empty list maps to a 404."""
    cs_body = json.dumps({"documents": []}).encode()
    authed_mock_clients.content_store.post = AsyncMock(return_value=_mock_http_response(200, cs_body))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/articles/{_DOC_UUID}", headers=_auth_headers())

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_article_metadata_passes_through_downstream_errors(authed_app, authed_mock_clients) -> None:
    """Non-200 from content-store is passed through unchanged (no fake 404)."""
    authed_mock_clients.content_store.post = AsyncMock(
        return_value=_mock_http_response(503, b'{"detail":"unavailable"}')
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/articles/{_DOC_UUID}", headers=_auth_headers())

    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_article_metadata_rejects_non_uuid(authed_app) -> None:
    """Path param is UUID-typed — garbage never reaches content-store."""
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/articles/not-a-uuid", headers=_auth_headers())
    assert resp.status_code == 422
