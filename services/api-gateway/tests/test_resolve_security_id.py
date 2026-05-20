"""Tests for ``resolve_security_id`` (PRD-0089 F2 step 3).

Covers the four documented resolution paths:

  1. UUID input → returns same UUID, no S2 call.
  2. Ticker input → looks up via S3 market-data, returns instrument_id.
  3. Ticker alias → returns canonical instrument_id + 301 redirect signal.
  4. Unknown ticker → raises InstrumentNotFoundError.

All S2 / S7 calls are mocked at the httpx.AsyncClient level via
``unittest.mock.AsyncMock`` — no live network, no DB.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
from api_gateway.clients import ServiceClients
from api_gateway.resolution import (
    InstrumentNotFoundError,
    ResolvedSecurity,
    resolve_security_id,
)

pytestmark = pytest.mark.unit


# Canonical UUIDs used by the dev seed (matches scripts/seed-dev-data.sql).
_AAPL_UUID = "01900000-0000-7000-8000-000000001001"
_META_UUID = "01900000-0000-7000-8000-000000001005"


@pytest.fixture(autouse=True)
def _flush_cache() -> None:
    """Clear the module-level TTLCache before each test.

    The cache is process-global so tests would leak state across each
    other without this fixture (a "ticker lookup" test could be served
    from a previous "uuid input" test's cache entry).
    """
    resolve_security_id.cache.clear()  # type: ignore[attr-defined]


def _mock_response(status_code: int, json_body: dict[str, Any] | None = None) -> MagicMock:
    """Build a mock httpx.Response with .status_code and .json()."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_body or {})
    return resp


def _make_clients(
    market_data: MagicMock | None = None,
    knowledge_graph: MagicMock | None = None,
) -> ServiceClients:
    """Build a ServiceClients dataclass with two mocked clients.

    The other 7 fields are MagicMocks too — they're never touched by
    the resolver but the dataclass requires all positional args.
    """

    # # WHY MagicMock with spec=httpx.AsyncClient: lets the resolver
    # # call .get() with no warnings while still letting us assert call
    # # counts. AsyncMock for the .get attribute so awaiting works.
    def _stub() -> MagicMock:
        c = MagicMock(spec=httpx.AsyncClient)
        c.get = AsyncMock()
        return c

    return ServiceClients(
        portfolio=_stub(),
        market_data=market_data or _stub(),
        market_ingestion=_stub(),
        content_ingestion=_stub(),
        content_store=_stub(),
        nlp_pipeline=_stub(),
        knowledge_graph=knowledge_graph or _stub(),
        rag_chat=_stub(),
        alert=_stub(),
    )


# ── Case 1: UUID input ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_uuid_input_returns_same_uuid_no_s2_call() -> None:
    """When the identifier is already a UUID, the resolver must short-
    circuit — no S3 lookup, no KG lookup. Both calls must remain at 0.
    """
    market_data = MagicMock(spec=httpx.AsyncClient)
    market_data.get = AsyncMock()
    kg = MagicMock(spec=httpx.AsyncClient)
    kg.get = AsyncMock()
    clients = _make_clients(market_data=market_data, knowledge_graph=kg)

    resolved = await resolve_security_id(_AAPL_UUID, clients=clients)

    assert isinstance(resolved, ResolvedSecurity)
    assert resolved.instrument_id == UUID(_AAPL_UUID)
    assert resolved.redirect_to_ticker is None
    # Zero network calls — the short-circuit is the whole point.
    market_data.get.assert_not_awaited()
    kg.get.assert_not_awaited()


# ── Case 2: ticker input → S2 lookup ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_ticker_input_resolves_via_s2() -> None:
    """A bare ticker like "AAPL" must trigger a single S3 lookup with
    upper-cased symbol; the returned UUID is what the resolver returns.
    """
    market_data = MagicMock(spec=httpx.AsyncClient)
    market_data.get = AsyncMock(
        return_value=_mock_response(200, {"id": _AAPL_UUID, "symbol": "AAPL"}),
    )
    clients = _make_clients(market_data=market_data)

    resolved = await resolve_security_id("AAPL", clients=clients)

    assert resolved.instrument_id == UUID(_AAPL_UUID)
    assert resolved.redirect_to_ticker is None
    # Exactly one S3 call, with the ticker normalised to uppercase.
    market_data.get.assert_awaited_once()
    call = market_data.get.await_args
    assert call.args[0] == "/api/v1/instruments/lookup"
    assert call.kwargs["params"]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_lowercase_ticker_normalised_before_lookup() -> None:
    """Lowercase input "aapl" must be upper-cased before the S3 call so
    the unique index on upper(symbol) hits.
    """
    market_data = MagicMock(spec=httpx.AsyncClient)
    market_data.get = AsyncMock(
        return_value=_mock_response(200, {"id": _AAPL_UUID, "symbol": "AAPL"}),
    )
    clients = _make_clients(market_data=market_data)

    resolved = await resolve_security_id("aapl", clients=clients)

    assert resolved.instrument_id == UUID(_AAPL_UUID)
    call = market_data.get.await_args
    # # WHY assert on params['symbol'] — the resolver must canonicalise
    # # to uppercase regardless of input case. A regression that sent
    # # "aapl" to S3 would still hit the unique index today (it lower-
    # # cases internally) but would defeat the cache by creating two
    # # entries for the same security.
    assert call.kwargs["params"]["symbol"] == "AAPL"


# ── Case 3: ticker alias → KG fallback + 301 ─────────────────────────────────


@pytest.mark.asyncio
async def test_ticker_alias_falls_back_to_kg_and_signals_301() -> None:
    """When S3 returns 404 for the ticker but the KG knows it as an
    alias (e.g. FB → META), the resolver returns the canonical
    instrument_id AND signals the route handler to issue a 301 by
    setting ``redirect_to_ticker`` to the canonical ticker.
    """
    market_data = MagicMock(spec=httpx.AsyncClient)
    market_data.get = AsyncMock(return_value=_mock_response(404, {}))
    kg = MagicMock(spec=httpx.AsyncClient)
    kg.get = AsyncMock(
        return_value=_mock_response(
            200,
            {"entity_id": _META_UUID, "ticker": "META"},
        ),
    )
    clients = _make_clients(market_data=market_data, knowledge_graph=kg)

    resolved = await resolve_security_id("FB", clients=clients)

    assert resolved.instrument_id == UUID(_META_UUID)
    # 301 signal — the route handler will redirect /instruments/FB →
    # /instruments/META so the URL bar canonicalises.
    assert resolved.redirect_to_ticker == "META"
    market_data.get.assert_awaited_once()
    kg.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_ticker_matches_canonical_no_301_signal() -> None:
    """When the KG returns the SAME ticker the user typed (no alias
    drift), no 301 signal — the URL bar is already correct.
    """
    market_data = MagicMock(spec=httpx.AsyncClient)
    market_data.get = AsyncMock(return_value=_mock_response(404, {}))
    kg = MagicMock(spec=httpx.AsyncClient)
    kg.get = AsyncMock(
        return_value=_mock_response(
            200,
            {"entity_id": _AAPL_UUID, "ticker": "AAPL"},
        ),
    )
    clients = _make_clients(market_data=market_data, knowledge_graph=kg)

    resolved = await resolve_security_id("AAPL", clients=clients)

    assert resolved.instrument_id == UUID(_AAPL_UUID)
    assert resolved.redirect_to_ticker is None


# ── Case 4: unknown ticker → InstrumentNotFoundError ─────────────────────────


@pytest.mark.asyncio
async def test_unknown_ticker_raises_not_found() -> None:
    """Both S3 and KG return 404 → the resolver raises
    InstrumentNotFoundError so the route handler can return a 404 with
    the attempted ticker echoed back (rendered by InstrumentNotFound.tsx).
    """
    market_data = MagicMock(spec=httpx.AsyncClient)
    market_data.get = AsyncMock(return_value=_mock_response(404, {}))
    kg = MagicMock(spec=httpx.AsyncClient)
    kg.get = AsyncMock(return_value=_mock_response(404, {}))
    clients = _make_clients(market_data=market_data, knowledge_graph=kg)

    with pytest.raises(InstrumentNotFoundError) as exc_info:
        await resolve_security_id("ZZZZZZ", clients=clients)

    # The identifier surfaces on the exception so the route handler can
    # echo it back in the 404 body without re-stringifying.
    assert exc_info.value.identifier == "ZZZZZZ"
    # Both fallbacks were attempted before raising — the resolver does
    # not silently give up after the first miss.
    market_data.get.assert_awaited_once()
    kg.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_identifier_raises_not_found_without_network() -> None:
    """Empty or whitespace identifier → immediate raise, no network."""
    market_data = MagicMock(spec=httpx.AsyncClient)
    market_data.get = AsyncMock()
    clients = _make_clients(market_data=market_data)

    with pytest.raises(InstrumentNotFoundError):
        await resolve_security_id("", clients=clients)

    market_data.get.assert_not_awaited()


# ── Cache behaviour ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repeated_lookup_serves_from_cache() -> None:
    """Second call with the same identifier must not hit the network —
    the in-process TTLCache short-circuits.
    """
    market_data = MagicMock(spec=httpx.AsyncClient)
    market_data.get = AsyncMock(
        return_value=_mock_response(200, {"id": _AAPL_UUID, "symbol": "AAPL"}),
    )
    clients = _make_clients(market_data=market_data)

    first = await resolve_security_id("AAPL", clients=clients)
    second = await resolve_security_id("AAPL", clients=clients)

    assert first == second
    # Only one network call across both lookups.
    assert market_data.get.await_count == 1


@pytest.mark.asyncio
async def test_cache_pop_invalidates_entry() -> None:
    """``resolve_security_id.cache.pop(key, None)`` (the documented
    invalidation entry point for the future entity.dirtied.v1 consumer)
    forces the next call to re-hit the network.
    """
    market_data = MagicMock(spec=httpx.AsyncClient)
    market_data.get = AsyncMock(
        return_value=_mock_response(200, {"id": _AAPL_UUID, "symbol": "AAPL"}),
    )
    clients = _make_clients(market_data=market_data)

    await resolve_security_id("AAPL", clients=clients)
    # Cache key is the lowercased identifier.
    resolve_security_id.cache.pop("aapl", None)  # type: ignore[attr-defined]
    await resolve_security_id("AAPL", clients=clients)

    assert market_data.get.await_count == 2
