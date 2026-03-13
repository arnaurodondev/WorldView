"""Quotes API router with cache-aside pattern."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from market_data.api.dependencies import get_quote_cache, get_uow
from market_data.api.schemas.quotes import BatchQuoteRequest, BatchQuoteResponse, QuoteResponse
from market_data.application.ports.repositories import QuoteRepository
from market_data.application.ports.uow import UnitOfWork
from market_data.domain.entities import Quote
from market_data.infrastructure.cache.quote_cache import QuoteCache

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(tags=["quotes"])

_CACHE_TTL = 5  # seconds


def _to_quote_response(quote: Quote) -> QuoteResponse:
    return QuoteResponse(
        instrument_id=quote.instrument_id,
        bid=str(quote.bid),
        ask=str(quote.ask),
        last=str(quote.last),
        volume=quote.volume,
        timestamp=quote.timestamp,
        updated_at=quote.updated_at,
    )


async def _get_quote_cached(
    instrument_id: str,
    repo: QuoteRepository,
    cache: QuoteCache,
) -> QuoteResponse | None:
    """Cache-aside fetch: check cache first, fall back to DB."""
    cached = await cache.get(instrument_id)
    if cached is not None:
        return cached

    quote = await repo.find_by_instrument(instrument_id)
    if quote is None:
        return None

    response = _to_quote_response(quote)
    await cache.set(instrument_id, response, ttl=_CACHE_TTL)
    return response


# Literal-path routes BEFORE path-param routes
@router.get("/quotes/latest", response_model=BatchQuoteResponse)
async def get_quotes_latest(
    instrument_ids: Annotated[list[str], Query()] = ...,  # type: ignore[assignment]
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
    cache: Annotated[QuoteCache, Depends(get_quote_cache)] = ...,  # type: ignore[assignment]
) -> BatchQuoteResponse:
    """Return the latest quotes for a batch of instruments (via query params)."""
    repo = uow.quotes_read
    result: dict[str, QuoteResponse | None] = {}
    for iid in instrument_ids:
        result[iid] = await _get_quote_cached(iid, repo, cache)
    return BatchQuoteResponse(quotes=result)


@router.get("/quotes/{instrument_id}", response_model=QuoteResponse)
async def get_quote(
    instrument_id: str,
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
    cache: Annotated[QuoteCache, Depends(get_quote_cache)] = ...,  # type: ignore[assignment]
) -> QuoteResponse:
    """Return the latest quote for a single instrument (cache-aside)."""
    response = await _get_quote_cached(instrument_id, uow.quotes_read, cache)
    if response is None:
        raise HTTPException(status_code=404, detail=f"Quote not found for instrument: {instrument_id}")
    return response


@router.post("/quotes/batch", response_model=BatchQuoteResponse)
async def get_quotes_batch(
    body: BatchQuoteRequest,
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
    cache: Annotated[QuoteCache, Depends(get_quote_cache)] = ...,  # type: ignore[assignment]
) -> BatchQuoteResponse:
    """Return the latest quotes for a batch of instruments (via POST body)."""
    repo = uow.quotes_read
    result: dict[str, QuoteResponse | None] = {}
    for iid in body.instrument_ids:
        result[iid] = await _get_quote_cached(iid, repo, cache)
    return BatchQuoteResponse(quotes=result)
