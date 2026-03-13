"""ORM model for the ``insider_transactions_snapshot`` fundamentals table (FIX-F7)."""

from __future__ import annotations

from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models.fundamentals._base import FundamentalsModelMixin


class InsiderTransactionsSnapshotModel(FundamentalsModelMixin, Base):
    """Embedded insider transactions snapshot from fundamentals response."""

    __tablename__ = "insider_transactions_snapshot"
