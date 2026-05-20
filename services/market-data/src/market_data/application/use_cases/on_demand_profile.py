"""OnDemandProfileUseCase — DB-first enrichment with EODHD fallback and persistence.

R25 3-phase pattern (F-D02 fix):
  Phase 1 (DB read): open a UoW, resolve instrument + security, snapshot the
                     fields we need into a plain dataclass, then close the UoW
                     so the DB session does NOT span the EODHD HTTP call.
  Phase 2 (HTTP):    NO DB session held while we call EODHD (10 s timeout).
  Phase 3 (DB write): open a fresh UoW, apply the COALESCE update + commit,
                     then close.

The use case is constructed with a UoW *factory* (a zero-arg callable that
returns an unentered UoW) rather than a single open UoW.  This is the only
way to safely separate read and write phases when the existing UoW context
manager is single-use (sessions are bound at ``__aenter__`` and closed at
``__aexit__``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import structlog

from market_data.domain._ticker_normalize import _normalize_ticker
from market_data.domain.errors import EodhRateLimitError, InstrumentNotFoundError  # noqa: F401

if TYPE_CHECKING:
    from collections.abc import Callable

    from market_data.application.ports.uow import UnitOfWork
    from market_data.infrastructure.eodhd.client import EodhHdClient

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

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


@dataclass(frozen=True, slots=True)
class _InstrumentSnapshot:
    """Plain-data snapshot of instrument + security fields after Phase 1.

    Holds only the values we need across the EODHD HTTP boundary so that no
    SQLAlchemy-bound objects (Instrument / Security entities) outlive the
    Phase-1 session.  This makes the R25 boundary explicit and avoids any
    accidental lazy-load attempts after the session is closed.
    """

    instrument_id: str
    security_id: str
    symbol: str
    exchange: str
    isin: str | None
    sector: str | None
    industry: str | None
    country: str | None
    currency_code: str | None
    sec_isin: str | None
    sec_currency: str | None
    sec_sector: str | None
    sec_industry: str | None
    sec_country: str | None
    sec_description: str | None


def _validate_ticker(ticker: str) -> None:
    """Validate ticker shape (SSRF guard).

    F-S10: error message is intentionally static (no echo of user input)
    to prevent reflected-XSS-style content in error responses.  The rejected
    value is logged separately via structlog so internal observability is
    preserved.
    """
    if not TICKER_PATTERN.match(ticker):
        logger.warning("on_demand_invalid_ticker", rejected=ticker)
        raise ValueError("Invalid ticker format")


def _validate_isin(isin: str) -> None:
    """Validate ISIN shape (SSRF guard) — see ``_validate_ticker`` for rationale."""
    if not ISIN_PATTERN.match(isin):
        logger.warning("on_demand_invalid_isin", rejected=isin)
        raise ValueError("Invalid ISIN format")


class OnDemandProfileUseCase:
    """Enrich a canonical entity profile via DB-first -> EODHD fallback.

    Steps:
    1. Resolve instrument from DB using ticker or ISIN.
    2. Fetch linked security; if ``description`` is already populated -> return
       with ``source="db"`` (no EODHD credit consumed).
    3. Otherwise call EODHD, persist enrichment fields to ``securities``, and
       return with ``source="eodhd_persisted"``.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        eodhd_client: EodhHdClient,
    ) -> None:
        self._uow_factory = uow_factory
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

        # SSRF validation before any external call.
        # Order matters:
        #   1. Validate the RAW (uppercased) input against TICKER_PATTERN.  We
        #      must do this BEFORE normalization because `_normalize_ticker`
        #      collapses `/` and `-` to `.`, which would let a path-traversal
        #      payload like `../../etc/passwd` survive validation (it becomes
        #      `......ETC.PASSWD`, all chars in the regex's allowed set).
        #   2. PLAN-0089 F2 step 7: only after the input is known-safe do we
        #      normalize to the canonical dot-form (BRK-B / brk.b / BRK/B →
        #      BRK.B) so the DB lookup hits the row that the Kafka consumers
        #      wrote under the canonical form.
        raw_upper_ticker = ticker.upper() if ticker else None
        upper_isin = isin.upper() if isin else None

        if raw_upper_ticker:
            _validate_ticker(raw_upper_ticker)
        if upper_isin:
            _validate_isin(upper_isin)

        # Normalize AFTER validation succeeded.
        upper_ticker = _normalize_ticker(raw_upper_ticker) if raw_upper_ticker else None

        # ── Phase 1: DB lookup (open + close session) ────────────────────────
        snapshot = await self._phase1_lookup(upper_ticker, upper_isin)

        # Short-circuit: DB already has the description, no EODHD needed.
        if snapshot.sec_description:
            return OnDemandProfileData(
                instrument_id=snapshot.instrument_id,
                security_id=snapshot.security_id,
                ticker=snapshot.symbol,
                exchange=snapshot.exchange,
                isin=snapshot.isin or snapshot.sec_isin,
                currency_code=snapshot.currency_code or snapshot.sec_currency,
                description=snapshot.sec_description,
                sector=snapshot.sector or snapshot.sec_sector,
                industry=snapshot.industry or snapshot.sec_industry,
                country=snapshot.country or snapshot.sec_country,
                source="db",
            )

        # ── Phase 2: EODHD HTTP call (NO DB session held) ────────────────────
        eodhd_data = await self._eodhd.get_fundamentals(snapshot.symbol, snapshot.exchange)

        if eodhd_data is None:
            raise InstrumentNotFoundError(f"EODHD returned 404 for {snapshot.symbol}.{snapshot.exchange}")

        general = eodhd_data.get("General", {})
        description = general.get("Description") or None
        eodhd_sector = general.get("Sector") or None
        eodhd_industry = general.get("Industry") or None
        eodhd_country = general.get("CountryISO") or None
        eodhd_isin = general.get("ISIN") or None
        eodhd_currency = general.get("CurrencyCode") or None

        # ── Phase 3: Persist enrichment (open fresh session, commit, close) ──
        await self._phase3_persist(
            security_id=snapshot.security_id,
            instrument_id=snapshot.instrument_id,
            description=description,
            sector=eodhd_sector,
            industry=eodhd_industry,
            country=eodhd_country,
            isin=eodhd_isin,
            currency=eodhd_currency,
        )

        return OnDemandProfileData(
            instrument_id=snapshot.instrument_id,
            security_id=snapshot.security_id,
            ticker=snapshot.symbol,
            exchange=snapshot.exchange,
            isin=eodhd_isin or snapshot.isin or snapshot.sec_isin,
            currency_code=eodhd_currency or snapshot.currency_code or snapshot.sec_currency,
            description=description,
            sector=eodhd_sector or snapshot.sector or snapshot.sec_sector,
            industry=eodhd_industry or snapshot.industry or snapshot.sec_industry,
            country=eodhd_country or snapshot.country or snapshot.sec_country,
            source="eodhd_persisted",
        )

    # ── private phase helpers ────────────────────────────────────────────────

    async def _phase1_lookup(
        self,
        upper_ticker: str | None,
        upper_isin: str | None,
    ) -> _InstrumentSnapshot:
        """Phase 1 — open a UoW, resolve instrument + security, return a snapshot.

        The UoW is closed before this returns so the session does NOT span
        the EODHD HTTP call (R25, F-D02).
        """
        async with self._uow_factory() as uow:
            inst = None
            if upper_ticker:
                inst = await uow.instruments_read.find_by_symbol_icase(upper_ticker)
            if inst is None and upper_isin:
                inst = await uow.instruments_read.find_by_isin(upper_isin)
            if inst is None:
                raise InstrumentNotFoundError(f"Instrument not found: ticker={upper_ticker!r} isin={upper_isin!r}")

            sec = await uow.securities_read.find_by_id(inst.security_id)

            return _InstrumentSnapshot(
                instrument_id=inst.id,
                security_id=inst.security_id,
                symbol=inst.symbol,
                exchange=inst.exchange,
                isin=inst.isin,
                sector=inst.sector,
                industry=inst.industry,
                country=inst.country,
                currency_code=inst.currency_code,
                sec_isin=sec.isin if sec else None,
                sec_currency=sec.currency if sec else None,
                sec_sector=sec.sector if sec else None,
                sec_industry=sec.industry if sec else None,
                sec_country=sec.country if sec else None,
                sec_description=sec.description if sec else None,
            )

    async def _phase3_persist(
        self,
        *,
        security_id: str,
        instrument_id: str,
        description: str | None,
        sector: str | None,
        industry: str | None,
        country: str | None,
        isin: str | None,
        currency: str | None,
    ) -> None:
        """Phase 3 — open a fresh UoW, COALESCE-update, commit, close."""
        security_fields: dict[str, str | None] = {
            k: v
            for k, v in {
                "description": description,
                "sector": sector,
                "industry": industry,
                "country": country,
                "currency": currency,
            }.items()
            if v is not None
        }
        instrument_metadata: dict[str, str | None] = {
            k: v
            for k, v in {
                "isin": isin,
                "sector": sector,
                "industry": industry,
                "country": country,
                "currency_code": currency,
            }.items()
            if v is not None
        }

        if not security_fields and not instrument_metadata:
            return

        async with self._uow_factory() as uow:
            if security_fields:
                await uow.securities.update_from_enrichment(security_id, security_fields)
            if instrument_metadata:
                await uow.instruments.update_metadata(instrument_id, instrument_metadata)
            await uow.commit()
