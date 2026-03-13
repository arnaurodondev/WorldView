"""ORM model for the ``technicals_snapshots`` fundamentals table."""

from __future__ import annotations

from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models.fundamentals._base import FundamentalsModelMixin


class TechnicalsSnapshotModel(FundamentalsModelMixin, Base):
    """Technical analysis snapshot data for an instrument."""

    __tablename__ = "technicals_snapshots"
