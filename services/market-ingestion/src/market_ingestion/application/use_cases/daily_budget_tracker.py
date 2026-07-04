"""DailyBudgetTracker — diagnostic headroom for EODHD's per-day credit spend.

Why a daily budget?
EODHD's plan grants ~100,000 credits/month, which works out to a ~3,300
credits/day steady-state allowance.  We want a *diagnostic* signal (a Grafana
gauge / alert input) that tells us how much of today's allotment we have already
burned, so operators can spot a runaway day before the monthly hard cap trips.

Why this was re-modelled (BP daily-budget mis-model)
----------------------------------------------------
The original tracker derived ``spent`` from the *instantaneous token bucket*::

    spent = burst_capacity - tokens

That bucket refills every second and, by design, runs near-empty whenever
consumption keeps pace with the refill rate.  So ``spent`` sat at ~full burst
permanently → ``is_over_daily_limit()`` was *always* True and the
``s2_eodhd_daily_budget_headroom`` gauge was permanently red and useless.  It
conflated *instantaneous bucket depletion* with *cumulative daily spend* — two
unrelated quantities.

Correct model
-------------
``spent`` is now the **cumulative** EODHD credits billed so far today, read from
the shared Valkey per-UTC-day counter maintained by ``EodhdQuotaService`` (the
same counter the cross-replica monthly guard increments on every billed fetch).
``allotted`` is the **real daily cap** = (monthly hard limit / ~30 days) times
safety_factor.  Headroom = (allotted - spent) / allotted, so it now reflects
actual consumption versus the daily allowance.

This remains diagnostic-only (it feeds the metric/route; it is NOT a hard gate —
the hard 100k/month enforcement lives in ``EodhdQuotaService.try_consume`` at
pipeline Step 0).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from common.time import utc_now  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from datetime import date

    from messaging.eodhd_quota.quota_service import EodhdQuotaService

logger = get_logger(__name__)


@dataclass
class DailyBudgetStatus:
    """Snapshot of today's EODHD credit budget status.

    Attributes:
        date:           The calendar date this status applies to (UTC).
        allotted:       Credits we allow today ((monthly_limit / ~30d) * safety_factor).
        spent:          Cumulative credits billed so far today (Valkey day counter).
        headroom_ratio: (allotted - spent) / allotted.
                        Positive  → within budget.
                        Zero      → exactly at the limit.
                        Negative  → over budget (spent > allotted).
    """

    date: date
    allotted: int
    spent: int
    headroom_ratio: float


class DailyBudgetTracker:
    """Compute today's EODHD daily-budget headroom from cumulative daily spend.

    Args:
        quota_service: The shared :class:`EodhdQuotaService`.  Its per-UTC-day
            Valkey counter is the cumulative-spend source.  May be ``None`` (no
            Valkey configured) — in that case headroom degrades to a neutral 1.0
            ("unknown / assume safe") rather than a misleading permanent red.
        safety_factor: Fraction of the amortised daily cap treated as the
            allotment (default 0.85 leaves a 15% buffer below the hard pace).

    Usage::

        tracker = DailyBudgetTracker(quota_service=qs, safety_factor=0.85)
        status = await tracker.get_status()
        if tracker.is_over_daily_limit(status):
            logger.warning("eodhd_daily_budget_exceeded", spent=status.spent)
    """

    def __init__(
        self,
        quota_service: EodhdQuotaService | None,
        safety_factor: float = 0.85,
    ) -> None:
        self._quota_service = quota_service
        self._safety_factor = safety_factor

    async def get_status(self) -> DailyBudgetStatus:
        """Compute today's budget status from the cumulative Valkey day counter.

        Returns:
            DailyBudgetStatus with allotted, spent, and headroom_ratio fields.
            When no quota service is available, returns a neutral status
            (headroom 1.0) — the budget is simply unknown, never falsely red.
        """
        today = utc_now().date()

        if self._quota_service is None:
            # No Valkey-backed counter → we cannot measure cumulative spend.
            # Report neutral headroom (1.0) instead of the old permanent-red lie.
            logger.debug("daily_budget_no_quota_service")
            return DailyBudgetStatus(date=today, allotted=0, spent=0, headroom_ratio=1.0)

        # Real daily cap = EODHD's per-UTC-day hard limit (dailyRateLimit), the
        # value the guard actually enforces.  Previously this amortised the
        # MONTHLY hard limit over 30.4 days (~3,289/day), which grossly
        # underestimated true headroom now that we know the limit is per-day.
        daily_cap = self._quota_service._daily_hard_limit
        allotted = int(daily_cap * self._safety_factor)

        if allotted <= 0:
            logger.warning("eodhd_daily_budget_zero_allotment", daily_cap=daily_cap)
            return DailyBudgetStatus(date=today, allotted=0, spent=0, headroom_ratio=0.0)

        # Cumulative credits billed so far today (UTC) from the shared counter.
        spent = await self._quota_service.get_daily_credits_used()

        headroom_ratio = (allotted - spent) / allotted

        logger.debug(
            "daily_budget_status",
            date=str(today),
            allotted=allotted,
            spent=spent,
            headroom_ratio=round(headroom_ratio, 4),
        )

        return DailyBudgetStatus(
            date=today,
            allotted=allotted,
            spent=spent,
            headroom_ratio=headroom_ratio,
        )

    def is_over_daily_limit(self, status: DailyBudgetStatus) -> bool:
        """Return True if cumulative daily spend has exceeded today's allotment.

        A negative headroom_ratio means spent > allotted.  This is diagnostic —
        it informs the metric/alert; it does not throttle traffic (the hard cap
        is enforced by EodhdQuotaService at pipeline Step 0).
        """
        return status.headroom_ratio < 0.0
