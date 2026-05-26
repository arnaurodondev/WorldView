"""Read-side query helpers for the fundamentals tables.

The ``FundamentalsRepository`` ABC is write-only (upsert-focused).  These
helpers provide read access to the fundamentals data for the API layer.

Note: The domain ``FundamentalsRecord.security_id`` maps to the DB column
``instrument_id`` (the FK to ``instruments.id``).  This is a legacy naming
convention preserved for backward compatibility.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from market_data.domain.entities import FundamentalsRecord
from market_data.domain.enums import FundamentalsSection, PeriodType
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

# Mapping from FundamentalsSection enum → ORM model class
_SECTION_MODEL_MAP: dict[FundamentalsSection, type] = {
    FundamentalsSection.INCOME_STATEMENT: IncomeStatementModel,
    FundamentalsSection.BALANCE_SHEET: BalanceSheetModel,
    FundamentalsSection.CASH_FLOW: CashFlowStatementModel,
    FundamentalsSection.HIGHLIGHTS: HighlightsModel,
    FundamentalsSection.VALUATION_RATIOS: ValuationRatiosModel,
    FundamentalsSection.TECHNICALS_SNAPSHOT: TechnicalsSnapshotModel,
    FundamentalsSection.SHARE_STATISTICS: ShareStatisticsModel,
    FundamentalsSection.SPLITS_DIVIDENDS: SplitsDividendsModel,
    FundamentalsSection.ANALYST_CONSENSUS: AnalystConsensusModel,
    FundamentalsSection.EARNINGS_HISTORY: EarningsHistoryModel,
    FundamentalsSection.EARNINGS_TREND: EarningsTrendModel,
    FundamentalsSection.EARNINGS_ANNUAL_TREND: EarningsAnnualTrendModel,
    FundamentalsSection.DIVIDEND_HISTORY: DividendHistoryModel,
    FundamentalsSection.OUTSTANDING_SHARES: OutstandingSharesModel,
    FundamentalsSection.COMPANY_PROFILE: CompanyProfileModel,
    FundamentalsSection.INSTITUTIONAL_HOLDERS: InstitutionalHoldersModel,
    FundamentalsSection.FUND_HOLDERS: FundHoldersModel,
    FundamentalsSection.INSIDER_TRANSACTIONS_SNAPSHOT: InsiderTransactionsSnapshotModel,
}

# Sections that use FundamentalsModelMixin (have period_type / period_end_date columns)
_MIXIN_SECTIONS: frozenset[FundamentalsSection] = frozenset(
    _SECTION_MODEL_MAP.keys() - {FundamentalsSection.COMPANY_PROFILE}
)


def _row_to_domain(row: object, section: FundamentalsSection) -> FundamentalsRecord:
    """Convert a mixin-based ORM fundamentals row to a domain ``FundamentalsRecord``."""
    return FundamentalsRecord(
        id=row.id,  # type: ignore[attr-defined]
        security_id=row.instrument_id,  # type: ignore[attr-defined]
        section=section,
        period_end=row.period_end_date,  # type: ignore[attr-defined]
        period_type=(
            PeriodType(row.period_type)  # type: ignore[attr-defined]
            if row.period_type in PeriodType._value2member_map_  # type: ignore[attr-defined]
            else PeriodType.ANNUAL
        ),
        data=row.data or {},  # type: ignore[attr-defined]
        source="",
        ingested_at=row.ingested_at,  # type: ignore[attr-defined]
    )


def _company_profile_row_to_domain(row: object) -> FundamentalsRecord:
    """Convert a CompanyProfileModel row (no period columns) to a domain record.

    Uses ``ingested_at`` as a surrogate ``period_end`` and ``PeriodType.SNAPSHOT``
    since company profile is a point-in-time snapshot with no fiscal period.
    """
    return FundamentalsRecord(
        id=row.id,  # type: ignore[attr-defined]
        security_id=row.instrument_id,  # type: ignore[attr-defined]
        section=FundamentalsSection.COMPANY_PROFILE,
        period_end=row.ingested_at,  # type: ignore[attr-defined]
        period_type=PeriodType.SNAPSHOT,
        data=row.data or {},  # type: ignore[attr-defined]
        source="",
        ingested_at=row.ingested_at,  # type: ignore[attr-defined]
    )


async def query_fundamentals(
    session: AsyncSession,
    security_id: str,
    section: FundamentalsSection,
    period_type: PeriodType | None = None,
) -> list[FundamentalsRecord]:
    """Query all records for a given instrument + section.

    Args:
        session: An open ``AsyncSession`` (use the read session for read-only callers).
        security_id: The instrument UUID (stored as instrument_id in DB).
        section: Which fundamentals section to query.
        period_type: Optional periodicity filter. When supplied, results are
            restricted to rows whose ``period_type`` column equals the given
            value (PLAN-0095 T-W1-01). The DB stores both QUARTERLY and ANNUAL
            rows in the same section table for income_statement / balance_sheet
            / cash_flow; without this filter the caller receives a mix and the
            most-recent annual row can shadow a same-period quarterly row, e.g.
            returning $200B ANNUAL revenue where the caller wanted $50B
            QUARTERLY. ``None`` (default) preserves backward-compatible "return
            all periodicities" behaviour.

    Returns:
        List of domain ``FundamentalsRecord`` instances ordered by
        ``period_end_date ASC`` (mixin sections) or ``ingested_at ASC``
        (company profile). The ascending order lets callers use ``slice(-N)``
        to grab the N most recent records without an additional sort pass.

    WHY ORDER BY: Without an explicit order, SQLAlchemy returns rows in
    heap / insertion order which is non-deterministic. For time-series
    sections (e.g. earnings_annual_trend) that have 30+ years of annual
    records, the frontend ``slice(-4)`` must receive them in ascending
    chronological order or it displays the oldest 4 instead of the newest 4.
    """
    model_class = _SECTION_MODEL_MAP.get(section)
    if model_class is None:
        return []

    if section == FundamentalsSection.COMPANY_PROFILE:
        # CompanyProfileModel has no period_end_date; sort by ingested_at ASC
        # so the caller always receives snapshots in ingestion order.
        # ``period_type`` is meaningless for company_profile (a point-in-time
        # snapshot, no period column), so we ignore the kwarg for this section
        # rather than raise — keeps the port signature uniform.
        result: Any = await session.execute(
            select(model_class)
            .where(model_class.instrument_id == security_id)  # type: ignore[attr-defined]
            .order_by(model_class.ingested_at.asc())  # type: ignore[attr-defined]
        )
        rows = result.scalars().all()
        return [_company_profile_row_to_domain(row) for row in rows]

    # Mixin sections all have period_end_date; sort ascending so newest records
    # are last and slice(-N) returns the N most recent entries.
    stmt = (
        select(model_class)
        .where(model_class.instrument_id == security_id)  # type: ignore[attr-defined]
        .order_by(model_class.period_end_date.asc())  # type: ignore[attr-defined]
    )
    # PLAN-0095 T-W1-01: optional periodicity filter. The mixin stores
    # ``period_type`` as a VARCHAR(20) (see _base.py); compare against the
    # enum's string value so SQLAlchemy renders a bind param of the same type.
    if period_type is not None:
        stmt = stmt.where(model_class.period_type == period_type.value)  # type: ignore[attr-defined]
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [_row_to_domain(row, section) for row in rows]
