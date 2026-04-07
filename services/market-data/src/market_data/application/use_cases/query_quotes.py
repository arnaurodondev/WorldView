"""Quote query use cases.

Cache-aside logic lives in the API router (the cache stores ``QuoteResponse``
API schema objects, which are an API-layer concern).  These use cases handle
only the DB-side retrieval, returning domain ``Quote`` entities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.application.ports.uow import ReadOnlyUnitOfWork
    from market_data.domain.entities import Quote


class GetQuoteUseCase:
    """Return the latest quote for a single instrument from the DB, or ``None``."""

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(self, instrument_id: str) -> Quote | None:
        return await self._uow.quotes_read.find_by_instrument(instrument_id)


class GetQuotesBatchUseCase:
    """Return the latest quotes for a batch of instrument IDs from the DB."""

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(self, instrument_ids: list[str]) -> list[Quote]:
        return await self._uow.quotes_read.find_by_instruments(instrument_ids)
