"""Unit tests for MarketTapeClient (PLAN-0102 W3 T-W3-03).

We mock the underlying ``httpx.AsyncClient.get`` rather than using respx
because respx is not in the rag-chat dev-deps and the patch-the-attribute
pattern matches the precedent set by ``test_s3_brief_client.py``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

pytestmark = pytest.mark.unit


def _make_client():
    from rag_chat.infrastructure.clients.market_tape_client import MarketTapeClient

    return MarketTapeClient(base_url="http://market-data.mock", timeout=5.0)


class _FakeResponse:
    """Minimal stand-in for httpx.Response — just enough for the client."""

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
async def test_happy_path_three_tickers():
    """Three tickers come back parsed into MarketTapeItems."""
    client = _make_client()
    payload = {
        "as_of": "2026-05-29T07:00:00+00:00",
        "tickers": [
            {"symbol": "SPY", "last_close": 542.13, "premkt_price": 543.20, "premkt_pct": 0.20, "session": "pre-mkt"},
            {"symbol": "QQQ", "last_close": 469.55, "premkt_price": 470.50, "premkt_pct": 0.20, "session": "pre-mkt"},
            {"symbol": "VIX", "last_close": 14.2, "premkt_price": 14.3, "premkt_pct": 0.70, "session": "open"},
        ],
    }
    captured_params: dict = {}

    async def _fake_get(path, params=None, headers=None):
        captured_params.update(params or {})
        return _FakeResponse(payload)

    with patch.object(client._client, "get", new=_fake_get):
        result = await client.get_tape(["SPY", "QQQ", "VIX"])

    assert captured_params["symbols"] == "SPY,QQQ,VIX"
    assert len(result.tickers) == 3
    assert result.tickers[0].symbol == "SPY"
    assert result.tickers[0].premkt_pct == 0.20
    assert result.tickers[2].session == "open"


@pytest.mark.asyncio
async def test_empty_symbol_list_returns_empty_result_without_calling_upstream():
    """Defensive — empty input skips the HTTP call entirely (no 422)."""
    client = _make_client()
    mock_get = AsyncMock()
    with patch.object(client._client, "get", new=mock_get):
        result = await client.get_tape([])
    mock_get.assert_not_awaited()
    assert result.tickers == []


@pytest.mark.asyncio
async def test_timeout_returns_empty_result():
    """R9 — timeouts surface as an empty result, never propagate."""
    client = _make_client()

    async def _fake_get(*_args, **_kwargs):
        raise httpx.TimeoutException("timed out")

    with patch.object(client._client, "get", new=_fake_get):
        result = await client.get_tape(["SPY"])
    assert result.tickers == []


@pytest.mark.asyncio
async def test_http_error_returns_empty_result():
    """R9 — 401/500 from market-data degrades to empty result."""
    client = _make_client()

    async def _fake_get(*_args, **_kwargs):
        return _FakeResponse({}, status_code=401)

    with patch.object(client._client, "get", new=_fake_get):
        result = await client.get_tape(["SPY"])
    assert result.tickers == []


@pytest.mark.asyncio
async def test_malformed_row_is_skipped_but_others_returned():
    """A bad row should not crash the brief — drop the row, keep the rest."""
    client = _make_client()
    payload = {
        "as_of": "2026-05-29T07:00:00+00:00",
        "tickers": [
            {"symbol": "SPY", "last_close": 540.0, "premkt_price": 541.0, "premkt_pct": 0.2, "session": "pre-mkt"},
            # Missing ``symbol`` — should be silently skipped.
            {"last_close": 100.0, "premkt_price": 101.0, "premkt_pct": 1.0, "session": "pre-mkt"},
        ],
    }

    async def _fake_get(*_args, **_kwargs):
        return _FakeResponse(payload)

    with patch.object(client._client, "get", new=_fake_get):
        result = await client.get_tape(["SPY", "BADROW"])
    assert len(result.tickers) == 1
    assert result.tickers[0].symbol == "SPY"


@pytest.mark.asyncio
async def test_null_premkt_price_passes_through():
    """``unavailable`` rows are preserved with None price + pct."""
    client = _make_client()
    payload = {
        "as_of": "2026-05-29T07:00:00+00:00",
        "tickers": [
            {
                "symbol": "VIX",
                "last_close": None,
                "premkt_price": None,
                "premkt_pct": None,
                "session": "unavailable",
            },
        ],
    }

    async def _fake_get(*_args, **_kwargs):
        return _FakeResponse(payload)

    with patch.object(client._client, "get", new=_fake_get):
        result = await client.get_tape(["VIX"])
    t = result.tickers[0]
    assert t.session == "unavailable"
    assert t.premkt_price is None
    assert t.last_close is None
