"""Unit tests for EarningsCalendarClient (PLAN-0102 W3 T-W3-03)."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import httpx
import pytest

pytestmark = pytest.mark.unit


def _make_client():
    from rag_chat.infrastructure.clients.earnings_calendar_client import (
        EarningsCalendarClient,
    )

    return EarningsCalendarClient(base_url="http://market-data.mock", timeout=5.0)


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "boom",
                request=httpx.Request("GET", "http://market-data.mock/x"),
                response=httpx.Response(self.status_code),
            )


@pytest.mark.asyncio
async def test_happy_path_parses_events():
    """Two events come back parsed into EarningsEvents with proper types."""
    client = _make_client()
    payload = {
        "from": "2026-05-29",
        "to": "2026-06-05",
        "events": [
            {
                "symbol": "NVDA",
                "entity_id": None,
                "report_date": "2026-05-30",
                "when": "AMC",
                "period": None,
                "consensus_eps": 0.83,
                "consensus_rev_usd": None,
            },
            {
                "symbol": "CRM",
                "entity_id": None,
                "report_date": "2026-05-31",
                "when": "AMC",
                "period": None,
                "consensus_eps": 1.55,
                "consensus_rev_usd": None,
            },
        ],
    }
    captured: dict = {}

    async def _fake_get(path, params=None, headers=None):
        captured.update(params or {})
        return _FakeResponse(payload)

    with patch.object(client._client, "get", new=_fake_get):
        result = await client.get_earnings(days_ahead=7)

    assert "from" in captured and "to" in captured
    assert result.from_date == date(2026, 5, 29)
    assert result.to_date == date(2026, 6, 5)
    assert len(result.events) == 2
    assert result.events[0].symbol == "NVDA"
    assert result.events[0].report_date == date(2026, 5, 30)
    assert result.events[0].when == "AMC"
    assert result.events[0].consensus_eps == 0.83


@pytest.mark.asyncio
async def test_days_ahead_clamps_to_zero_when_negative():
    """Negative days_ahead clamps to 0 so the query is always valid."""
    client = _make_client()
    captured: dict = {}

    async def _fake_get(path, params=None, headers=None):
        captured.update(params or {})
        return _FakeResponse({"from": "", "to": "", "events": []})

    with patch.object(client._client, "get", new=_fake_get):
        await client.get_earnings(days_ahead=-5)

    # from and to should be the SAME day when days_ahead clamps to 0
    assert captured["from"] == captured["to"]


@pytest.mark.asyncio
async def test_days_ahead_clamps_to_90_max():
    """Values above 90 are clamped — protects against router's 422 cap."""
    client = _make_client()
    captured: dict = {}

    async def _fake_get(path, params=None, headers=None):
        captured.update(params or {})
        return _FakeResponse({"from": "", "to": "", "events": []})

    with patch.object(client._client, "get", new=_fake_get):
        await client.get_earnings(days_ahead=365)

    from_d = date.fromisoformat(captured["from"])
    to_d = date.fromisoformat(captured["to"])
    assert (to_d - from_d).days == 90


@pytest.mark.asyncio
async def test_timeout_returns_empty_result():
    """R9 — timeouts surface as an empty result."""
    client = _make_client()

    async def _fake_get(*_args, **_kwargs):
        raise httpx.TimeoutException("timed out")

    with patch.object(client._client, "get", new=_fake_get):
        result = await client.get_earnings(days_ahead=7)
    assert result.events == []


@pytest.mark.asyncio
async def test_http_error_returns_empty_result():
    """R9 — 5xx degrades to empty result, never raises."""
    client = _make_client()

    async def _fake_get(*_args, **_kwargs):
        return _FakeResponse({}, status_code=500)

    with patch.object(client._client, "get", new=_fake_get):
        result = await client.get_earnings(days_ahead=7)
    assert result.events == []


@pytest.mark.asyncio
async def test_malformed_row_skipped():
    """One bad row should not crash the brief — drop it and keep the rest."""
    client = _make_client()
    payload = {
        "from": "2026-05-29",
        "to": "2026-06-05",
        "events": [
            {
                "symbol": "NVDA",
                "entity_id": None,
                "report_date": "2026-05-30",
                "when": "AMC",
                "period": None,
                "consensus_eps": 0.83,
                "consensus_rev_usd": None,
            },
            # Missing report_date — should be silently dropped.
            {
                "symbol": "BADROW",
                "entity_id": None,
                "when": None,
                "period": None,
                "consensus_eps": None,
                "consensus_rev_usd": None,
            },
        ],
    }

    async def _fake_get(*_args, **_kwargs):
        return _FakeResponse(payload)

    with patch.object(client._client, "get", new=_fake_get):
        result = await client.get_earnings(days_ahead=7)
    assert len(result.events) == 1
    assert result.events[0].symbol == "NVDA"


@pytest.mark.asyncio
async def test_empty_calendar_returns_empty_events():
    """The router emits ``events: []`` when the worker hasn't populated yet."""
    client = _make_client()

    async def _fake_get(*_args, **_kwargs):
        return _FakeResponse({"from": "2026-05-29", "to": "2026-06-05", "events": []})

    with patch.object(client._client, "get", new=_fake_get):
        result = await client.get_earnings(days_ahead=7)
    assert result.events == []
    assert result.from_date == date(2026, 5, 29)
