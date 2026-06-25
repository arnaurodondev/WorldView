"""Tests for W5 computed routes (T-S9-07).

Covers:
  - T-S9-01: GET /v1/instruments/{id}/peers proxy
  - T-S9-02: GET /v1/fundamentals/{id}/intraday-stats
  - T-S9-03: GET /v1/fundamentals/{id}/multi-period-returns
  - T-S9-04: GET /v1/fundamentals/{id}/price-levels

All routes require authentication. Tests verify:
  - 401 without auth
  - 200 / expected response shape with auth + S3 mock
  - Fail-soft behaviour when S3 returns non-200 (computed endpoints return nulls)
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
_JWT_PAYLOAD = {"sub": "user-1", "tenant_id": "t-1", "exp": 9999999999}

_INSTRUMENT_UUID = "11111111-1111-1111-1111-111111111111"


def _make_jwt() -> str:
    return jwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _mock_http_response(status: int, content: bytes = b"{}") -> MagicMock:
    """Build a minimal httpx.Response mock with status_code + content."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    resp.text = content.decode()
    # Guard: non-JSON error bodies (e.g. "Internal Server Error") must not crash
    # the mock constructor — .json() raises ValueError for non-JSON content.
    try:
        resp.json.return_value = json.loads(content)
    except json.JSONDecodeError:
        resp.json.side_effect = ValueError("invalid JSON")
    return resp


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_jwt()}"}


# ── T-S9-01: peers proxy ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_peers_proxy_requires_auth(authed_app) -> None:
    """GET /v1/instruments/{id}/peers returns 401 without a Bearer token."""
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/instruments/{_INSTRUMENT_UUID}/peers")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_peers_proxy_forwards_to_s3(authed_app, authed_mock_clients) -> None:
    """GET /v1/instruments/{id}/peers proxies to S3 and returns its response."""
    s3_body = json.dumps(
        {
            "instrument_id": _INSTRUMENT_UUID,
            "industry": "Technology",
            "peers": [
                {
                    "instrument_id": "22222222-2222-2222-2222-222222222222",
                    "ticker": "MSFT",
                    "name": "Microsoft",
                    "market_cap": 3.0e12,
                    "pe_ratio": 35.0,
                    "return_1y": 12.5,
                    "change_pct": 0.3,
                }
            ],
        }
    ).encode()
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_http_response(200, s3_body))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/instruments/{_INSTRUMENT_UUID}/peers",
            params={"limit": "3"},
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["instrument_id"] == _INSTRUMENT_UUID
    assert len(payload["peers"]) == 1
    assert payload["peers"][0]["ticker"] == "MSFT"
    # Verify the limit query param was forwarded to S3.
    call_kwargs = authed_mock_clients.market_data.get.call_args
    assert call_kwargs.kwargs.get("params", {}).get("limit") == "3"


# ── T-S9-02: intraday-stats ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_intraday_stats_requires_auth(authed_app) -> None:
    """GET /v1/fundamentals/{id}/intraday-stats returns 401 without auth."""
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/fundamentals/{_INSTRUMENT_UUID}/intraday-stats")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_intraday_stats_returns_nulls_on_s3_error(authed_app, authed_mock_clients) -> None:
    """When all S3 calls fail, intraday-stats returns 200 with null fields (fail-soft)."""
    # All three S3 calls return 500 — endpoint must not crash.
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_http_response(500, b"Internal Server Error"))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/fundamentals/{_INSTRUMENT_UUID}/intraday-stats",
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["instrument_id"] == _INSTRUMENT_UUID
    # All computed fields must be null when S3 fails.
    assert payload["vwap"] is None
    assert payload["atr_14"] is None
    assert payload["rsi_14"] is None
    assert payload["gap_pct"] is None
    # B-Q-2 required fields must be present (null when data is missing).
    assert "day_open" in payload
    assert "rel_volume" in payload
    assert payload["day_open"] is None
    assert payload["rel_volume"] is None


@pytest.mark.asyncio
async def test_intraday_stats_computes_vwap(authed_app, authed_mock_clients) -> None:
    """VWAP is computed from 5m bars returned by S3."""
    # 3 intraday 5m bars with volume.
    intraday_body = json.dumps(
        {
            "bars": [
                {
                    "timestamp": "2026-05-21T14:35:00",
                    "open": 100.0,
                    "high": 102.0,
                    "low": 99.0,
                    "close": 101.0,
                    "volume": 1000,
                },
                {
                    "timestamp": "2026-05-21T14:40:00",
                    "open": 101.0,
                    "high": 103.0,
                    "low": 100.0,
                    "close": 102.0,
                    "volume": 2000,
                },
                {
                    "timestamp": "2026-05-21T14:45:00",
                    "open": 102.0,
                    "high": 104.0,
                    "low": 101.0,
                    "close": 103.0,
                    "volume": 1500,
                },
            ]
        }
    ).encode()
    # 15 daily bars — enough for ATR/RSI but we just want VWAP here.
    daily_bars = [
        {
            "timestamp": f"2026-05-{i:02d}T00:00:00",
            "open": 100.0,
            "high": 102.0,
            "low": 98.0,
            "close": 100.0 + i,
            "volume": 500000,
        }
        for i in range(1, 16)
    ]
    daily_body = json.dumps({"bars": daily_bars}).encode()
    tech_body = b'{"records": []}'

    # S3 mock: return different responses per call order.
    authed_mock_clients.market_data.get = AsyncMock(
        side_effect=[
            _mock_http_response(200, intraday_body),  # 5m bars (VWAP)
            _mock_http_response(200, daily_body),  # 1d bars (ATR/RSI/GAP)
            _mock_http_response(200, tech_body),  # technicals (SI)
        ]
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/fundamentals/{_INSTRUMENT_UUID}/intraday-stats",
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    payload = resp.json()
    # VWAP = sum(typical x vol) / sum(vol)
    # Bar 1: typical=(102+99+101)/3=100.667, vol=1000
    # Bar 2: typical=(103+100+102)/3=101.667, vol=2000
    # Bar 3: typical=(104+101+103)/3=102.667, vol=1500
    expected_vwap = (100.667 * 1000 + 101.667 * 2000 + 102.667 * 1500) / 4500
    assert payload["vwap"] is not None
    assert abs(payload["vwap"] - expected_vwap) < 0.01


@pytest.mark.asyncio
async def test_intraday_stats_day_open_from_intraday(authed_app, authed_mock_clients) -> None:
    """day_open is the first intraday bar's open when intraday data is available."""
    intraday_body = json.dumps(
        {
            "bars": [
                {
                    "timestamp": "2026-05-21T14:35:00",
                    "open": 155.25,
                    "high": 157.0,
                    "low": 154.0,
                    "close": 156.0,
                    "volume": 1000,
                },
                {
                    "timestamp": "2026-05-21T14:40:00",
                    "open": 156.0,
                    "high": 158.0,
                    "low": 155.0,
                    "close": 157.0,
                    "volume": 2000,
                },
            ]
        }
    ).encode()
    # 15 daily bars — only last bar's open (110.0) is needed as fallback.
    daily_bars = [
        {
            "timestamp": f"2026-05-{i:02d}T00:00:00",
            "open": 100.0 + i,
            "high": 102.0 + i,
            "low": 98.0 + i,
            "close": 100.0 + i,
            "volume": 500000,
        }
        for i in range(1, 16)
    ]
    daily_body = json.dumps({"bars": daily_bars}).encode()
    tech_body = b'{"records": []}'

    authed_mock_clients.market_data.get = AsyncMock(
        side_effect=[
            _mock_http_response(200, intraday_body),
            _mock_http_response(200, daily_body),
            _mock_http_response(200, tech_body),
        ]
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/fundamentals/{_INSTRUMENT_UUID}/intraday-stats",
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    payload = resp.json()
    # day_open must come from the first intraday bar, not the daily bar.
    assert payload["day_open"] == 155.25


@pytest.mark.asyncio
async def test_intraday_stats_day_open_fallback_to_daily(authed_app, authed_mock_clients) -> None:
    """day_open falls back to the last daily bar's open when no intraday data is available."""
    intraday_body = json.dumps({"bars": []}).encode()
    daily_bars = [
        {
            "timestamp": f"2026-05-{i:02d}T00:00:00",
            "open": 200.0 + i,
            "high": 205.0 + i,
            "low": 195.0 + i,
            "close": 202.0 + i,
            "volume": 400000,
        }
        for i in range(1, 16)
    ]
    daily_body = json.dumps({"bars": daily_bars}).encode()
    tech_body = b'{"records": []}'

    authed_mock_clients.market_data.get = AsyncMock(
        side_effect=[
            _mock_http_response(200, intraday_body),
            _mock_http_response(200, daily_body),
            _mock_http_response(200, tech_body),
        ]
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/fundamentals/{_INSTRUMENT_UUID}/intraday-stats",
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    payload = resp.json()
    # day_open should be the last daily bar's open (i=15 → open=200.0+15=215.0).
    assert payload["day_open"] == 215.0
    # rel_volume uses today's daily bar as fallback when no intraday bars exist.
    # All 15 daily bars have volume=400000; baseline (bars[0..13]) avg = 400000;
    # today (bar[14]) volume = 400000 → rel_volume = 1.0.
    assert payload["rel_volume"] is not None
    assert abs(payload["rel_volume"] - 1.0) < 0.001


@pytest.mark.asyncio
async def test_intraday_stats_rel_volume(authed_app, authed_mock_clients) -> None:
    """rel_volume = today_intraday_volume / avg_volume_30d (excluding today's daily bar)."""
    # Two intraday bars with known volumes: 3000 + 7000 = 10 000 today.
    intraday_body = json.dumps(
        {
            "bars": [
                {
                    "timestamp": "2026-05-21T14:35:00",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 3000,
                },
                {
                    "timestamp": "2026-05-21T14:40:00",
                    "open": 100.5,
                    "high": 102.0,
                    "low": 100.0,
                    "close": 101.0,
                    "volume": 7000,
                },
            ]
        }
    ).encode()
    # 16 daily bars: first 15 are baseline (avg vol = 5000 each), last is today.
    # Baseline avg = 5000; today volume = 10 000 → rel_volume = 2.0.
    daily_bars = [
        {
            "timestamp": f"2026-05-{i:02d}T00:00:00",
            "open": 100.0,
            "high": 102.0,
            "low": 98.0,
            "close": 100.0,
            "volume": 5000,
        }
        for i in range(1, 17)  # 16 bars; bar 16 = "today" (excluded from baseline)
    ]
    daily_body = json.dumps({"bars": daily_bars}).encode()
    tech_body = b'{"records": []}'

    authed_mock_clients.market_data.get = AsyncMock(
        side_effect=[
            _mock_http_response(200, intraday_body),
            _mock_http_response(200, daily_body),
            _mock_http_response(200, tech_body),
        ]
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/fundamentals/{_INSTRUMENT_UUID}/intraday-stats",
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    payload = resp.json()
    # today_volume=10000, baseline avg=5000 → rel_volume=2.0
    assert payload["rel_volume"] is not None
    assert abs(payload["rel_volume"] - 2.0) < 0.001


@pytest.mark.asyncio
async def test_intraday_stats_rel_volume_null_when_zero_avg(authed_app, authed_mock_clients) -> None:
    """rel_volume is null when avg_volume_30d is zero (avoid division by zero)."""
    intraday_body = json.dumps(
        {
            "bars": [
                {
                    "timestamp": "2026-05-21T14:35:00",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 5000,
                },
            ]
        }
    ).encode()
    # Daily bars all have volume=0 → avg_volume_30d = 0 → rel_volume must be null.
    daily_bars = [
        {
            "timestamp": f"2026-05-{i:02d}T00:00:00",
            "open": 100.0,
            "high": 102.0,
            "low": 98.0,
            "close": 100.0,
            "volume": 0,
        }
        for i in range(1, 16)
    ]
    daily_body = json.dumps({"bars": daily_bars}).encode()
    tech_body = b'{"records": []}'

    authed_mock_clients.market_data.get = AsyncMock(
        side_effect=[
            _mock_http_response(200, intraday_body),
            _mock_http_response(200, daily_body),
            _mock_http_response(200, tech_body),
        ]
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/fundamentals/{_INSTRUMENT_UUID}/intraday-stats",
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["rel_volume"] is None


@pytest.mark.asyncio
async def test_intraday_stats_rel_volume_daily_fallback(authed_app, authed_mock_clients) -> None:
    """rel_volume uses today's daily bar volume when no intraday bars are available.

    This mirrors the dev/weekend scenario: market is closed so no 5m intraday
    bars are ingested, but the daily bar for today has a completed volume.
    """
    # No intraday bars (market closed / weekend).
    intraday_body = json.dumps({"bars": []}).encode()
    # 16 daily bars: first 15 are baseline (avg vol=10000 each), last is today (vol=20000).
    # Expected rel_volume = 20000 / 10000 = 2.0.
    daily_bars = [
        {
            "timestamp": f"2026-05-{i:02d}T00:00:00",
            "open": 100.0,
            "high": 102.0,
            "low": 98.0,
            "close": 100.0,
            "volume": 10000,
        }
        for i in range(1, 16)  # 15 baseline bars
    ] + [
        {
            "timestamp": "2026-05-16T00:00:00",
            "open": 101.0,
            "high": 103.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 20000,  # today's bar — 2x the average
        }
    ]
    daily_body = json.dumps({"bars": daily_bars}).encode()
    tech_body = b'{"records": []}'

    authed_mock_clients.market_data.get = AsyncMock(
        side_effect=[
            _mock_http_response(200, intraday_body),
            _mock_http_response(200, daily_body),
            _mock_http_response(200, tech_body),
        ]
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/fundamentals/{_INSTRUMENT_UUID}/intraday-stats",
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    payload = resp.json()
    # Daily fallback: baseline avg = 10000, today = 20000 → rel_volume = 2.0.
    assert payload["rel_volume"] is not None
    assert abs(payload["rel_volume"] - 2.0) < 0.001


@pytest.mark.asyncio
async def test_intraday_stats_rel_volume_null_when_today_daily_vol_zero(authed_app, authed_mock_clients) -> None:
    """rel_volume is null when the daily fallback bar has volume=0 (non-trading day)."""
    intraday_body = json.dumps({"bars": []}).encode()
    # 15 baseline bars with non-zero volume + today bar with volume=0.
    daily_bars = [
        {
            "timestamp": f"2026-05-{i:02d}T00:00:00",
            "open": 100.0,
            "high": 102.0,
            "low": 98.0,
            "close": 100.0,
            "volume": 5000,
        }
        for i in range(1, 16)
    ] + [
        {
            "timestamp": "2026-05-16T00:00:00",
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 0,  # non-trading day or no data
        }
    ]
    daily_body = json.dumps({"bars": daily_bars}).encode()
    tech_body = b'{"records": []}'

    authed_mock_clients.market_data.get = AsyncMock(
        side_effect=[
            _mock_http_response(200, intraday_body),
            _mock_http_response(200, daily_body),
            _mock_http_response(200, tech_body),
        ]
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/fundamentals/{_INSTRUMENT_UUID}/intraday-stats",
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    payload = resp.json()
    # volume=0 treated as "no data" to avoid reporting rel_volume=0.0 on non-trading days.
    assert payload["rel_volume"] is None


# ── T-S9-03: multi-period-returns ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multi_period_returns_requires_auth(authed_app) -> None:
    """GET /v1/fundamentals/{id}/multi-period-returns returns 401 without auth."""
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/fundamentals/{_INSTRUMENT_UUID}/multi-period-returns")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_multi_period_returns_structure(authed_app, authed_mock_clients) -> None:
    """multi-period-returns returns a dict with 7 period keys."""
    # Build 260 daily bars so 1Y period has enough data.
    bars = [
        {
            "timestamp": f"2025-{1 + (i // 28):02d}-{1 + (i % 28):02d}T00:00:00",
            "open": 100.0,
            "high": 105.0,
            "low": 95.0,
            "close": 100.0 + i * 0.1,
            "volume": 500000,
        }
        for i in range(260)
    ]
    body = json.dumps({"bars": bars}).encode()
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_http_response(200, body))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/fundamentals/{_INSTRUMENT_UUID}/multi-period-returns",
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["instrument_id"] == _INSTRUMENT_UUID
    periods = payload["periods"]
    # All 7 period keys must be present.
    for key in ("1D", "5D", "1M", "3M", "6M", "YTD", "1Y"):
        assert key in periods, f"Missing period key: {key}"


@pytest.mark.asyncio
async def test_multi_period_returns_nulls_on_s3_error(authed_app, authed_mock_clients) -> None:
    """When S3 fails, all period returns are null."""
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_http_response(500, b"Internal Server Error"))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/fundamentals/{_INSTRUMENT_UUID}/multi-period-returns",
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    payload = resp.json()
    for v in payload["periods"].values():
        assert v is None


# ── T-S9-04: price-levels ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_price_levels_requires_auth(authed_app) -> None:
    """GET /v1/fundamentals/{id}/price-levels returns 401 without auth."""
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/fundamentals/{_INSTRUMENT_UUID}/price-levels")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_price_levels_structure(authed_app, authed_mock_clients) -> None:
    """price-levels returns R3/R2/R1/PIVOT/S1/S2/S3 levels + ma50/ma200."""
    # 210 daily bars: enough for MA200 + pivot computation.
    bars = [
        {
            "timestamp": f"2025-{1 + (i // 28):02d}-{1 + (i % 28):02d}T00:00:00",
            "open": 150.0,
            "high": 155.0 + i * 0.01,
            "low": 145.0 - i * 0.01,
            "close": 150.0 + i * 0.05,
            "volume": 1000000,
        }
        for i in range(210)
    ]
    body = json.dumps({"bars": bars}).encode()
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_http_response(200, body))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/fundamentals/{_INSTRUMENT_UUID}/price-levels",
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["instrument_id"] == _INSTRUMENT_UUID
    levels = payload["levels"]
    assert len(levels) == 7
    labels = [lv["label"] for lv in levels]
    for expected_label in ("R3", "R2", "R1", "PIVOT", "S1", "S2", "S3"):
        assert expected_label in labels
    # MA50 must be populated (we have 210 bars > 50).
    assert payload["ma50"] is not None
    # MA200 must be populated (we have 210 bars > 200).
    assert payload["ma200"] is not None
    # Each level must have value, label, direction.
    for lv in levels:
        assert "value" in lv
        assert "direction" in lv
        assert lv["direction"] in ("above", "below", "at")


@pytest.mark.asyncio
async def test_price_levels_empty_on_insufficient_bars(authed_app, authed_mock_clients) -> None:
    """price-levels returns empty levels list when fewer than 2 bars exist."""
    body = json.dumps(
        {
            "bars": [
                {"timestamp": "2026-05-21", "open": 100.0, "high": 102.0, "low": 98.0, "close": 101.0, "volume": 1000}
            ]
        }
    ).encode()
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_http_response(200, body))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/fundamentals/{_INSTRUMENT_UUID}/price-levels",
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["levels"] == []
    assert payload["ma50"] is None
    assert payload["ma200"] is None
