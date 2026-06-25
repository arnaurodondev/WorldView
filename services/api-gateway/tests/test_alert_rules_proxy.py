"""Contract tests for the /v1/alert-rules gateway proxy routes (PLAN-0113 T-1-05).

Verifies auth gating, downstream path mapping, no-store caching, and status
pass-through. Reuses the shared ``client`` / ``authed_client`` /
``authed_mock_clients`` fixtures from the gateway test conftest.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

pytestmark = pytest.mark.unit

_RULE_ID = "00000000-0000-0000-0000-0000000000cc"
_DUMMY_JWT = (
    "eyJhbGciOiJIUzI1NiJ9" ".eyJzdWIiOiJ1c2VyLTEiLCJ1c2VyX2lkIjoidXNlci0xIiwidGVuYW50X2lkIjoidGVuYW50LTEifQ" ".sig"
)


def _downstream(status: int = 200, content: bytes = b"{}") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    return resp


# ── Auth enforcement ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_rule_requires_auth(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post("/v1/alert-rules", json={})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_rules_requires_auth(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.get("/v1/alert-rules")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_rule_requires_auth(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.get(f"/v1/alert-rules/{_RULE_ID}")
    assert resp.status_code == 401


# ── Proxy mapping ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_rule_proxies_to_s10(authed_client, authed_mock_clients) -> None:  # type: ignore[no-untyped-def]
    authed_mock_clients.alert.post = AsyncMock(return_value=_downstream(201, b'{"rule_id":"x"}'))
    resp = await authed_client.post(
        "/v1/alert-rules",
        json={"rule_type": "PRICE_CROSS", "condition": {}},
        headers={"Authorization": f"Bearer {_DUMMY_JWT}"},
    )
    assert resp.status_code == 201
    call_args = authed_mock_clients.alert.post.call_args
    assert call_args[0][0] == "/api/v1/alert-rules"
    assert resp.headers.get("Cache-Control") == "no-store"


@pytest.mark.asyncio
async def test_list_rules_forwards_query_params(authed_client, authed_mock_clients) -> None:  # type: ignore[no-untyped-def]
    authed_mock_clients.alert.get = AsyncMock(return_value=_downstream(200, b'{"items":[],"total":0}'))
    resp = await authed_client.get(
        "/v1/alert-rules",
        params={"enabled": "true", "rule_type": "PRICE_CROSS"},
        headers={"Authorization": f"Bearer {_DUMMY_JWT}"},
    )
    assert resp.status_code == 200
    call_args = authed_mock_clients.alert.get.call_args
    assert call_args[0][0] == "/api/v1/alert-rules"
    assert call_args.kwargs["params"]["enabled"] == "true"


@pytest.mark.asyncio
async def test_delete_rule_proxies_and_passes_404(authed_client, authed_mock_clients) -> None:  # type: ignore[no-untyped-def]
    authed_mock_clients.alert.delete = AsyncMock(return_value=_downstream(404, b'{"detail":"Rule not found"}'))
    resp = await authed_client.delete(
        f"/v1/alert-rules/{_RULE_ID}",
        headers={"Authorization": f"Bearer {_DUMMY_JWT}"},
    )
    assert resp.status_code == 404
    call_args = authed_mock_clients.alert.delete.call_args
    assert call_args[0][0] == f"/api/v1/alert-rules/{_RULE_ID}"


@pytest.mark.asyncio
async def test_no_legacy_tenant_user_headers_leak(authed_client, authed_mock_clients) -> None:  # type: ignore[no-untyped-def]
    """PRD-0025 — X-Tenant-Id / X-User-Id must not be forwarded (JWT is the source)."""
    authed_mock_clients.alert.get = AsyncMock(return_value=_downstream(200, b'{"items":[],"total":0}'))
    resp = await authed_client.get(
        "/v1/alert-rules",
        headers={"Authorization": f"Bearer {_DUMMY_JWT}"},
    )
    assert resp.status_code == 200
    headers = authed_mock_clients.alert.get.call_args.kwargs.get("headers", {})
    assert "X-Tenant-Id" not in headers
    assert "X-User-Id" not in headers
