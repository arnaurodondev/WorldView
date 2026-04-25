"""DailyBudgetTracker — enforces a daily credit sub-budget for EODHD API calls.

Why a daily budget?
The EODHD token-bucket (ProviderBudget) refills continuously at a fixed rate,
but a misconfigured scheduler or a runaway worker can exhaust the burst capacity
quickly.  DailyBudgetTracker reads the ProviderBudget from the DB and computes
a "daily allotment" = burst_capacity * safety_factor.  By comparing the current
remaining tokens to this allotment we can detect over-consumption early.

Design note:
  The ProviderBudget entity uses a token-bucket model (burst_capacity / tokens /
  refill_rate).  We map it to the daily-budget concept as follows:

    allotted  = burst_capacity * safety_factor
                 (maximum tokens we allow per refill cycle, with a buffer)
    spent     = burst_capacity - tokens
                 (tokens consumed since the last full refill)
    headroom  = (allotted - spent) / allotted
                 (> 0 = within budget; < 0 = over the safe limit)

  This is intentionally simplified — a full monthly quota integration would
  require a separate monthly_credits field on ProviderBudget, which is not
  yet implemented.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from common.time import utc_now  # type: ignore[import-untyped]
from market_ingestion.domain.enums import Provider
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from datetime import date

    from market_ingestion.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)


@dataclass
class DailyBudgetStatus:
    """Snapshot of today's EODHD credit budget status.

    Attributes:
        date:           The calendar date this status applies to (UTC).
        allotted:       Maximum credits we allow today (burst_capacity * safety_factor).
        spent:          Credits consumed since the last full refill
                        (burst_capacity - remaining_tokens).
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
    """Read the ProviderBudget from the DB and compute a daily budget status.

    Usage::

        tracker = DailyBudgetTracker(uow=uow, safety_factor=0.85)
        status = await tracker.get_status()
        if tracker.is_over_daily_limit(status):
            raise ProviderRateLimited("Daily budget exhausted")
    """

    def __init__(self, uow: UnitOfWork, safety_factor: float = 0.85) -> None:
        # The UoW used to read ProviderBudget from the DB.
        self._uow = uow
        # Multiply the burst capacity by this factor to leave a safety buffer.
        # Default of 0.85 means we treat 85% of burst_capacity as the daily limit.
        self._safety_factor = safety_factor

    async def get_status(self) -> DailyBudgetStatus:
        """Compute today's budget status from the ProviderBudget in the DB.

        Returns:
            DailyBudgetStatus with allotted, spent, and headroom_ratio fields.
            If no ProviderBudget row exists for EODHD, creates one with defaults.
        """
        async with self._uow:
            # get_or_create ensures we never return None even on first run
            budget = await self._uow.budgets.get_or_create(Provider.EODHD)

        # burst_capacity is the maximum token pool size — treat it as the
        # "total tokens available per full refill cycle" for budget purposes.
        burst = budget.burst_capacity

        # allotted = burst capacity * safety_factor (floor to int for display)
        if burst <= 0:
            # Guard against a misconfigured budget with zero capacity.
            logger.warning("eodhd_budget_zero_burst_capacity", burst_capacity=burst)
            return DailyBudgetStatus(
                date=utc_now().date(),
                allotted=0,
                spent=0,
                headroom_ratio=0.0,
            )

        allotted = int(burst * self._safety_factor)

        # spent = tokens consumed since last full refill
        # (tokens is the current remaining token count; burst is the max)
        remaining = max(0.0, budget.tokens)
        spent = int(burst - remaining)

        # headroom: positive → safe, negative → over budget
        headroom_ratio = (allotted - spent) / allotted

        today = utc_now().date()

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
        """Return True if spent credits have exceeded the daily allotment.

        A negative headroom_ratio means spent > allotted, i.e. we have consumed
        more than the safety-factor-adjusted burst capacity.
        """
        return status.headroom_ratio < 0.0
