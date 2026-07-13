"""Unit tests for PredictionMoveDetector (PLAN-0056 Wave D1, T-D-1-01).

The detector scans open prediction markets, measures Δ implied-probability over
a window, gates on |Δ| + liquidity + volume, and emits ``market.prediction.move``
events through the outbox. These tests mock the UnitOfWork / repos entirely — no
DB, no Kafka.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.domain.entities import PredictionMarket, PredictionMarketSnapshot
from market_data.infrastructure.workers.prediction_move_detector import (
    PredictionMoveDetector,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=UTC)
_MARKET_ID = "0xcondition_abc"
_TOK_YES = "tok_yes"
_TOK_NO = "tok_no"


def _settings(**overrides: object) -> SimpleNamespace:
    """Minimal settings stub exposing only the fields the detector reads."""
    base = {
        "prediction_move_window_hours": 24,
        "prediction_move_interval_label": "1d",
        "prediction_move_delta_threshold": 0.15,
        "prediction_move_min_liquidity_usd": 5_000.0,
        "prediction_move_min_volume_usd": 1_000.0,
        "prediction_move_market_page_size": 200,
        "prediction_move_snapshot_limit": 500,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _market(
    *,
    market_id: str = _MARKET_ID,
    resolution_status: str = "open",
    outcomes: list[dict] | None = None,
) -> PredictionMarket:
    if outcomes is None:
        outcomes = [
            {"name": "Yes", "token_id": _TOK_YES},
            {"name": "No", "token_id": _TOK_NO},
        ]
    return PredictionMarket(
        market_id=market_id,
        question="Will X happen?",
        outcomes=outcomes,
        resolution_status=resolution_status,
    )


def _snapshot(
    *,
    snapshot_at: datetime,
    yes: float,
    no: float,
    liquidity: float | None = 10_000.0,
    volume_24h: float | None = 5_000.0,
) -> PredictionMarketSnapshot:
    return PredictionMarketSnapshot(
        market_id=_MARKET_ID,
        snapshot_at=snapshot_at,
        outcomes_prices={"Yes": yes, "No": no},
        source_event_id="evt-1",
        liquidity=None if liquidity is None else Decimal(str(liquidity)),
        volume_24h=None if volume_24h is None else Decimal(str(volume_24h)),
    )


def _make_uow(
    *,
    markets: list[PredictionMarket],
    snapshots: list[PredictionMarketSnapshot],
    earliest: PredictionMarketSnapshot | None | object = ...,
) -> MagicMock:
    """Build a fully-mocked UoW returning ``markets`` then an empty page.

    ``earliest`` is what ``get_earliest_snapshot_at_or_after`` returns (the true
    window-start baseline, FIX 2). Defaults (``...``) to ``snapshots[-1]`` — the
    genuine earliest for a short list — so existing 2-snapshot tests keep their
    semantics; pass an explicit value to simulate a LIMIT-truncated scan.
    """
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)

    total = len(markets)

    async def _list_markets(*, status: str, query: object, limit: int, offset: int):
        # Single page: return everything at offset 0, empty afterwards.
        if offset == 0:
            return ([(m, None) for m in markets], total)
        return ([], total)

    uow.prediction_markets_read = MagicMock()
    uow.prediction_markets_read.list_markets = AsyncMock(side_effect=_list_markets)

    resolved_earliest = (snapshots[-1] if snapshots else None) if earliest is ... else earliest

    uow.prediction_market_snapshots_read = MagicMock()
    uow.prediction_market_snapshots_read.list_snapshots = AsyncMock(return_value=snapshots)
    uow.prediction_market_snapshots_read.get_earliest_snapshot_at_or_after = AsyncMock(
        return_value=resolved_earliest,
    )

    uow.outbox_events = MagicMock()
    uow.outbox_events.create = AsyncMock(return_value="outbox-row-1")
    uow.commit = AsyncMock()
    return uow


def _two_snapshots(*, yes_start: float, yes_end: float, **kw: object) -> list[PredictionMarketSnapshot]:
    """Return [latest, earliest] (DESC by snapshot_at) — the repo contract."""
    earliest = _snapshot(snapshot_at=_NOW - timedelta(hours=20), yes=yes_start, no=1 - yes_start)
    latest = _snapshot(
        snapshot_at=_NOW,
        yes=yes_end,
        no=1 - yes_end,
        **kw,  # type: ignore[arg-type]
    )
    return [latest, earliest]


class TestEmitsOnMaterialMove:
    """Move above threshold + sufficient liquidity/volume → exactly 1 (affirmative) event."""

    @pytest.mark.asyncio
    async def test_emits_single_affirmative_move_with_correct_fields(self) -> None:
        # FIX-1 regression: a binary market where BOTH outcomes clear the gate
        # (Yes 0.40→0.65 = +0.25; No 0.60→0.35 = -0.25) must emit exactly ONE
        # event — for the affirmative (Yes) token — NEVER a second No event.
        snaps = _two_snapshots(yes_start=0.40, yes_end=0.65)
        uow = _make_uow(markets=[_market()], snapshots=snaps)
        detector = PredictionMoveDetector(uow_factory=lambda: uow, settings=_settings())

        emitted = await detector.run_cycle()

        # Affirmative-only → exactly one event, never the complementary No event.
        assert emitted == 1
        assert uow.outbox_events.create.await_count == 1
        uow.commit.assert_awaited_once()

        call = uow.outbox_events.create.await_args_list[0]
        assert call.kwargs["event_type"] == "market.prediction.move"
        assert call.kwargs["topic"] == "market.prediction.move.v1"
        assert call.kwargs["partition_key"] == _MARKET_ID
        p = call.kwargs["payload"]
        # The single event is the affirmative (Yes) token, NOT the No token.
        assert p["token_id"] == _TOK_YES
        assert p["market_id"] == _MARKET_ID
        assert p["outcome_name"] == "Yes"
        assert p["direction"] == "up"
        assert p["prev_price"] == pytest.approx(0.40)
        assert p["new_price"] == pytest.approx(0.65)
        assert p["delta"] == pytest.approx(0.25)
        assert p["liquidity"] == pytest.approx(10_000.0)
        assert p["volume_24h"] == pytest.approx(5_000.0)
        assert p["is_backfill"] is False

        # Explicitly assert the No token was never emitted (complementary-collapse
        # eliminated at the source).
        emitted_tokens = {c.kwargs["payload"]["token_id"] for c in uow.outbox_events.create.await_args_list}
        assert _TOK_NO not in emitted_tokens

    @pytest.mark.asyncio
    async def test_direction_down_and_token_resolution(self) -> None:
        # Yes 0.80 → 0.50 = -0.30 (down). Affirmative-only → one Yes event.
        snaps = _two_snapshots(yes_start=0.80, yes_end=0.50)
        uow = _make_uow(markets=[_market()], snapshots=snaps)
        detector = PredictionMoveDetector(uow_factory=lambda: uow, settings=_settings())

        emitted = await detector.run_cycle()

        assert emitted == 1
        p = uow.outbox_events.create.await_args_list[0].kwargs["payload"]
        assert p["outcome_name"] == "Yes"
        assert p["direction"] == "down"
        assert p["token_id"] == _TOK_YES

    @pytest.mark.asyncio
    async def test_no_yes_outcome_falls_back_to_first_outcome(self) -> None:
        # No outcome named "yes" → the FIRST outcome (list order) is the
        # affirmative. "Trump" 0.40 → 0.65 = +0.25 clears; "Biden" is ignored.
        market = _market(
            outcomes=[
                {"name": "Trump", "token_id": "tok_trump"},
                {"name": "Biden", "token_id": "tok_biden"},
            ],
        )
        # Snapshot prices are keyed by the market's outcome names (frozen entity,
        # so build with the right keys directly rather than mutating).
        earliest = PredictionMarketSnapshot(
            market_id=_MARKET_ID,
            snapshot_at=_NOW - timedelta(hours=20),
            outcomes_prices={"Trump": 0.40, "Biden": 0.60},
            source_event_id="evt-1",
            liquidity=Decimal("10000"),
            volume_24h=Decimal("5000"),
        )
        latest = PredictionMarketSnapshot(
            market_id=_MARKET_ID,
            snapshot_at=_NOW,
            outcomes_prices={"Trump": 0.65, "Biden": 0.35},
            source_event_id="evt-1",
            liquidity=Decimal("10000"),
            volume_24h=Decimal("5000"),
        )
        uow = _make_uow(markets=[market], snapshots=[latest, earliest])
        detector = PredictionMoveDetector(uow_factory=lambda: uow, settings=_settings())

        emitted = await detector.run_cycle()

        assert emitted == 1
        p = uow.outbox_events.create.await_args_list[0].kwargs["payload"]
        assert p["outcome_name"] == "Trump"
        assert p["token_id"] == "tok_trump"  # noqa: S105 — test fixture token id, not a secret
        assert p["direction"] == "up"


class TestGates:
    """Every gate must independently suppress emission."""

    @pytest.mark.asyncio
    async def test_below_delta_threshold_no_emit(self) -> None:
        # +0.10 < 0.15 → suppressed.
        snaps = _two_snapshots(yes_start=0.40, yes_end=0.50)
        uow = _make_uow(markets=[_market()], snapshots=snaps)
        detector = PredictionMoveDetector(uow_factory=lambda: uow, settings=_settings())

        emitted = await detector.run_cycle()

        assert emitted == 0
        uow.outbox_events.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_insufficient_liquidity_no_emit(self) -> None:
        # Material Δ but liquidity below the 5,000 floor.
        snaps = _two_snapshots(yes_start=0.40, yes_end=0.70, liquidity=100.0)
        uow = _make_uow(markets=[_market()], snapshots=snaps)
        detector = PredictionMoveDetector(uow_factory=lambda: uow, settings=_settings())

        emitted = await detector.run_cycle()

        assert emitted == 0
        uow.outbox_events.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_liquidity_no_emit(self) -> None:
        # Unknown (None) liquidity must fail the gate — never treated as liquid.
        snaps = _two_snapshots(yes_start=0.40, yes_end=0.70, liquidity=None)
        uow = _make_uow(markets=[_market()], snapshots=snaps)
        detector = PredictionMoveDetector(uow_factory=lambda: uow, settings=_settings())

        emitted = await detector.run_cycle()

        assert emitted == 0
        uow.outbox_events.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_insufficient_volume_no_emit(self) -> None:
        # Material Δ but 24h volume below the 1,000 floor.
        snaps = _two_snapshots(yes_start=0.40, yes_end=0.70, volume_24h=10.0)
        uow = _make_uow(markets=[_market()], snapshots=snaps)
        detector = PredictionMoveDetector(uow_factory=lambda: uow, settings=_settings())

        emitted = await detector.run_cycle()

        assert emitted == 0
        uow.outbox_events.create.assert_not_awaited()


class TestDedup:
    """Same move re-observed in the same window must not re-emit."""

    @pytest.mark.asyncio
    async def test_same_window_not_reemitted(self) -> None:
        snaps = _two_snapshots(yes_start=0.40, yes_end=0.65)
        uow = _make_uow(markets=[_market()], snapshots=snaps)
        detector = PredictionMoveDetector(uow_factory=lambda: uow, settings=_settings())

        first = await detector.run_cycle()
        assert first == 1

        # Re-run over the identical snapshots (same latest.snapshot_at) → dedup.
        uow.outbox_events.create.reset_mock()
        second = await detector.run_cycle()
        assert second == 0
        uow.outbox_events.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_newer_snapshot_reemits(self) -> None:
        detector = PredictionMoveDetector(
            uow_factory=None,  # replaced per-cycle below
            settings=_settings(),
        )

        # Cycle 1 — emits at snapshot _NOW.
        snaps1 = _two_snapshots(yes_start=0.40, yes_end=0.65)
        uow1 = _make_uow(markets=[_market()], snapshots=snaps1)
        detector._uow_factory = lambda: uow1  # type: ignore[assignment]
        assert await detector.run_cycle() == 1

        # Cycle 2 — a strictly-newer latest snapshot still material → re-emits.
        newer_latest = _snapshot(snapshot_at=_NOW + timedelta(hours=1), yes=0.66, no=0.34)
        earliest = _snapshot(snapshot_at=_NOW - timedelta(hours=19), yes=0.40, no=0.60)
        uow2 = _make_uow(markets=[_market()], snapshots=[newer_latest, earliest])
        detector._uow_factory = lambda: uow2  # type: ignore[assignment]
        assert await detector.run_cycle() == 1


class TestWindowStartBaseline:
    """FIX 2: Δ is measured from the TRUE window start, not the LIMIT-truncated one."""

    @pytest.mark.asyncio
    async def test_slow_move_over_full_window_clears_threshold(self) -> None:
        # Simulate a market with MORE than ``snapshot_limit`` snapshots in the
        # window: ``list_snapshots`` returns only the newest page, whose OLDEST
        # element (``snapshots[-1]``) is a mid-window price (0.55). Measuring Δ
        # from there (the OLD bug) gives +0.10 < 0.15 → suppressed. The detector
        # instead uses ``get_earliest_snapshot_at_or_after`` → the true window
        # start (0.40), giving +0.25 which clears τ.
        latest = _snapshot(snapshot_at=_NOW, yes=0.65, no=0.35)
        truncated_oldest = _snapshot(snapshot_at=_NOW - timedelta(hours=2), yes=0.55, no=0.45)
        true_window_start = _snapshot(snapshot_at=_NOW - timedelta(hours=23), yes=0.40, no=0.60)

        uow = _make_uow(
            markets=[_market()],
            snapshots=[latest, truncated_oldest],  # LIMIT-truncated page
            earliest=true_window_start,  # what the new repo read returns
        )
        detector = PredictionMoveDetector(uow_factory=lambda: uow, settings=_settings())

        emitted = await detector.run_cycle()

        # The full-window Δ (0.40 → 0.65 = +0.25) clears the 0.15 threshold.
        assert emitted == 1
        p = uow.outbox_events.create.await_args_list[0].kwargs["payload"]
        assert p["prev_price"] == pytest.approx(0.40)  # true window start, not 0.55
        assert p["new_price"] == pytest.approx(0.65)
        assert p["delta"] == pytest.approx(0.25)
        # The new repo read was consulted for the window-start baseline.
        uow.prediction_market_snapshots_read.get_earliest_snapshot_at_or_after.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_window_start_snapshot_skipped(self) -> None:
        # The window-start read returns None (no snapshot at/after window_start) →
        # cannot measure Δ → skip.
        latest = _snapshot(snapshot_at=_NOW, yes=0.65, no=0.35)
        uow = _make_uow(markets=[_market()], snapshots=[latest], earliest=None)
        detector = PredictionMoveDetector(uow_factory=lambda: uow, settings=_settings())

        emitted = await detector.run_cycle()

        assert emitted == 0
        uow.outbox_events.create.assert_not_awaited()


class TestSkips:
    """Resolved markets, unresolved tokens, and thin snapshot history are skipped."""

    @pytest.mark.asyncio
    async def test_resolved_market_skipped(self) -> None:
        # Defensive guard: even if the repo returns a non-open market, skip it.
        snaps = _two_snapshots(yes_start=0.40, yes_end=0.70)
        market = _market(resolution_status="resolved")
        uow = _make_uow(markets=[market], snapshots=snaps)
        detector = PredictionMoveDetector(uow_factory=lambda: uow, settings=_settings())

        emitted = await detector.run_cycle()

        assert emitted == 0
        uow.outbox_events.create.assert_not_awaited()
        # Resolved markets are skipped before any snapshot scan.
        uow.prediction_market_snapshots_read.list_snapshots.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unresolved_token_skipped(self) -> None:
        # Market has no token_id mapping for its outcomes → cannot emit.
        market = _market(outcomes=[{"name": "Yes"}, {"name": "No"}])
        snaps = _two_snapshots(yes_start=0.40, yes_end=0.70)
        uow = _make_uow(markets=[market], snapshots=snaps)
        detector = PredictionMoveDetector(uow_factory=lambda: uow, settings=_settings())

        emitted = await detector.run_cycle()

        assert emitted == 0
        uow.outbox_events.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_insufficient_snapshot_history_skipped(self) -> None:
        # Only one snapshot in the window → cannot measure Δ.
        one = [_snapshot(snapshot_at=_NOW, yes=0.65, no=0.35)]
        uow = _make_uow(markets=[_market()], snapshots=one)
        detector = PredictionMoveDetector(uow_factory=lambda: uow, settings=_settings())

        emitted = await detector.run_cycle()

        assert emitted == 0
        uow.outbox_events.create.assert_not_awaited()
        # Commit still runs (no-op) so the cycle is clean.
        uow.commit.assert_awaited_once()
