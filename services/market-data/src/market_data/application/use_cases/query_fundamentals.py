"""Fundamentals query use cases."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.application.ports.uow import UnitOfWork
    from market_data.domain.entities import FundamentalsRecord
    from market_data.domain.enums import FundamentalsSection


class GetFundamentalsSectionUseCase:
    """Return fundamentals records for one instrument section, or all sections."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        instrument_id: str,
        section: FundamentalsSection,
    ) -> list[FundamentalsRecord]:
        """Return all records for the given instrument and section."""
        return await self._uow.fundamentals_read.find_by_section(instrument_id, section)

    async def execute_all_sections(self, instrument_id: str) -> list[FundamentalsRecord]:
        """Return records for all fundamentals sections for the given instrument."""
        from market_data.domain.enums import FundamentalsSection as FundamentalsSectionEnum

        records: list[FundamentalsRecord] = []
        for section in FundamentalsSectionEnum:
            section_records = await self._uow.fundamentals_read.find_by_section(instrument_id, section)
            records.extend(section_records)
        return records
