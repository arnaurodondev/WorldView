"""Instrument API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from portfolio.api.dependencies import UoWDep
from portfolio.api.schemas import InstrumentResponse
from portfolio.application.use_cases.instrument import GetInstrumentByIdUseCase, ListInstrumentsUseCase

router = APIRouter(tags=["instruments"])


@router.get("/instruments", response_model=list[InstrumentResponse])
async def list_instruments(uow: UoWDep) -> list[InstrumentResponse]:
    uc = ListInstrumentsUseCase()
    instruments = await uc.execute(uow)
    return [
        InstrumentResponse(
            id=i.id,
            symbol=i.symbol,
            exchange=i.exchange,
            name=i.name,
            currency=i.currency,
            asset_class=i.asset_class,
        )
        for i in instruments
    ]


@router.get("/instruments/{instrument_id}", response_model=InstrumentResponse)
async def get_instrument(instrument_id: UUID, uow: UoWDep) -> InstrumentResponse:
    uc = GetInstrumentByIdUseCase()
    instrument = await uc.execute(instrument_id, uow)
    return InstrumentResponse(
        id=instrument.id,
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        name=instrument.name,
        currency=instrument.currency,
        asset_class=instrument.asset_class,
    )
