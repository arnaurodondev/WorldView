"""Unit tests for prediction market query use cases (PRD-0019 Wave B-2)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.use_cases.query_prediction_markets import (
    GetPredictionMarketHistoryUseCase,
    GetPredictionMarketUseCase,
    ListPredictionMarketsUseCase,
)
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
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_snapshot(
    market_id: str = "mkt-001",
    outcomes_prices: dict[str, float] | None = None,
) -> PredictionMarketSnapshot:
    return PredictionMarketSnapshot(
        market_id=market_id,
        snapshot_at=_SNAP_AT,
        outcomes_prices=outcomes_prices or {"Yes": 0.72, "No": 0.28},
        source_event_id="evt-001",
        volume_24h=Decimal("1000.0"),
    )


def _make_uow(
    market: PredictionMarket | None = None,
    markets: list[PredictionMarket] | None = None,
    total: int = 0,
    snapshots: list[PredictionMarketSnapshot] | None = None,
    latest_prices: dict[str, dict[str, float]] | None = None,
) -> MagicMock:
    uow = MagicMock()

    markets_repo = MagicMock()
    markets_repo.find_by_market_id = AsyncMock(return_value=market)
    markets_repo.list_markets = AsyncMock(return_value=(markets or [], total))
    uow.prediction_markets_read = markets_repo

    snapshots_repo = MagicMock()
    snapshots_repo.list_snapshots = AsyncMock(return_value=snapshots or [])
    snapshots_repo.get_latest_prices_batch = AsyncMock(return_value=latest_prices or {})
    uow.prediction_market_snapshots_read = snapshots_repo

    return uow


# ── ListPredictionMarketsUseCase ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_markets_returns_tuples() -> None:
    """Execute returns a list of (market, outcomes_prices) tuples and total count."""
    market = _make_market()
    prices = {"Yes": 0.72, "No": 0.28}
    uow = _make_uow(markets=[market], total=1, latest_prices={"mkt-001": prices})

    uc = ListPredictionMarketsUseCase(uow)
    result, total = await uc.execute(status="open")

    assert total == 1
    assert len(result) == 1
    got_market, got_prices = result[0]
    assert got_market is market
    assert got_prices == prices


@pytest.mark.asyncio
async def test_list_markets_empty_returns_empty_list() -> None:
    """Empty result set returns ([], 0) without calling get_latest_prices_batch."""
    uow = _make_uow(markets=[], total=0)
    uc = ListPredictionMarketsUseCase(uow)

    result, total = await uc.execute()

    assert result == []
    assert total == 0
    uow.prediction_market_snapshots_read.get_latest_prices_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_markets_status_all_passes_none_to_repo() -> None:
    """status='all' is translated to None (no status filter) before repo call."""
    uow = _make_uow(markets=[], total=0)
    uc = ListPredictionMarketsUseCase(uow)
    await uc.execute(status="all")

    uow.prediction_markets_read.list_markets.assert_awaited_once()
    call_kwargs = uow.prediction_markets_read.list_markets.call_args.kwargs
    assert call_kwargs["status"] is None


@pytest.mark.asyncio
async def test_list_markets_missing_price_defaults_to_empty_dict() -> None:
    """Markets with no snapshot get an empty prices dict (not a KeyError)."""
    market = _make_market()
    uow = _make_uow(markets=[market], total=1, latest_prices={})  # no prices for mkt-001

    uc = ListPredictionMarketsUseCase(uow)
    result, _ = await uc.execute()

    _, prices = result[0]
    assert prices == {}


# ── GetPredictionMarketUseCase ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_market_found_returns_tuple() -> None:
    """execute returns (market, outcomes_prices) when market exists."""
    market = _make_market()
    snapshot = _make_snapshot()
    uow = _make_uow(market=market, snapshots=[snapshot])

    uc = GetPredictionMarketUseCase(uow)
    result = await uc.execute("mkt-001")

    assert result is not None
    got_market, got_prices = result
    assert got_market is market
    assert got_prices == {"Yes": 0.72, "No": 0.28}


@pytest.mark.asyncio
async def test_get_market_not_found_returns_none() -> None:
    """execute returns None when market_id does not exist."""
    uow = _make_uow(market=None)
    uc = GetPredictionMarketUseCase(uow)

    result = await uc.execute("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_market_no_snapshots_returns_empty_prices() -> None:
    """When no snapshots exist the prices dict is empty (not an error)."""
    market = _make_market()
    uow = _make_uow(market=market, snapshots=[])

    uc = GetPredictionMarketUseCase(uow)
    result = await uc.execute("mkt-001")

    assert result is not None
    _, prices = result
    assert prices == {}


# ── GetPredictionMarketHistoryUseCase ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_returns_snapshots() -> None:
    """execute returns the snapshot list for an existing market."""
    market = _make_market()
    snap1 = _make_snapshot()
    snap2 = _make_snapshot(outcomes_prices={"Yes": 0.68, "No": 0.32})
    uow = _make_uow(market=market, snapshots=[snap1, snap2])

    uc = GetPredictionMarketHistoryUseCase(uow)
    result = await uc.execute("mkt-001", limit=500)

    assert result is not None
    assert len(result) == 2


@pytest.mark.asyncio
async def test_history_market_not_found_returns_none() -> None:
    """execute returns None when market does not exist."""
    uow = _make_uow(market=None)
    uc = GetPredictionMarketHistoryUseCase(uow)

    result = await uc.execute("missing-market")
    assert result is None


@pytest.mark.asyncio
async def test_use_case_history_from_equals_to_raises() -> None:
    """from_dt == to_dt raises ValueError."""
    uow = _make_uow()
    uc = GetPredictionMarketHistoryUseCase(uow)
    dt = datetime(2026, 4, 1, tzinfo=UTC)

    with pytest.raises(ValueError, match="before"):
        await uc.execute("mkt-001", from_dt=dt, to_dt=dt)


@pytest.mark.asyncio
async def test_use_case_history_from_after_to_raises() -> None:
    """from_dt > to_dt raises ValueError."""
    uow = _make_uow()
    uc = GetPredictionMarketHistoryUseCase(uow)
    from_dt = datetime(2026, 4, 9, tzinfo=UTC)
    to_dt = datetime(2026, 4, 1, tzinfo=UTC)

    with pytest.raises(ValueError):
        await uc.execute("mkt-001", from_dt=from_dt, to_dt=to_dt)


# ── test_outcome_price_assembly (integration of router logic) ────────────────
# The assembly is done by _build_outcomes in the router — test it here inline
# to satisfy the plan's test spec (test_outcome_price_assembly).


def test_outcome_price_assembly() -> None:
    """OutcomePrice[] built from market.outcomes + latest snapshot prices; fallback to 0.0."""
    from market_data.api.routers.prediction_markets import _build_outcomes

    outcomes = [
        {"name": "Yes", "token_id": "t1"},
        {"name": "No", "token_id": "t2"},
        {"name": "Undecided", "token_id": "t3"},
    ]
    prices = {"Yes": 0.72, "No": 0.28}

    result = _build_outcomes(outcomes, prices)

    assert len(result) == 3
    yes = next(r for r in result if r.name == "Yes")
    no = next(r for r in result if r.name == "No")
    undecided = next(r for r in result if r.name == "Undecided")

    assert yes.price == 0.72
    assert no.price == 0.28
    assert undecided.price == 0.0  # fallback for missing outcome
    assert yes.token_id == "t1"  # noqa: S105
