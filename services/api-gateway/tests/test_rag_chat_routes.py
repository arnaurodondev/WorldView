"""Unit tests for S9 → S8 RAG/Chat proxy routes (T-G-1-01)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_SECRET = "test-secret"  # noqa: S105
_TENANT_ID = "00000000-0000-0000-0000-000000000010"
_USER_ID = "00000000-0000-0000-0000-000000000011"

_JWT_PAYLOAD = {
    "sub": _USER_ID,
    "tenant_id": _TENANT_ID,
    "exp": 9999999999,
}


def _make_jwt() -> str:
    return jwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _mock_response(status: int = 200, body: dict | None = None, content: bytes | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content if content is not None else json.dumps(body or {}).encode()
    resp.json.return_value = body or {}
    return resp


@pytest.mark.asyncio
async def test_s9_chat_route_proxied(authed_app, authed_mock_clients) -> None:
    """POST /v1/chat → proxied to S8 /api/v1/chat, returns 200."""
    authed_mock_clients.rag_chat.post = AsyncMock(
        return_value=_mock_response(200, {"answer": "Apple revenue was $120B.", "citations": []})
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat",
            json={"message": "What is Apple revenue?"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.rag_chat.post.assert_called_once()
    call_kwargs = authed_mock_clients.rag_chat.post.call_args
    assert "/api/v1/chat" in call_kwargs[0][0]


@pytest.mark.asyncio
async def test_s9_chat_stream_not_buffered(authed_app, authed_mock_clients) -> None:
    """POST /v1/chat/stream → StreamingResponse with text/event-stream content type."""

    # Build a minimal SSE byte stream
    sse_lines = [
        b'event: status\ndata: {"step": "loading"}\n\n',
        b'event: token\ndata: {"text": "Apple"}\n\n',
    ]

    class _FakeStream:
        """Minimal async context manager that yields SSE bytes."""

        async def __aenter__(self) -> _FakeStream:
            return self

        async def __aexit__(self, *_: object) -> None:
            pass

        async def aiter_bytes(self):  # type: ignore[return]
            for chunk in sse_lines:
                yield chunk

    authed_mock_clients.rag_chat.stream = MagicMock(return_value=_FakeStream())

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/stream",
            json={"message": "Latest Apple news?"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")


# ── F-04: Chat auth guards ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_s9_chat_requires_auth(app, mock_clients) -> None:
    """F-04: POST /v1/chat without auth → 401; downstream never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/v1/chat", json={"message": "hello"})

    assert resp.status_code == 401
    mock_clients.rag_chat.post.assert_not_called()


@pytest.mark.asyncio
async def test_s9_chat_stream_requires_auth(app, mock_clients) -> None:
    """F-04: POST /v1/chat/stream without auth → 401; downstream never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/v1/chat/stream", json={"message": "hello"})

    assert resp.status_code == 401
    mock_clients.rag_chat.stream.assert_not_called()


@pytest.mark.asyncio
async def test_s9_does_not_forward_legacy_tenant_user_headers(authed_app, authed_mock_clients) -> None:
    """F-MAJOR-013: X-Tenant-Id / X-User-Id are NO LONGER forwarded to backends.

    Backends extract tenant_id/user_id from the X-Internal-JWT payload.
    Only X-Internal-JWT is forwarded by _auth_headers().
    """
    captured_headers: dict[str, str] = {}

    async def _capture_post(path: str, **kwargs: object) -> MagicMock:
        captured_headers.update(kwargs.get("headers", {}))  # type: ignore[arg-type]
        return _mock_response(200, {"answer": "ok", "citations": []})

    authed_mock_clients.rag_chat.post = _capture_post

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/v1/chat",
            json={"message": "test"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    # Legacy headers MUST NOT be forwarded (F-MAJOR-013)
    assert "X-Tenant-Id" not in captured_headers
    assert "X-User-Id" not in captured_headers


@pytest.mark.asyncio
async def test_s9_threads_list_proxied(app, mock_clients) -> None:
    """GET /v1/threads → proxied to S8 /api/v1/threads."""
    mock_clients.rag_chat.get = AsyncMock(return_value=_mock_response(200, {"threads": [], "total": 0}))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/threads",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    mock_clients.rag_chat.get.assert_called_once()
    assert "/api/v1/threads" in mock_clients.rag_chat.get.call_args[0][0]


@pytest.mark.asyncio
async def test_s9_thread_delete_proxied(app, mock_clients) -> None:
    """DELETE /v1/threads/{id} → proxied to S8 /api/v1/threads/{id}."""
    thread_id = "01900000-0000-7000-8000-000000000001"
    mock_clients.rag_chat.delete = AsyncMock(return_value=_mock_response(200, {"deleted": True}))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(
            f"/v1/threads/{thread_id}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    mock_clients.rag_chat.delete.assert_called_once()
    assert thread_id in mock_clients.rag_chat.delete.call_args[0][0]
