"""Unit tests for prediction market query use cases (PRD-0019 Wave B-2)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.use_cases.query_prediction_markets import (
    CountPredictionMarketCategoriesUseCase,
    GetPredictionEventUseCase,
    GetPredictionMarketHistoryUseCase,
    GetPredictionMarketPriceHistoryUseCase,
    GetPredictionMarketTradesUseCase,
    GetPredictionMarketUseCase,
    ListPredictionEventsUseCase,
    ListPredictionMarketsUseCase,
)
from market_data.domain.entities import (
    PredictionEvent,
    PredictionMarket,
    PredictionMarketPrice,
    PredictionMarketSnapshot,
    PredictionMarketTrade,
)

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


def _make_price(
    token_id: str = "t1",  # noqa: S107
    interval: str = "1h",
    price: str = "0.72",
    outcome_name: str | None = "Yes",
) -> PredictionMarketPrice:
    return PredictionMarketPrice(
        market_id="mkt-001",
        token_id=token_id,
        interval=interval,
        window_start_ts=_SNAP_AT,
        price=Decimal(price),
        outcome_name=outcome_name,
    )


def _make_trade(
    trade_id: str = "trd-1",
    side: str = "buy",
    size_usd: str | None = "100.0",
) -> PredictionMarketTrade:
    return PredictionMarketTrade(
        market_id="mkt-001",
        trade_id=trade_id,
        token_id="t1",
        price=Decimal("0.72"),
        side=side,
        ts=_SNAP_AT,
        size_usd=Decimal(size_usd) if size_usd is not None else None,
    )


def _make_event(event_id: str = "evt-001", name: str = "Fed decision") -> PredictionEvent:
    return PredictionEvent(
        event_id=event_id,
        name=name,
        category="macro",
        start_date=_NOW,
        end_date=None,
        market_count=3,
    )


def _make_uow(
    market: PredictionMarket | None = None,
    markets: list[PredictionMarket] | None = None,
    total: int = 0,
    snapshots: list[PredictionMarketSnapshot] | None = None,
    latest_prices: dict[str, dict[str, float]] | None = None,
    volumes_by_market: dict[str, Decimal | None] | None = None,
    prices: list[PredictionMarketPrice] | None = None,
    trades: list[PredictionMarketTrade] | None = None,
    events: list[PredictionEvent] | None = None,
    events_total: int = 0,
    event: PredictionEvent | None = None,
) -> MagicMock:
    uow = MagicMock()

    markets_repo = MagicMock()
    markets_repo.find_by_market_id = AsyncMock(return_value=market)
    # PLAN-0048 D-1: ``list_markets`` now returns ``(market, latest_volume_24h)`` pairs.
    # Tests that don't pass ``volumes_by_market`` default to ``None`` per market
    # (matches the previous behaviour where volume was always None).
    volumes = volumes_by_market or {}
    pairs = [(m, volumes.get(m.market_id)) for m in (markets or [])]
    markets_repo.list_markets = AsyncMock(return_value=(pairs, total))
    uow.prediction_markets_read = markets_repo

    snapshots_repo = MagicMock()
    snapshots_repo.list_snapshots = AsyncMock(return_value=snapshots or [])
    snapshots_repo.get_latest_prices_batch = AsyncMock(return_value=latest_prices or {})
    uow.prediction_market_snapshots_read = snapshots_repo

    # PLAN-0056 A4: interval prices / trades / events read repos.
    prices_repo = MagicMock()
    prices_repo.list_prices = AsyncMock(return_value=prices or [])
    uow.prediction_market_prices_read = prices_repo

    trades_repo = MagicMock()
    trades_repo.list_trades = AsyncMock(return_value=trades or [])
    uow.prediction_market_trades_read = trades_repo

    events_repo = MagicMock()
    events_repo.list_events = AsyncMock(return_value=(events or [], events_total))
    events_repo.find_by_event_id = AsyncMock(return_value=event)
    uow.prediction_events_read = events_repo

    return uow


# ── ListPredictionMarketsUseCase ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_markets_returns_tuples() -> None:
    """Execute returns a list of (market, outcomes_prices, volume_24h) tuples and total count."""
    market = _make_market()
    prices = {"Yes": 0.72, "No": 0.28}
    uow = _make_uow(
        markets=[market],
        total=1,
        latest_prices={"mkt-001": prices},
        volumes_by_market={"mkt-001": Decimal("1500.00")},
    )

    uc = ListPredictionMarketsUseCase(uow)
    result, total = await uc.execute(status="open")

    assert total == 1
    assert len(result) == 1
    got_market, got_prices, got_volume = result[0]
    assert got_market is market
    assert got_prices == prices
    # PLAN-0048 D-1: volume_24h is now plumbed through from the repo JOIN.
    assert got_volume == Decimal("1500.00")


@pytest.mark.asyncio
async def test_list_markets_volume_none_when_no_snapshot() -> None:
    """Markets without snapshots get volume_24h=None (LEFT JOIN behaviour)."""
    market = _make_market()
    uow = _make_uow(markets=[market], total=1, latest_prices={"mkt-001": {}})

    uc = ListPredictionMarketsUseCase(uow)
    result, _ = await uc.execute()

    _, _, volume = result[0]
    assert volume is None


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

    _, prices, _vol = result[0]
    assert prices == {}


# ── PLAN-0049 T-C-3-03: category filter (F-QAC-06 fix) ───────────────────────


@pytest.mark.asyncio
async def test_list_markets_forwards_category_to_repo() -> None:
    """Execute forwards category= to the repo port verbatim.

    F-QAC-06: the category filter is the user-visible feature of T-C-3-03.
    Without this assertion the SQL filter could be silently dropped by a
    refactor and no existing test would catch it (the gateway proxy contract
    tests stop one layer above the SQL).
    """
    uow = _make_uow(markets=[], total=0)
    uc = ListPredictionMarketsUseCase(uow)

    await uc.execute(status="open", category="politics")

    call_kwargs = uow.prediction_markets_read.list_markets.call_args.kwargs
    assert call_kwargs["category"] == "politics"


@pytest.mark.asyncio
async def test_list_markets_omits_category_when_not_provided() -> None:
    """Default execute() passes category=None — no filter applied at the SQL layer.

    F-QAC-06: pins the default-arg contract so a future signature change that
    swaps the default to "" or "all" trips the test.
    """
    uow = _make_uow(markets=[], total=0)
    uc = ListPredictionMarketsUseCase(uow)

    await uc.execute(status="open")

    call_kwargs = uow.prediction_markets_read.list_markets.call_args.kwargs
    assert call_kwargs["category"] is None


# ── GetPredictionMarketUseCase ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_market_found_returns_tuple() -> None:
    """execute returns (market, outcomes_prices, volume_24h) when market exists."""
    market = _make_market()
    snapshot = _make_snapshot()
    uow = _make_uow(market=market, snapshots=[snapshot])

    uc = GetPredictionMarketUseCase(uow)
    result = await uc.execute("mkt-001")

    assert result is not None
    got_market, got_prices, got_volume = result
    assert got_market is market
    assert got_prices == {"Yes": 0.72, "No": 0.28}
    # PLAN-0048 D-1: detail also surfaces volume_24h from the latest snapshot.
    assert got_volume == Decimal("1000.0")


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
    _, prices, volume = result
    assert prices == {}
    assert volume is None


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


# ── PLAN-0053 T-C-3-05: count_open_by_category ──────────────────────────────────


@pytest.mark.asyncio
async def test_count_categories_returns_repo_data() -> None:
    """The use case is a thin pass-through over the repo's count_open_by_category."""
    uow = MagicMock()
    repo = MagicMock()
    repo.count_open_by_category = AsyncMock(return_value=[("macro", 12), ("politics", 8), ("crypto", 41)])
    uow.prediction_markets_read = repo

    use_case = CountPredictionMarketCategoriesUseCase(uow)
    result = await use_case.execute()

    assert result == [("macro", 12), ("politics", 8), ("crypto", 41)]
    repo.count_open_by_category.assert_awaited_once()


@pytest.mark.asyncio
async def test_count_categories_handles_null_category() -> None:
    """A NULL category bucket flows through unchanged (frontend handles rendering)."""
    uow = MagicMock()
    repo = MagicMock()
    repo.count_open_by_category = AsyncMock(return_value=[("macro", 5), (None, 3)])
    uow.prediction_markets_read = repo

    use_case = CountPredictionMarketCategoriesUseCase(uow)
    result = await use_case.execute()

    assert result == [("macro", 5), (None, 3)]


@pytest.mark.asyncio
async def test_count_categories_empty() -> None:
    """No open markets → empty list (NOT an error)."""
    uow = MagicMock()
    repo = MagicMock()
    repo.count_open_by_category = AsyncMock(return_value=[])
    uow.prediction_markets_read = repo

    use_case = CountPredictionMarketCategoriesUseCase(uow)
    result = await use_case.execute()

    assert result == []


# ── PLAN-0056 A4: GetPredictionMarketPriceHistoryUseCase ─────────────────────


@pytest.mark.asyncio
async def test_price_history_reads_prices_repo() -> None:
    """When market exists, execute reads interval bars from prices_read.list_prices."""
    market = _make_market()
    bars = [_make_price(interval="1h"), _make_price(interval="1h", price="0.70")]
    uow = _make_uow(market=market, prices=bars)

    uc = GetPredictionMarketPriceHistoryUseCase(uow)
    result = await uc.execute("mkt-001", interval="1h", limit=500)

    assert result is not None
    assert len(result) == 2
    # It must query the prices hypertable, NOT the snapshots repo.
    call_kwargs = uow.prediction_market_prices_read.list_prices.call_args.kwargs
    assert call_kwargs["interval"] == "1h"
    uow.prediction_market_snapshots_read.list_snapshots.assert_not_awaited()


@pytest.mark.asyncio
async def test_price_history_forwards_token_id() -> None:
    """token_id is forwarded verbatim to the repo to narrow to one series."""
    uow = _make_uow(market=_make_market(), prices=[])
    uc = GetPredictionMarketPriceHistoryUseCase(uow)

    await uc.execute("mkt-001", interval="1d", token_id="t1")

    call_kwargs = uow.prediction_market_prices_read.list_prices.call_args.kwargs
    assert call_kwargs["token_id"] == "t1"  # noqa: S105


@pytest.mark.asyncio
async def test_price_history_market_not_found_returns_none() -> None:
    """execute returns None when the market does not exist (→ 404 upstream)."""
    uow = _make_uow(market=None)
    uc = GetPredictionMarketPriceHistoryUseCase(uow)

    result = await uc.execute("missing", interval="1h")
    assert result is None


@pytest.mark.asyncio
async def test_price_history_from_after_to_raises() -> None:
    """from_dt > to_dt raises ValueError (→ 400 upstream)."""
    uow = _make_uow(market=_make_market())
    uc = GetPredictionMarketPriceHistoryUseCase(uow)
    from_dt = datetime(2026, 4, 9, tzinfo=UTC)
    to_dt = datetime(2026, 4, 1, tzinfo=UTC)

    with pytest.raises(ValueError, match="before"):
        await uc.execute("mkt-001", interval="1h", from_dt=from_dt, to_dt=to_dt)


# ── PLAN-0056 A4: GetPredictionMarketTradesUseCase ───────────────────────────


@pytest.mark.asyncio
async def test_trades_returns_list() -> None:
    """execute returns the trade list for an existing market."""
    trades = [_make_trade("trd-1"), _make_trade("trd-2", side="sell")]
    uow = _make_uow(market=_make_market(), trades=trades)

    uc = GetPredictionMarketTradesUseCase(uow)
    result = await uc.execute("mkt-001", limit=100)

    assert result is not None
    assert len(result) == 2


@pytest.mark.asyncio
async def test_trades_forwards_since_filter() -> None:
    """The since bound is forwarded to the repo verbatim."""
    since = datetime(2026, 4, 9, 10, 0, 0, tzinfo=UTC)
    uow = _make_uow(market=_make_market(), trades=[])
    uc = GetPredictionMarketTradesUseCase(uow)

    await uc.execute("mkt-001", since=since, limit=50)

    call_kwargs = uow.prediction_market_trades_read.list_trades.call_args.kwargs
    assert call_kwargs["since"] == since
    assert call_kwargs["limit"] == 50


@pytest.mark.asyncio
async def test_trades_market_not_found_returns_none() -> None:
    """execute returns None when the market does not exist (→ 404 upstream)."""
    uow = _make_uow(market=None)
    uc = GetPredictionMarketTradesUseCase(uow)

    result = await uc.execute("missing")
    assert result is None
    uow.prediction_market_trades_read.list_trades.assert_not_awaited()


# ── PLAN-0056 A4: ListPredictionEventsUseCase / GetPredictionEventUseCase ─────


@pytest.mark.asyncio
async def test_list_events_returns_events_and_total() -> None:
    """execute returns (events, total) straight from the repo."""
    events = [_make_event("evt-001"), _make_event("evt-002", name="Election")]
    uow = _make_uow(events=events, events_total=2)

    uc = ListPredictionEventsUseCase(uow)
    result, total = await uc.execute(limit=50, offset=0)

    assert total == 2
    assert len(result) == 2
    call_kwargs = uow.prediction_events_read.list_events.call_args.kwargs
    assert call_kwargs["limit"] == 50
    assert call_kwargs["offset"] == 0


@pytest.mark.asyncio
async def test_get_event_found_returns_entity() -> None:
    """execute returns the event when it exists."""
    event = _make_event("evt-001")
    uow = _make_uow(event=event)

    uc = GetPredictionEventUseCase(uow)
    result = await uc.execute("evt-001")

    assert result is event


@pytest.mark.asyncio
async def test_get_event_not_found_returns_none() -> None:
    """execute returns None when the event does not exist (→ 404 upstream)."""
    uow = _make_uow(event=None)
    uc = GetPredictionEventUseCase(uow)

    result = await uc.execute("missing")
    assert result is None
