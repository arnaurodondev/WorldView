"""PredictionMoveDetector — S3 material implied-probability move detector.

PLAN-0056 Wave D1 (T-D-1-01).

Every cycle this worker scans every OPEN prediction market, measures how far
each outcome's implied probability moved over a lookback window, and — when the
move clears three config-driven gates — emits a ``market.prediction.move.v1``
event through the transactional **outbox** (R8).  The S7 ``PredictionSignalEmitter``
(Wave D2) consumes those events, joins ``market_id`` (Polymarket ``conditionId``)
to entity exposures + polarity, and fans a per-entity signal out to the alert
pipeline.

Design invariants
-----------------
* **R9 (own DB only)** — reads/writes touch only the market-data database via
  its own Unit of Work; no cross-service DB access.
* **R27 (read replica for scans)** — the per-market snapshot scan and the
  open-market listing use the ``*_read`` accessors, which bind to the read
  (replica) session.  The single emit is the only write.
* **R8 (outbox)** — the move event is written to ``outbox_events`` inside the
  same transaction as (well, alongside) the reads and committed once; the
  standalone dispatcher forwards it to Kafka.  We never produce to Kafka
  directly.
* **No hardcoded thresholds** — the Δ threshold, liquidity/volume floors, window
  length, page/snapshot caps and cadence all come from ``Settings`` (env vars).

Affirmative-outcome only (why we emit ONE move per market)
----------------------------------------------------------
A Polymarket prediction market is overwhelmingly **binary** (Yes / No). The two
outcome tokens move in lock-step, equal-and-opposite: a +0.25 Yes swing is a
-0.25 No swing over the same window. Emitting a move for *every* outcome
therefore produced two events per market with the same ``(market_id, window)``.
The S7 ``PredictionSignalEmitter`` dedups on ``uuid5`` keyed on
``(condition_id, trigger, window)`` **without** ``token_id``, so the two
complementary events collapsed and an *arbitrary* one won — for the No token the
downstream polarity/adverseness (which is framed against the affirmative / YES
resolution) was then computed backwards.

We fix this at the source: emit **at most one** move per market per cycle, for
the **affirmative** outcome only. The affirmative token is selected as:

1. the outcome whose name equals ``"yes"`` (case-insensitive); else
2. the **first** outcome in the market's static ``outcomes`` list — we iterate
   the JSONB list order (stable / deterministic), never dict iteration order.

This ties the emitted move to the exact frame the polarity classifier reasons
about, eliminates the complementary-collapse, and makes ``_is_adverse``
downstream correct as written. Non-binary markets (rare on Polymarket) are
tracked by their affirmative/first outcome only — an accepted simplification.

Gating (noise floor)
--------------------
The affirmative move is emitted only when ALL hold, using the **latest**
snapshot's liquidity/volume:

1. ``abs(delta) >= prediction_move_delta_threshold``
2. ``liquidity >= prediction_move_min_liquidity_usd``
3. ``volume_24h >= prediction_move_min_volume_usd``

where ``delta = latest_price - window_start_price`` for the affirmative outcome.

Dedup
-----
Dedup is keyed on ``(market_id, token_id)`` via an in-memory *watermark*: the
``snapshot_at`` of the latest snapshot at the moment we emitted.  A move is only
(re-)emitted when the latest snapshot is **strictly newer** than that watermark.

Consequences:
* Re-running a cycle over the *same* snapshots re-observes the same
  ``latest.snapshot_at`` → ``<= watermark`` → **no re-emit** (the "same move in
  the same window" case).
* A genuinely newer snapshot that still clears the gates *can* re-emit — that is
  a new observation of an ongoing move, which is desirable; as the window slides
  the window-start ages out and ``delta`` eventually falls below τ, so emission
  self-terminates.

The watermark is intentionally in-memory (not persisted): a process restart may
re-observe a still-material move once, but the downstream S7 emitter is
idempotent per ``(condition_id, trigger, window)`` (Wave D2), so a single
duplicate is absorbed there rather than paying for extra DB dedup state here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from common.time import to_iso8601, utc_now  # type: ignore[import-untyped]
from market_data.domain.events import PredictionMarketMove
from market_data.infrastructure.messaging.outbox.dispatcher import (
    EVENT_TOPIC_MAP,
    event_to_outbox_payload,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

    from market_data.application.ports.uow import UnitOfWork
    from market_data.config import Settings
    from market_data.domain.entities import PredictionMarket


class _UoWFactory(Protocol):
    """Callable returning an entered-on-``async with`` :class:`UnitOfWork`."""

    def __call__(self) -> UnitOfWork: ...


class PredictionMoveDetector:
    """Detects material implied-probability moves and emits move events.

    Args:
        uow_factory: Zero-arg callable returning a fresh ``UnitOfWork`` (used as
            an ``async with`` context per cycle). The UoW must expose the
            ``prediction_markets_read`` / ``prediction_market_snapshots_read``
            replica accessors and the ``outbox_events`` write repo.
        settings: Service settings supplying the (env-driven) gates & caps.
        logger: Optional structlog logger; a module logger is used if omitted.
    """

    def __init__(
        self,
        uow_factory: _UoWFactory | Callable[[], Any],
        settings: Settings,
        *,
        logger: Any | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._log = logger or get_logger("market_data.prediction_move_detector")

        # Snapshot the config once at construction — a running worker uses a
        # stable gate for the life of the process (a redeploy picks up changes).
        self._window_hours: int = settings.prediction_move_window_hours
        self._interval_label: str = settings.prediction_move_interval_label
        self._delta_threshold: float = settings.prediction_move_delta_threshold
        self._min_liquidity: float = settings.prediction_move_min_liquidity_usd
        self._min_volume: float = settings.prediction_move_min_volume_usd
        self._page_size: int = settings.prediction_move_market_page_size
        self._snapshot_limit: int = settings.prediction_move_snapshot_limit

        # Dedup watermark: (market_id, token_id) -> latest snapshot_at at emit.
        self._last_emitted: dict[tuple[str, str], datetime] = {}

    async def run_cycle(self) -> int:
        """Run one full detection sweep; return the number of events emitted.

        A single UoW spans the whole cycle: all scans use the read replica; any
        emitted move rows are written to the outbox and committed once at the
        end (R8). Returning the emit count makes the worker loop observable and
        the unit tests assertable (audit-return-persistence).
        """
        window_start = utc_now() - timedelta(hours=self._window_hours)
        emitted = 0
        scanned = 0

        async with self._uow_factory() as uow:
            offset = 0
            while True:
                # R27: open-market listing via the read replica.
                markets, total = await uow.prediction_markets_read.list_markets(
                    status="open",
                    query=None,
                    limit=self._page_size,
                    offset=offset,
                )
                if not markets:
                    break
                for market, _latest_volume in markets:
                    scanned += 1
                    emitted += await self._process_market(uow, market, window_start)
                offset += self._page_size
                if offset >= total:
                    break

            # Single commit flushes any outbox rows written this cycle. Safe to
            # call even when nothing was emitted (no-op write session commit).
            await uow.commit()

        self._log.info(
            "prediction_move_detector_cycle_completed",
            markets_scanned=scanned,
            moves_emitted=emitted,
            window_hours=self._window_hours,
        )
        return emitted

    async def _process_market(
        self,
        uow: Any,
        market: PredictionMarket,
        window_start: datetime,
    ) -> int:
        """Evaluate one market's outcomes; emit qualifying moves. Returns count."""
        # Defensive skip — ``list_markets(status="open")`` already filters, but a
        # belt-and-suspenders guard keeps resolved/closed markets out even if the
        # repo contract changes (and makes the skip unit-testable in isolation).
        if market.resolution_status != "open":
            return 0

        # Static outcome descriptors: [{"name", "token_id"}] in JSONB (insertion)
        # order — deterministic, unlike dict iteration over a prices map. We keep
        # the order so the affirmative fallback (first outcome) is stable.
        ordered_outcomes: list[tuple[str, str]] = []
        for outcome in market.outcomes or []:
            if not isinstance(outcome, dict):
                continue
            name = outcome.get("name")
            token_id = outcome.get("token_id")
            if name and token_id:
                ordered_outcomes.append((str(name), str(token_id)))

        if not ordered_outcomes:
            # No outcome resolves to a CLOB token — cannot emit a usable move
            # (S7 joins on token_id). Skip rather than emit with an empty token.
            self._log.debug(
                "prediction_move_unresolved_token",
                market_id=market.market_id,
            )
            return 0

        # AFFIRMATIVE-OUTCOME selection (see module docstring): prefer the outcome
        # literally named "yes" (case-insensitive); else fall back to the FIRST
        # outcome in the static list. We emit at most ONE move per market — for
        # this token — so the S7 polarity frame is never inverted.
        affirmative_name, affirmative_token = next(
            (pair for pair in ordered_outcomes if pair[0].strip().lower() == "yes"),
            ordered_outcomes[0],
        )

        # R27: snapshot scan via the read replica; DESC by snapshot_at. Used for
        # the LATEST snapshot (window end) + its liquidity/volume conviction.
        snapshots = await uow.prediction_market_snapshots_read.list_snapshots(
            market.market_id,
            from_dt=window_start,
            to_dt=None,
            limit=self._snapshot_limit,
        )
        if not snapshots:
            return 0
        latest = snapshots[0]  # newest (window end)

        # FIX (window-start truncation): the LATEST ``limit`` DESC rows do NOT
        # contain the true window start once a market has more than ``limit``
        # snapshots in the window — ``snapshots[-1]`` would then be the
        # ``limit``-th newest, shrinking the measured window and letting slow
        # moves fall silently under τ. Fetch the true earliest-in-window row
        # explicitly (R27: read replica).
        window_start_snap = await uow.prediction_market_snapshots_read.get_earliest_snapshot_at_or_after(
            market.market_id,
            window_start,
        )
        if window_start_snap is None or window_start_snap.snapshot_at >= latest.snapshot_at:
            # Need a distinct window-start and window-end to measure Δ.
            return 0

        # Liquidity/volume gate uses the LATEST snapshot's conviction fields. A
        # missing (None) value fails the gate — we never treat "unknown" as
        # "liquid enough".
        liquidity = float(latest.liquidity) if latest.liquidity is not None else None
        volume_24h = float(latest.volume_24h) if latest.volume_24h is not None else None
        if liquidity is None or liquidity < self._min_liquidity:
            return 0
        if volume_24h is None or volume_24h < self._min_volume:
            return 0

        new_price = latest.outcomes_prices.get(affirmative_name)
        prev_price = window_start_snap.outcomes_prices.get(affirmative_name)
        if new_price is None or prev_price is None:
            # Affirmative outcome not priced at both ends — cannot measure Δ.
            return 0

        delta = float(new_price) - float(prev_price)
        if abs(delta) < self._delta_threshold:
            return 0  # Δ gate

        # Dedup watermark: only emit when this snapshot is strictly newer than the
        # last one we emitted for this (market, affirmative token).
        dedup_key = (market.market_id, affirmative_token)
        watermark = self._last_emitted.get(dedup_key)
        if watermark is not None and latest.snapshot_at <= watermark:
            return 0

        direction = "up" if delta > 0 else "down"
        event = PredictionMarketMove(
            market_id=market.market_id,
            token_id=affirmative_token,
            outcome_name=affirmative_name,
            interval=self._interval_label,
            prev_price=float(prev_price),
            new_price=float(new_price),
            delta=delta,
            direction=direction,
            liquidity=liquidity,
            volume_24h=volume_24h,
            window_start_ts=to_iso8601(window_start_snap.snapshot_at),
            is_backfill=False,
        )
        # R8: write to the outbox (not Kafka). ``partition_key=market_id`` pins
        # every move for a market to one partition so S7 observes them in causal
        # order.
        await uow.outbox_events.create(
            event_type=event.event_type,
            topic=EVENT_TOPIC_MAP[event.event_type],
            payload=event_to_outbox_payload(event),
            partition_key=market.market_id,
        )
        self._last_emitted[dedup_key] = latest.snapshot_at
        self._log.info(
            "prediction_move_emitted",
            market_id=market.market_id,
            token_id=affirmative_token,
            outcome_name=affirmative_name,
            delta=round(delta, 4),
            direction=direction,
            liquidity=liquidity,
            volume_24h=volume_24h,
        )
        return 1
