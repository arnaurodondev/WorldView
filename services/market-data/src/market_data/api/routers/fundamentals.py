"""Fundamentals API router.

Path parameter ``instrument_id`` is the instrument UUID (not security UUID).
Fundamentals records are stored per instrument in the DB.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from market_data.api.dependencies import get_uow
from market_data.api.schemas.fundamentals import FundamentalsRecordResponse, FundamentalsResponse
from market_data.application.ports.uow import UnitOfWork
from market_data.domain.entities import FundamentalsRecord
from market_data.domain.enums import FundamentalsSection
from market_data.infrastructure.db.repositories.fundamentals_query import query_fundamentals

router = APIRouter(tags=["fundamentals"])

_INSTRUMENT_ID_PARAM = Path(
    description=(
        "Instrument UUID. Fundamentals are stored per instrument. "
        "This path parameter was historically named 'security_id' but refers to the instrument UUID."
    )
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


async def _fetch_section(
    instrument_id: str,
    section: FundamentalsSection,
    uow: UnitOfWork,
) -> list[FundamentalsRecord]:
    """Fetch fundamentals records via the read session.

    ``query_fundamentals`` accepts an ``AsyncSession`` directly so that the
    read replica is used when one is configured.
    """
    session = uow.get_read_session()
    return await query_fundamentals(session, security_id=instrument_id, section=section)


@router.get("/fundamentals/{instrument_id}", response_model=FundamentalsResponse)
async def get_fundamentals(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return all fundamentals sections for the given instrument."""
    records: list[FundamentalsRecord] = []
    for section in FundamentalsSection:
        section_records = await _fetch_section(instrument_id, section, uow)
        records.extend(section_records)
    if not records:
        raise HTTPException(status_code=404, detail=f"No fundamentals found for instrument: {instrument_id}")
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/income-statement", response_model=FundamentalsResponse)
async def get_income_statement(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return income statement records for the given instrument."""
    records = await _fetch_section(instrument_id, FundamentalsSection.INCOME_STATEMENT, uow)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/balance-sheet", response_model=FundamentalsResponse)
async def get_balance_sheet(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return balance sheet records for the given instrument."""
    records = await _fetch_section(instrument_id, FundamentalsSection.BALANCE_SHEET, uow)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/cash-flow", response_model=FundamentalsResponse)
async def get_cash_flow(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return cash flow statement records for the given instrument."""
    records = await _fetch_section(instrument_id, FundamentalsSection.CASH_FLOW, uow)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/highlights", response_model=FundamentalsResponse)
async def get_highlights(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return highlights (TTM metrics) for the given instrument."""
    records = await _fetch_section(instrument_id, FundamentalsSection.HIGHLIGHTS, uow)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/valuation", response_model=FundamentalsResponse)
async def get_valuation(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return valuation ratio records for the given instrument."""
    records = await _fetch_section(instrument_id, FundamentalsSection.VALUATION_RATIOS, uow)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/analyst-consensus", response_model=FundamentalsResponse)
async def get_analyst_consensus(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return analyst consensus records for the given instrument."""
    records = await _fetch_section(instrument_id, FundamentalsSection.ANALYST_CONSENSUS, uow)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/dividends", response_model=FundamentalsResponse)
async def get_dividends(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return dividend history records for the given instrument."""
    records = await _fetch_section(instrument_id, FundamentalsSection.DIVIDEND_HISTORY, uow)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/earnings", response_model=FundamentalsResponse)
async def get_earnings(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return earnings history records for the given instrument."""
    records = await _fetch_section(instrument_id, FundamentalsSection.EARNINGS_HISTORY, uow)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/company-profile", response_model=FundamentalsResponse)
async def get_company_profile(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return company profile for the given instrument."""
    records = await _fetch_section(instrument_id, FundamentalsSection.COMPANY_PROFILE, uow)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/institutional-holders", response_model=FundamentalsResponse)
async def get_institutional_holders(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return institutional holders data for the given instrument."""
    records = await _fetch_section(instrument_id, FundamentalsSection.INSTITUTIONAL_HOLDERS, uow)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/fund-holders", response_model=FundamentalsResponse)
async def get_fund_holders(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return fund holders data for the given instrument."""
    records = await _fetch_section(instrument_id, FundamentalsSection.FUND_HOLDERS, uow)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])


@router.get("/fundamentals/{instrument_id}/insider-transactions-snapshot", response_model=FundamentalsResponse)
async def get_insider_transactions_snapshot(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
) -> FundamentalsResponse:
    """Return insider transactions snapshot for the given instrument."""
    records = await _fetch_section(instrument_id, FundamentalsSection.INSIDER_TRANSACTIONS_SNAPSHOT, uow)
    return FundamentalsResponse(security_id=instrument_id, records=[_to_record_response(r) for r in records])
