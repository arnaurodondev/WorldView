"""Instruments API router."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from market_data.api.dependencies import (
    get_lookup_instrument_uc,
    get_on_demand_profile_uc,
    get_search_instruments_uc,
    require_internal_jwt,
)
from market_data.api.schemas.instruments import (
    InstrumentFlagsResponse,
    InstrumentListResponse,
    InstrumentLookupDetailResponse,
    InstrumentLookupResponse,
    InstrumentResponse,
    OnDemandProfileResponse,
)
from market_data.application.use_cases.lookup_instrument import InstrumentLookupUseCase
from market_data.application.use_cases.on_demand_profile import OnDemandProfileUseCase
from market_data.application.use_cases.query_instruments import SearchInstrumentsUseCase
from market_data.domain.entities import Instrument
from market_data.domain.errors import EodhRateLimitError, InstrumentNotFoundError

router = APIRouter(tags=["instruments"])


def _to_response(instrument: Instrument) -> InstrumentResponse:
    return InstrumentResponse(
        id=instrument.id,
        security_id=instrument.security_id,
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        is_active=instrument.is_active,
        flags=InstrumentFlagsResponse(
            has_ohlcv=instrument.flags.has_ohlcv,
            has_quotes=instrument.flags.has_quotes,
            has_fundamentals=instrument.flags.has_fundamentals,
        ),
        created_at=instrument.created_at,
    )


# IMPORTANT: /lookup and /on-demand-profile MUST be defined BEFORE any
# path-param route (e.g., /{instrument_id}) to prevent FastAPI from matching
# the literal string "lookup" as a UUID path parameter.


@router.get(
    "/instruments/lookup",
    response_model=InstrumentLookupDetailResponse | InstrumentLookupResponse,
)
async def lookup_instrument(
    symbol: Annotated[
        str | None,
        Query(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-]+$"),
    ] = None,
    isin: Annotated[
        str | None,
        Query(min_length=12, max_length=12, pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$"),
    ] = None,
    id: Annotated[UUID | None, Query()] = None,  # noqa: A002
    extra_info: bool = Query(False),
    uc: Annotated[InstrumentLookupUseCase, Depends(get_lookup_instrument_uc)] = ...,  # type: ignore[assignment]
) -> InstrumentLookupDetailResponse | InstrumentLookupResponse:
    """Unified instrument lookup by id, isin, or symbol.

    At least one parameter is required. Priority: id > isin > symbol.
    Set ``extra_info=true`` to include enrichment fields (name, sector,
    industry, country, currency_code, description).
    """
    try:
        result = await uc.execute(
            id=str(id) if id else None,
            isin=isin,
            symbol=symbol,
            extra_info=extra_info,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="At least one of id, isin, or symbol is required") from exc
    except InstrumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Instrument not found") from exc

    inst = result.instrument
    if extra_info:
        sec = result.security
        return InstrumentLookupDetailResponse(
            id=inst.id,
            symbol=inst.symbol,
            exchange=inst.exchange,
            is_active=inst.is_active,
            name=inst.name,
            isin=inst.isin or (sec.isin if sec else None),
            sector=inst.sector or (sec.sector if sec else None),
            industry=inst.industry or (sec.industry if sec else None),
            country=inst.country or (sec.country if sec else None),
            currency_code=inst.currency_code or (sec.currency if sec else None),
            description=sec.description if sec else None,
        )

    return InstrumentLookupResponse(
        id=inst.id,
        symbol=inst.symbol,
        exchange=inst.exchange,
        is_active=inst.is_active,
    )


@router.get("/instruments/on-demand-profile", response_model=OnDemandProfileResponse)
async def on_demand_profile(
    # F-S03: route-level SSRF pattern guards.  Belt-and-suspenders alongside
    # the use-case validation: FastAPI rejects malformed input with 422 before
    # the use case ever sees it, but the use case still validates as a defence
    # in depth (e.g. when the use case is called from another worker, not HTTP).
    ticker: Annotated[
        str | None,
        Query(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-]+$"),
    ] = None,
    isin: Annotated[
        str | None,
        Query(min_length=12, max_length=12, pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$"),
    ] = None,
    _: Annotated[None, Depends(require_internal_jwt)] = None,
    uc: Annotated[OnDemandProfileUseCase, Depends(get_on_demand_profile_uc)] = ...,  # type: ignore[assignment]
) -> OnDemandProfileResponse:
    """Fetch (and persist) a structured enrichment profile for an instrument.

    DB-first: returns cached data when ``securities.description`` is already
    populated.  Falls back to EODHD and persists the result.
    Requires ``X-Internal-JWT`` — internal endpoint, not exposed to clients.
    """
    try:
        data = await uc.execute(ticker=ticker, isin=isin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InstrumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Instrument not found") from exc
    except EodhRateLimitError as exc:
        raise HTTPException(status_code=429, detail="EODHD rate limit exceeded -- retry later") from exc

    return OnDemandProfileResponse(
        instrument_id=data.instrument_id,
        security_id=data.security_id,
        ticker=data.ticker,
        exchange=data.exchange,
        isin=data.isin,
        currency_code=data.currency_code,
        description=data.description,
        sector=data.sector,
        industry=data.industry,
        country=data.country,
        source=data.source,
    )


@router.get("/instruments/symbol/{symbol}", response_model=InstrumentLookupResponse)
async def get_instrument_by_symbol(
    symbol: str,
    exchange: Annotated[str | None, Query(description="Optional exchange filter")] = None,
    uc: Annotated[InstrumentLookupUseCase, Depends(get_lookup_instrument_uc)] = ...,  # type: ignore[assignment]
) -> InstrumentLookupResponse:
    """Lookup an instrument by symbol (case-insensitive), with optional ``exchange`` filter.

    The underlying use case resolves by symbol; when ``exchange`` is supplied we
    validate the resolved instrument matches and 404 otherwise (the symbol may
    exist on a different exchange).
    """
    try:
        result = await uc.execute(symbol=symbol)
    except InstrumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Instrument not found") from exc

    inst = result.instrument
    if exchange is not None and inst.exchange.upper() != exchange.upper():
        raise HTTPException(status_code=404, detail="Instrument not found for symbol+exchange")
    return InstrumentLookupResponse(
        id=inst.id,
        symbol=inst.symbol,
        exchange=inst.exchange,
        is_active=inst.is_active,
    )


@router.get("/instruments", response_model=InstrumentListResponse)
async def list_instruments(
    query: Annotated[str, Query(description="Symbol/exchange substring search")] = "",
    has_ohlcv: Annotated[bool | None, Query(description="Filter by OHLCV data availability")] = None,
    has_quotes: Annotated[bool | None, Query(description="Filter by quote data availability")] = None,
    has_fundamentals: Annotated[bool | None, Query(description="Filter by fundamentals data availability")] = None,
    exchange: Annotated[str | None, Query(description="Filter by exchange code")] = None,
    limit: Annotated[int, Query(ge=1, le=1000, description="Page size")] = 100,
    offset: Annotated[int, Query(ge=0, description="Page offset")] = 0,
    uc: Annotated[SearchInstrumentsUseCase, Depends(get_search_instruments_uc)] = ...,  # type: ignore[assignment]
) -> InstrumentListResponse:
    """List instruments with optional DB-side filters and pagination."""
    total, items = await uc.execute(
        query,
        has_ohlcv=has_ohlcv,
        has_quotes=has_quotes,
        has_fundamentals=has_fundamentals,
        exchange=exchange,
        limit=limit,
        offset=offset,
    )
    return InstrumentListResponse(
        items=[_to_response(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


# IMPORTANT: this path-param route MUST be declared LAST so it does not shadow
# the literal-string routes above (``/instruments/lookup``,
# ``/instruments/on-demand-profile``, ``/instruments/symbol/{symbol}``,
# ``/instruments``). FastAPI matches in declaration order.
@router.get("/instruments/{instrument_id}", response_model=InstrumentResponse)
async def get_instrument_by_id(
    instrument_id: UUID,
    uc: Annotated[InstrumentLookupUseCase, Depends(get_lookup_instrument_uc)] = ...,  # type: ignore[assignment]
) -> InstrumentResponse:
    """Lookup an instrument by UUID. Returns 404 when unknown."""
    try:
        result = await uc.execute(id=str(instrument_id))
    except InstrumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Instrument not found") from exc
    return _to_response(result.instrument)
