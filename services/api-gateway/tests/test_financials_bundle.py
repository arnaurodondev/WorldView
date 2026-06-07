"""Tests for POST /v1/fundamentals/{instrument_id}/financials-bundle.

PLAN-0099 follow-up E — Financials tab cold-start bundle that collapses
~8 RTTs into 1.

Coverage:
  1. Auth required (no Bearer → 401, no downstream traffic).
  2. Happy path — every leg returns a dict, response shape contains all
     documented fields, leg-to-field routing is correct.
  3. Per-leg failure (non-200) degrades to ``None`` for that field; other
     legs still succeed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt as _pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_SECRET = "test-secret"  # noqa: S105

# Stable test instrument id (UUID-shaped — required by the path-param UUID type).
_IID = "01900000-0000-7000-8000-000000000001"


def _make_jwt(user_id: str = "user-1", tenant_id: str = "tenant-1") -> str:
    """Issue a test HS256 JWT for the conftest TestAuthMiddleware."""
    return _pyjwt.encode(
        {"sub": user_id, "user_id": user_id, "tenant_id": tenant_id},
        _JWT_SECRET,
        algorithm="HS256",
    )


def _make_resp(status: int, data: dict | None) -> MagicMock:
    """Build a mocked httpx.Response with status + JSON body."""
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.json.return_value = data or {}
    r.text = "" if status == 200 else "downstream error"
    r.content = b"{}"
    r.headers = {}
    return r


# Fake payloads — distinguishable per leg so we can verify routing.
_FAKE_FUNDAMENTALS = {"security_id": _IID, "records": [{"section": "highlights"}]}
_FAKE_SNAPSHOT = {"instrument_id": _IID, "eps_ttm": 6.5}
_FAKE_INCOME = {"records": [{"section": "income_statement"}]}
_FAKE_EARNINGS = {"records": [{"section": "earnings_annual_trend"}]}
_FAKE_SHARES = {"records": [{"section": "share_statistics"}]}
_FAKE_SPLITS = {"records": [{"section": "splits_dividends"}]}


def _path_dispatcher(overrides: dict[str, MagicMock] | None = None) -> AsyncMock:
    """Build a market_data.get side_effect that routes by S3 path substring.

    ``overrides`` lets a test override a specific leg with a custom response
    (e.g. a 5xx to exercise per-leg failure paths). Keys are substrings.
    """
    overrides = overrides or {}

    async def _dispatch(path: str, **_kwargs: object) -> MagicMock:
        # Match the most specific path first — /snapshot before /fundamentals/.
        # Path order here mirrors the fan-out in the route.
        if "/snapshot" in path:
            return overrides.get("snapshot") or _make_resp(200, _FAKE_SNAPSHOT)
        if "/income-statement" in path:
            return overrides.get("income") or _make_resp(200, _FAKE_INCOME)
        if "/earnings-annual-trend" in path:
            return overrides.get("earnings") or _make_resp(200, _FAKE_EARNINGS)
        if "/share-statistics" in path:
            return overrides.get("shares") or _make_resp(200, _FAKE_SHARES)
        if "/splits-dividends" in path:
            return overrides.get("splits") or _make_resp(200, _FAKE_SPLITS)
        # Bare /fundamentals/{id} — catch-all (after the more-specific paths).
        return overrides.get("fundamentals") or _make_resp(200, _FAKE_FUNDAMENTALS)

    return AsyncMock(side_effect=_dispatch)


@pytest.mark.asyncio
async def test_financials_bundle_requires_auth(app, mock_clients) -> None:
    """No Bearer → 401, no downstream traffic fired."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/v1/fundamentals/{_IID}/financials-bundle")
    assert resp.status_code == 401
    mock_clients.market_data.get.assert_not_called()


@pytest.mark.asyncio
async def test_financials_bundle_happy_path_keyed_shape(authed_client, authed_mock_clients) -> None:
    """All legs succeed → every documented field is present and routed correctly."""
    authed_mock_clients.market_data.get = _path_dispatcher()

    resp = await authed_client.post(
        f"/v1/fundamentals/{_IID}/financials-bundle",
        headers={"Authorization": f"Bearer {_make_jwt()}"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Every documented field present.
    for key in (
        "fundamentals",
        "fundamentals_snapshot",
        "income_statement",
        "earnings_history",
        "share_statistics",
        "splits_dividends",
        "beat_miss_history",
        "fundamentals_timeseries",
    ):
        assert key in body, f"missing field: {key}"

    # Routing — each leg's payload landed under the right field.
    assert body["fundamentals"] == _FAKE_FUNDAMENTALS
    assert body["fundamentals_snapshot"] == _FAKE_SNAPSHOT
    assert body["income_statement"] == _FAKE_INCOME
    assert body["earnings_history"] == _FAKE_EARNINGS
    assert body["share_statistics"] == _FAKE_SHARES
    assert body["splits_dividends"] == _FAKE_SPLITS
    # beat_miss_history is intentionally aliased to earnings_history (see route docstring).
    assert body["beat_miss_history"] == _FAKE_EARNINGS
    # fundamentals_timeseries is reserved (always None today).
    assert body["fundamentals_timeseries"] is None


@pytest.mark.asyncio
async def test_financials_bundle_per_leg_failure_degrades_to_null(authed_client, authed_mock_clients) -> None:
    """A single failing leg (non-200 downstream) → that field is None; others succeed."""
    # snapshot leg returns 500; everything else is OK.
    authed_mock_clients.market_data.get = _path_dispatcher(
        overrides={"snapshot": _make_resp(500, {"detail": "S3 sick"})}
    )

    resp = await authed_client.post(
        f"/v1/fundamentals/{_IID}/financials-bundle",
        headers={"Authorization": f"Bearer {_make_jwt()}"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()

    # The failing leg is None.
    assert body["fundamentals_snapshot"] is None
    # The other legs flowed through.
    assert body["fundamentals"] == _FAKE_FUNDAMENTALS
    assert body["income_statement"] == _FAKE_INCOME
    assert body["earnings_history"] == _FAKE_EARNINGS
    assert body["share_statistics"] == _FAKE_SHARES
    assert body["splits_dividends"] == _FAKE_SPLITS
    # beat_miss_history alias still mirrors earnings_history.
    assert body["beat_miss_history"] == _FAKE_EARNINGS


@pytest.mark.asyncio
async def test_financials_bundle_transport_error_degrades_to_null(authed_client, authed_mock_clients) -> None:
    """An httpx transport error on one leg → that field is None; others succeed."""

    async def _dispatch(path: str, **_kwargs: object) -> MagicMock:
        if "/share-statistics" in path:
            raise httpx.ConnectError("S3 unreachable")
        if "/snapshot" in path:
            return _make_resp(200, _FAKE_SNAPSHOT)
        if "/income-statement" in path:
            return _make_resp(200, _FAKE_INCOME)
        if "/earnings-annual-trend" in path:
            return _make_resp(200, _FAKE_EARNINGS)
        if "/splits-dividends" in path:
            return _make_resp(200, _FAKE_SPLITS)
        return _make_resp(200, _FAKE_FUNDAMENTALS)

    authed_mock_clients.market_data.get = AsyncMock(side_effect=_dispatch)

    resp = await authed_client.post(
        f"/v1/fundamentals/{_IID}/financials-bundle",
        headers={"Authorization": f"Bearer {_make_jwt()}"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["share_statistics"] is None
    # Other legs still succeed.
    assert body["fundamentals"] == _FAKE_FUNDAMENTALS
    assert body["fundamentals_snapshot"] == _FAKE_SNAPSHOT
