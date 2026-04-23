"""Portfolio entity."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from portfolio.domain.enums import PortfolioStatus
from portfolio.domain.errors import PortfolioArchivedError


@dataclass
class Portfolio:
    """A named collection of holdings owned by a single user within a tenant.

    Unique constraint: (owner_id, name).
    """

    tenant_id: UUID
    owner_id: UUID
    name: str
    currency: str = "USD"
    id: UUID = field(default_factory=new_uuid)
    status: PortfolioStatus = PortfolioStatus.ACTIVE
    created_at: datetime = field(default_factory=utc_now)

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
        self.status = PortfolioStatus.ARCHIVED
