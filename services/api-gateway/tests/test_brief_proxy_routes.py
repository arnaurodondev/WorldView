"""Unit tests for PLAN-0066 Wave B proxy route: GET /v1/briefings/morning/history.

Tests verify:
  - Authenticated request is forwarded to S8 (rag-chat) with query params
  - Unauthenticated request → 401 (gateway auth guard fires before downstream call)

Uses the shared conftest fixtures (app, authed_app, authed_mock_clients) which
build the API gateway with mocked service clients and optional user injection.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_PAYLOAD = {"sub": "user-1", "tenant_id": "t-1", "exp": 9999999999}
_JWT_SECRET = "test-secret"  # noqa: S105


def _make_jwt() -> str:
    return jwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _mock_response(status: int, content: bytes = b"{}") -> MagicMock:
    """Build a mock httpx.Response with the given status code and JSON body."""
    import json as _json

    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    try:
        resp.json = MagicMock(return_value=_json.loads(content.decode()))
    except Exception:
        resp.json = MagicMock(return_value={})
    return resp


# ── T-W10-B-03: proxy history passthrough ────────────────────────────────────


@pytest.mark.asyncio
async def test_proxy_brief_history_passthrough(authed_app, authed_mock_clients) -> None:
    """GET /v1/briefings/morning/history → S8 rag-chat forwarded with query params.

    WHY: the gateway must transparently pass page + page_size query params to S8
    so S8 can apply its own Query constraints (page_size capped at 50).
    """
    history_body = b'{"items": [], "total": 0, "page": 0, "page_size": 10}'
    authed_mock_clients.rag_chat.get = AsyncMock(
        return_value=_mock_response(200, history_body),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/briefings/morning/history",
            params={"page": "0", "page_size": "10"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200

    # Verify S8 was called with the correct path
    authed_mock_clients.rag_chat.get.assert_called_once()
    call_args = authed_mock_clients.rag_chat.get.call_args
    # WHY positional: proxy code calls clients.rag_chat.get(path, params=..., headers=...)
    path_arg = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert "/api/v1/briefings/morning/history" in path_arg

    # Verify query params forwarded
    kwargs = call_args[1]
    assert "params" in kwargs
    assert kwargs["params"].get("page") == "0" or kwargs["params"].get("page") == 0
    assert kwargs["params"].get("page_size") == "10" or kwargs["params"].get("page_size") == 10


@pytest.mark.asyncio
async def test_proxy_brief_history_requires_auth(app, mock_clients) -> None:
    """GET /v1/briefings/morning/history without auth → 401; S8 never called.

    WHY: the gateway auth guard checks request.state.user before forwarding.
    The 'app' fixture does NOT inject user state (no bearer injection).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/briefings/morning/history")

    assert resp.status_code == 401
    # S8 must NOT be called — auth should fail at the gateway before proxying
    mock_clients.rag_chat.get.assert_not_called()
