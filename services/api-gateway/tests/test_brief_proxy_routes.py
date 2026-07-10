"""Unit tests for PLAN-0066 Wave B/C/D/E proxy routes for morning-brief endpoints.

Waves covered:
  Wave B — GET /v1/briefings/morning/history
  Wave C — GET /v1/briefings/morning/diff
            POST /v1/briefings/feedback/bullet
            POST /v1/briefings/feedback/brief
  Wave D — POST /v1/briefings/chat/discuss
  Wave E — POST /v1/briefings/{brief_id}/create-alert (placeholder)

All tests verify:
  - Authenticated request is forwarded to S8 (rag-chat) with the correct path
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


# ── T-W10-C-01: proxy brief diff passthrough ─────────────────────────────────


@pytest.mark.asyncio
async def test_proxy_brief_diff_passthrough(authed_app, authed_mock_clients) -> None:
    """GET /v1/briefings/morning/diff → S8 rag-chat forwarded.

    WHY: the gateway must forward the diff request to S8 which performs a 2-row
    DB fetch and in-memory compare.  No query params are required.
    """
    diff_body = b'{"added": [], "removed": [], "unchanged": []}'
    authed_mock_clients.rag_chat.get = AsyncMock(
        return_value=_mock_response(200, diff_body),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/briefings/morning/diff",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200

    authed_mock_clients.rag_chat.get.assert_called_once()
    call_args = authed_mock_clients.rag_chat.get.call_args
    # WHY positional: proxy calls clients.rag_chat.get(path, headers=...)
    path_arg = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert "/api/v1/briefings/morning/diff" in path_arg


@pytest.mark.asyncio
async def test_proxy_brief_diff_requires_auth(app, mock_clients) -> None:
    """GET /v1/briefings/morning/diff without auth → 401; S8 never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/briefings/morning/diff")

    assert resp.status_code == 401
    mock_clients.rag_chat.get.assert_not_called()


# ── T-W10-C-02: proxy feedback/bullet passthrough ────────────────────────────


@pytest.mark.asyncio
async def test_proxy_brief_feedback_bullet(authed_app, authed_mock_clients) -> None:
    """POST /v1/briefings/feedback/bullet → S8 rag-chat forwarded with JSON body.

    WHY: the gateway must forward the raw body bytes to S8 so S8 can validate
    brief_id, section_idx, bullet_idx, and reaction via Pydantic.
    """
    req_body = b'{"brief_id": "br-1", "section_idx": 0, "bullet_idx": 1, "reaction": "helpful"}'
    authed_mock_clients.rag_chat.post = AsyncMock(
        return_value=_mock_response(201, b'{"id": "fb-1"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/briefings/feedback/bullet",
            content=req_body,
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "Content-Type": "application/json",
            },
        )

    # WHY 201 from the mock: S8 returns 201 Created on successful feedback write;
    # the gateway passes the upstream status code through unchanged.
    assert resp.status_code == 201

    authed_mock_clients.rag_chat.post.assert_called_once()
    call_args = authed_mock_clients.rag_chat.post.call_args
    path_arg = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert "/api/v1/briefings/feedback/bullet" in path_arg


@pytest.mark.asyncio
async def test_proxy_brief_feedback_bullet_requires_auth(app, mock_clients) -> None:
    """POST /v1/briefings/feedback/bullet without auth → 401; S8 never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/briefings/feedback/bullet",
            content=b"{}",
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 401
    mock_clients.rag_chat.post.assert_not_called()


# ── T-W10-C-03: proxy feedback/brief passthrough ─────────────────────────────


@pytest.mark.asyncio
async def test_proxy_brief_feedback_brief_passthrough(authed_app, authed_mock_clients) -> None:
    """POST /v1/briefings/feedback/brief → S8 rag-chat forwarded with JSON body.

    WHY: star-rating feedback (1-5) must reach S8 so it can persist the rating
    and adjust LLM prompt weights over time.
    """
    req_body = b'{"brief_id": "br-1", "rating": 4}'
    authed_mock_clients.rag_chat.post = AsyncMock(
        return_value=_mock_response(201, b'{"id": "fb-2"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/briefings/feedback/brief",
            content=req_body,
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 201

    authed_mock_clients.rag_chat.post.assert_called_once()
    call_args = authed_mock_clients.rag_chat.post.call_args
    path_arg = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert "/api/v1/briefings/feedback/brief" in path_arg


# ── T-W10-D-01: proxy chat/discuss passthrough ───────────────────────────────


@pytest.mark.asyncio
async def test_proxy_brief_discuss(authed_app, authed_mock_clients) -> None:
    """POST /v1/briefings/chat/discuss → S8 rag-chat forwarded with JSON body.

    WHY: follow-up chat questions are forwarded to S8 which runs an LLM completion;
    S9 acts as a thin proxy and must not modify or buffer the body.
    """
    req_body = b'{"brief_id": "br-1", "message": "Why is NVDA down?"}'
    authed_mock_clients.rag_chat.post = AsyncMock(
        return_value=_mock_response(200, b'{"reply": "Because of macro concerns."}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/briefings/chat/discuss",
            content=req_body,
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200

    authed_mock_clients.rag_chat.post.assert_called_once()
    call_args = authed_mock_clients.rag_chat.post.call_args
    path_arg = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert "/api/v1/briefings/chat/discuss" in path_arg


@pytest.mark.asyncio
async def test_proxy_brief_discuss_requires_auth(app, mock_clients) -> None:
    """POST /v1/briefings/chat/discuss without auth → 401; S8 never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/briefings/chat/discuss",
            content=b"{}",
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 401
    mock_clients.rag_chat.post.assert_not_called()


# ── T-W10-E-01: proxy {brief_id}/create-alert placeholder passthrough ─────────


@pytest.mark.asyncio
async def test_proxy_brief_create_alert_passthrough(authed_app, authed_mock_clients) -> None:
    """POST /v1/briefings/{brief_id}/create-alert → S8 rag-chat forwarded.

    WHY: the placeholder route must be registered at S9 so the API surface is
    stable before Wave F ships the real S8 implementation.  S8 currently returns
    404 for this path; S9 passes that through unchanged.
    """
    brief_id = "br-abc123"
    # Simulate S8 returning 404 until Wave F ships the real endpoint
    authed_mock_clients.rag_chat.post = AsyncMock(
        return_value=_mock_response(404, b'{"detail": "Not implemented yet"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/v1/briefings/{brief_id}/create-alert",
            content=b'{"ticker": "NVDA"}',
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "Content-Type": "application/json",
            },
        )

    # WHY 404: S8 placeholder returns 404; S9 passes status through unchanged
    assert resp.status_code == 404

    authed_mock_clients.rag_chat.post.assert_called_once()
    call_args = authed_mock_clients.rag_chat.post.call_args
    path_arg = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert f"/api/v1/briefings/{brief_id}/create-alert" in path_arg


@pytest.mark.asyncio
async def test_proxy_brief_create_alert_requires_auth(app, mock_clients) -> None:
    """POST /v1/briefings/{brief_id}/create-alert without auth → 401; S8 never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/briefings/br-1/create-alert",
            content=b"{}",
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 401
    mock_clients.rag_chat.post.assert_not_called()


# ── Morning brief force-regenerate proxy ──────────────────────────────────────


@pytest.mark.asyncio
async def test_proxy_morning_generate_passthrough(authed_app, authed_mock_clients) -> None:
    """POST /v1/briefings/morning/generate → S8 forwarded; 202 + body passed through.

    WHY: backs the dashboard "Regenerate" button — S8 bypasses its staleness
    check and regenerates; S9 must pass the 202 + {"status": "queued"}
    envelope through unchanged.
    """
    body = b'{"status": "queued", "generated_at": "2026-06-10T06:00:00+00:00"}'
    authed_mock_clients.rag_chat.post = AsyncMock(return_value=_mock_response(202, body))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/briefings/morning/generate",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 202
    assert resp.json()["status"] == "queued"

    authed_mock_clients.rag_chat.post.assert_called_once()
    call_args = authed_mock_clients.rag_chat.post.call_args
    path_arg = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert "/api/v1/briefings/morning/generate" in path_arg


@pytest.mark.asyncio
async def test_proxy_morning_generate_requires_auth(app, mock_clients) -> None:
    """POST /v1/briefings/morning/generate without auth → 401; S8 never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/v1/briefings/morning/generate")

    assert resp.status_code == 401
    mock_clients.rag_chat.post.assert_not_called()


@pytest.mark.asyncio
async def test_proxy_morning_generate_timeout_returns_503(authed_app, authed_mock_clients) -> None:
    """S8 timeout during regeneration → 503 (not 500) so the frontend can retry."""
    authed_mock_clients.rag_chat.post = AsyncMock(side_effect=httpx.TimeoutException("LLM slow"))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/briefings/morning/generate",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 503


# ── PLAN-0056 Wave E1: morning-brief prediction leg ──────────────────────────


@pytest.mark.asyncio
async def test_morning_brief_attaches_prediction_signals(authed_app, authed_mock_clients) -> None:
    """A healthy S8 brief is augmented with a ``prediction_signals`` leg from S3."""
    authed_mock_clients.rag_chat.get = AsyncMock(
        return_value=_mock_response(200, b'{"summary": "Markets calm", "sections": []}')
    )
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, b'{"items": [{"market_id": "m-1"}], "total": 1}')
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/briefings/morning",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    # Original brief content preserved…
    assert body["summary"] == "Markets calm"
    # …plus the new prediction leg populated from S3.
    assert body["prediction_signals"]["items"][0]["market_id"] == "m-1"
    # S3 was queried for the top open prediction markets.
    assert authed_mock_clients.market_data.get.call_args[0][0] == "/api/v1/prediction-markets"


@pytest.mark.asyncio
async def test_morning_brief_prediction_leg_failure_is_none(authed_app, authed_mock_clients) -> None:
    """A failing prediction leg degrades to ``None`` and never breaks the brief."""
    authed_mock_clients.rag_chat.get = AsyncMock(return_value=_mock_response(200, b'{"summary": "Markets calm"}'))
    # S3 raises → leg must swallow the error and return None.
    authed_mock_clients.market_data.get = AsyncMock(side_effect=httpx.ConnectError("S3 down"))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/briefings/morning",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"] == "Markets calm"
    assert body["prediction_signals"] is None


@pytest.mark.asyncio
async def test_morning_brief_prediction_leg_non200_is_none(authed_app, authed_mock_clients) -> None:
    """A non-200 from S3 → ``prediction_signals`` is None (brief still 200)."""
    authed_mock_clients.rag_chat.get = AsyncMock(return_value=_mock_response(200, b'{"summary": "Markets calm"}'))
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_response(503, b"{}"))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/briefings/morning",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    assert resp.json()["prediction_signals"] is None


@pytest.mark.asyncio
async def test_morning_brief_upstream_error_not_augmented(authed_app, authed_mock_clients) -> None:
    """A non-200 S8 brief passes through untouched — S3 is never called."""
    authed_mock_clients.rag_chat.get = AsyncMock(return_value=_mock_response(500, b'{"detail": "boom"}'))
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_response(200, b'{"items": []}'))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/briefings/morning",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    # 5xx is sanitised by proxy_json_response (→ 502); prediction leg not added.
    assert resp.status_code == 502
    authed_mock_clients.market_data.get.assert_not_called()


@pytest.mark.asyncio
async def test_morning_brief_requires_auth(app, mock_clients) -> None:
    """Missing JWT → 401; neither S8 nor S3 is called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/briefings/morning")

    assert resp.status_code == 401
    mock_clients.rag_chat.get.assert_not_called()
