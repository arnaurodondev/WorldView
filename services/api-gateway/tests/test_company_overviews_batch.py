"""Tests for POST /v1/companies/overviews:batch (FIX F-1).

The batch endpoint fans-in N company-overview lookups into one round-trip so
dashboard widgets (PreMarketMoversWidget, SectorHeatmapWidget, PortfolioSummary)
no longer fire one HTTP request per ticker.

Coverage:
  1. Auth required (missing Bearer → 401, no downstream traffic).
  2. Happy path: each id returns a CompanyOverview-shaped dict, keyed by the
     original id.
  3. Per-leg failure ⇒ that id maps to null (other legs still succeed).
  4. Validation: empty `instrument_ids` ⇒ 422.
  5. Validation: >50 `instrument_ids` ⇒ 422.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt as _pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_SECRET = "test-secret"  # noqa: S105


def _make_jwt(user_id: str = "user-1", tenant_id: str = "tenant-1") -> str:
    """Issue a test HS256 JWT for use with authed_app's TestAuthMiddleware."""
    return _pyjwt.encode(
        {"sub": user_id, "user_id": user_id, "tenant_id": tenant_id},
        _JWT_SECRET,
        algorithm="HS256",
    )


def _make_resp(status: int, data: dict) -> MagicMock:
    """Build a mocked httpx.Response with status + JSON body."""
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.json.return_value = data
    r.text = "" if status == 200 else "downstream error"
    return r


@pytest.mark.asyncio
async def test_overviews_batch_requires_auth(app, mock_clients) -> None:
    """No Bearer → 401, downstream untouched."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/companies/overviews:batch",
            json={"instrument_ids": ["01900000-0000-7000-8000-000000000001"]},
        )
    assert resp.status_code == 401
    mock_clients.market_data.get.assert_not_called()


@pytest.mark.asyncio
async def test_overviews_batch_happy_path_returns_keyed_map(authed_client, authed_mock_clients) -> None:
    """Each requested id maps to a CompanyOverview-shaped dict.

    Uses the same mock-dispatcher pattern as test_company_overview_composes_responses
    so the underlying get_company_overview helper sees a realistic 4-leg
    market-data fanout.
    """
    id_a = "01900000-0000-7000-8000-000000000001"
    id_b = "01900000-0000-7000-8000-000000000002"

    inst_a = {"id": id_a, "symbol": "AAPL", "exchange": "NASDAQ", "is_active": True}
    inst_b = {"id": id_b, "symbol": "MSFT", "exchange": "NASDAQ", "is_active": True}
    profile = {"records": [{"data": {"Name": "Co", "Currency": "USD"}}]}
    ohlcv = {"items": [], "total": 0, "timeframe": "1d"}
    quote = {"instrument_id": id_a, "last": "100.0", "volume": 0, "timestamp": "2026-06-01T00:00:00Z"}
    fundamentals = {"security_id": id_a, "records": []}

    async def _dispatch(path: str, **kwargs: object) -> MagicMock:
        # WHY route by URL substring: get_company_overview fans 4-5 parallel
        # calls per id; the mock must answer each consistently regardless of
        # asyncio ordering.
        if "ohlcv" in path:
            return _make_resp(200, ohlcv)
        if "quotes" in path:
            return _make_resp(200, quote)
        if "company-profile" in path:
            return _make_resp(200, profile)
        if "fundamentals" in path:
            return _make_resp(200, fundamentals)
        # /api/v1/instruments/{id} — route by id substring
        if id_b in path:
            return _make_resp(200, inst_b)
        return _make_resp(200, inst_a)

    authed_mock_clients.market_data.get = AsyncMock(side_effect=_dispatch)

    transport = ASGITransport(app=authed_client._transport.app)  # type: ignore[attr-defined]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/companies/overviews:batch",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
            json={"instrument_ids": [id_a, id_b]},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "overviews" in body
    overviews = body["overviews"]
    # Both ids present in the response map.
    assert set(overviews.keys()) == {id_a, id_b}
    # Each value is either null or a dict with the expected top-level keys.
    for id_ in (id_a, id_b):
        ov = overviews[id_]
        assert ov is not None, f"leg for {id_} should not have failed"
        for key in ("instrument", "quote", "ohlcv", "fundamentals"):
            assert key in ov


@pytest.mark.asyncio
async def test_overviews_batch_leg_failure_maps_to_null(authed_client, authed_mock_clients) -> None:
    """A single failing leg returns null for that id; other legs still succeed."""
    id_ok = "01900000-0000-7000-8000-000000000010"
    id_fail = "01900000-0000-7000-8000-000000000099"

    inst_ok = {"id": id_ok, "symbol": "OK", "exchange": "NASDAQ", "is_active": True}
    profile = {"records": []}
    ohlcv = {"items": [], "total": 0, "timeframe": "1d"}
    quote = {"instrument_id": id_ok, "last": "1.0", "volume": 0, "timestamp": "2026-06-01T00:00:00Z"}

    async def _dispatch(path: str, **kwargs: object) -> MagicMock:
        # The failing id 404s on EVERY downstream call (instrument lookup AND
        # KG fallback), which triggers DownstreamError → gathered as exception.
        if id_fail in path:
            return _make_resp(404, {"detail": "not found"})
        if "ohlcv" in path:
            return _make_resp(200, ohlcv)
        if "quotes" in path:
            return _make_resp(200, quote)
        if "company-profile" in path or "fundamentals" in path:
            return _make_resp(200, profile)
        return _make_resp(200, inst_ok)

    authed_mock_clients.market_data.get = AsyncMock(side_effect=_dispatch)
    # KG fallback also 404s for the failing id (so resolve_security_id raises).
    authed_mock_clients.knowledge_graph.get = AsyncMock(return_value=_make_resp(404, {"detail": "not found"}))

    transport = ASGITransport(app=authed_client._transport.app)  # type: ignore[attr-defined]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/companies/overviews:batch",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
            json={"instrument_ids": [id_ok, id_fail]},
        )

    assert resp.status_code == 200, resp.text
    overviews = resp.json()["overviews"]
    assert overviews[id_ok] is not None
    assert overviews[id_fail] is None


@pytest.mark.asyncio
async def test_overviews_batch_empty_returns_422(authed_client) -> None:
    """Empty `instrument_ids` is rejected by pydantic min_length=1."""
    resp = await authed_client.post(
        "/v1/companies/overviews:batch",
        headers={"Authorization": f"Bearer {_make_jwt()}"},
        json={"instrument_ids": []},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_overviews_batch_over_50_returns_422(authed_client) -> None:
    """>50 ids → 422 (max_length cap protects downstream from fan-out abuse)."""
    ids = [f"01900000-0000-7000-8000-{i:012d}" for i in range(51)]
    resp = await authed_client.post(
        "/v1/companies/overviews:batch",
        headers={"Authorization": f"Bearer {_make_jwt()}"},
        json={"instrument_ids": ids},
    )
    assert resp.status_code == 422
