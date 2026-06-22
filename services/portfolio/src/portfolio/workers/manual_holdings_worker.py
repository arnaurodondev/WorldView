"""ManualHoldingsWorker — nightly full sweep to recompute MANUAL portfolio holdings.

PLAN-0114 W1 / T-W1-08.

WHY a nightly worker in addition to the Kafka consumer:
    The Kafka consumer handles real-time event-driven recomputes: every time a
    MANUAL portfolio transaction is recorded, the consumer receives a
    PortfolioHoldingRecomputeRequested event and rebuilds holdings within seconds.

    The nightly worker is a fallback safety net for two scenarios:
    1. The consumer was down during a burst of transactions (e.g. first deploy).
    2. An advisory-lock collision caused the consumer to skip a recompute.

    At 22:00 UTC every night the worker iterates every MANUAL portfolio that
    has at least one transaction and recomputes holdings if they haven't been
    freshly recomputed (or unconditionally — idempotency ensures safety).

    Cron expression: ``"0 22 * * *"`` (22:00 UTC, daily).

Entry point::

    python -m portfolio.workers.manual_holdings_worker
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from observability import get_logger, start_metrics_server  # type: ignore[import-untyped]
from portfolio.application.use_cases.compute_manual_holdings import (
    ComputeManualHoldingsCommand,
    ComputeManualHoldingsUseCase,
)
from portfolio.domain.enums import PortfolioKind

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Cron expression — 22:00 UTC daily
CRON_EXPRESSION = "0 22 * * *"


def _seconds_until_next_run() -> float:
    """Compute seconds until the next 22:00 UTC wall-clock trigger.

    Simple implementation: finds the next occurrence of HH:MM=22:00 UTC
    relative to the current UTC time. Fires immediately if it's already past
    22:00 on the current day and we haven't fired today yet (handled by the
    run loop which tracks last_run_date).
    """
    now = datetime.now(tz=UTC)
    target = now.replace(hour=22, minute=0, second=0, microsecond=0)
    if now >= target:
        # Already past 22:00 today — next run is tomorrow.
        from datetime import timedelta

        target = target + timedelta(days=1)
    return (target - now).total_seconds()


class ManualHoldingsWorker:
    """Nightly worker: recompute holdings for all MANUAL portfolios.

    PLAN-0114 W1 / T-W1-08.

    The worker iterates all non-root active portfolios and filters to MANUAL
    kind. For each MANUAL portfolio with at least one transaction it calls
    ``ComputeManualHoldingsUseCase`` with ``trigger='scheduled'``.

    Advisory lock: the use case attempts ``pg_try_advisory_xact_lock``; if
    the Kafka consumer is currently processing a recompute for the same
    portfolio, this worker skips that portfolio and moves on.
    """

    CRON_EXPRESSION = CRON_EXPRESSION

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        emit_holding_changed_events: bool = False,
    ) -> None:
        self._session_factory = session_factory
        self._use_case = ComputeManualHoldingsUseCase(
            emit_holding_changed_events=emit_holding_changed_events,
        )

    async def run(self) -> None:
        """Main loop — wakes at 22:00 UTC, runs one full pass, then sleeps."""
        logger.info("manual_holdings_worker_started")  # type: ignore[no-any-return]

        while True:
            sleep_seconds = _seconds_until_next_run()
            logger.info(  # type: ignore[no-any-return]
                "manual_holdings_worker_sleeping",
                sleep_seconds=round(sleep_seconds),
            )
            await asyncio.sleep(sleep_seconds)

            try:
                await self.run_once()
            except Exception as exc:
                logger.error(  # type: ignore[no-any-return]
                    "manual_holdings_worker_cycle_error",
                    error=str(exc),
                )

    async def run_once(self) -> None:
        """Run a single pass over all MANUAL portfolios.

        Opens a fresh UoW for portfolio listing, then a separate UoW per
        portfolio recomputation (same pattern as BrokerageTransactionSyncWorker).
        """
        from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

        logger.info("manual_holdings_worker_cycle_started")  # type: ignore[no-any-return]
        start = time.monotonic()

        # ── 1. Load all MANUAL portfolios (short UoW, read-only) ─────────────
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            # list_all_non_root_active returns MANUAL + BROKERAGE portfolios.
            # We filter to MANUAL here in Python (no extra SQL needed — the list
            # is small for the user counts we target: ≤ 5 portfolios / user).
            all_portfolios = await uow.portfolios.list_all_non_root_active()

        manual_portfolios = [p for p in all_portfolios if p.kind == PortfolioKind.MANUAL]
        logger.info(  # type: ignore[no-any-return]
            "manual_holdings_worker_portfolios_found",
            total=len(all_portfolios),
            manual=len(manual_portfolios),
        )

        processed = 0
        skipped = 0
        errors = 0

        # ── 2. Recompute each MANUAL portfolio ────────────────────────────────
        for portfolio in manual_portfolios:
            try:
                async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
                    # Check if portfolio has at least one transaction (avoid
                    # creating an empty UoW overhead for portfolios with no history).
                    _transactions, total = await uow.transactions.list_by_portfolio(
                        portfolio.id,
                        portfolio.tenant_id,
                        limit=1,
                        offset=0,
                    )
                    if total == 0:
                        # No transactions yet — skip (holdings table is already empty).
                        skipped += 1
                        continue

                    cmd = ComputeManualHoldingsCommand(
                        portfolio_id=portfolio.id,
                        tenant_id=portfolio.tenant_id,
                        owner_id=portfolio.owner_id,
                        trigger="scheduled",
                    )
                    result = await self._use_case.execute(cmd, uow)
                    if result.skipped:
                        skipped += 1
                    else:
                        processed += 1
                        logger.debug(  # type: ignore[no-any-return]
                            "manual_holdings_worker_portfolio_done",
                            portfolio_id=str(portfolio.id),
                            upserted=result.upserted,
                            deleted=result.deleted,
                        )
            except Exception as exc:
                errors += 1
                logger.error(  # type: ignore[no-any-return]
                    "manual_holdings_worker_portfolio_error",
                    portfolio_id=str(portfolio.id),
                    error=str(exc),
                )

        elapsed = time.monotonic() - start
        logger.info(  # type: ignore[no-any-return]
            "manual_holdings_worker_cycle_done",
            elapsed_seconds=round(elapsed, 2),
            processed=processed,
            skipped=skipped,
            errors=errors,
        )


# ── Process entry point ───────────────────────────────────────────────────────


async def main() -> None:
    from observability import configure_logging  # type: ignore[import-untyped]
    from portfolio.config import Settings
    from portfolio.infrastructure.db.session import _build_factories

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="portfolio-manual-holdings-worker",
        level=settings.log_level,
        json=settings.log_json,
    )

    metrics_handle = start_metrics_server(
        service_name="portfolio-manual-holdings-worker",
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    worker = ManualHoldingsWorker(
        session_factory=write_factory,
        emit_holding_changed_events=getattr(settings, "emit_holding_changed_events", False),
    )
    try:
        await worker.run()
    finally:
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()


if __name__ == "__main__":
    asyncio.run(main())
