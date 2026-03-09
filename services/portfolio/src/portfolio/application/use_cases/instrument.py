"""Instrument read use cases."""

from __future__ import annotations

from typing import TYPE_CHECKING

from portfolio.domain.errors import InstrumentNotFoundError

if TYPE_CHECKING:
    from uuid import UUID

    from portfolio.application.ports.unit_of_work import UnitOfWork
    from portfolio.domain.entities import InstrumentRef


class GetInstrumentUseCase:
    async def execute(self, symbol: str, exchange: str, uow: UnitOfWork) -> InstrumentRef:
        instrument = await uow.instruments.get_by_symbol_exchange(symbol, exchange)
        if instrument is None:
            raise InstrumentNotFoundError(f"Instrument {symbol}:{exchange} not found")
        return instrument


class GetInstrumentByIdUseCase:
    async def execute(self, instrument_id: UUID, uow: UnitOfWork) -> InstrumentRef:
        instrument = await uow.instruments.get(instrument_id)
        if instrument is None:
            raise InstrumentNotFoundError(f"Instrument {instrument_id} not found")
        return instrument


class ListInstrumentsUseCase:
    async def execute(self, uow: UnitOfWork) -> list[InstrumentRef]:
        return await uow.instruments.list_all()
