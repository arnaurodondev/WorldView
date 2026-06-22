"""Portfolio entity."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from portfolio.domain.enums import CostBasisMethod, PortfolioKind, PortfolioStatus
from portfolio.domain.errors import PortfolioArchivedError, RootPortfolioNotArchivableError


@dataclass
class Portfolio:
    """A named collection of holdings owned by a single user within a tenant.

    Unique constraint: (owner_id, name).

    PLAN-0046 Wave 3 / T-46-3-01: ``kind`` discriminates between user-managed
    (MANUAL), broker-synced (BROKERAGE) and the auto-provisioned aggregate
    (ROOT). The DB enforces ``UNIQUE (owner_id) WHERE kind = 'root'`` so each
    user has at most one root portfolio.
    """

    tenant_id: UUID
    owner_id: UUID
    name: str
    currency: str = "USD"
    id: UUID = field(default_factory=new_uuid)
    status: PortfolioStatus = PortfolioStatus.ACTIVE
    # Default ``MANUAL`` keeps backwards compatibility with all existing
    # construction sites (CreatePortfolioUseCase, brokerage flows, tests).
    kind: PortfolioKind = PortfolioKind.MANUAL
    # PLAN-0114 W1: cost basis algorithm for MANUAL portfolios.
    # R11-compatible: nullable default keeps brokerage + old rows unchanged.
    cost_basis_method: CostBasisMethod = CostBasisMethod.FIFO
    created_at: datetime = field(default_factory=utc_now)
    # REQ-002a: caller-supplied ``Idempotency-Key`` (UUID) recorded on creation.
    # Nullable for legacy rows + callers that don't send the header. A partial
    # unique index on (tenant_id, idempotency_key) WHERE idempotency_key IS NOT
    # NULL enforces uniqueness only when set (migration 0019).
    idempotency_key: UUID | None = None

    def is_active(self) -> bool:
        return self.status == PortfolioStatus.ACTIVE

    def rename(self, new_name: str) -> None:
        if self.status == PortfolioStatus.ARCHIVED:
            raise PortfolioArchivedError(
                "Cannot rename an archived portfolio",
                tenant_id=self.tenant_id,
            )
        self.name = new_name

    def archive(self) -> None:
        # PLAN-0046 Wave 3: the ROOT portfolio is undeletable. The check lives
        # here (not in the use case) so every code path — API archive, brokerage
        # cleanup, future cron jobs — gets the same guard for free.
        if self.kind == PortfolioKind.ROOT:
            raise RootPortfolioNotArchivableError(
                "Root portfolio cannot be archived",
                tenant_id=self.tenant_id,
                details={"portfolio_id": str(self.id), "kind": str(self.kind)},
            )
        self.status = PortfolioStatus.ARCHIVED
