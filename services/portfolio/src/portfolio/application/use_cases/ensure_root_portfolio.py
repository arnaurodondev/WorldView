"""EnsureRootPortfolioUseCase — idempotently provision a user's ROOT portfolio.

PLAN-0046 Wave 3 / T-46-3-02.

The ROOT portfolio is an aggregate view across all of a user's other
portfolios (manual + brokerage). Each user has exactly one — enforced by
the partial unique index ``uq_portfolios_owner_root``. This use case is
called from two places:

1. ``ProvisionUserUseCase`` — at the end of every successful provision call
   so newly-created users get a root immediately and pre-OIDC users that
   were just linked also acquire one.
2. ``backfill_root_portfolios.py`` — one-shot script that creates roots for
   any pre-existing user that doesn't have one yet (run once per environment
   after migration 0011).

The use case is fully idempotent: calling it twice for the same user is a
no-op on the second call (and incurs no DB writes beyond the ``find``).

WHY no Kafka event emitted: the root portfolio is an internal construct —
no downstream consumer reasons over it. PortfolioCreated is *not* emitted
for ROOT to avoid polluting consumer dashboards / metrics with synthetic
portfolios that hold no positions of their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from common.ids import new_uuid  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.enums import PortfolioKind

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)  # type: ignore[no-any-return]

# WHY a constant: every root portfolio shares the same display name. Centralising
# it here keeps the domain language consistent and makes it trivial to rename in
# one place if the product copy ever changes ("All Accounts" → "Combined" etc.).
ROOT_PORTFOLIO_NAME = "All Accounts"


@dataclass(frozen=True)
class EnsureRootPortfolioResult:
    """Outcome of ``EnsureRootPortfolioUseCase.execute``."""

    portfolio_id: UUID
    created: bool  # True if a fresh root was just inserted, False if it already existed


class EnsureRootPortfolioUseCase:
    """Idempotently create the ``All Accounts`` ROOT portfolio for a user."""

    async def execute(
        self,
        owner_id: UUID,
        tenant_id: UUID,
        uow: UnitOfWork,
        *,
        currency: str = "USD",
    ) -> EnsureRootPortfolioResult:
        # ── Idempotency fast-path ────────────────────────────────────────
        existing = await uow.portfolios.find_root_by_owner(owner_id, tenant_id)
        if existing is not None:
            return EnsureRootPortfolioResult(portfolio_id=existing.id, created=False)

        # ── Create fresh ROOT ───────────────────────────────────────────
        root = Portfolio(
            id=new_uuid(),
            tenant_id=tenant_id,
            owner_id=owner_id,
            name=ROOT_PORTFOLIO_NAME,
            currency=currency,
            kind=PortfolioKind.ROOT,
        )
        await uow.portfolios.save(root)
        # WHY no commit() here: callers (provision_user, backfill script) own
        # their transaction boundaries. Inside ProvisionUserUseCase the root
        # save is bundled with tenant/user inserts in a single commit; the
        # backfill script commits per user explicitly.
        logger.info(
            "root_portfolio_provisioned",
            owner_id=str(owner_id),
            tenant_id=str(tenant_id),
            portfolio_id=str(root.id),
        )
        return EnsureRootPortfolioResult(portfolio_id=root.id, created=True)
