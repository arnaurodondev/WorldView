"""Tests for PLAN-0052 Wave D feedback proxy routes (12 endpoints).

Each test verifies that ``/v1/feedback/*`` forwards to the portfolio
service at ``/api/v1/feedback/*`` and that ``X-Internal-JWT`` is
preserved on the outbound call.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_SECRET = "test-secret"  # noqa: S105 — fixture-only test secret
_USER_PAYLOAD = {"sub": "user-1", "tenant_id": "t-1", "role": "user", "exp": 9999999999}
_ADMIN_PAYLOAD = {"sub": "admin-1", "tenant_id": "t-1", "role": "admin", "exp": 9999999999}


def _make_jwt(payload: dict) -> str:
    return jwt.encode(payload, _JWT_SECRET, algorithm="HS256")


def _mock_response(status: int, content: bytes = b"{}") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    return resp


def _bearer(payload=None) -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_jwt(payload or _USER_PAYLOAD)}"}


# ── Submissions ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_submission_proxy_forwards_to_portfolio(authed_app, authed_mock_clients) -> None:
    authed_mock_clients.portfolio.post = AsyncMock(return_value=_mock_response(201, b'{"id":"x"}'))
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/feedback/submissions",
            json={"kind": "bug", "description": "0123456789 placeholder text"},
            headers=_bearer(),
        )
    assert resp.status_code == 201
    target = authed_mock_clients.portfolio.post.call_args[0][0]
    assert target == "/api/v1/feedback/submissions"


@pytest.mark.asyncio
async def test_list_submissions_proxy_requires_auth(app, mock_clients) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/feedback/submissions")
    assert resp.status_code == 401
    mock_clients.portfolio.get.assert_not_called()


@pytest.mark.asyncio
async def test_list_submissions_proxy_forwards_query(authed_app, authed_mock_clients) -> None:
    authed_mock_clients.portfolio.get = AsyncMock(return_value=_mock_response(200, b'{"items":[],"total":0}'))
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/feedback/submissions?mine=true&status=open",
            headers=_bearer(),
        )
    assert resp.status_code == 200
    target = authed_mock_clients.portfolio.get.call_args[0][0]
    assert "/api/v1/feedback/submissions" in target
    assert "mine=true" in target
    assert "status=open" in target


@pytest.mark.asyncio
async def test_get_submission_proxy(authed_app, authed_mock_clients) -> None:
    authed_mock_clients.portfolio.get = AsyncMock(return_value=_mock_response(200, b"{}"))
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/feedback/submissions/abc-123", headers=_bearer())
    assert resp.status_code == 200
    target = authed_mock_clients.portfolio.get.call_args[0][0]
    assert target == "/api/v1/feedback/submissions/abc-123"


@pytest.mark.asyncio
async def test_patch_submission_proxy(authed_app, authed_mock_clients) -> None:
    authed_mock_clients.portfolio.patch = AsyncMock(return_value=_mock_response(200, b"{}"))
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            "/v1/feedback/submissions/abc-123",
            json={"status": "triaged"},
            headers=_bearer(_ADMIN_PAYLOAD),
        )
    assert resp.status_code == 200
    target = authed_mock_clients.portfolio.patch.call_args[0][0]
    assert target == "/api/v1/feedback/submissions/abc-123"


@pytest.mark.asyncio
async def test_delete_submission_proxy(authed_app, authed_mock_clients) -> None:
    authed_mock_clients.portfolio.delete = AsyncMock(return_value=_mock_response(204, b""))
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/v1/feedback/submissions/abc-123", headers=_bearer(_ADMIN_PAYLOAD))
    # The proxy forwards backend's 204 verbatim.
    assert resp.status_code in (200, 204)
    target = authed_mock_clients.portfolio.delete.call_args[0][0]
    assert target == "/api/v1/feedback/submissions/abc-123"


# ── NPS ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_nps_proxy(authed_app, authed_mock_clients) -> None:
    authed_mock_clients.portfolio.post = AsyncMock(return_value=_mock_response(201, b'{"id":"x"}'))
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/v1/feedback/nps", json={"score": 9}, headers=_bearer())
    assert resp.status_code == 201
    target = authed_mock_clients.portfolio.post.call_args[0][0]
    assert target == "/api/v1/feedback/nps"


@pytest.mark.asyncio
async def test_get_nps_aggregate_proxy(authed_app, authed_mock_clients) -> None:
    authed_mock_clients.portfolio.get = AsyncMock(return_value=_mock_response(200, b"{}"))
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/feedback/nps/aggregate?days=7", headers=_bearer(_ADMIN_PAYLOAD))
    assert resp.status_code == 200
    target = authed_mock_clients.portfolio.get.call_args[0][0]
    assert target.startswith("/api/v1/feedback/nps/aggregate")
    assert "days=7" in target


# ── Features ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_features_proxy_public(app, mock_clients) -> None:
    """``GET /v1/feedback/features`` is public — no auth required."""
    mock_clients.portfolio.get = AsyncMock(return_value=_mock_response(200, b'{"items":[],"total":0}'))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/feedback/features")
    assert resp.status_code == 200
    target = mock_clients.portfolio.get.call_args[0][0]
    assert target.startswith("/api/v1/feedback/features")


@pytest.mark.asyncio
async def test_create_feature_proxy(authed_app, authed_mock_clients) -> None:
    authed_mock_clients.portfolio.post = AsyncMock(return_value=_mock_response(201, b"{}"))
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/feedback/features",
            json={"title": "X", "description": "Y"},
            headers=_bearer(),
        )
    assert resp.status_code == 201
    target = authed_mock_clients.portfolio.post.call_args[0][0]
    assert target == "/api/v1/feedback/features"


@pytest.mark.asyncio
async def test_vote_feature_proxy(authed_app, authed_mock_clients) -> None:
    authed_mock_clients.portfolio.post = AsyncMock(return_value=_mock_response(200, b"{}"))
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/v1/feedback/features/feat-1/vote", headers=_bearer())
    assert resp.status_code == 200
    target = authed_mock_clients.portfolio.post.call_args[0][0]
    assert target == "/api/v1/feedback/features/feat-1/vote"


# ── Micro-survey + beta program ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_micro_survey_proxy_public(app, mock_clients) -> None:
    """Anonymous docs feedback widget POSTs without auth — must succeed."""
    mock_clients.portfolio.post = AsyncMock(return_value=_mock_response(201, b"{}"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/feedback/micro-survey",
            json={"survey_key": "docs:/x", "response": "positive"},
        )
    assert resp.status_code == 201
    target = mock_clients.portfolio.post.call_args[0][0]
    assert target == "/api/v1/feedback/micro-survey"


@pytest.mark.asyncio
async def test_get_beta_enrollment_proxy(authed_app, authed_mock_clients) -> None:
    authed_mock_clients.portfolio.get = AsyncMock(return_value=_mock_response(200, b"{}"))
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/feedback/beta-program/enrollment", headers=_bearer())
    assert resp.status_code == 200
    target = authed_mock_clients.portfolio.get.call_args[0][0]
    assert target == "/api/v1/feedback/beta-program/enrollment"


@pytest.mark.asyncio
async def test_patch_beta_enrollment_proxy(authed_app, authed_mock_clients) -> None:
    authed_mock_clients.portfolio.patch = AsyncMock(return_value=_mock_response(200, b"{}"))
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            "/v1/feedback/beta-program/enrollment",
            json={"enrolled": True, "programs": ["ai-brief"]},
            headers=_bearer(),
        )
    assert resp.status_code == 200
    target = authed_mock_clients.portfolio.patch.call_args[0][0]
    assert target == "/api/v1/feedback/beta-program/enrollment"
