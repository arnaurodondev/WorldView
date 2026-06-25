"""Fundamentals query use cases."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.application.ports.uow import ReadOnlyUnitOfWork
    from market_data.domain.entities import FundamentalsRecord
    from market_data.domain.enums import FundamentalsSection, PeriodType


class GetFundamentalsSectionUseCase:
    """Return fundamentals records for one instrument section, or all sections."""

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        instrument_id: str,
        section: FundamentalsSection,
        period_type: PeriodType | None = None,
    ) -> list[FundamentalsRecord]:
        """Return all records for the given instrument and section.

        2026-06-11 (backend-gaps wave 3): ``period_type`` is forwarded to the
        repository so the statement endpoints can select ANNUAL records.
        Without it, the repo's BP-546 defensive default pinned balance_sheet /
        cash_flow to QUARTERLY — the 17k+ ANNUAL rows in the DB were
        unreachable through the section API.
        """
        return await self._uow.fundamentals_read.find_by_section(instrument_id, section, period_type)

    async def execute_all_sections(self, instrument_id: str) -> list[FundamentalsRecord]:
        """Return records for all fundamentals sections for the given instrument."""
        from market_data.domain.enums import FundamentalsSection as FundamentalsSectionEnum

        records: list[FundamentalsRecord] = []
        for section in FundamentalsSectionEnum:
            section_records = await self._uow.fundamentals_read.find_by_section(instrument_id, section)
            records.extend(section_records)
        return records
