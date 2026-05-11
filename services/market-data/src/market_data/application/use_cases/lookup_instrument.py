"""InstrumentLookupUseCase — unified instrument lookup by id, isin, or symbol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from market_data.domain.errors import InstrumentNotFoundError

if TYPE_CHECKING:
    from market_data.application.ports.uow import ReadOnlyUnitOfWork
    from market_data.domain.entities import Instrument, Security


@dataclass(frozen=True, slots=True)
class InstrumentLookupResult:
    """Resolved instrument with optional security enrichment data."""

    instrument: Instrument
    security: Security | None = None


class InstrumentLookupUseCase:
    """Resolve an instrument using the first matching lookup key.

    Priority: id > isin > symbol (most-specific to least-specific).
    At least one key must be provided.
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        id: str | None = None,  # noqa: A002
        isin: str | None = None,
        symbol: str | None = None,
        extra_info: bool = False,
    ) -> InstrumentLookupResult:
        """Return the first instrument that matches the supplied key.

        When ``extra_info=True``, also fetches the linked ``Security`` row so
        that the caller can include enrichment fields (description, etc.).

        Raises ``InstrumentNotFoundError`` when no instrument is found.
        Raises ``ValueError`` when no lookup key is provided.
        """
        if not any([id, isin, symbol]):
            raise ValueError("At least one of id, isin, or symbol must be provided")

        instrument: Instrument | None = None

        if id:
            instrument = await self._uow.instruments_read.find_by_id(id)

        if instrument is None and isin:
            instrument = await self._uow.instruments_read.find_by_isin(isin)

        if instrument is None and symbol:
            instrument = await self._uow.instruments_read.find_by_symbol_icase(symbol)

        if instrument is None:
            raise InstrumentNotFoundError(f"Instrument not found: id={id!r} isin={isin!r} symbol={symbol!r}")

        security: Security | None = None
        if extra_info:
            security = await self._uow.securities_read.find_by_id(instrument.security_id)

        return InstrumentLookupResult(instrument=instrument, security=security)
