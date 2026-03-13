"""ORM model for the ``highlights`` fundamentals table (FIX-F10)."""

from __future__ import annotations

from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models.fundamentals._base import FundamentalsModelMixin


class HighlightsModel(FundamentalsModelMixin, Base):
    """TTM operational metrics (revenue, EBITDA, EPS, ROE, ROA) for an instrument."""

    __tablename__ = "highlights"
