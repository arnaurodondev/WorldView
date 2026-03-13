"""ORM model for the ``dividend_summary`` fundamentals table.

Note: ``dividend_summary`` is not a ``FundamentalsSection`` enum value in the
domain layer but is present in the legacy database schema.  It is included
here for completeness per the planning response (MD-002).
"""

from __future__ import annotations

from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models.fundamentals._base import FundamentalsModelMixin


class DividendSummaryModel(FundamentalsModelMixin, Base):
    """Aggregated dividend summary data for an instrument."""

    __tablename__ = "dividend_summary"
