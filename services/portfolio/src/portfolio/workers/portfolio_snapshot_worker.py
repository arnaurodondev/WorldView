"""PortfolioSnapshotWorker — daily portfolio value snapshot writer.

PLAN-0046 Wave 4 / T-46-4-02 + T-46-4-03.

Process model:
    - Long-lived async worker (one process; same pattern as
      ``BrokerageTransactionSyncWorker``).
    - Sleeps until **21:30 UTC** every day, then runs one full pass.
      21:30 UTC is ~16:30 ET, well after the NYSE 20:00 UTC close, so
      EODHD has published the official daily bars by the time we read.
    - Skips weekends and a hard-coded list of US (NYSE) holidays for
      2025/2026 — for v1 we don't pull pandas-market-calendars to keep
      the dependency footprint small. The list is full-year for both
      years.
    - Idempotent: re-running for the same date is a no-op via
      ``ON CONFLICT DO UPDATE`` in the repository.

Two-phase pass per scheduled run (single trading day):

    Phase 1: for every non-root active portfolio, call
             ``ComputePortfolioValueUseCase`` to write a snapshot
             keyed on ``(portfolio_id, today)``.
    Phase 2: for every root active portfolio, sum the same-date
             snapshots of the owner's non-root active portfolios and
             upsert one row for the root portfolio. We re-read the
             snapshots from DB rather than carrying them in memory so
             a partial Phase-1 failure doesn't poison the root sum.

Per-portfolio try/except wraps both phases — a single bad portfolio
must not stop the whole pass.

Entry point::

    python -m portfolio.workers.portfolio_snapshot_worker
"""

from __future__ import annotations

import asyncio
import time
import urllib.parse
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import httpx
import jwt as pyjwt

from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.use_cases.compute_portfolio_value import (
    ComputePortfolioValueCommand,
    ComputePortfolioValueUseCase,
    OHLCVPriceClient,
)
from portfolio.domain.entities.portfolio_value_snapshot import (
    DATA_QUALITY_OK,
    DATA_QUALITY_PARTIAL_PRICES,
    PortfolioValueSnapshot,
)
from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from portfolio.config import Settings
    from portfolio.domain.entities.portfolio import Portfolio

logger = get_logger(__name__)  # type: ignore[no-any-return]


# ── Scheduling constants ──────────────────────────────────────────────────────
# 21:30 UTC ≈ 16:30 ET — comfortably after NYSE 20:00 UTC close so EODHD has
# the official daily bars published. Tweaking this requires no code change to
# the worker logic; only the wake-up calculation in ``_seconds_until_next_run``.
SCHEDULED_HOUR_UTC = 21
SCHEDULED_MINUTE_UTC = 30


# Hard-coded NYSE holidays for 2025 + 2026 (full year for both).
# Source: NYSE published holiday calendar.
# Why hard-coded (not pandas-market-calendars):
#   - the dependency drags in pandas + numpy (~30 MB) which is a large delta
#     for a service that otherwise has no DataFrame use.
#   - the worker only needs a binary "is this a trading day" answer; an
#     exhaustive set lookup is enough.
# When 2027 rolls around, this list is the only place to update.
_NYSE_HOLIDAYS: frozenset[date] = frozenset(
    {
        # 2025
        date(2025, 1, 1),  # New Year's Day
        date(2025, 1, 20),  # MLK Day
        date(2025, 2, 17),  # Washington's Birthday
        date(2025, 4, 18),  # Good Friday
        date(2025, 5, 26),  # Memorial Day
        date(2025, 6, 19),  # Juneteenth
        date(2025, 7, 4),  # Independence Day
        date(2025, 9, 1),  # Labor Day
        date(2025, 11, 27),  # Thanksgiving
        date(2025, 12, 25),  # Christmas
        # 2026
        date(2026, 1, 1),  # New Year's Day
        date(2026, 1, 19),  # MLK Day
        date(2026, 2, 16),  # Washington's Birthday
        date(2026, 4, 3),  # Good Friday
        date(2026, 5, 25),  # Memorial Day
        date(2026, 6, 19),  # Juneteenth
        date(2026, 7, 3),  # Independence Day observed (July 4 is Saturday)
        date(2026, 9, 7),  # Labor Day
        date(2026, 11, 26),  # Thanksgiving
        date(2026, 12, 25),  # Christmas
    },
)


def is_trading_day(d: date) -> bool:
    """Return True iff ``d`` is a US/NYSE trading day.

    A trading day is Monday-Friday and not a NYSE holiday. Public so the
    backfill script can re-use the same definition (consistency matters
    — a date counted as a trading day by the worker but a holiday by the
    backfill, or vice-versa, would silently desync the time-series).
    """
    if d.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        return False
    return d not in _NYSE_HOLIDAYS


# ── HTTP price client ─────────────────────────────────────────────────────────


def _system_jwt_headers() -> dict[str, str]:
    """Generate ``X-Internal-JWT`` for service-to-service calls to market-data.

    Same rationale as ``BrokerageTransactionSyncWorker._system_jwt_headers``:
    in dev S3 runs with ``skip_verification=True`` and accepts any
    decodable JWT. Production needs a real S9-signed token.
    """
    now = int(time.time())
    token = pyjwt.encode(
        {
            "iss": "worldview-gateway",
            "sub": "system:portfolio-snapshot",
            "user_id": "00000000-0000-0000-0000-000000000000",
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "role": "system",
            "iat": now,
            "exp": now + 86400,
        },
        "dev-skip-verification-key-for-portfolio-snapshot-worker",
        algorithm="HS256",
    )
    return {"X-Internal-JWT": token}


class HttpOHLCVPriceClient(OHLCVPriceClient):
    """Production ``OHLCVPriceClient`` backed by S3 (market-data).

    Uses the existing ``GET /api/v1/ohlcv/{instrument_id}?start=Y&end=Y&limit=1``
    endpoint. We pass ``start == end == as_of_date`` so the result is at
    most one bar. This avoids adding a new ``/ohlcv/single`` endpoint to
    S3 in this wave (the plan explicitly defers that).
    """

    def __init__(self, http: httpx.AsyncClient, market_data_url: str) -> None:
        self._http = http
        self._base_url = market_data_url.rstrip("/")

    async def get_close_on_date(
        self,
        instrument_id: object,  # UUID — typed as object to match Protocol structurally
        on_date: date,
    ) -> Decimal | None:
        # URL-encode just in case — instrument_id is a UUID, but defensive
        # against future refactors that might pass a symbol.
        url = (
            f"{self._base_url}/api/v1/ohlcv/{urllib.parse.quote(str(instrument_id), safe='')}"
            f"?start={on_date.isoformat()}&end={on_date.isoformat()}&limit=1"
        )
        try:
            response = await self._http.get(url)
        except Exception as exc:
            # Transient — propagate so the per-portfolio try/except in the
            # worker can decide whether to abort just this portfolio's
            # snapshot or carry on with zero contribution. We choose the
            # latter (treat as missing) by catching here; a transient
            # outage on every holding would otherwise produce a snapshot
            # of total_value=0 which is misleading. Returning None is
            # consistent with "no bar on this date".
            logger.warning(  # type: ignore[no-any-return]
                "ohlcv_price_fetch_error",
                instrument_id=str(instrument_id),
                on_date=on_date.isoformat(),
                error=type(exc).__name__,
            )
            return None

        if response.status_code == 404:
            return None
        if response.status_code != 200:
            logger.warning(  # type: ignore[no-any-return]
                "ohlcv_price_unexpected_status",
                instrument_id=str(instrument_id),
                on_date=on_date.isoformat(),
                status=response.status_code,
            )
            return None

        body = response.json()
        items = body.get("items") or []
        if not items:
            return None
        # The endpoint returns ``close`` as a string (Pydantic plugin keeps
        # decimals as strings on the wire). Use Decimal directly to avoid
        # float precision issues.
        return Decimal(str(items[0]["close"]))


# ── Worker ────────────────────────────────────────────────────────────────────


def _seconds_until_next_run(now: datetime) -> float:
    """Seconds from ``now`` (UTC) to the next 21:30 UTC.

    Always returns a strictly positive number — if the current time is
    already past 21:30, schedules for tomorrow.
    """
    target = now.replace(
        hour=SCHEDULED_HOUR_UTC,
        minute=SCHEDULED_MINUTE_UTC,
        second=0,
        microsecond=0,
    )
    if target <= now:
        target = target + timedelta(days=1)
    return (target - now).total_seconds()


class PortfolioSnapshotWorker:
    """Daily worker: write one ``PortfolioValueSnapshot`` per portfolio.

    Dependencies are injected — tests construct a worker with a fake
    session factory, fake price client, and run a single ``run_once``
    pass directly without touching the scheduling loop.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        price_client: OHLCVPriceClient,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._price_client = price_client
        self._settings = settings

    # ── Public entry points ───────────────────────────────────────────────────

    async def run(self) -> None:
        """Long-running scheduling loop (production entry point).

        F-001 / F-017 (QA 2026-04-28): on startup, before sleeping for up
        to 24 hours, we walk the past 30 trading days and fill in any
        missing snapshot rows. This eliminates the "empty equity chart
        for 6+ hours after every container restart" failure mode and
        also recovers automatically from multi-day outages.

        Order of operations:

        1. Startup catch-up — for each non-root active portfolio, check
           which of the past 30 trading days are missing a snapshot and
           run ``ComputePortfolioValueUseCase`` for those dates. Then
           re-aggregate root snapshots for any dates that gained
           sub-portfolio rows. Per-day try/except so one failure doesn't
           halt the whole catch-up.
        2. Today's snapshot — also run "today" if it's a trading day so
           the chart is fresh for users logging in immediately after a
           deploy.
        3. Normal schedule loop — sleep until 21:30 UTC and run once
           per trading day from there on.
        """
        logger.info("portfolio_snapshot_worker_started")  # type: ignore[no-any-return]

        try:
            await self._startup_catchup()
        except Exception as exc:
            # Catch broadly: the catch-up is best-effort. A failure here
            # must not prevent the regular schedule from starting.
            logger.error(  # type: ignore[no-any-return]
                "portfolio_snapshot_worker_startup_catchup_failed",
                error=type(exc).__name__,
                error_message=str(exc),
            )

        while True:
            now = datetime.now(tz=UTC)
            sleep_seconds = _seconds_until_next_run(now)
            logger.info(  # type: ignore[no-any-return]
                "portfolio_snapshot_worker_sleeping",
                sleep_seconds=int(sleep_seconds),
            )
            await asyncio.sleep(sleep_seconds)

            today = datetime.now(tz=UTC).date()
            if not is_trading_day(today):
                logger.info(  # type: ignore[no-any-return]
                    "portfolio_snapshot_worker_skip_non_trading_day",
                    date=today.isoformat(),
                )
                continue

            try:
                await self.run_once(today)
            except Exception as exc:
                logger.error(  # type: ignore[no-any-return]
                    "portfolio_snapshot_worker_cycle_error",
                    error=str(exc),
                )

    async def _startup_catchup(self, lookback_trading_days: int = 30) -> None:
        """Fill in missing snapshot rows for the past N trading days.

        F-001 / F-017 implementation. We iterate calendar days backwards
        from today, skipping weekends/holidays, until we have visited
        ``lookback_trading_days`` actual trading days. For each such date:

        * Phase 1 (per-portfolio): if no snapshot row exists for that
          ``(portfolio_id, date)`` pair, compute one. Per-portfolio
          try/except so a single bad portfolio doesn't poison the whole
          catch-up. We only WRITE missing dates — already-present rows
          are left untouched (idempotent).
        * Phase 2 (root aggregation): re-run the root aggregator for the
          same date so any newly-written sub-portfolio rows are reflected
          in the root sum. Idempotent on dates that already had
          everything.

        This is the only place in the worker that does a multi-day pass —
        the steady-state schedule loop does single-day runs.
        """
        today = datetime.now(tz=UTC).date()

        # Build the list of trading days to consider, walking backwards.
        # We include today only when it's a trading day so first-deploy
        # users see a fresh chart on day 1.
        trading_days: list[date] = []
        cursor = today
        # Bounded calendar walk — at worst we walk lookback_trading_days * 2
        # calendar days (one weekend + one mid-week holiday is rare).
        max_calendar_days = lookback_trading_days * 3
        steps = 0
        while len(trading_days) < lookback_trading_days and steps < max_calendar_days:
            if is_trading_day(cursor):
                trading_days.append(cursor)
            cursor = cursor - timedelta(days=1)
            steps += 1

        # Sort ascending so when we walk and run Phase 2 the root
        # aggregation sees a consistent forward-in-time series. (Phase 1
        # is per-portfolio idempotent so order within Phase 1 doesn't
        # matter, but Phase 2 reads back the rows so the ordering keeps
        # logs readable.)
        trading_days.sort()

        logger.info(  # type: ignore[no-any-return]
            "portfolio_snapshot_worker_startup_catchup_start",
            trading_day_count=len(trading_days),
            from_date=trading_days[0].isoformat() if trading_days else None,
            to_date=trading_days[-1].isoformat() if trading_days else None,
        )

        # Pre-load portfolios once; the loop below just checks per-day
        # existence to skip the price-fetching work when a row is already
        # written.
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            portfolios = await uow.portfolios.list_all_non_root_active()

        use_case = ComputePortfolioValueUseCase(self._price_client)

        # Per-day Phase 1
        for d in trading_days:
            wrote_any = False
            for portfolio in portfolios:
                try:
                    async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
                        # Idempotency: skip if a row already exists for this
                        # (portfolio, date). The repo's ``list_range`` over
                        # a single day is the cheapest existence probe we
                        # have without adding a new port method.
                        existing = await uow.portfolio_value_snapshots.list_range(
                            portfolio.id,
                            d,
                            d,
                        )
                        if existing:
                            logger.info(  # type: ignore[no-any-return]
                                "portfolio_snapshot_catchup_skip_existing",
                                portfolio_id=str(portfolio.id),
                                date=d.isoformat(),
                            )
                            continue

                        # F-210 (QA iter-2): skip empty portfolios in catch-up
                        # too — same rationale as the steady-state pass.
                        holdings = await uow.holdings.list_by_portfolio(portfolio.id)
                        if not holdings:
                            logger.info(  # type: ignore[no-any-return]
                                "portfolio_snapshot_catchup_skip_empty",
                                portfolio_id=str(portfolio.id),
                                date=d.isoformat(),
                            )
                            continue

                        await use_case.execute(
                            ComputePortfolioValueCommand(
                                portfolio_id=portfolio.id,
                                tenant_id=portfolio.tenant_id,
                                as_of_date=d,
                            ),
                            uow,
                        )
                        await uow.commit()
                        wrote_any = True
                        logger.info(  # type: ignore[no-any-return]
                            "portfolio_snapshot_catchup_wrote",
                            portfolio_id=str(portfolio.id),
                            date=d.isoformat(),
                        )
                except Exception as exc:
                    # Same defensive policy as the steady-state pass — keep
                    # going even if one portfolio is broken.
                    logger.error(  # type: ignore[no-any-return]
                        "portfolio_snapshot_catchup_compute_failed",
                        portfolio_id=str(portfolio.id),
                        date=d.isoformat(),
                        error=type(exc).__name__,
                        error_message=str(exc),
                    )

            # Phase 2 only when we actually wrote something for this day.
            # Skipping the aggregation when all sub-portfolios were already
            # snapshotted keeps catch-up fast (no redundant DB reads).
            if wrote_any:
                try:
                    await self._aggregate_root_portfolios(d)
                except Exception as exc:
                    logger.error(  # type: ignore[no-any-return]
                        "portfolio_snapshot_catchup_root_aggregate_failed",
                        date=d.isoformat(),
                        error=type(exc).__name__,
                        error_message=str(exc),
                    )

        logger.info("portfolio_snapshot_worker_startup_catchup_complete")  # type: ignore[no-any-return]

    async def run_once(self, as_of_date: date) -> None:
        """Single pass — Phase 1 (non-root) then Phase 2 (root aggregation).

        Public so tests / backfill scripts can drive the same code path
        without going through the sleep loop.
        """
        await self._snapshot_non_root_portfolios(as_of_date)
        await self._aggregate_root_portfolios(as_of_date)

    # ── Phase 1: non-root portfolios ──────────────────────────────────────────

    async def _snapshot_non_root_portfolios(self, as_of_date: date) -> None:
        """Compute snapshots for every non-root active portfolio.

        One UoW + commit per portfolio so a single failure does not
        roll back successful snapshots from earlier in the iteration.

        F-210 (QA iter-2): skip writing snapshots for genuinely empty
        portfolios (no holdings, total_value == total_cost == 0). The
        previous behaviour wrote a $0 row every trading day, producing a
        flat-zero equity curve that the frontend dutifully rendered as a
        line at $0 — misleading users into thinking the chart was broken.
        Empty portfolios now stay empty in the time-series; the frontend
        renders an "Open a position to see your equity curve" empty state
        instead.
        """
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            portfolios = await uow.portfolios.list_all_non_root_active()

        logger.info(  # type: ignore[no-any-return]
            "portfolio_snapshot_phase1_start",
            as_of_date=as_of_date.isoformat(),
            portfolio_count=len(portfolios),
        )

        use_case = ComputePortfolioValueUseCase(self._price_client)

        for portfolio in portfolios:
            try:
                async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
                    # F-210: probe holdings first; if the portfolio is empty
                    # AND the (yet-to-be-computed) snapshot would be a $0
                    # row, skip writing entirely. We can't precisely predict
                    # the use case's output without running it, so we use
                    # holdings as the cheap pre-check: a portfolio with
                    # zero holdings has no positions to value, so any
                    # snapshot would necessarily be (total_value=0,
                    # total_cost=0). Cash is not yet tracked (v1).
                    holdings = await uow.holdings.list_by_portfolio(portfolio.id)
                    if not holdings:
                        logger.info(  # type: ignore[no-any-return]
                            "portfolio_snapshot_skip_empty",
                            portfolio_id=str(portfolio.id),
                            as_of_date=as_of_date.isoformat(),
                        )
                        continue

                    await use_case.execute(
                        ComputePortfolioValueCommand(
                            portfolio_id=portfolio.id,
                            tenant_id=portfolio.tenant_id,
                            as_of_date=as_of_date,
                        ),
                        uow,
                    )
                    await uow.commit()
            except Exception as exc:
                # WHY catch broadly: a single bad portfolio (e.g. corrupted
                # holding row, transient DB error mid-pass) must not stop
                # the worker. Phase 2 still proceeds — the root aggregation
                # will simply omit this portfolio's contribution for today,
                # and the next scheduled run will retry.
                logger.error(  # type: ignore[no-any-return]
                    "portfolio_snapshot_compute_failed",
                    portfolio_id=str(portfolio.id),
                    error=type(exc).__name__,
                    error_message=str(exc),
                )

    # ── Phase 2: root portfolio aggregation ───────────────────────────────────

    async def _aggregate_root_portfolios(self, as_of_date: date) -> None:
        """Sum each user's non-root snapshots into a root snapshot row.

        This runs AFTER Phase 1 so the read picks up everything that
        was successfully written. We deliberately re-read from DB (vs
        keeping Phase 1 results in memory) so partial Phase-1 success
        is reflected accurately in the root sum.
        """
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            roots: list[Portfolio] = await uow.portfolios.list_active_root()

        logger.info(  # type: ignore[no-any-return]
            "portfolio_snapshot_phase2_start",
            as_of_date=as_of_date.isoformat(),
            root_count=len(roots),
        )

        for root in roots:
            try:
                async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
                    sub_ids = await uow.portfolios.list_non_root_active_ids_by_owner(
                        root.owner_id,
                        root.tenant_id,
                    )
                    if not sub_ids:
                        # User has only the root (auto-provisioned but never
                        # added a real portfolio) — write a zero row so the
                        # time-series still has a point for today.
                        zero = PortfolioValueSnapshot(
                            portfolio_id=root.id,
                            tenant_id=root.tenant_id,
                            snapshot_date=as_of_date,
                            total_value=Decimal(0),
                            total_cost=Decimal(0),
                            cash_value=Decimal(0),
                        )
                        await uow.portfolio_value_snapshots.upsert(zero)
                        await uow.commit()
                        continue

                    total_value = Decimal(0)
                    total_cost = Decimal(0)
                    cash_value = Decimal(0)
                    # F-401: propagate ``partial_prices`` upward — if any
                    # sub-portfolio used a stale-price or cost-basis fallback,
                    # the aggregated root row inherits that flag so the user
                    # sees the caveat even when looking at the "All Accounts"
                    # view rather than the individual account.
                    aggregated_data_quality = DATA_QUALITY_OK
                    for sub_id in sub_ids:
                        # We pull just the one row matching today's date.
                        rows = await uow.portfolio_value_snapshots.list_range(
                            sub_id,
                            as_of_date,
                            as_of_date,
                        )
                        if rows:
                            row = rows[0]
                            total_value += row.total_value
                            total_cost += row.total_cost
                            cash_value += row.cash_value
                            if row.data_quality != DATA_QUALITY_OK:
                                aggregated_data_quality = DATA_QUALITY_PARTIAL_PRICES

                    aggregated = PortfolioValueSnapshot(
                        portfolio_id=root.id,
                        tenant_id=root.tenant_id,
                        snapshot_date=as_of_date,
                        total_value=total_value,
                        total_cost=total_cost,
                        cash_value=cash_value,
                        data_quality=aggregated_data_quality,
                    )
                    await uow.portfolio_value_snapshots.upsert(aggregated)
                    await uow.commit()
            except Exception as exc:
                logger.error(  # type: ignore[no-any-return]
                    "portfolio_snapshot_root_aggregate_failed",
                    portfolio_id=str(root.id),
                    error=type(exc).__name__,
                    error_message=str(exc),
                )


# ── Process entry point ───────────────────────────────────────────────────────


async def main() -> None:
    """Wire dependencies and start the snapshot worker."""
    from observability import configure_logging  # type: ignore[import-untyped]
    from portfolio.config import Settings
    from portfolio.infrastructure.db.session import _build_factories

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="portfolio-snapshot-worker",
        level=settings.log_level,
        json=settings.log_json,
    )

    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    async with httpx.AsyncClient(timeout=10.0, headers=_system_jwt_headers()) as http_client:
        price_client = HttpOHLCVPriceClient(
            http=http_client,
            market_data_url=settings.market_data_service_url,
        )
        worker = PortfolioSnapshotWorker(
            session_factory=write_factory,
            price_client=price_client,
            settings=settings,
        )
        await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
