"""Unit tests for GET /api/v1/admin/llm-costs on api-gateway (PLAN-0033 T-F-1-01)."""

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


def _make_jwt(role: str = "user") -> str:
    return jwt.encode(
        {"sub": _USER_ID, "tenant_id": _TENANT_ID, "role": role, "exp": 9_999_999_999},
        _JWT_SECRET,
        algorithm="HS256",
    )


def _mock_response(status: int = 200, body: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = json.dumps(body or {}).encode()
    resp.json.return_value = body or {}
    resp.raise_for_status = MagicMock()  # no-op by default
    if status >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status}",
            request=MagicMock(),
            response=resp,
        )
    return resp


def _cost_body(service: str, period: str = "2026-04") -> dict:
    """Build a minimal valid LlmCostsResponse payload."""
    return {
        "service": service,
        "period": period,
        "total_estimated_cost_usd": 1.23,
        "total_calls": 50,
        "total_tokens_in": 100000,
        "total_tokens_out": 20000,
        "success_rate": 0.98,
        "breakdown": [
            {
                "dimension": "gemini",
                "calls": 50,
                "tokens_in": 100000,
                "tokens_out": 20000,
                "estimated_cost_usd": 1.23,
                "success_rate": 0.98,
            }
        ],
    }


# ── Test cases ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_costs_200_all_services_ok(authed_app, authed_mock_clients) -> None:
    """All three services respond — 200 with aggregated totals."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(return_value=_mock_response(200, _cost_body("nlp-pipeline")))
    authed_mock_clients.knowledge_graph.get = AsyncMock(return_value=_mock_response(200, _cost_body("knowledge-graph")))
    authed_mock_clients.rag_chat.get = AsyncMock(return_value=_mock_response(200, _cost_body("rag-chat")))

    transport = ASGITransport(app=authed_app)
    admin_jwt = _make_jwt(role="admin")
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/admin/llm-costs",
            params={"period": "2026-04"},
            headers={"Authorization": f"Bearer {admin_jwt}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["period"] == "2026-04"
    assert len(body["services"]) == 3
    # Grand total = 3 services x 1.23 USD each
    assert abs(body["grand_total_estimated_cost_usd"] - 3.69) < 0.01
    assert body["grand_total_calls"] == 150


@pytest.mark.asyncio
async def test_admin_costs_200_partial_failure(authed_app, authed_mock_clients) -> None:
    """One service fails — 200 returned with error field on the failing service."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(return_value=_mock_response(200, _cost_body("nlp-pipeline")))
    authed_mock_clients.knowledge_graph.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    authed_mock_clients.rag_chat.get = AsyncMock(return_value=_mock_response(200, _cost_body("rag-chat")))

    transport = ASGITransport(app=authed_app)
    admin_jwt = _make_jwt(role="admin")
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/admin/llm-costs",
            headers={"Authorization": f"Bearer {admin_jwt}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    kg_summary = next(s for s in body["services"] if s["service"] == "knowledge-graph")
    assert kg_summary["error"] is not None
    assert kg_summary["total_calls"] == 0


@pytest.mark.asyncio
async def test_admin_costs_503_all_services_fail(authed_app, authed_mock_clients) -> None:
    """All three services fail — 503 is returned."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(side_effect=Exception("timeout"))
    authed_mock_clients.knowledge_graph.get = AsyncMock(side_effect=Exception("timeout"))
    authed_mock_clients.rag_chat.get = AsyncMock(side_effect=Exception("timeout"))

    transport = ASGITransport(app=authed_app)
    admin_jwt = _make_jwt(role="admin")
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/admin/llm-costs",
            headers={"Authorization": f"Bearer {admin_jwt}"},
        )

    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_admin_costs_403_non_admin_user(authed_app) -> None:
    """Non-admin user → HTTP 403."""
    transport = ASGITransport(app=authed_app)
    user_jwt = _make_jwt(role="user")
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/admin/llm-costs",
            headers={"Authorization": f"Bearer {user_jwt}"},
        )

    assert resp.status_code == 403
    assert "Admin" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_admin_costs_403_unauthenticated(authed_app) -> None:
    """No Authorization header → HTTP 403 (user is None → fails admin check)."""
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/admin/llm-costs")

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_costs_default_period(authed_app, authed_mock_clients) -> None:
    """Omitting period defaults to the current UTC month; downstream is called with it."""
    from datetime import UTC, datetime

    now = datetime.now(tz=UTC)
    expected_period = f"{now.year:04d}-{now.month:02d}"

    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(200, _cost_body("nlp-pipeline", expected_period))
    )
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, _cost_body("knowledge-graph", expected_period))
    )
    authed_mock_clients.rag_chat.get = AsyncMock(
        return_value=_mock_response(200, _cost_body("rag-chat", expected_period))
    )

    transport = ASGITransport(app=authed_app)
    admin_jwt = _make_jwt(role="admin")
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/admin/llm-costs",
            headers={"Authorization": f"Bearer {admin_jwt}"},
        )

    assert resp.status_code == 200
    assert resp.json()["period"] == expected_period
