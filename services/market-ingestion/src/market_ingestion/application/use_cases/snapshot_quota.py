"""SnapshotEodhdQuotaUseCase — persist quota usage to DB for observability.

Purpose:
  Reads the ProviderBudget for EODHD from the DB and returns a QuotaSnapshot
  dataclass that the admin endpoint and Grafana can use to display historical
  quota data.

Design:
  This use case intentionally reads only from the DB (no Valkey integration)
  to keep it simple and testable.  If Valkey-backed monthly credit tracking
  is added in a future wave, the ValkeyClient can be injected here and the
  credits_used field updated from Valkey before returning the snapshot.

  The "monthly_budget" is approximated from the token-bucket's burst_capacity:
    - burst_capacity   → daily/session token pool
    - refill_rate      → tokens restored per second
  A proper monthly credit counter would require a separate DB column; until
  that column exists we expose the token-bucket metrics as a useful proxy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from common.time import utc_now  # type: ignore[import-untyped]
from market_ingestion.domain.enums import Provider
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_ingestion.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)


@dataclass
class QuotaSnapshot:
    """Point-in-time view of the EODHD quota state.

    Attributes:
        provider:           Always "eodhd" for this use case.
        month_year:         ISO month string, e.g. "2026-04".
        credits_used:       Tokens consumed since last full refill
                            (burst_capacity - current_tokens).
        budget_limit:       Burst capacity (maximum token pool size).
        utilization_ratio:  credits_used / budget_limit (0.0 - 1.0+).
        tokens_remaining:   Exact remaining token count from the bucket.
        refill_rate:        Tokens per second the bucket refills at.
    """

    provider: str
    month_year: str
    credits_used: int
    budget_limit: int
    utilization_ratio: float
    tokens_remaining: float
    refill_rate: float


class SnapshotEodhdQuotaUseCase:
    """Read ProviderBudget and return a QuotaSnapshot for the admin endpoint.

    Usage::

        uc = SnapshotEodhdQuotaUseCase(uow=uow)
        snapshot = await uc.execute()
        # snapshot.utilization_ratio → 0.35 means 35% of burst used
    """

    def __init__(self, uow: UnitOfWork) -> None:
        # Inject the unit of work; callers typically pass a read-only UoW.
        self._uow = uow

    async def execute(self) -> QuotaSnapshot:
        """Return a QuotaSnapshot for the EODHD provider.

        Reads the ProviderBudget from the DB.  If no row exists for EODHD,
        ``get_or_create`` initialises one with provider defaults.

        Returns:
            QuotaSnapshot with token-bucket fields mapped to quota semantics.
        """
        async with self._uow:
            budget = await self._uow.budgets.get_or_create(Provider.EODHD)

        now = utc_now()
        # Format as "YYYY-MM" for human-readable month labelling.
        month_year = now.strftime("%Y-%m")

        burst = budget.burst_capacity
        remaining = max(0.0, budget.tokens)

        # credits_used = tokens consumed from the current burst pool.
        credits_used = max(0, int(burst - remaining))

        # utilization_ratio: how much of the burst capacity has been used.
        utilization_ratio = (credits_used / burst) if burst > 0 else 0.0

        snapshot = QuotaSnapshot(
            provider="eodhd",
            month_year=month_year,
            credits_used=credits_used,
            budget_limit=int(burst),
            utilization_ratio=utilization_ratio,
            tokens_remaining=remaining,
            refill_rate=budget.refill_rate,
        )

        logger.info(
            "eodhd_quota_snapshot",
            month_year=month_year,
            credits_used=credits_used,
            budget_limit=int(burst),
            utilization_ratio=round(utilization_ratio, 4),
        )

        return snapshot
