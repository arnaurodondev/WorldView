"""Unit tests for Quotes API (MD-024)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import get_quote_cache, get_quote_uc
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


def _make_app(mock_quote_uc: MagicMock, mock_cache: AsyncMock) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(quotes_router.router, prefix="/api/v1")

    app.dependency_overrides[get_quote_uc] = lambda: mock_quote_uc
    app.dependency_overrides[get_quote_cache] = lambda: mock_cache

    return app, TestClient(app)


def _make_mocks(
    quote: Quote | None = None,
    cache_hit: bool = False,
) -> tuple[MagicMock, AsyncMock]:
    mock_uc = MagicMock()
    mock_uc.execute = AsyncMock(return_value=quote)

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

    return mock_uc, mock_cache


def test_get_quote_found_from_db() -> None:
    """GET /api/v1/quotes/{id} returns quote from DB on cache miss."""
    quote = _make_quote()
    mock_uc, mock_cache = _make_mocks(quote=quote, cache_hit=False)
    _, client = _make_app(mock_uc, mock_cache)

    resp = client.get("/api/v1/quotes/instr-001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["instrument_id"] == "instr-001"
    assert data["bid"] == "309.90"


def test_get_quote_found_from_cache() -> None:
    """GET /api/v1/quotes/{id} returns quote from cache on cache hit."""
    quote = _make_quote()
    mock_uc, mock_cache = _make_mocks(quote=quote, cache_hit=True)
    _, client = _make_app(mock_uc, mock_cache)

    resp = client.get("/api/v1/quotes/instr-001")
    assert resp.status_code == 200
    mock_uc.execute.assert_not_awaited()


def test_get_quote_not_found() -> None:
    """GET /api/v1/quotes/{id} returns 404 when no quote exists."""
    mock_uc, mock_cache = _make_mocks(quote=None)
    _, client = _make_app(mock_uc, mock_cache)

    resp = client.get("/api/v1/quotes/nonexistent")
    assert resp.status_code == 404


def test_batch_quotes_post() -> None:
    """POST /api/v1/quotes/batch returns quotes for all requested instruments."""
    iid_found = "01900000-0000-7000-8000-000000001001"
    iid_missing = "01900000-0000-7000-8000-000000001999"
    quote = _make_quote(iid_found)
    mock_uc, mock_cache = _make_mocks(quote=quote)
    mock_uc.execute = AsyncMock(side_effect=lambda iid: quote if iid == iid_found else None)
    _, client = _make_app(mock_uc, mock_cache)

    resp = client.post("/api/v1/quotes/batch", json={"instrument_ids": [iid_found, iid_missing]})
    assert resp.status_code == 200
    data = resp.json()["quotes"]
    assert iid_found in data
    assert iid_missing in data


def test_batch_quotes_post_rejects_non_uuid() -> None:
    """POST /api/v1/quotes/batch returns 422 for non-UUID instrument_ids."""
    mock_uc, mock_cache = _make_mocks(quote=None)
    _, client = _make_app(mock_uc, mock_cache)

    resp = client.post("/api/v1/quotes/batch", json={"instrument_ids": ["SPY"]})
    assert resp.status_code == 422


def test_batch_quotes_get_latest() -> None:
    """GET /api/v1/quotes/latest returns quotes for all query-param instruments."""
    quote = _make_quote("instr-001")
    mock_uc, mock_cache = _make_mocks(quote=quote)
    mock_uc.execute = AsyncMock(side_effect=lambda iid: quote if iid == "instr-001" else None)
    _, client = _make_app(mock_uc, mock_cache)

    resp = client.get("/api/v1/quotes/latest?instrument_ids=instr-001&instrument_ids=instr-002")
    assert resp.status_code == 200
    data = resp.json()["quotes"]
    assert "instr-001" in data


def test_get_quote_sets_cache_on_db_hit() -> None:
    """On DB hit, the quote is cached for future requests."""
    quote = _make_quote()
    mock_uc, mock_cache = _make_mocks(quote=quote, cache_hit=False)
    _, client = _make_app(mock_uc, mock_cache)

    client.get("/api/v1/quotes/instr-001")
    mock_cache.set.assert_awaited_once()


def test_get_quote_response_null_fields() -> None:
    """GET /api/v1/quotes/{id} returns null for bid/ask/last/volume when entity fields are None (D-004)."""
    null_quote = Quote(
        instrument_id="instr-001",
        bid=None,
        ask=None,
        last=None,
        volume=None,
        timestamp=datetime(2024, 3, 15, 14, 30, tzinfo=UTC),
        updated_at=datetime(2024, 3, 15, 14, 30, tzinfo=UTC),
    )
    mock_uc, mock_cache = _make_mocks(quote=null_quote, cache_hit=False)
    _, client = _make_app(mock_uc, mock_cache)

    resp = client.get("/api/v1/quotes/instr-001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["bid"] is None
    assert data["ask"] is None
    assert data["last"] is None
    assert data["volume"] is None


def test_get_quote_cache_key_format() -> None:
    """QuoteCache uses the versioned key format quote:v1:{instrument_id}."""
    from market_data.infrastructure.cache.quote_cache import QuoteCache

    cache = QuoteCache.__new__(QuoteCache)
    cache._client = None  # type: ignore[assignment]
    assert cache._key("instr-001") == "quote:v1:instr-001"
