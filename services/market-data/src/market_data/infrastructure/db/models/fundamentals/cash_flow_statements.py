"""ORM model for the ``cash_flow_statements`` fundamentals table."""

from __future__ import annotations

from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models.fundamentals._base import FundamentalsModelMixin


class CashFlowStatementModel(FundamentalsModelMixin, Base):
    """Periodic cash flow statement data for an instrument."""

    __tablename__ = "cash_flow_statements"
