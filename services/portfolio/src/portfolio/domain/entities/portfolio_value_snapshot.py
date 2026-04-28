"""Portfolio value snapshot — daily point in the value time-series.

PLAN-0046 Wave 4 / T-46-4-01.

One row per ``(portfolio_id, snapshot_date)``. Written by
``PortfolioSnapshotWorker`` once per trading day; read by analytics
endpoints (value-history, drawdown, returns).

The aggregate is intentionally flat — analytics derive everything
they need from ``total_value``, ``total_cost`` and ``cash_value``
without needing per-instrument detail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]


@dataclass
class PortfolioValueSnapshot:
    """Aggregate value/cost for one portfolio on one calendar date."""

    portfolio_id: UUID
    tenant_id: UUID
    snapshot_date: date
    total_value: Decimal
    total_cost: Decimal
    # ``cash_value`` is reserved for v2 — broker cash balance is not
    # tracked in v1 so this is always Decimal(0). Keeping the field on
    # the entity (rather than computing later) avoids a follow-up
    # migration when we wire SnapTrade balances.
    cash_value: Decimal = Decimal(0)
    id: UUID = field(default_factory=new_uuid)
    created_at: datetime = field(default_factory=utc_now)
