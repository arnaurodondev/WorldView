"""ORM model for the ``institutional_holders`` fundamentals table (FIX-F6)."""

from __future__ import annotations

from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models.fundamentals._base import FundamentalsModelMixin


class InstitutionalHoldersModel(FundamentalsModelMixin, Base):
    """Institutional holder data for an instrument."""

    __tablename__ = "institutional_holders"
