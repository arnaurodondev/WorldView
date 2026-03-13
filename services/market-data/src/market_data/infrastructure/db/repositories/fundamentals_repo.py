"""PostgreSQL adapter for FundamentalsRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.dialects.postgresql import insert

from market_data.application.ports.repositories import FundamentalsRepository
from market_data.domain.enums import FundamentalsSection
from market_data.infrastructure.db.models.fundamentals import (
    AnalystConsensusModel,
    BalanceSheetModel,
    CashFlowStatementModel,
    CompanyProfileModel,
    DividendHistoryModel,
    EarningsAnnualTrendModel,
    EarningsHistoryModel,
    EarningsTrendModel,
    FundHoldersModel,
    HighlightsModel,
    IncomeStatementModel,
    InsiderTransactionsSnapshotModel,
    InstitutionalHoldersModel,
    OutstandingSharesModel,
    ShareStatisticsModel,
    SplitsDividendsModel,
    TechnicalsSnapshotModel,
    ValuationRatiosModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from market_data.domain.entities import FundamentalsRecord


class PgFundamentalsRepository(FundamentalsRepository):
    """SQLAlchemy-backed implementation of FundamentalsRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _upsert_section(self, model_class: type[Any], record: FundamentalsRecord) -> None:
        """Generic upsert for any fundamentals model."""
        table_name = str(getattr(model_class, "__tablename__", "fundamentals"))
        stmt = insert(model_class).values(
            id=record.id,
            instrument_id=record.security_id,  # domain uses security_id; maps to instrument_id FK
            period_type=str(record.period_type),
            period_end_date=record.period_end,
            data=record.data,
            ingested_at=record.ingested_at,
        )
        stmt = stmt.on_conflict_do_update(
            constraint=f"uq_{table_name}_instrument_period",
            set_={
                "data": stmt.excluded.data,
                "ingested_at": stmt.excluded.ingested_at,
            },
        )
        await self._session.execute(stmt)

    # ── per-section upserts ────────────────────────────────────────────────────

    async def upsert_income_statement(self, record: FundamentalsRecord) -> None:
        await self._upsert_section(IncomeStatementModel, record)

    async def upsert_balance_sheet(self, record: FundamentalsRecord) -> None:
        await self._upsert_section(BalanceSheetModel, record)

    async def upsert_cash_flow(self, record: FundamentalsRecord) -> None:
        await self._upsert_section(CashFlowStatementModel, record)

    async def upsert_valuation_ratios(self, record: FundamentalsRecord) -> None:
        await self._upsert_section(ValuationRatiosModel, record)

    async def upsert_technicals_snapshot(self, record: FundamentalsRecord) -> None:
        await self._upsert_section(TechnicalsSnapshotModel, record)

    async def upsert_share_statistics(self, record: FundamentalsRecord) -> None:
        await self._upsert_section(ShareStatisticsModel, record)

    async def upsert_splits_dividends(self, record: FundamentalsRecord) -> None:
        await self._upsert_section(SplitsDividendsModel, record)

    async def upsert_analyst_consensus(self, record: FundamentalsRecord) -> None:
        await self._upsert_section(AnalystConsensusModel, record)

    async def upsert_earnings_history(self, record: FundamentalsRecord) -> None:
        await self._upsert_section(EarningsHistoryModel, record)

    async def upsert_earnings_trend(self, record: FundamentalsRecord) -> None:
        await self._upsert_section(EarningsTrendModel, record)

    async def upsert_earnings_annual_trend(self, record: FundamentalsRecord) -> None:
        await self._upsert_section(EarningsAnnualTrendModel, record)

    async def upsert_dividend_history(self, record: FundamentalsRecord) -> None:
        await self._upsert_section(DividendHistoryModel, record)

    async def upsert_outstanding_shares(self, record: FundamentalsRecord) -> None:
        await self._upsert_section(OutstandingSharesModel, record)

    async def upsert_highlights(self, record: FundamentalsRecord) -> None:
        await self._upsert_section(HighlightsModel, record)

    async def upsert_company_profile(self, record: FundamentalsRecord) -> None:
        """Upsert company profile — conflict on instrument_id only (one row per instrument)."""
        stmt = insert(CompanyProfileModel).values(
            id=record.id,
            instrument_id=record.security_id,
            data=record.data,
            ingested_at=record.ingested_at,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_company_profiles_instrument",
            set_={
                "data": stmt.excluded.data,
                "ingested_at": stmt.excluded.ingested_at,
            },
        )
        await self._session.execute(stmt)

    async def upsert_institutional_holders(self, record: FundamentalsRecord) -> None:
        await self._upsert_section(InstitutionalHoldersModel, record)

    async def upsert_fund_holders(self, record: FundamentalsRecord) -> None:
        await self._upsert_section(FundHoldersModel, record)

    async def upsert_insider_transactions_snapshot(self, record: FundamentalsRecord) -> None:
        await self._upsert_section(InsiderTransactionsSnapshotModel, record)

    async def merge_upsert(self, records: list[FundamentalsRecord], instrument_id: str) -> None:
        """Route each record to the correct per-section upsert method."""
        _dispatch = {
            FundamentalsSection.INCOME_STATEMENT: self.upsert_income_statement,
            FundamentalsSection.BALANCE_SHEET: self.upsert_balance_sheet,
            FundamentalsSection.CASH_FLOW: self.upsert_cash_flow,
            FundamentalsSection.HIGHLIGHTS: self.upsert_highlights,
            FundamentalsSection.VALUATION_RATIOS: self.upsert_valuation_ratios,
            FundamentalsSection.TECHNICALS_SNAPSHOT: self.upsert_technicals_snapshot,
            FundamentalsSection.SHARE_STATISTICS: self.upsert_share_statistics,
            FundamentalsSection.SPLITS_DIVIDENDS: self.upsert_splits_dividends,
            FundamentalsSection.ANALYST_CONSENSUS: self.upsert_analyst_consensus,
            FundamentalsSection.EARNINGS_HISTORY: self.upsert_earnings_history,
            FundamentalsSection.EARNINGS_TREND: self.upsert_earnings_trend,
            FundamentalsSection.EARNINGS_ANNUAL_TREND: self.upsert_earnings_annual_trend,
            FundamentalsSection.DIVIDEND_HISTORY: self.upsert_dividend_history,
            FundamentalsSection.OUTSTANDING_SHARES: self.upsert_outstanding_shares,
            FundamentalsSection.COMPANY_PROFILE: self.upsert_company_profile,
            FundamentalsSection.INSTITUTIONAL_HOLDERS: self.upsert_institutional_holders,
            FundamentalsSection.FUND_HOLDERS: self.upsert_fund_holders,
            FundamentalsSection.INSIDER_TRANSACTIONS_SNAPSHOT: self.upsert_insider_transactions_snapshot,
        }
        for record in records:
            handler = _dispatch.get(record.section)
            if handler is not None:
                await handler(record)
