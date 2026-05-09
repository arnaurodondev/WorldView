"""Unit tests for S10Client HTTP adapter (PLAN-0082 Wave A).

Tests cover:
  - Auth headers (X-User-Id, X-Tenant-Id) are forwarded to S10
  - Successful response returns the parsed list
  - Any error (exception from _get) degrades gracefully to []
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit


def _make_client():
    """Construct an S10Client pointed at a mock S9 base URL."""
    from rag_chat.infrastructure.clients.s10_client import S10Client

    return S10Client(base_url="http://s9-mock", timeout=5.0)


@pytest.mark.asyncio
async def test_get_alerts_passes_auth_headers() -> None:
    """X-User-Id and X-Tenant-Id must be forwarded as extra_headers to _get."""
    client = _make_client()
    captured_headers: dict = {}

    async def _mock_get(path: str, params=None, *, extra_headers=None, **kwargs) -> dict:
        captured_headers.update(extra_headers or {})
        # Return an envelope with an "alerts" key (standard S10 contract)
        return {"alerts": [{"id": "a1", "ticker": "AAPL"}]}

    with patch.object(client, "_get", new=_mock_get):
        result = await client.get_alerts(user_id="user-123", tenant_id="tenant-456")

    assert captured_headers.get("X-User-Id") == "user-123", f"Expected X-User-Id='user-123', got {captured_headers!r}"
    assert (
        captured_headers.get("X-Tenant-Id") == "tenant-456"
    ), f"Expected X-Tenant-Id='tenant-456', got {captured_headers!r}"
    # Verify the result is the unwrapped list
    assert result == [{"id": "a1", "ticker": "AAPL"}]


@pytest.mark.asyncio
async def test_get_alerts_returns_list() -> None:
    """When _get returns a valid envelope, get_alerts returns the alerts list."""
    client = _make_client()
    alerts_data = [
        {"id": "b1", "ticker": "NVDA", "alert_type": "signal"},
        {"id": "b2", "ticker": "MSFT", "alert_type": "price"},
    ]
    mock_response = {"alerts": alerts_data}

    with patch.object(client, "_get", new=AsyncMock(return_value=mock_response)):
        result = await client.get_alerts(user_id="u1", tenant_id="t1")

    assert result == alerts_data, f"Expected alerts list, got {result!r}"


@pytest.mark.asyncio
async def test_get_alerts_returns_empty_on_error() -> None:
    """When _get returns {} (BaseUpstreamClient error path), get_alerts returns []."""
    client = _make_client()

    # BaseUpstreamClient._get returns {} on timeout/HTTP error (R9 contract).
    # S10Client must translate that into an empty list (not raise, not return {}).
    with patch.object(client, "_get", new=AsyncMock(return_value={})):
        result = await client.get_alerts(user_id="u1", tenant_id="t1")

    assert result == [], f"Expected [], got {result!r}"
