"""Unit tests for Quotes API (MD-024)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import get_quote_cache, get_uow
from market_data.api.routers import quotes as quotes_router
from market_data.api.schemas.quotes import QuoteResponse
from market_data.domain.entities import Quote
from market_data.infrastructure.cache.quote_cache import QuoteCache

pytestmark = pytest.mark.unit


def _make_quote(instrument_id: str = "instr-001") -> Quote:
    return Quote(
        instrument_id=instrument_id,
        bid=Decimal("309.90"),
        ask=Decimal("310.10"),
        last=Decimal("310.00"),
        volume=2_000_000,
        timestamp=datetime(2024, 3, 15, 14, 30, tzinfo=UTC),
        updated_at=datetime(2024, 3, 15, 14, 30, tzinfo=UTC),
    )


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[misc]
    yield


def _make_app(mock_uow: AsyncMock, mock_cache: AsyncMock) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(quotes_router.router, prefix="/api/v1")

    async def override_get_uow():  # type: ignore[misc]
        yield mock_uow

    async def override_get_cache() -> AsyncMock:
        return mock_cache

    app.dependency_overrides[get_uow] = override_get_uow
    app.dependency_overrides[get_quote_cache] = override_get_cache
    return app, TestClient(app)


def _make_mocks(
    quote: Quote | None = None,
    cache_hit: bool = False,
) -> tuple[AsyncMock, AsyncMock]:
    mock_uow = AsyncMock()
    quotes_repo = MagicMock()
    quotes_repo.find_by_instrument = AsyncMock(return_value=quote)
    quotes_repo.find_by_instruments = AsyncMock(return_value=[quote] if quote else [])
    mock_uow.quotes_read = quotes_repo
    # Keep write-side alias for assertion compatibility
    mock_uow.quotes = quotes_repo

    mock_cache = AsyncMock(spec=QuoteCache)
    if cache_hit and quote:
        q_resp = QuoteResponse(
            instrument_id=quote.instrument_id,
            bid=str(quote.bid),
            ask=str(quote.ask),
            last=str(quote.last),
            volume=quote.volume,
            timestamp=quote.timestamp,
            updated_at=quote.updated_at,
        )
        mock_cache.get = AsyncMock(return_value=q_resp)
    else:
        mock_cache.get = AsyncMock(return_value=None)
    mock_cache.set = AsyncMock()

    return mock_uow, mock_cache


def test_get_quote_found_from_db() -> None:
    """GET /api/v1/quotes/{id} returns quote from DB on cache miss."""
    quote = _make_quote()
    mock_uow, mock_cache = _make_mocks(quote=quote, cache_hit=False)
    _, client = _make_app(mock_uow, mock_cache)

    resp = client.get("/api/v1/quotes/instr-001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["instrument_id"] == "instr-001"
    assert data["bid"] == "309.90"


def test_get_quote_found_from_cache() -> None:
    """GET /api/v1/quotes/{id} returns quote from cache on cache hit."""
    quote = _make_quote()
    mock_uow, mock_cache = _make_mocks(quote=quote, cache_hit=True)
    _, client = _make_app(mock_uow, mock_cache)

    resp = client.get("/api/v1/quotes/instr-001")
    assert resp.status_code == 200
    mock_uow.quotes.find_by_instrument.assert_not_awaited()


def test_get_quote_not_found() -> None:
    """GET /api/v1/quotes/{id} returns 404 when no quote exists."""
    mock_uow, mock_cache = _make_mocks(quote=None)
    _, client = _make_app(mock_uow, mock_cache)

    resp = client.get("/api/v1/quotes/nonexistent")
    assert resp.status_code == 404


def test_batch_quotes_post() -> None:
    """POST /api/v1/quotes/batch returns quotes for all requested instruments."""
    quote = _make_quote("instr-001")
    mock_uow, mock_cache = _make_mocks(quote=quote)
    _, client = _make_app(mock_uow, mock_cache)

    resp = client.post("/api/v1/quotes/batch", json={"instrument_ids": ["instr-001", "instr-missing"]})
    assert resp.status_code == 200
    data = resp.json()["quotes"]
    assert "instr-001" in data
    assert "instr-missing" in data


def test_batch_quotes_get_latest() -> None:
    """GET /api/v1/quotes/latest returns quotes for all query-param instruments."""
    quote = _make_quote("instr-001")
    mock_uow, mock_cache = _make_mocks(quote=quote)
    _, client = _make_app(mock_uow, mock_cache)

    resp = client.get("/api/v1/quotes/latest?instrument_ids=instr-001&instrument_ids=instr-002")
    assert resp.status_code == 200
    data = resp.json()["quotes"]
    assert "instr-001" in data


def test_get_quote_sets_cache_on_db_hit() -> None:
    """On DB hit, the quote is cached for future requests."""
    quote = _make_quote()
    mock_uow, mock_cache = _make_mocks(quote=quote, cache_hit=False)
    _, client = _make_app(mock_uow, mock_cache)

    client.get("/api/v1/quotes/instr-001")
    mock_cache.set.assert_awaited_once()


def test_get_quote_cache_key_format() -> None:
    """QuoteCache uses the versioned key format quote:v1:{instrument_id}."""
    from market_data.infrastructure.cache.quote_cache import QuoteCache

    cache = QuoteCache.__new__(QuoteCache)
    cache._client = None  # type: ignore[assignment]
    assert cache._key("instr-001") == "quote:v1:instr-001"
