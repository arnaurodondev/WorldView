"""Instrument query use cases."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.application.ports.uow import ReadOnlyUnitOfWork
    from market_data.domain.entities import Instrument


class GetInstrumentByIdUseCase:
    """Return the instrument with the given UUID, or ``None``."""

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(self, instrument_id: str) -> Instrument | None:
        return await self._uow.instruments_read.find_by_id(instrument_id)


class GetInstrumentBySymbolUseCase:
    """Return the instrument for the given symbol/exchange pair, or ``None``."""

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(self, symbol: str, exchange: str = "") -> Instrument | None:
        return await self._uow.instruments_read.find_by_symbol_exchange(symbol, exchange)


class SearchInstrumentsUseCase:
    """Search instruments with pagination and optional DB-side filters.

    Returns ``(total_count, items)`` so the caller can build paginated responses.
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        query: str = "",
        *,
        has_ohlcv: bool | None = None,
        has_quotes: bool | None = None,
        has_fundamentals: bool | None = None,
        exchange: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[int, list[Instrument]]:
        repo = self._uow.instruments_read
        total = await repo.count(
            query,
            has_ohlcv=has_ohlcv,
            has_quotes=has_quotes,
            has_fundamentals=has_fundamentals,
            exchange=exchange,
        )
        items = await repo.search(
            query,
            has_ohlcv=has_ohlcv,
            has_quotes=has_quotes,
            has_fundamentals=has_fundamentals,
            exchange=exchange,
            limit=limit,
            offset=offset,
        )
        return total, items
