"""ScheduleDueTasksUseCase — scheduler tick for market data ingestion.

Three-phase tick:
  1. Load all enabled polling policies.
  2. For each policy: evaluate backfill/incremental status and create tasks.
  3. Apply provider budgets and enqueue idempotently (ON CONFLICT DO NOTHING).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from common.time import utc_now  # type: ignore[import-untyped]
from market_ingestion.domain.entities.ingestion_task import IngestionTask
from market_ingestion.domain.enums import DatasetType
from market_ingestion.domain.value_objects import DateRange, Timeframe
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_ingestion.application.ports.unit_of_work import UnitOfWork
    from market_ingestion.domain.entities.polling_policy import PollingPolicy
    from market_ingestion.domain.entities.watermark import Watermark

logger = get_logger(__name__)

# EODHD charges different API-credit amounts per endpoint type.
# The budget system consumes this many tokens per task so that the provider
# budget actually reflects real API cost rather than task count.
# Source: https://eodhd.com/financial-apis/api-limits
_EODHD_CREDIT_COST: dict[str, float] = {
    DatasetType.FUNDAMENTALS.value: 10.0,  # /api/fundamentals/:ticker = 10 credits
    DatasetType.OHLCV.value: 1.0,  # /api/eod/:ticker = 1 credit
    DatasetType.QUOTES.value: 1.0,  # /api/real-time/:ticker = 1 credit
    # Intraday endpoints (/api/intraday/:ticker) cost 5 credits each.
    # These use DatasetType.OHLCV with timeframe ∈ {"1h","5m","1m"}.
    # The per-task cost is overridden in _apply_budgets for intraday timeframes.
    DatasetType.NEWS_SENTIMENT.value: 5.0,  # /api/news = 5 credits
    DatasetType.EARNINGS_CALENDAR.value: 1.0,
    DatasetType.ECONOMIC_EVENTS.value: 1.0,
    DatasetType.MACRO_INDICATOR.value: 1.0,
    DatasetType.INSIDER_TRANSACTIONS.value: 1.0,
    DatasetType.YIELD_CURVE.value: 1.0,
    DatasetType.MARKET_CAP.value: 1.0,
}

# Intraday timeframes that hit /api/intraday (5 credits each).
_INTRADAY_TIMEFRAMES: frozenset[str] = frozenset({"1m", "5m", "1h"})

# EOD OHLCV timeframes (daily/weekly/monthly) are routed to Yahoo Finance as the
# PRIMARY provider (config routing_ohlcv_eod = "yahoo_finance:100,eodhd:80"); EODHD
# is only a zero-bar FAILOVER.  In steady state these tasks consume ZERO EODHD
# credits, so the scheduler must NOT pre-charge the EODHD token bucket for them.
# Pre-charging (the old behaviour) burned ~2_200 phantom EODHD credits/day on the
# 554 enabled `eodhd ohlcv 1d` policies and — because the budget gate stops at the
# first exhaustion — could STARVE the genuinely-EODHD fundamentals tasks (priority
# 2, ranked *below* ohlcv-1d priority 5) under quota pressure.  EODHD failover is
# still guarded at execution time by the circuit breaker and the monthly quota
# service, so skipping the scheduler pre-charge does not let a Yahoo outage flood
# EODHD uncontrolled (BP-EODHD-QUOTA).
_YAHOO_ROUTED_EOD_TIMEFRAMES: frozenset[str] = frozenset({"1d", "1w", "1mo", "1M"})

# FIX-INTRADAY-DEDUP: all intraday OHLCV timeframes whose incremental tasks must
# use a per-minute dedupe bucket instead of a per-day bucket.  With day-truncated
# range_start:range_end the dedupe_key is identical for every scheduler tick of
# the same UTC day, so ON CONFLICT DO NOTHING swallows every re-enqueue and the
# pipeline fetches intraday bars exactly once per day (~2% of expected bars).
# Daily-and-slower timeframes keep the day bucket (original FIX-DEDUP intent).
_INTRADAY_DEDUP_TIMEFRAMES: frozenset[str] = frozenset({"1m", "5m", "15m", "30m", "1h", "4h"})

# CATCH-UP (2026-06-16): cap on how far back an INCREMENTAL task may resume its
# range_start from the data high-water mark after a gap.  Before this, range_start
# was hard-pinned to today-midnight, so a multi-day outage (e.g. the 2026-06-13..15
# platform-down window) was never backfilled — incremental fetches only ever asked
# for "today".  We now resume from the watermark's last-fetched day, bounded by this
# cap so a long-dormant policy issues one bounded catch-up request rather than an
# unbounded range; gaps wider than this should use the explicit backfill path
# (``backfill_enabled`` + ``backfill_start_date``).  Alpaca batches up to 10k bars
# per symbol/call, so a one-week catch-up is a single request, and bar upserts are
# idempotent so re-fetching the boundary day is a no-op.
_MAX_CATCHUP_DAYS: int = 7


@dataclass
class SchedulerTickResult:
    """Summary of one scheduler tick."""

    tasks_enqueued: int = 0
    policies_evaluated: int = 0
    budget_limited: int = 0


class ScheduleDueTasksUseCase:
    """Schedule ingestion tasks for all due polling policies.

    Construction::

        use_case = ScheduleDueTasksUseCase(uow, max_tasks_per_tick=500)
        result = await use_case.execute()
    """

    def __init__(
        self,
        uow: UnitOfWork,
        max_tasks_per_tick: int = 1000,
    ) -> None:
        self._uow = uow
        self._max_tasks_per_tick = max_tasks_per_tick

    async def execute(self) -> SchedulerTickResult:
        """Run one scheduler tick and return a summary."""
        result = SchedulerTickResult()
        now = utc_now()

        async with self._uow:
            # Phase 1: Load enabled policies
            policies = await self._uow.policies.list_enabled()
            result.policies_evaluated = len(policies)

            if not policies:
                logger.info("scheduler_tick_no_policies")
                await self._uow.commit()
                return result

            # Phase 2: Build candidate tasks for each policy.
            # Track which policies triggered backfill so we only flip the flag
            # after we confirm those tasks survived budget/cap filtering.
            candidate_tasks: list[IngestionTask] = []
            backfill_policies: list[PollingPolicy] = []
            for policy in policies:
                tasks = await self._build_tasks_for_policy(policy, now, backfill_policies)
                candidate_tasks.extend(tasks)

            # Phase 3: Apply budgets and cap
            budgeted_tasks = await self._apply_budgets(candidate_tasks, now)
            if len(candidate_tasks) > len(budgeted_tasks):
                result.budget_limited = len(candidate_tasks) - len(budgeted_tasks)

            # Respect max cap
            final_tasks = budgeted_tasks[: self._max_tasks_per_tick]

            # Idempotent enqueue
            if final_tasks:
                inserted = await self._uow.tasks.add_many(final_tasks)
                result.tasks_enqueued = inserted

            # Only flip backfill_enabled=False for policies whose backfill tasks
            # were actually enqueued (i.e. survived budget/cap filtering).
            for bp in backfill_policies:
                # FIX-BACKFILL-FLAG: Match on provider+symbol+dataset_type+timeframe so
                # two OHLCV policies sharing the same provider/symbol but differing only
                # in timeframe cannot steal each other's flag flip (BP-075).
                policy_tasks_enqueued = any(
                    str(t.provider) == str(bp.provider)
                    and t.symbol == bp.symbol
                    and str(t.dataset_type) == str(bp.dataset_type)
                    and (t.timeframe or "") == (bp.timeframe or "")
                    for t in final_tasks
                )
                if policy_tasks_enqueued:
                    bp.backfill_enabled = False
                    await self._uow.policies.save(bp)

            await self._uow.commit()

        logger.info(
            "scheduler_tick_complete",
            policies_evaluated=result.policies_evaluated,
            tasks_enqueued=result.tasks_enqueued,
            budget_limited=result.budget_limited,
        )
        return result

    # ------------------------------------------------------------------

    async def _build_tasks_for_policy(
        self,
        policy: PollingPolicy,
        now: datetime,
        backfill_policies: list[PollingPolicy],
    ) -> list[IngestionTask]:
        """Evaluate a single policy and return candidate tasks.

        Policies that generate backfill tasks are appended to *backfill_policies*
        so the caller can flip backfill_enabled=False only after the tasks are
        confirmed enqueued (i.e. survived budget and cap filtering).
        """
        tasks: list[IngestionTask] = []

        # Determine the set of symbols to schedule
        symbols: list[str | None] = [policy.symbol]  # None = wildcard (handled in loop)

        for symbol in symbols:
            if symbol is None:
                # Wildcard — skip for now; wave 03 wires symbol discovery
                logger.debug("scheduler_skip_wildcard_policy", policy_id=policy.id)
                continue

            # FIX-WM: Pass variant so the watermark key matches the one
            # used by execute_task.py (which passes task.variant).  Without
            # this, FUNDAMENTALS tasks create a separate watermark row during
            # execution and the scheduler checks a stale variant=NULL row.
            task_variant = self._derive_variant(policy)
            watermark = await self._uow.watermarks.get_or_create(
                provider=str(policy.provider),
                dataset_type=str(policy.dataset_type),
                symbol=symbol,
                exchange=policy.exchange,
                timeframe=policy.timeframe,
                variant=task_variant,
            )

            if policy.backfill_enabled and policy.backfill_start_date is not None:
                # One-shot backfill mode: enqueue historical chunks.
                # Do NOT flip backfill_enabled here — wait until we know
                # the tasks survived budget/cap filtering (done by the caller).
                backfill_tasks = self._build_backfill_tasks(policy, symbol, now)
                if backfill_tasks:
                    tasks.extend(backfill_tasks)
                    backfill_policies.append(policy)
            else:
                # Incremental mode — schedule if due and no active task exists.
                # FIX-WALLCLOCK: is_due() expects the WALL-CLOCK time of the last
                # run, not a data timestamp.  current_bar_ts is the data high-water
                # mark (e.g. tomorrow-midnight for a full-day range), which made
                # every policy "not due" until the next UTC day — pinning all
                # incremental policies to exactly one fetch per day.
                # last_success_at is written by the worker on every successful
                # fetch (watermark_repository.save) and is the correct clock.
                if policy.is_due(watermark.last_success_at):
                    # FIX-VARIANT: task_variant (computed above for watermark)
                    # must also be passed to has_active_task so fundamentals
                    # tasks (variant="annual") are detected as active.
                    already_queued = await self._uow.tasks.has_active_task(
                        provider=policy.provider,
                        dataset_type=policy.dataset_type,
                        symbol=symbol,
                        exchange=policy.exchange,
                        timeframe=policy.timeframe,
                        variant=task_variant,
                    )
                    if already_queued:
                        logger.debug(
                            "scheduler_skip_active_task",
                            provider=str(policy.provider),
                            dataset_type=str(policy.dataset_type),
                            symbol=symbol,
                        )
                        continue
                    task = self._build_incremental_task(policy, symbol, now, watermark)
                    if task is not None:
                        tasks.append(task)

        return tasks

    @staticmethod
    def _derive_variant(policy: PollingPolicy) -> str | None:
        """Return the task variant for a policy (matches factory method logic)."""
        if policy.dataset_type == DatasetType.FUNDAMENTALS:
            from market_ingestion.domain.enums import FundamentalsVariant

            return FundamentalsVariant.ANNUAL.value
        return None

    def _build_incremental_task(
        self,
        policy: PollingPolicy,
        symbol: str,
        now: datetime,
        watermark: Watermark | None = None,
    ) -> IngestionTask | None:
        """Create one incremental task for a due policy.

        ``watermark`` (optional, backward-compatible) supplies the data
        high-water mark used for staleness-proportional catch-up after a gap —
        see ``_MAX_CATCHUP_DAYS``.  When omitted the legacy today-only range is
        used.
        """
        from datetime import timedelta

        # FIX-DEDUP: Truncate to UTC-day boundaries so the dedupe_key stays
        # stable across all scheduler ticks within the same day.  Without this,
        # range_end = now produces a different SHA-256 hash every tick and
        # ON CONFLICT DO NOTHING never fires, causing unbounded task growth.
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        range_start = today

        # CATCH-UP: when the data high-water mark lags behind today (an outage
        # or a long dormant period), resume range_start from the last-fetched
        # day instead of today, bounded by _MAX_CATCHUP_DAYS, so the gap is
        # actually refetched.  range_start stays day-truncated so the dedupe key
        # is stable across same-day ticks until a successful fetch advances the
        # watermark; once it does, the next tick's range_start advances with it.
        if watermark is not None and watermark.current_bar_ts is not None:
            wm_day = watermark.current_bar_ts.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            if wm_day < today:
                range_start = max(wm_day, today - timedelta(days=_MAX_CATCHUP_DAYS))
        if policy.dataset_type == DatasetType.OHLCV and (policy.timeframe or "") in _INTRADAY_DEDUP_TIMEFRAMES:
            # FIX-INTRADAY-DEDUP: bucket intraday tasks per MINUTE, not per day.
            # A day-stable dedupe_key makes ON CONFLICT DO NOTHING swallow every
            # same-day re-enqueue, so intraday policies fetched once per day.
            # Truncating range_end to the minute gives each scheduler tick in a
            # new minute a distinct dedupe_key while still deduping ticks that
            # land within the same minute.  range_start stays at day-start: the
            # full-day refetch is cheap (Alpaca batches 1000 symbols/call) and
            # downstream bar upserts are idempotent.
            range_end = now.replace(second=0, microsecond=0)
            if range_end <= range_start:
                # Guard for ticks in the 00:00 UTC minute — DateRange requires
                # start < end strictly.
                range_end = range_start + timedelta(minutes=1)
        else:
            # Daily-and-slower datasets keep the stable full-day bucket.
            range_end = today + timedelta(days=1)
        date_range = DateRange(start=range_start, end=range_end)

        if policy.dataset_type == DatasetType.OHLCV:
            tf = Timeframe(policy.timeframe or "1d")
            return IngestionTask.create_ohlcv_task(
                provider=policy.provider,
                symbol=symbol,
                timeframe=tf,
                date_range=date_range,
                exchange=policy.exchange,
            )
        if policy.dataset_type == DatasetType.QUOTES:
            return IngestionTask.create_quote_task(
                provider=policy.provider,
                symbol=symbol,
                date_range=date_range,
                exchange=policy.exchange,
            )
        if policy.dataset_type == DatasetType.FUNDAMENTALS:
            from market_ingestion.domain.enums import FundamentalsVariant

            variant = FundamentalsVariant.ANNUAL
            return IngestionTask.create_fundamentals_task(
                provider=policy.provider,
                symbol=symbol,
                variant=variant,
                date_range=date_range,
                exchange=policy.exchange,
            )
        if policy.dataset_type == DatasetType.EARNINGS_CALENDAR:
            # WHY no symbol/exchange args: earnings calendar is a global fetch —
            # symbol and exchange are encoded as fixed "CALENDAR"/"EARNINGS" inside
            # create_earnings_calendar_task so the dedupe_key stays stable per day.
            return IngestionTask.create_earnings_calendar_task(
                provider=policy.provider,
                date_range=date_range,
            )
        if policy.dataset_type == DatasetType.NEWS_SENTIMENT:
            return IngestionTask.create_news_sentiment_task(
                provider=policy.provider,
                symbol=symbol,
                date_range=date_range,
                exchange=policy.exchange,
            )
        if policy.dataset_type == DatasetType.ECONOMIC_EVENTS:
            # WHY no exchange: economic events are global/country-level, not per-exchange.
            # symbol encodes the country code as "EVENTS.<ISO3>" (e.g. "EVENTS.USA").
            return IngestionTask.create_economic_events_task(
                provider=policy.provider,
                symbol=symbol,
                date_range=date_range,
            )
        if policy.dataset_type == DatasetType.MACRO_INDICATOR:
            # WHY no exchange: macro indicators are country-level World Bank / EODHD data.
            # symbol encodes "COUNTRY.indicator_name" (e.g. "USA.gdp_current_usd").
            return IngestionTask.create_macro_indicator_task(
                provider=policy.provider,
                symbol=symbol,
                date_range=date_range,
            )
        if policy.dataset_type == DatasetType.INSIDER_TRANSACTIONS:
            return IngestionTask.create_insider_transactions_task(
                provider=policy.provider,
                symbol=symbol,
                date_range=date_range,
                exchange=policy.exchange,
            )
        if policy.dataset_type == DatasetType.YIELD_CURVE:
            # WHY no exchange: yield curve series are global identifiers (e.g. "US10Y"),
            # not per-exchange. execute_task.py passes symbol directly to fetch_yield_curve().
            return IngestionTask.create_yield_curve_task(
                provider=policy.provider,
                symbol=symbol,
                date_range=date_range,
            )
        if policy.dataset_type == DatasetType.MARKET_CAP:
            return IngestionTask.create_market_cap_task(
                provider=policy.provider,
                symbol=symbol,
                date_range=date_range,
                exchange=policy.exchange,
            )
        logger.debug(
            "scheduler_unsupported_dataset_type",
            dataset_type=str(policy.dataset_type),
            symbol=symbol,
        )
        return None

    def _build_backfill_tasks(
        self,
        policy: PollingPolicy,
        symbol: str,
        now: datetime,
    ) -> list[IngestionTask]:
        """Create chunked OHLCV tasks for the policy's backfill range."""
        from datetime import timedelta

        if policy.backfill_start_date is None or policy.dataset_type != DatasetType.OHLCV:
            return []

        chunk_days = policy.backfill_days or 30
        start_dt = datetime(
            policy.backfill_start_date.year,
            policy.backfill_start_date.month,
            policy.backfill_start_date.day,
            tzinfo=UTC,
        )
        # FIX-BACKFILL: Truncate end to UTC midnight so the last chunk always
        # produces the same dedupe_key within a given day.  Without this,
        # end_dt = now drifts every tick and the last chunk bypasses dedup.
        end_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)

        tasks: list[IngestionTask] = []
        current = start_dt
        tf = Timeframe(policy.timeframe or "1d")
        while current < end_dt:
            chunk_end = min(current + timedelta(days=chunk_days), end_dt)
            date_range = DateRange(start=current, end=chunk_end)
            tasks.append(
                IngestionTask.create_ohlcv_task(
                    provider=policy.provider,
                    symbol=symbol,
                    timeframe=tf,
                    date_range=date_range,
                    exchange=policy.exchange,
                )
            )
            current = chunk_end

        return tasks

    async def _apply_budgets(
        self,
        tasks: list[IngestionTask],
        now: datetime,
    ) -> list[IngestionTask]:
        """Filter tasks through provider budgets; consume a token per task kept."""
        if not tasks:
            return []

        # Group by provider
        by_provider: dict[str, list[IngestionTask]] = {}
        for task in tasks:
            by_provider.setdefault(str(task.provider), []).append(task)

        kept: list[IngestionTask] = []
        for provider_str, ptasks in by_provider.items():
            from market_ingestion.domain.enums import Provider

            provider = Provider(provider_str)
            # SELECT FOR UPDATE prevents concurrent scheduler workers from over-consuming
            # the token bucket (BP-036). Falls back to get_or_create if no row exists.
            budget = await self._uow.budgets.get_for_update(provider)
            if budget is None:
                budget = await self._uow.budgets.get_or_create(provider)

            # Replenish tokens based on elapsed time since last refill.
            elapsed = (now - budget.last_refill_at).total_seconds()
            if elapsed > 0:
                budget.refill(elapsed)

            for task in ptasks:
                # EOD OHLCV (daily/weekly/monthly) routes to Yahoo Finance, not
                # EODHD — do NOT charge the EODHD bucket for it (see
                # _YAHOO_ROUTED_EOD_TIMEFRAMES note above).  These tasks are kept
                # unconditionally; their real cost is borne by Yahoo (free) and
                # any EODHD failover is guarded downstream at execution time.
                if (
                    provider == Provider.EODHD
                    and str(task.dataset_type) == DatasetType.OHLCV.value
                    and task.timeframe in _YAHOO_ROUTED_EOD_TIMEFRAMES
                ):
                    kept.append(task)
                    continue

                # Consume credits proportional to the EODHD endpoint cost so
                # the budget accurately throttles expensive endpoints (e.g.
                # fundamentals = 10 credits) not just task count (BP-183).
                cost = _EODHD_CREDIT_COST.get(str(task.dataset_type), 1.0)
                # Intraday timeframes hit a different EODHD endpoint (5 credits).
                if str(task.dataset_type) == DatasetType.OHLCV.value and task.timeframe in _INTRADAY_TIMEFRAMES:
                    cost = 5.0
                if budget.try_consume(cost):
                    kept.append(task)
                else:
                    logger.debug(
                        "scheduler_budget_exhausted",
                        provider=provider_str,
                        remaining_tasks=len(ptasks),
                        credit_cost=cost,
                    )
                    break  # budget exhausted for this provider

            await self._uow.budgets.save(budget)

        return kept
