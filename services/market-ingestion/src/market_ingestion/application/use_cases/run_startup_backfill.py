"""RunStartupBackfillUseCase — one-shot backfill orchestration on scheduler boot.

PLAN-0055 A-2: when ``settings.auto_backfill_on_startup`` is True the scheduler
process spawns this as an ``asyncio.create_task`` (non-blocking) immediately
before its main tick loop. The use case iterates every enabled polling policy
that has ``backfill_enabled=True`` and enqueues a backfill task for the window
``[now - INITIAL_DAYS, now]`` — capped to ``YEARS * 365`` days — unless the
policy's ``backfill_start_date`` already covers (i.e. precedes) that horizon.

Idempotent: re-running on a restarted container is a no-op for any policy whose
``backfill_start_date`` is already at or before the requested horizon.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from market_ingestion.application.use_cases.backfill import (
    BackfillUseCase,
    default_chunk_days_for_timeframe,
)
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_ingestion.application.ports.unit_of_work import UnitOfWork
    from market_ingestion.application.services.provider_routing_cache import ProviderRoutingCache
    from market_ingestion.config import Settings
    from market_ingestion.domain.entities.polling_policy import PollingPolicy
    from market_ingestion.domain.enums import Provider

logger = get_logger(__name__)


@dataclass(frozen=True)
class StartupBackfillSummary:
    """Outcome of a startup backfill pass — emitted as structured log fields."""

    enqueued: int = 0
    skipped: int = 0
    failed: int = 0


class RunStartupBackfillUseCase:
    """Enqueue backfill tasks for every enabled, backfill-eligible polling policy.

    Constructor params are injected so the scheduler can plug in its existing
    write/read session factories. The use case is **best-effort**: a failure on
    one policy is logged and the loop continues — never raises out.
    """

    def __init__(
        self,
        *,
        uow_factory: Callable[[], UnitOfWork],
        settings: Settings,
        routing: ProviderRoutingCache,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings
        self._routing = routing

    async def execute(self) -> StartupBackfillSummary:
        """Run the one-shot pass; safe to call repeatedly (idempotent on cursors)."""
        if not self._settings.auto_backfill_on_startup:
            return StartupBackfillSummary()

        # Clamp INITIAL_DAYS to the YEARS hard cap. ``min`` because INITIAL_DAYS is
        # the operator's ratchet — an over-eager value gets quietly clamped rather
        # than blowing up at startup.
        max_days = self._settings.auto_backfill_years * 365
        horizon_days = min(self._settings.auto_backfill_initial_days, max_days)
        horizon_start = _utc_now() - timedelta(days=horizon_days)

        # We use a fresh UoW just to load policies; per-policy enqueue gets its own
        # transaction below (BP-007 — small transactions, no cross-policy poisoning).
        list_uow = self._uow_factory()
        async with list_uow:
            policies: list[PollingPolicy] = await list_uow.policies.list_enabled()
        backfill_policies = [p for p in policies if p.backfill_enabled]

        enqueued = 0
        skipped = 0
        failed = 0

        for policy in backfill_policies:
            try:
                if self._already_covered(policy, horizon_start):
                    skipped += 1
                    continue
                await self._enqueue_for_policy(policy, horizon_start)
                enqueued += 1
            except Exception as exc:  # — best-effort, isolate per policy
                failed += 1
                logger.warning(
                    "startup_backfill_policy_failed",
                    policy_id=str(policy.id),
                    provider=str(policy.provider),
                    symbol=policy.symbol,
                    error=str(exc),
                )

        summary = StartupBackfillSummary(enqueued=enqueued, skipped=skipped, failed=failed)
        logger.info(
            "startup_backfill_completed",
            enqueued=summary.enqueued,
            skipped=summary.skipped,
            failed=summary.failed,
            horizon_days=horizon_days,
        )
        return summary

    @staticmethod
    def _already_covered(policy: PollingPolicy, horizon_start: datetime) -> bool:
        """Whether this policy already has a watermark at or before ``horizon_start``.

        ``backfill_start_date`` is the only cursor on the entity (no
        ``backfill_status`` field exists). If it's set and already at/before the
        requested window, the existing backfill covers us — skip.
        """
        existing = policy.backfill_start_date
        if existing is None:
            return False
        # Normalize date → datetime for comparison.
        if not isinstance(existing, datetime):
            from datetime import datetime as _dt

            existing = _dt(existing.year, existing.month, existing.day, tzinfo=UTC)
        if existing.tzinfo is None:
            existing = existing.replace(tzinfo=UTC)
        return existing <= horizon_start

    async def _enqueue_for_policy(self, policy: PollingPolicy, horizon_start: datetime) -> None:
        timeframe = policy.timeframe or "1d"
        chunk_days = default_chunk_days_for_timeframe(timeframe)
        provider = self._resolve_provider(policy)
        symbol = policy.symbol or ""
        # Empty symbol policies (wildcards) cannot be backfilled by symbol-keyed
        # tasks. Skip them at the orchestration layer — the regular scheduler
        # tick will discover symbols separately.
        if not symbol:
            return

        uow = self._uow_factory()
        backfill = BackfillUseCase(uow)
        await backfill.execute(
            provider=provider,
            symbol=symbol,
            start_date=horizon_start,
            end_date=_utc_now(),
            timeframe=timeframe,
            chunk_days=chunk_days,
            exchange=policy.exchange,
        )

    def _resolve_provider(self, policy: PollingPolicy) -> Provider:
        """Use the routing cache primary if a route exists; fall back to the policy provider.

        Routing weights (MARKET_INGESTION_ROUTING_OHLCV_EOD etc.) are the canonical
        source of truth for "which provider should we ask for this dataset+timeframe?".
        Falling back to the policy's static provider keeps legacy seeded data working.
        """
        from market_ingestion.domain.enums import Provider as _ProviderEnum

        try:
            primary = self._routing.primary_for(
                dataset_type=str(policy.dataset_type),
                timeframe=policy.timeframe,
            )
            return _ProviderEnum(primary)
        except (KeyError, ValueError, AttributeError):
            return policy.provider


def _utc_now() -> datetime:
    """Direct import would create a cycle through common — keep it inline."""
    import common.time  # type: ignore[import-untyped]

    return common.time.utc_now()
