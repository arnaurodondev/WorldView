"""BP-661 regression — S6Client.resolve_entity_by_ticker phantom-twin handling.

Multiple canonicals can share the same ticker when a BP-459-style phantom
duplicate exists in intelligence_db ("AAPL Stock" and "Apple Inc." both
carry ticker=AAPL). The old first-exact-match loop returned whichever
candidate S6 ranked first (the phantom, at confidence 0.95) — the twin has
no description/exchange and a thin intelligence bundle, degrading every
downstream tool. The fix prefers exact-ticker matches whose canonical name
does NOT embed the ticker as a token.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from rag_chat.domain.entities.chat import ResolvedEntity
from rag_chat.infrastructure.clients.s6_client import S6Client

pytestmark = pytest.mark.unit

_APPLE_ID = UUID("01900000-0000-7000-8000-000000001001")
_PHANTOM_ID = UUID("52a92aa8-750e-4b97-8838-521ce2ce9f74")


def _entity(entity_id: UUID, name: str, confidence: float, ticker: str | None) -> ResolvedEntity:
    return ResolvedEntity(
        entity_id=entity_id,
        canonical_name=name,
        entity_type="financial_instrument",
        confidence=confidence,
        matched_text="AAPL",
        ticker=ticker,
    )


def _client_with(candidates: list[ResolvedEntity]) -> S6Client:
    client = S6Client(base_url="http://test-s6:8006", timeout=1.0)
    client.resolve_entities = AsyncMock(return_value=candidates)  # type: ignore[method-assign]
    return client


class TestPhantomTwinDisambiguation:
    @pytest.mark.asyncio
    async def test_prefers_real_canonical_over_phantom_twin(self) -> None:
        """The live AAPL case: phantom twin ranked FIRST must lose to Apple Inc."""
        client = _client_with(
            [
                _entity(_PHANTOM_ID, "AAPL Stock", 0.95, "AAPL"),
                _entity(_APPLE_ID, "Apple Inc.", 0.90, "AAPL"),
            ]
        )
        resolved = await client.resolve_entity_by_ticker("AAPL")
        assert resolved == _APPLE_ID

    @pytest.mark.asyncio
    async def test_exchange_style_phantom_names_are_filtered(self) -> None:
        """'NasdaqGS:AAPL' / 'AAPL.US' shapes also embed the ticker → filtered."""
        client = _client_with(
            [
                _entity(_PHANTOM_ID, "NasdaqGS:AAPL", 0.97, "AAPL"),
                _entity(UUID(int=3), "AAPL.US", 0.96, "AAPL"),
                _entity(_APPLE_ID, "Apple Inc.", 0.90, "AAPL"),
            ]
        )
        resolved = await client.resolve_entity_by_ticker("AAPL")
        assert resolved == _APPLE_ID

    @pytest.mark.asyncio
    async def test_single_exact_match_unchanged(self) -> None:
        """One exact ticker match → returned as before (no twin to disambiguate)."""
        client = _client_with([_entity(_APPLE_ID, "Apple Inc.", 0.92, "AAPL")])
        resolved = await client.resolve_entity_by_ticker("AAPL")
        assert resolved == _APPLE_ID

    @pytest.mark.asyncio
    async def test_all_phantom_shaped_falls_back_to_first_exact(self) -> None:
        """When EVERY exact match embeds the ticker, the first (top-confidence) wins."""
        client = _client_with(
            [
                _entity(_PHANTOM_ID, "AAPL Stock", 0.95, "AAPL"),
                _entity(UUID(int=4), "AAPL.US", 0.91, "AAPL"),
            ]
        )
        resolved = await client.resolve_entity_by_ticker("AAPL")
        assert resolved == _PHANTOM_ID

    @pytest.mark.asyncio
    async def test_no_exact_match_falls_back_to_best_confidence(self) -> None:
        """Legacy inexact fallback preserved: no ticker-field match → top candidate."""
        client = _client_with([_entity(_APPLE_ID, "Apple Inc.", 0.85, None)])
        resolved = await client.resolve_entity_by_ticker("AAPL")
        assert resolved == _APPLE_ID

    @pytest.mark.asyncio
    async def test_no_candidates_returns_none(self) -> None:
        client = _client_with([])
        resolved = await client.resolve_entity_by_ticker("ZZZZ")
        assert resolved is None
