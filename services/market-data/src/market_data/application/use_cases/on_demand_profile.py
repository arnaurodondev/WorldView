"""OnDemandProfileUseCase — DB-first enrichment with EODHD fallback and persistence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from market_data.domain.errors import EodhRateLimitError, InstrumentNotFoundError  # noqa: F401

if TYPE_CHECKING:
    from market_data.application.ports.uow import UnitOfWork
    from market_data.infrastructure.eodhd.client import EodhHdClient

# SSRF validation patterns — only allow safe ticker/ISIN formats before
# constructing any EODHD URL (guards against path traversal via ticker param).
TICKER_PATTERN = re.compile(r"^[A-Z0-9.\-]{1,20}$")
ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


@dataclass(frozen=True, slots=True)
class OnDemandProfileData:
    """Result of an on-demand enrichment fetch."""

    instrument_id: str
    security_id: str
    ticker: str
    exchange: str
    isin: str | None
    currency_code: str | None
    description: str | None
    sector: str | None
    industry: str | None
    country: str | None
    source: Literal["db", "eodhd_persisted"]


def _validate_ticker(ticker: str) -> None:
    if not TICKER_PATTERN.match(ticker):
        raise ValueError(f"Invalid ticker format: {ticker!r}")


def _validate_isin(isin: str) -> None:
    if not ISIN_PATTERN.match(isin):
        raise ValueError(f"Invalid ISIN format: {isin!r}")


class OnDemandProfileUseCase:
    """Enrich a canonical entity profile via DB-first -> EODHD fallback.

    Steps:
    1. Resolve instrument from DB using ticker or ISIN.
    2. Fetch linked security; if ``description`` is already populated -> return
       with ``source="db"`` (no EODHD credit consumed).
    3. Otherwise call EODHD, persist enrichment fields to ``securities``, and
       return with ``source="eodhd_persisted"``.
    """

    def __init__(self, uow: UnitOfWork, eodhd_client: EodhHdClient) -> None:
        self._uow = uow
        self._eodhd = eodhd_client

    async def execute(
        self,
        *,
        ticker: str | None = None,
        isin: str | None = None,
    ) -> OnDemandProfileData:
        """Resolve and enrich the instrument profile.

        SSRF validation is applied before any EODHD URL construction.
        Raises ``ValueError`` on invalid ticker/ISIN format.
        Raises ``InstrumentNotFoundError`` when the instrument does not exist.
        Raises ``EodhRateLimitError`` when EODHD returns 429.
        """
        if not any([ticker, isin]):
            raise ValueError("At least one of ticker or isin must be provided")

        # SSRF validation before any external call
        upper_ticker = ticker.upper() if ticker else None
        upper_isin = isin.upper() if isin else None

        if upper_ticker:
            _validate_ticker(upper_ticker)
        if upper_isin:
            _validate_isin(upper_isin)

        # --- Phase 1: DB lookup ---
        inst = None
        if upper_ticker:
            inst = await self._uow.instruments_read.find_by_symbol_icase(upper_ticker)
        if inst is None and upper_isin:
            inst = await self._uow.instruments_read.find_by_isin(upper_isin)
        if inst is None:
            raise InstrumentNotFoundError(f"Instrument not found: ticker={ticker!r} isin={isin!r}")

        sec = await self._uow.securities_read.find_by_id(inst.security_id)

        # --- Phase 2: return from DB if description already populated ---
        if sec is not None and sec.description:
            return OnDemandProfileData(
                instrument_id=inst.id,
                security_id=inst.security_id,
                ticker=inst.symbol,
                exchange=inst.exchange,
                isin=inst.isin or sec.isin,
                currency_code=inst.currency_code or sec.currency,
                description=sec.description,
                sector=inst.sector or sec.sector,
                industry=inst.industry or sec.industry,
                country=inst.country or sec.country,
                source="db",
            )

        # --- Phase 3: EODHD on-demand fetch ---
        eodhd_data = await self._eodhd.get_fundamentals(inst.symbol, inst.exchange)

        if eodhd_data is None:
            raise InstrumentNotFoundError(f"EODHD returned 404 for {inst.symbol}.{inst.exchange}")

        general = eodhd_data.get("General", {})
        description = general.get("Description") or None
        eodhd_sector = general.get("Sector") or None
        eodhd_industry = general.get("Industry") or None
        eodhd_country = general.get("CountryISO") or None
        eodhd_isin = general.get("ISIN") or None
        eodhd_currency = general.get("CurrencyCode") or None

        # --- Phase 4: Persist enrichment results to DB ---
        security_fields: dict[str, str | None] = {
            k: v
            for k, v in {
                "description": description,
                "sector": eodhd_sector,
                "industry": eodhd_industry,
                "country": eodhd_country,
                "currency": eodhd_currency,
            }.items()
            if v is not None
        }
        if security_fields:
            await self._uow.securities.update_from_enrichment(inst.security_id, security_fields)

        instrument_metadata: dict[str, str | None] = {
            k: v
            for k, v in {
                "isin": eodhd_isin,
                "sector": eodhd_sector,
                "industry": eodhd_industry,
                "country": eodhd_country,
                "currency_code": eodhd_currency,
            }.items()
            if v is not None
        }
        if instrument_metadata:
            await self._uow.instruments.update_metadata(inst.id, instrument_metadata)

        await self._uow.commit()

        return OnDemandProfileData(
            instrument_id=inst.id,
            security_id=inst.security_id,
            ticker=inst.symbol,
            exchange=inst.exchange,
            isin=eodhd_isin or inst.isin or (sec.isin if sec else None),
            currency_code=eodhd_currency or inst.currency_code or (sec.currency if sec else None),
            description=description,
            sector=eodhd_sector or inst.sector or (sec.sector if sec else None),
            industry=eodhd_industry or inst.industry or (sec.industry if sec else None),
            country=eodhd_country or inst.country or (sec.country if sec else None),
            source="eodhd_persisted",
        )
