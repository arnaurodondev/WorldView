"""Tests for the F-2 dashboard bundle composer + endpoint.

Verifies:
  1. Happy path — all 6 legs return data, _meta.partial=False.
  2. Partial failure — failing legs degrade to None, others succeed.
  3. Response shape — every documented field is present.
  4. Timeout — TimeoutError → HTTPException(504).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from api_gateway.clients import ServiceClients
from api_gateway.clients.dashboard_bundle import get_dashboard_bundle

pytestmark = pytest.mark.unit


def _make_service_clients() -> ServiceClients:
    """Build a ServiceClients where every field is a MagicMock httpx.AsyncClient."""
    return ServiceClients(
        **{f.name: MagicMock(spec=httpx.AsyncClient) for f in ServiceClients.__dataclass_fields__.values()}
    )


_FAKE_BRIEF = {"summary": "Markets opened higher."}
_FAKE_PORTFOLIOS = {"portfolios": [{"portfolio_id": "p1", "name": "Main"}]}
_FAKE_GAINERS = {"results": [{"ticker": "AAPL", "metrics": {"daily_return": 0.03}}]}
_FAKE_LOSERS = {"results": [{"ticker": "XYZ", "metrics": {"daily_return": -0.05}}]}
_FAKE_HEATMAP = {"sectors": [{"name": "Technology", "change_pct": 1.2}]}
_FAKE_ALERTS = {"alerts": [{"alert_id": "a1", "severity": "HIGH"}]}


def _fake_response(payload: dict | None, status: int = 200) -> MagicMock:
    """Build a MagicMock httpx.Response with .status_code and .json()."""
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.json = MagicMock(return_value=payload or {})
    r.text = "{}"
    r.headers = {}
    r.content = b"{}"
    return r


@pytest.mark.asyncio
async def test_dashboard_bundle_happy_path() -> None:
    """All 6 legs return data → no partial flag, every field populated."""
    clients = _make_service_clients()

    # rag-chat → brief
    clients.rag_chat.get = AsyncMock(return_value=_fake_response(_FAKE_BRIEF))
    # portfolio → portfolios
    clients.portfolio.get = AsyncMock(return_value=_fake_response(_FAKE_PORTFOLIOS))
    # alert → recent_alerts
    clients.alert.get = AsyncMock(return_value=_fake_response(_FAKE_ALERTS))
    # market-data → top_movers (gainers+losers) AND heatmap
    # The composer calls get_top_movers + get_market_heatmap which both go
    # through clients.market_data.get under the hood. We mock those at the
    # module-import level for stability.
    with (
        patch(
            "api_gateway.clients.dashboard_bundle.get_top_movers",
            new=AsyncMock(side_effect=[_FAKE_GAINERS, _FAKE_LOSERS]),
        ),
        patch(
            "api_gateway.clients.dashboard_bundle.get_market_heatmap",
            new=AsyncMock(return_value=_FAKE_HEATMAP),
        ),
    ):
        result = await get_dashboard_bundle(
            clients,
            make_headers=lambda: {"X-Internal-JWT": "stub"},
        )

    # Shape check — every documented field present
    for key in ("brief", "portfolios", "top_gainers", "top_losers", "sector_heatmap", "recent_alerts", "workspace"):
        assert key in result, f"missing field: {key}"

    # Values flow through unchanged
    assert result["brief"] == _FAKE_BRIEF
    assert result["portfolios"] == _FAKE_PORTFOLIOS
    assert result["top_gainers"] == _FAKE_GAINERS
    assert result["top_losers"] == _FAKE_LOSERS
    assert result["sector_heatmap"] == _FAKE_HEATMAP
    assert result["recent_alerts"] == _FAKE_ALERTS
    # workspace is intentionally always None — no upstream endpoint exists.
    assert result["workspace"] is None

    # _meta reports no failures
    assert result["_meta"]["partial"] is False
    assert result["_meta"]["legs_failed"] == 0


@pytest.mark.asyncio
async def test_dashboard_bundle_partial_failure_degrades_to_none() -> None:
    """When some legs raise, those legs degrade to None and others succeed.

    Verifies the per-leg ``except Exception`` guards in the composer.
    """
    clients = _make_service_clients()

    # brief succeeds
    clients.rag_chat.get = AsyncMock(return_value=_fake_response(_FAKE_BRIEF))
    # portfolios fails
    clients.portfolio.get = AsyncMock(side_effect=RuntimeError("S1 down"))
    # alerts succeed
    clients.alert.get = AsyncMock(return_value=_fake_response(_FAKE_ALERTS))

    with (
        patch(
            "api_gateway.clients.dashboard_bundle.get_top_movers",
            # gainers OK, losers raises
            new=AsyncMock(side_effect=[_FAKE_GAINERS, RuntimeError("S3 movers down")]),
        ),
        patch(
            "api_gateway.clients.dashboard_bundle.get_market_heatmap",
            new=AsyncMock(side_effect=RuntimeError("S3 heatmap down")),
        ),
    ):
        result = await get_dashboard_bundle(clients)

    # Successful legs
    assert result["brief"] == _FAKE_BRIEF
    assert result["top_gainers"] == _FAKE_GAINERS
    assert result["recent_alerts"] == _FAKE_ALERTS
    # Failed legs degrade to None
    assert result["portfolios"] is None
    assert result["top_losers"] is None
    assert result["sector_heatmap"] is None
    # workspace always None
    assert result["workspace"] is None

    # _meta reflects the 3 failures
    assert result["_meta"]["partial"] is True
    assert result["_meta"]["legs_failed"] == 3


@pytest.mark.asyncio
async def test_dashboard_bundle_timeout_raises_504() -> None:
    """Overall timeout → HTTPException(504)."""
    from fastapi import HTTPException

    clients = _make_service_clients()

    # Make brief hang forever — asyncio.wait_for will raise TimeoutError.
    async def _hang(*_a: object, **_kw: object) -> object:
        import asyncio

        await asyncio.sleep(10)
        return {}

    clients.rag_chat.get = AsyncMock(side_effect=_hang)
    clients.portfolio.get = AsyncMock(return_value=_fake_response(_FAKE_PORTFOLIOS))
    clients.alert.get = AsyncMock(return_value=_fake_response(_FAKE_ALERTS))

    with (
        patch(
            "api_gateway.clients.dashboard_bundle.get_top_movers",
            new=AsyncMock(return_value=_FAKE_GAINERS),
        ),
        patch(
            "api_gateway.clients.dashboard_bundle.get_market_heatmap",
            new=AsyncMock(return_value=_FAKE_HEATMAP),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        # Tight timeout so the test runs fast.
        await get_dashboard_bundle(clients, overall_timeout_s=0.05)

    assert exc_info.value.status_code == 504
