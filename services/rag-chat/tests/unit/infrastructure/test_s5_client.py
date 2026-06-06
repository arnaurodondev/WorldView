"""Unit tests for S5Client (alert service adapter).

Verifies safe-degradation contract: get_pending_alerts returns [] on
any error (timeout, HTTP 5xx, connection refused) — never raises.
"""

from __future__ import annotations

import httpx
import pytest
from rag_chat.infrastructure.clients.s5_client import S5Client

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class TestS5Client:
    async def test_get_pending_alerts_success(self) -> None:
        mock_response = httpx.Response(
            200,
            json={
                "alerts": [
                    {
                        "alert_id": "00000000-0000-0000-0000-000000000001",
                        "entity_id": "00000000-0000-0000-0000-000000000002",
                        "alert_type": "price_drop",
                        "severity": "high",
                        "payload": {},
                        "created_at": "2026-04-24T12:00:00+00:00",
                    },
                ]
            },
        )
        transport = httpx.MockTransport(lambda req: mock_response)
        client = S5Client.__new__(S5Client)
        client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
        client._internal_jwt = None

        result = await client.get_pending_alerts("user1", "tenant1")
        assert len(result) == 1
        assert result[0].alert_type == "price_drop"
        assert result[0].severity == "high"

    async def test_server_error_returns_empty(self) -> None:
        transport = httpx.MockTransport(lambda req: httpx.Response(500))
        client = S5Client.__new__(S5Client)
        client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
        client._internal_jwt = None

        result = await client.get_pending_alerts("user1", "tenant1")
        assert result == []

    async def test_timeout_returns_empty(self) -> None:
        def raise_timeout(req: httpx.Request) -> httpx.Response:
            msg = "timed out"
            raise httpx.TimeoutException(msg)

        transport = httpx.MockTransport(raise_timeout)
        client = S5Client.__new__(S5Client)
        client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
        client._internal_jwt = None

        result = await client.get_pending_alerts("user1", "tenant1")
        assert result == []

    async def test_passes_jwt_header(self) -> None:
        captured_headers: dict[str, str] = {}

        def capture_req(req: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(req.headers))
            return httpx.Response(200, json={"alerts": []})

        transport = httpx.MockTransport(capture_req)
        client = S5Client.__new__(S5Client)
        client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
        client._internal_jwt = "my-jwt-token"

        await client.get_pending_alerts("user1", "tenant1")
        assert captured_headers.get("x-internal-jwt") == "my-jwt-token"

    async def test_multiple_alerts_parsed(self) -> None:
        mock_response = httpx.Response(
            200,
            json={
                "alerts": [
                    {
                        "alert_id": "00000000-0000-0000-0000-000000000001",
                        "entity_id": "00000000-0000-0000-0000-000000000002",
                        "alert_type": "price_drop",
                        "severity": "high",
                        "payload": {"threshold": -5.0},
                        "created_at": "2026-04-24T12:00:00+00:00",
                    },
                    {
                        "alert_id": "00000000-0000-0000-0000-000000000003",
                        "entity_id": "00000000-0000-0000-0000-000000000004",
                        "alert_type": "volume_spike",
                        "severity": "medium",
                        "payload": {},
                        "created_at": "2026-04-24T13:00:00+00:00",
                    },
                ]
            },
        )
        transport = httpx.MockTransport(lambda req: mock_response)
        client = S5Client.__new__(S5Client)
        client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
        client._internal_jwt = None

        result = await client.get_pending_alerts("user1", "tenant1")
        assert len(result) == 2
        assert result[1].alert_type == "volume_spike"

    async def test_malformed_json_returns_empty(self) -> None:
        mock_response = httpx.Response(200, json={"unexpected": "format"})
        transport = httpx.MockTransport(lambda req: mock_response)
        client = S5Client.__new__(S5Client)
        client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
        client._internal_jwt = None

        result = await client.get_pending_alerts("user1", "tenant1")
        assert result == []

    # ── PLAN-0094 follow-up: service-caller endpoint ──────────────────────
    async def test_get_pending_alerts_for_user_calls_internal_path(self) -> None:
        """The service-token method must hit /internal/v1/users/{user_id}/alerts/pending."""
        captured_paths: list[str] = []

        def capture_req(req: httpx.Request) -> httpx.Response:
            captured_paths.append(req.url.path)
            return httpx.Response(200, json={"alerts": []})

        transport = httpx.MockTransport(capture_req)
        client = S5Client.__new__(S5Client)
        client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
        client._internal_jwt = "svc-jwt"

        user_id = "11111111-2222-3333-4444-555555555555"
        await client.get_pending_alerts_for_user(user_id, "tenant1")
        assert captured_paths == [f"/internal/v1/users/{user_id}/alerts/pending"]

    async def test_get_pending_alerts_for_user_returns_empty_on_403(self) -> None:
        """Forbidden (allow-list mismatch) must degrade to [] — never raise."""
        transport = httpx.MockTransport(lambda req: httpx.Response(403, json={"detail": "denied"}))
        client = S5Client.__new__(S5Client)
        client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
        client._internal_jwt = "svc-jwt"

        result = await client.get_pending_alerts_for_user("user1", "tenant1")
        assert result == []
