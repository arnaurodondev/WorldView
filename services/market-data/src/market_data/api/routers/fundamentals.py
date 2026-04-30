"""Fundamentals API router.

Path parameter ``instrument_id`` is the instrument UUID (not security UUID).
Fundamentals records are stored per instrument in the DB.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path

from market_data.api.dependencies import get_fundamentals_section_uc, get_fundamentals_snapshot_uc
from market_data.api.schemas.fundamentals import (
    FundamentalsRecordResponse,
    FundamentalsResponse,
    FundamentalsSnapshotResponse,
)
from market_data.application.use_cases.query_fundamentals import GetFundamentalsSectionUseCase
from market_data.domain.entities import FundamentalsRecord
from market_data.domain.enums import FundamentalsSection

router = APIRouter(tags=["fundamentals"])

# PLAN-0059 W0 fix F-010 (2026-04-30):
# `pattern=` constrains the path parameter to a UUID-shaped string. Without
# this, a request to GET /v1/fundamentals/screen (the screener endpoint
# defined in fundamental_metrics.router) was falling through to
# /fundamentals/{instrument_id} with instrument_id="screen", asyncpg then
# rejected the literal as a UUID with DataError → 500. With the pattern,
# non-UUID paths return 422 Validation Error and FastAPI keeps looking for
# another matching route — which is what we want when /screen is a literal.
_UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
_INSTRUMENT_ID_PARAM = Path(
    pattern=_UUID_PATTERN,
    description=(
        "Instrument UUID. Fundamentals are stored per instrument. "
        "This path parameter was historically named 'security_id' but refers to the instrument UUID."
    ),
)


def _to_record_response(record: FundamentalsRecord) -> FundamentalsRecordResponse:
    return FundamentalsRecordResponse(
        id=record.id,
        security_id=record.security_id,
        section=str(record.section),
        period_end=record.period_end,
        period_type=str(record.period_type),
        data=record.data,
        source=record.source,
        ingested_at=record.ingested_at,
    )


# NOTE: /fundamentals/{instrument_id}/snapshot MUST be registered before
# /fundamentals/{instrument_id} to prevent FastAPI matching "snapshot" as an
# instrument_id.  FastAPI evaluates routes in registration order.
@router.get("/fundamentals/{instrument_id}/snapshot", response_model=FundamentalsSnapshotResponse)
async def get_fundamentals_snapshot(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[Any, Depends(get_fundamentals_snapshot_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsSnapshotResponse:
    """Return the pre-computed flat snapshot of 10 key derived metrics.

    WHY /snapshot sub-path: this endpoint returns a flat typed snapshot
    (one row per instrument) rather than the raw section records that the
    parent /fundamentals/{id} returns.  The snapshot is populated by the
    backfill script and updated on each EODHD ingest cycle.

    Returns 200 with all-null fields if the snapshot row exists but no
    data has been ingested yet.  Returns 404 only if the instrument itself
    is unknown — callers should always get a typed response shape.
    """
    result = await uc.execute(instrument_id)
    if result is None:
        # No snapshot row yet — return a shell with nulls rather than 404.
        # WHY not 404: the FundamentalsTab must render "—" placeholders (not an
        # error state) for instruments that haven't been backfilled yet.
        return FundamentalsSnapshotResponse(instrument_id=instrument_id)
    return FundamentalsSnapshotResponse(**result)


@router.get("/fundamentals/{instrument_id}", response_model=FundamentalsResponse)
async def get_fundamentals(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetFundamentalsSectionUseCase, Depends(get_fundamentals_section_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return all fundamentals sections for the given instrument."""
    records = await uc.execute_all_sections(instrument_id)
    if not records:
        raise HTTPException(status_code=404, detail=f"No fundamentals found for instrument: {instrument_id}")
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/income-statement", response_model=FundamentalsResponse)
async def get_income_statement(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetFundamentalsSectionUseCase, Depends(get_fundamentals_section_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return income statement records for the given instrument."""
    records = await uc.execute(instrument_id, FundamentalsSection.INCOME_STATEMENT)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/balance-sheet", response_model=FundamentalsResponse)
async def get_balance_sheet(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetFundamentalsSectionUseCase, Depends(get_fundamentals_section_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return balance sheet records for the given instrument."""
    records = await uc.execute(instrument_id, FundamentalsSection.BALANCE_SHEET)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/cash-flow", response_model=FundamentalsResponse)
async def get_cash_flow(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetFundamentalsSectionUseCase, Depends(get_fundamentals_section_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return cash flow statement records for the given instrument."""
    records = await uc.execute(instrument_id, FundamentalsSection.CASH_FLOW)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/highlights", response_model=FundamentalsResponse)
async def get_highlights(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetFundamentalsSectionUseCase, Depends(get_fundamentals_section_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return highlights (TTM metrics) for the given instrument."""
    records = await uc.execute(instrument_id, FundamentalsSection.HIGHLIGHTS)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/valuation", response_model=FundamentalsResponse)
async def get_valuation(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetFundamentalsSectionUseCase, Depends(get_fundamentals_section_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return valuation ratio records for the given instrument."""
    records = await uc.execute(instrument_id, FundamentalsSection.VALUATION_RATIOS)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/analyst-consensus", response_model=FundamentalsResponse)
async def get_analyst_consensus(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetFundamentalsSectionUseCase, Depends(get_fundamentals_section_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return analyst consensus records for the given instrument."""
    records = await uc.execute(instrument_id, FundamentalsSection.ANALYST_CONSENSUS)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/dividends", response_model=FundamentalsResponse)
async def get_dividends(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetFundamentalsSectionUseCase, Depends(get_fundamentals_section_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return dividend history records for the given instrument."""
    records = await uc.execute(instrument_id, FundamentalsSection.DIVIDEND_HISTORY)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/earnings", response_model=FundamentalsResponse)
async def get_earnings(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetFundamentalsSectionUseCase, Depends(get_fundamentals_section_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return earnings history records for the given instrument."""
    records = await uc.execute(instrument_id, FundamentalsSection.EARNINGS_HISTORY)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/company-profile", response_model=FundamentalsResponse)
async def get_company_profile(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetFundamentalsSectionUseCase, Depends(get_fundamentals_section_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return company profile for the given instrument."""
    records = await uc.execute(instrument_id, FundamentalsSection.COMPANY_PROFILE)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/institutional-holders", response_model=FundamentalsResponse)
async def get_institutional_holders(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetFundamentalsSectionUseCase, Depends(get_fundamentals_section_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return institutional holders data for the given instrument."""
    records = await uc.execute(instrument_id, FundamentalsSection.INSTITUTIONAL_HOLDERS)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/fund-holders", response_model=FundamentalsResponse)
async def get_fund_holders(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetFundamentalsSectionUseCase, Depends(get_fundamentals_section_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return fund holders data for the given instrument."""
    records = await uc.execute(instrument_id, FundamentalsSection.FUND_HOLDERS)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/insider-transactions-snapshot", response_model=FundamentalsResponse)
async def get_insider_transactions_snapshot(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetFundamentalsSectionUseCase, Depends(get_fundamentals_section_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return insider transactions snapshot for the given instrument."""
    records = await uc.execute(instrument_id, FundamentalsSection.INSIDER_TRANSACTIONS_SNAPSHOT)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/technicals-snapshot", response_model=FundamentalsResponse)
async def get_technicals_snapshot(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetFundamentalsSectionUseCase, Depends(get_fundamentals_section_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return technical indicators snapshot for the given instrument.

    WHY: Beta, 52W range, moving averages, short interest — all derived from
    EODHD technicals.  S9 proxies this as /v1/fundamentals/{id}/technicals.
    """
    records = await uc.execute(instrument_id, FundamentalsSection.TECHNICALS_SNAPSHOT)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/share-statistics", response_model=FundamentalsResponse)
async def get_share_statistics(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetFundamentalsSectionUseCase, Depends(get_fundamentals_section_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return share statistics for the given instrument.

    WHY: Shares outstanding, float, short interest, % held by insiders/institutions.
    Used by the Ownership sidebar panel on the instrument detail page.
    """
    records = await uc.execute(instrument_id, FundamentalsSection.SHARE_STATISTICS)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/splits-dividends", response_model=FundamentalsResponse)
async def get_splits_dividends(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetFundamentalsSectionUseCase, Depends(get_fundamentals_section_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return stock splits and dividend history for the given instrument.

    WHY: Dividend dates, amounts, and split history — used by the Dividends
    section in FundamentalsTab and the SplitsDividends sidebar component.
    """
    records = await uc.execute(instrument_id, FundamentalsSection.SPLITS_DIVIDENDS)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/earnings-trend", response_model=FundamentalsResponse)
async def get_earnings_trend(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetFundamentalsSectionUseCase, Depends(get_fundamentals_section_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return forward earnings trend estimates for the given instrument.

    WHY: Analyst EPS and revenue estimates by quarter/year — used by the
    EarningsHistoryChart component in FundamentalsTab.
    """
    records = await uc.execute(instrument_id, FundamentalsSection.EARNINGS_TREND)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/earnings-annual-trend", response_model=FundamentalsResponse)
async def get_earnings_annual_trend(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetFundamentalsSectionUseCase, Depends(get_fundamentals_section_uc)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return annual earnings trend estimates for the given instrument.

    WHY: Annual EPS/revenue projections — supplementary data for the
    EarningsHistoryChart when quarterly data is insufficient.
    """
    records = await uc.execute(instrument_id, FundamentalsSection.EARNINGS_ANNUAL_TREND)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])
