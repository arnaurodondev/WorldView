"""Instrument API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from portfolio.api.dependencies import ReadUoWDep
from portfolio.api.schemas import InstrumentResponse, PaginatedResponse
from portfolio.application.use_cases.instrument import GetInstrumentByIdUseCase, ListInstrumentsUseCase

router = APIRouter(tags=["instruments"])


@router.get("/instruments", response_model=PaginatedResponse[InstrumentResponse])
async def list_instruments(
    uow: ReadUoWDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse[InstrumentResponse]:
    uc = ListInstrumentsUseCase()
    instruments, total = await uc.execute(uow, limit=limit, offset=offset)
    return PaginatedResponse(
        items=[
            InstrumentResponse(
                id=i.id,
                symbol=i.symbol,
                exchange=i.exchange,
                name=i.name,
                currency=i.currency,
                asset_class=i.asset_class,
                entity_id=i.entity_id,
            )
            for i in instruments
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/instruments/{instrument_id}", response_model=InstrumentResponse)
async def get_instrument(instrument_id: UUID, uow: ReadUoWDep) -> InstrumentResponse:
    uc = GetInstrumentByIdUseCase()
    instrument = await uc.execute(instrument_id, uow)
    return InstrumentResponse(
        id=instrument.id,
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        name=instrument.name,
        currency=instrument.currency,
        asset_class=instrument.asset_class,
        entity_id=instrument.entity_id,
    )
