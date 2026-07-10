"""Unit tests for prediction markets API endpoints (PRD-0019 Wave B-2)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import (
    get_list_prediction_markets_uc,
    get_prediction_market_history_uc,
    get_prediction_market_uc,
)
from market_data.api.routers import prediction_markets
from market_data.domain.entities import PredictionMarket, PredictionMarketSnapshot

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 9, 12, 0, 0, tzinfo=UTC)
_SNAP_AT = datetime(2026, 4, 9, 11, 55, 0, tzinfo=UTC)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_market(
    market_id: str = "mkt-001",
    resolution_status: str = "open",
    question: str = "Will the Fed cut rates?",
) -> PredictionMarket:
    return PredictionMarket(
        market_id=market_id,
        question=question,
        outcomes=[{"name": "Yes", "token_id": "t1"}, {"name": "No", "token_id": "t2"}],
        resolution_status=resolution_status,
        close_time=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_snapshot(
    market_id: str = "mkt-001",
    outcomes_prices: dict[str, float] | None = None,
    liquidity: Decimal | None = None,
) -> PredictionMarketSnapshot:
    return PredictionMarketSnapshot(
        market_id=market_id,
        snapshot_at=_SNAP_AT,
        outcomes_prices=outcomes_prices or {"Yes": 0.72, "No": 0.28},
        source_event_id="evt-001",
        volume_24h=Decimal("1500.0"),
        liquidity=liquidity,
    )


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[misc]
    yield


def _make_app(
    list_uc: MagicMock | None = None,
    detail_uc: MagicMock | None = None,
    history_uc: MagicMock | None = None,
) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(prediction_markets.router, prefix="/api/v1")
    # Auth is now handled by InternalJWTMiddleware at the app level (PRD-0025).
    # Unit tests use a bare router app without the middleware, so no auth override needed.
    if list_uc is not None:
        app.dependency_overrides[get_list_prediction_markets_uc] = lambda: list_uc
    if detail_uc is not None:
        app.dependency_overrides[get_prediction_market_uc] = lambda: detail_uc
    if history_uc is not None:
        app.dependency_overrides[get_prediction_market_history_uc] = lambda: history_uc
    return app, TestClient(app)


def _make_list_uc(
    pairs: list[tuple[PredictionMarket, dict[str, float], Decimal | None]] | None = None,
    total: int = 0,
) -> MagicMock:
    # PLAN-0048 D-1: list use case now returns ``(market, prices, volume_24h)`` triples.
    uc = MagicMock()
    uc.execute = AsyncMock(return_value=(pairs or [], total))
    return uc


def _make_detail_uc(result: tuple[PredictionMarket, dict[str, float], Decimal | None] | None) -> MagicMock:
    # PLAN-0048 D-1: detail use case now returns ``(market, prices, volume_24h)``.
    uc = MagicMock()
    uc.execute = AsyncMock(return_value=result)
    return uc


def _make_history_uc(
    snapshots: list[PredictionMarketSnapshot] | None = None,
    raises: Exception | None = None,
) -> MagicMock:
    uc = MagicMock()
    if raises is not None:
        uc.execute = AsyncMock(side_effect=raises)
    else:
        uc.execute = AsyncMock(return_value=snapshots)
    return uc


# ── List endpoint ─────────────────────────────────────────────────────────────


def test_list_markets_endpoint_200() -> None:
    """GET /api/v1/prediction-markets returns 200 with PredictionMarketsListResponse."""
    market = _make_market()
    prices = {"Yes": 0.72, "No": 0.28}
    # PLAN-0048 D-1: include volume_24h in the use case result; the router
    # forwards it through to the response.
    uc = _make_list_uc(pairs=[(market, prices, Decimal("1500.50"))], total=1)
    _, client = _make_app(list_uc=uc)

    resp = client.get("/api/v1/prediction-markets")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["market_id"] == "mkt-001"
    assert item["question"] == "Will the Fed cut rates?"
    assert item["resolution_status"] == "open"
    # PLAN-0048 D-1: list endpoint now surfaces non-null volume_24h.
    assert item["volume_24h"] == pytest.approx(1500.50)


def test_list_markets_endpoint_volume_null_when_no_snapshot() -> None:
    """List endpoint preserves null volume_24h for markets without snapshots."""
    market = _make_market()
    uc = _make_list_uc(pairs=[(market, {}, None)], total=1)
    _, client = _make_app(list_uc=uc)

    resp = client.get("/api/v1/prediction-markets")

    assert resp.status_code == 200
    assert resp.json()["items"][0]["volume_24h"] is None


def test_list_markets_filters_by_status() -> None:
    """?status=resolved passes status='resolved' to the use case."""
    market = _make_market(resolution_status="resolved")
    uc = _make_list_uc(pairs=[(market, {}, None)], total=1)
    _, client = _make_app(list_uc=uc)

    resp = client.get("/api/v1/prediction-markets?status=resolved")

    assert resp.status_code == 200
    uc.execute.assert_awaited_once()
    kwargs = uc.execute.call_args.kwargs
    assert kwargs["status"] == "resolved"
    assert resp.json()["items"][0]["resolution_status"] == "resolved"


def test_list_markets_query_filter() -> None:
    """?query=fed passes the query through to the use case."""
    market = _make_market()
    uc = _make_list_uc(pairs=[(market, {}, None)], total=1)
    _, client = _make_app(list_uc=uc)

    resp = client.get("/api/v1/prediction-markets?query=fed")

    assert resp.status_code == 200
    kwargs = uc.execute.call_args.kwargs
    assert kwargs["query"] == "fed"


def test_list_markets_invalid_limit() -> None:
    """?limit=0 returns 422 (FastAPI param validation)."""
    uc = _make_list_uc()
    _, client = _make_app(list_uc=uc)

    resp = client.get("/api/v1/prediction-markets?limit=0")

    assert resp.status_code == 422


def test_list_markets_invalid_status() -> None:
    """?status=unknown returns 422."""
    uc = _make_list_uc()
    _, client = _make_app(list_uc=uc)

    resp = client.get("/api/v1/prediction-markets?status=unknown")

    assert resp.status_code == 422


def test_list_markets_outcomes_in_response() -> None:
    """Each item contains an outcomes list with price fields."""
    market = _make_market()
    prices = {"Yes": 0.65, "No": 0.35}
    uc = _make_list_uc(pairs=[(market, prices, Decimal("250.00"))], total=1)
    _, client = _make_app(list_uc=uc)

    resp = client.get("/api/v1/prediction-markets")
    item = resp.json()["items"][0]

    assert len(item["outcomes"]) == 2
    yes = next(o for o in item["outcomes"] if o["name"] == "Yes")
    assert yes["price"] == pytest.approx(0.65)


# ── Detail endpoint ───────────────────────────────────────────────────────────


def test_get_market_endpoint_200() -> None:
    """GET /api/v1/prediction-markets/{id} returns PredictionMarketDetailResponse."""
    market = _make_market()
    prices = {"Yes": 0.72, "No": 0.28}
    # PLAN-0048 D-1: detail use case returns (market, prices, volume_24h).
    uc = _make_detail_uc((market, prices, Decimal("999.99")))
    _, client = _make_app(detail_uc=uc)

    resp = client.get("/api/v1/prediction-markets/mkt-001")

    assert resp.status_code == 200
    data = resp.json()
    assert data["market_id"] == "mkt-001"
    assert "created_at" in data  # detail includes created_at
    # PLAN-0048 D-1: detail surfaces non-null volume_24h.
    assert data["volume_24h"] == pytest.approx(999.99)


def test_get_market_endpoint_404() -> None:
    """GET /api/v1/prediction-markets/{id} returns 404 for unknown market."""
    uc = _make_detail_uc(None)
    _, client = _make_app(detail_uc=uc)

    resp = client.get("/api/v1/prediction-markets/nonexistent")

    assert resp.status_code == 404


# ── History endpoint ──────────────────────────────────────────────────────────


def test_get_history_endpoint_200() -> None:
    """GET /api/v1/prediction-markets/{id}/history returns time-series snapshots."""
    snaps = [
        _make_snapshot(outcomes_prices={"Yes": 0.72, "No": 0.28}),
        _make_snapshot(outcomes_prices={"Yes": 0.68, "No": 0.32}),
    ]
    uc = _make_history_uc(snapshots=snaps)
    _, client = _make_app(history_uc=uc)

    resp = client.get("/api/v1/prediction-markets/mkt-001/history")

    assert resp.status_code == 200
    data = resp.json()
    assert data["market_id"] == "mkt-001"
    assert len(data["snapshots"]) == 2
    first = data["snapshots"][0]
    assert "snapshot_at" in first
    assert "outcomes_prices" in first
    assert first["outcomes_prices"]["Yes"] == pytest.approx(0.72)


def test_get_history_exposes_liquidity() -> None:
    """PLAN-0056 A1: each history snapshot surfaces liquidity on the wire.

    A snapshot carrying a Decimal liquidity round-trips into the response as a
    float; a snapshot without liquidity serialises as ``liquidity: null``.
    """
    snaps = [
        _make_snapshot(liquidity=Decimal("12345.67")),
        _make_snapshot(liquidity=None),
    ]
    uc = _make_history_uc(snapshots=snaps)
    _, client = _make_app(history_uc=uc)

    resp = client.get("/api/v1/prediction-markets/mkt-001/history")

    assert resp.status_code == 200
    snapshots = resp.json()["snapshots"]
    assert snapshots[0]["liquidity"] == pytest.approx(12345.67)
    assert snapshots[1]["liquidity"] is None


def test_get_history_endpoint_404() -> None:
    """Returns 404 when history use case returns None (market not found)."""
    uc = _make_history_uc(snapshots=None)
    _, client = _make_app(history_uc=uc)

    resp = client.get("/api/v1/prediction-markets/missing/history")

    assert resp.status_code == 404


def test_history_invalid_date_range() -> None:
    """from_dt > to_dt → use case raises ValueError → 400 response."""
    uc = _make_history_uc(raises=ValueError("from_dt must be strictly before to_dt"))
    _, client = _make_app(history_uc=uc)

    resp = client.get("/api/v1/prediction-markets/mkt-001/history?from=2026-04-09T12:00:00Z&to=2026-04-01T00:00:00Z")

    assert resp.status_code == 400
    assert "before" in resp.json()["detail"]


def test_history_invalid_limit() -> None:
    """?limit=0 returns 422 (FastAPI param validation)."""
    uc = _make_history_uc(snapshots=[])
    _, client = _make_app(history_uc=uc)

    resp = client.get("/api/v1/prediction-markets/mkt-001/history?limit=0")

    assert resp.status_code == 422
