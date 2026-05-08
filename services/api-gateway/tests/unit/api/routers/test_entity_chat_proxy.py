"""Tests for PLAN-0074 Wave G proxy routes — T-G-04:

  POST /v1/chat/entity-context       → S8 (synchronous)
  POST /v1/chat/entity-context/stream → S8 (SSE streaming)

Tests follow the conftest.py fixture convention.
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
_TENANT_ID = "00000000-0000-0000-0000-000000000010"
_USER_ID = "00000000-0000-0000-0000-000000000011"
_ENTITY_UUID = "01930000-0000-7000-8000-000000000001"

_JWT_PAYLOAD = {
    "sub": _USER_ID,
    "tenant_id": _TENANT_ID,
    "exp": 9999999999,
}


def _make_jwt() -> str:
    return jwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _mock_response(status: int = 200, body: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = json.dumps(body or {}).encode()
    resp.json.return_value = body or {}
    return resp


# ── POST /v1/chat/entity-context (synchronous) ───────────────────────────────


@pytest.mark.asyncio
async def test_entity_chat_requires_auth(app, mock_clients) -> None:
    """POST /v1/chat/entity-context without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/entity-context",
            json={"entity_id": _ENTITY_UUID, "question": "What is Apple's outlook?"},
        )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_entity_chat_happy_path(authed_app, authed_mock_clients) -> None:
    """POST /v1/chat/entity-context → S8 returns 200; response forwarded."""
    answer_payload = {
        "answer": "Apple has strong revenue growth driven by iPhone.",
        "citations": [],
        "contradictions": [],
    }
    authed_mock_clients.rag_chat.post = AsyncMock(
        return_value=_mock_response(200, answer_payload),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/entity-context",
            json={"entity_id": _ENTITY_UUID, "question": "What is Apple's revenue outlook?"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "Apple has strong revenue growth driven by iPhone."
    call_path = authed_mock_clients.rag_chat.post.call_args[0][0]
    assert call_path == "/api/v1/chat/entity-context"


@pytest.mark.asyncio
async def test_entity_chat_invalid_entity_id_rejected(authed_app, authed_mock_clients) -> None:
    """POST /v1/chat/entity-context with non-UUID entity_id → 422."""
    authed_mock_clients.rag_chat.post = AsyncMock()

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/entity-context",
            json={"entity_id": "not-a-uuid", "question": "What is the risk?"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 422
    authed_mock_clients.rag_chat.post.assert_not_called()


@pytest.mark.asyncio
async def test_entity_chat_empty_question_rejected(authed_app, authed_mock_clients) -> None:
    """POST /v1/chat/entity-context with empty question → 400."""
    authed_mock_clients.rag_chat.post = AsyncMock()

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/entity-context",
            json={"entity_id": _ENTITY_UUID, "question": "   "},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 400
    authed_mock_clients.rag_chat.post.assert_not_called()


@pytest.mark.asyncio
async def test_entity_chat_error_from_s8_forwarded(authed_app, authed_mock_clients) -> None:
    """POST /v1/chat/entity-context — S8 429 (LLM rate limit) is forwarded."""
    authed_mock_clients.rag_chat.post = AsyncMock(
        return_value=_mock_response(429, {"detail": "LLM rate limit exceeded"}),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/entity-context",
            json={"entity_id": _ENTITY_UUID, "question": "Any recent earnings?"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 429


# ── POST /v1/chat/entity-context/stream (SSE) ────────────────────────────────


@pytest.mark.asyncio
async def test_entity_chat_stream_requires_auth(app, mock_clients) -> None:
    """POST /v1/chat/entity-context/stream without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/entity-context/stream",
            json={"entity_id": _ENTITY_UUID, "question": "Any news?"},
        )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_entity_chat_stream_passes_sse_chunks(authed_app, authed_mock_clients) -> None:
    """POST /v1/chat/entity-context/stream → SSE chunks pass through with correct content-type."""
    sse_chunks = [
        b'event: token\ndata: {"text": "Apple"}\n\n',
        b'event: token\ndata: {"text": " revenue"}\n\n',
    ]

    class _FakeStream:
        async def __aenter__(self) -> _FakeStream:
            return self

        async def __aexit__(self, *_: object) -> None:
            pass

        async def aiter_bytes(self):  # type: ignore[return]
            for chunk in sse_chunks:
                yield chunk

    authed_mock_clients.rag_chat.stream = MagicMock(return_value=_FakeStream())

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/entity-context/stream",
            json={"entity_id": _ENTITY_UUID, "question": "What is the revenue?"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    # Verify S8 stream endpoint was called with correct path.
    call_args = authed_mock_clients.rag_chat.stream.call_args
    assert "/api/v1/chat/entity-context/stream" in call_args[0]


@pytest.mark.asyncio
async def test_entity_chat_stream_invalid_entity_id_rejected(authed_app, authed_mock_clients) -> None:
    """POST /v1/chat/entity-context/stream with non-UUID entity_id → 422."""
    authed_mock_clients.rag_chat.stream = MagicMock()

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/entity-context/stream",
            json={"entity_id": "not-a-uuid", "question": "What is the risk?"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 422
    authed_mock_clients.rag_chat.stream.assert_not_called()
