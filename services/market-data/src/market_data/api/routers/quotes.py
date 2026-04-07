"""Quotes API router with cache-aside pattern.

Cache-aside orchestration (check cache → DB miss → populate cache) lives here
in the router because the cache stores serialised ``QuoteResponse`` API objects,
making it an API-layer concern.  Use cases return raw domain ``Quote`` entities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from market_data.api.dependencies import get_quote_cache, get_quote_uc
from market_data.api.schemas.quotes import BatchQuoteRequest, BatchQuoteResponse, QuoteResponse
from market_data.application.use_cases.query_quotes import GetQuoteUseCase
from market_data.domain.entities import Quote
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_data.infrastructure.cache.quote_cache import QuoteCache
else:
    from market_data.infrastructure.cache.quote_cache import QuoteCache

logger = get_logger(__name__)

router = APIRouter(tags=["quotes"])

_CACHE_TTL = 5  # seconds


def _to_quote_response(quote: Quote) -> QuoteResponse:
    return QuoteResponse(
        instrument_id=quote.instrument_id,
        bid=str(quote.bid) if quote.bid is not None else None,
        ask=str(quote.ask) if quote.ask is not None else None,
        last=str(quote.last) if quote.last is not None else None,
        volume=quote.volume,
        timestamp=quote.timestamp,
        updated_at=quote.updated_at,
    )


async def _get_quote_cached(
    instrument_id: str,
    uc: GetQuoteUseCase,
    cache: QuoteCache,
) -> QuoteResponse | None:
    """Cache-aside fetch: check cache first, fall back to DB via use case."""
    cached = await cache.get(instrument_id)
    if cached is not None:
        return cached

    quote = await uc.execute(instrument_id)
    if quote is None:
        return None

    response = _to_quote_response(quote)
    await cache.set(instrument_id, response, ttl=_CACHE_TTL)
    return response


# Literal-path routes BEFORE path-param routes
@router.get("/quotes/latest", response_model=BatchQuoteResponse)
async def get_quotes_latest(
    instrument_ids: Annotated[list[str], Query(max_length=200)] = ...,  # type: ignore[assignment]  # F-SEC-006
    uc: Annotated[GetQuoteUseCase, Depends(get_quote_uc)] = ...,  # type: ignore[assignment]
    cache: Annotated[QuoteCache, Depends(get_quote_cache)] = ...,  # type: ignore[assignment]
) -> BatchQuoteResponse:
    """Return the latest quotes for a batch of instruments (via query params)."""
    result: dict[str, QuoteResponse | None] = {}
    for iid in instrument_ids:
        result[iid] = await _get_quote_cached(iid, uc, cache)
    return BatchQuoteResponse(quotes=result)


@router.get("/quotes/{instrument_id}", response_model=QuoteResponse)
async def get_quote(
    instrument_id: str,
    uc: Annotated[GetQuoteUseCase, Depends(get_quote_uc)] = ...,  # type: ignore[assignment]
    cache: Annotated[QuoteCache, Depends(get_quote_cache)] = ...,  # type: ignore[assignment]
) -> QuoteResponse:
    """Return the latest quote for a single instrument (cache-aside)."""
    response = await _get_quote_cached(instrument_id, uc, cache)
    if response is None:
        raise HTTPException(status_code=404, detail=f"Quote not found for instrument: {instrument_id}")
    return response


@router.post("/quotes/batch", response_model=BatchQuoteResponse)
async def get_quotes_batch(
    body: BatchQuoteRequest,
    uc: Annotated[GetQuoteUseCase, Depends(get_quote_uc)] = ...,  # type: ignore[assignment]
    cache: Annotated[QuoteCache, Depends(get_quote_cache)] = ...,  # type: ignore[assignment]
) -> BatchQuoteResponse:
    """Return the latest quotes for a batch of instruments (via POST body)."""
    result: dict[str, QuoteResponse | None] = {}
    for iid in body.instrument_ids:
        result[iid] = await _get_quote_cached(iid, uc, cache)
    return BatchQuoteResponse(quotes=result)
