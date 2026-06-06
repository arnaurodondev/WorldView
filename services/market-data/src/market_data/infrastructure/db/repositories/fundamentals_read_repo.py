"""Read-only fundamentals repository implementation.

Wraps ``fundamentals_query.query_fundamentals`` to satisfy the
``FundamentalsReadRepository`` port so the API layer never imports
infrastructure functions directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from market_data.application.ports.repositories import FundamentalsReadRepository
from market_data.infrastructure.db.repositories.fundamentals_query import query_fundamentals

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from market_data.domain.entities import FundamentalsRecord
    from market_data.domain.enums import FundamentalsSection, PeriodType


class PgFundamentalsReadRepository(FundamentalsReadRepository):
    """SQLAlchemy-backed read repository for fundamentals section data."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_section(
        self,
        instrument_id: str,
        section: FundamentalsSection,
        period_type: PeriodType | None = None,
    ) -> list[FundamentalsRecord]:
        """Return all fundamentals records for the given instrument and section.

        PLAN-0095 T-W1-01: ``period_type`` is an optional periodicity filter
        forwarded straight through to :func:`query_fundamentals`.
        """
        return await query_fundamentals(
            self._session,
            security_id=instrument_id,
            section=section,
            period_type=period_type,
        )
