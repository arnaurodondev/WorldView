"""Unit tests for QueryEntityResolverUseCase (PLAN-0015-B T-B-2-01)."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest
from nlp_pipeline.application.use_cases.query_entity_resolver import (
    QueryEntityResolverUseCase,
    _normalize,
)

_ENTITY_ID = uuid.UUID("018f1e2a-0000-7000-8000-000000000001")
_ENTITY_DATA = {
    "canonical_name": "Apple Inc",
    "entity_type": "company",
    "ticker": "AAPL",
    "isin": None,
}


def _make_resolver(
    *,
    exact: dict | None = None,
    ticker_isin: dict | None = None,
    fuzzy: dict | None = None,
    entity_data: dict | None = None,
    valkey_cached: str | None = None,
) -> QueryEntityResolverUseCase:
    alias_repo = AsyncMock()
    alias_repo.batch_exact_match = AsyncMock(return_value=exact or {})
    alias_repo.batch_ticker_isin_match = AsyncMock(return_value=ticker_isin or {})
    alias_repo.batch_fuzzy_trigram = AsyncMock(return_value=fuzzy or {})

    canonical_repo = AsyncMock()
    canonical_repo.get = AsyncMock(return_value=entity_data or _ENTITY_DATA)

    valkey = AsyncMock()
    valkey.get = AsyncMock(return_value=valkey_cached)
    valkey.set = AsyncMock()

    return QueryEntityResolverUseCase(
        alias_repo=alias_repo,
        canonical_repo=canonical_repo,
        valkey=valkey,
        ner_client=None,
        embedding_client=None,
        embedding_repo=None,
    )


@pytest.mark.unit
class TestNormalize:
    def test_lowercase_strips_punctuation(self) -> None:
        assert _normalize("Apple, Inc.") == "apple inc"

    def test_collapses_whitespace(self) -> None:
        assert _normalize("  Apple   Inc  ") == "apple inc"

    def test_unicode_normalized(self) -> None:
        # NFKD decomposes Á → A + combining accent; the combining mark is stripped by [^\w\s]
        # Result is "a pple" (space where the accent was), then collapsed → "a pple"
        result = _normalize("Ápple")
        assert result == "a pple"


@pytest.mark.unit
class TestQueryEntityResolverUseCase:
    @pytest.mark.asyncio
    async def test_resolve_exact_alias_match(self) -> None:
        """Stage 1 exact alias match returns confidence=1.0, resolution_stage=1."""
        resolver = _make_resolver(exact={"apple": _ENTITY_ID})
        results, normalized = await resolver.execute("Apple")

        assert normalized == "apple"
        assert len(results) == 1
        r = results[0]
        assert r.entity_id == _ENTITY_ID
        assert r.canonical_name == "Apple Inc"
        assert r.confidence == 1.0
        assert r.resolution_stage == 1
        assert r.ticker == "AAPL"
        assert r.isin is None

    @pytest.mark.asyncio
    async def test_resolve_ticker_match(self) -> None:
        """Stage 2 ticker match returns confidence=0.95, resolution_stage=2."""
        resolver = _make_resolver(ticker_isin={"AAPL": _ENTITY_ID})
        results, _ = await resolver.execute("AAPL")

        assert len(results) == 1
        r = results[0]
        assert r.entity_id == _ENTITY_ID
        assert r.confidence == 0.95
        assert r.resolution_stage == 2

    @pytest.mark.asyncio
    async def test_resolve_fuzzy_match(self) -> None:
        """Stage 3 fuzzy trigram match returns confidence=sim*0.90, resolution_stage=3."""
        sim = 0.85
        resolver = _make_resolver(fuzzy={"appl": [(_ENTITY_ID, sim)]})
        results, _ = await resolver.execute("Appl")

        assert len(results) == 1
        r = results[0]
        assert r.entity_id == _ENTITY_ID
        assert abs(r.confidence - sim * 0.90) < 1e-9
        assert r.resolution_stage == 3

    @pytest.mark.asyncio
    async def test_resolve_cache_hit_returns_without_db(self) -> None:
        """When Valkey has a cached result, alias/canonical repos are NOT called."""
        cached_payload = json.dumps(
            [
                {
                    "entity_id": str(_ENTITY_ID),
                    "canonical_name": "Apple Inc",
                    "entity_type": "company",
                    "confidence": 1.0,
                    "matched_text": "apple",
                    "resolution_stage": 1,
                    "ticker": "AAPL",
                    "isin": None,
                }
            ]
        )
        resolver = _make_resolver(valkey_cached=cached_payload)

        results, _ = await resolver.execute("Apple")

        assert len(results) == 1
        assert results[0].confidence == 1.0
        # Repos must NOT have been called (result came from cache)
        resolver._alias_repo.batch_exact_match.assert_not_called()  # type: ignore[attr-defined]
        resolver._canonical_repo.get.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_resolve_below_min_confidence_filtered(self) -> None:
        """Results below min_confidence=0.45 are excluded from output."""
        sim = 0.40  # 0.40 * 0.90 = 0.36 < 0.45
        resolver = _make_resolver(fuzzy={"appl": [(_ENTITY_ID, sim)]})
        results, _ = await resolver.execute("Appl", min_confidence=0.45)

        assert results == []

    @pytest.mark.asyncio
    async def test_highest_confidence_wins_across_stages(self) -> None:
        """When same entity appears in stage 1 and stage 3, stage 1 confidence is kept."""
        sim = 0.85  # stage 3 confidence = 0.765
        resolver = _make_resolver(
            exact={"apple": _ENTITY_ID},
            fuzzy={"apple": [(_ENTITY_ID, sim)]},
        )
        results, _ = await resolver.execute("Apple")

        assert len(results) == 1
        assert results[0].confidence == 1.0  # stage 1 wins
        assert results[0].resolution_stage == 1

    @pytest.mark.asyncio
    async def test_no_results_on_no_matches(self) -> None:
        """When no stages match, returns an empty list."""
        resolver = _make_resolver()
        results, normalized = await resolver.execute("xyznonexistent")

        assert results == []
        assert normalized == "xyznonexistent"
