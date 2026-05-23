"""Unit tests for ArticleClaimSearchUseCase (Wave C-1)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)


def _make_claim_repo(results: list | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.search_claims = AsyncMock(return_value=results or [])
    return repo


def _claim_result(
    entity_id: object = None,
    claim_type: str = "analyst_rating",
    polarity: str = "positive",
    confidence: float = 0.80,
) -> object:
    from knowledge_graph.application.ports.claim_repository import ClaimSearchResult

    return ClaimSearchResult(
        claim_id=uuid4(),
        subject_entity_id=entity_id or uuid4(),
        claim_type=claim_type,
        polarity=polarity,
        claim_text="Some claim text",
        extraction_confidence=confidence,
        doc_id=uuid4(),
        created_at=_NOW,
    )


class TestArticleClaimSearchUseCase:
    def test_claim_search_by_entity(self) -> None:
        """Returns claims for given entity_ids."""
        from knowledge_graph.application.use_cases.claim_search import (
            ArticleClaimSearchUseCase,
        )

        entity_id = uuid4()
        expected = [_claim_result(entity_id=entity_id)]
        repo = _make_claim_repo(results=expected)

        result = asyncio.run(
            ArticleClaimSearchUseCase().execute(
                claim_repo=repo,
                entity_ids=[entity_id],
            ),
        )

        assert result == expected
        repo.search_claims.assert_called_once()
        call_kwargs = repo.search_claims.call_args.kwargs
        assert call_kwargs["entity_ids"] == [entity_id]

    def test_claim_search_claim_type_filter(self) -> None:
        """Filtered by claim_type — passed through to repository."""
        from knowledge_graph.application.use_cases.claim_search import (
            ArticleClaimSearchUseCase,
        )

        repo = _make_claim_repo()

        asyncio.run(
            ArticleClaimSearchUseCase().execute(
                claim_repo=repo,
                entity_ids=[uuid4()],
                claim_types=["analyst_rating"],
            ),
        )

        call_kwargs = repo.search_claims.call_args.kwargs
        assert call_kwargs["claim_types"] == ["analyst_rating"]

    def test_claim_search_date_range(self) -> None:
        """Outside date range excluded — date params forwarded to repo."""
        from knowledge_graph.application.use_cases.claim_search import (
            ArticleClaimSearchUseCase,
        )

        repo = _make_claim_repo()
        d_from = date(2026, 1, 1)
        d_to = date(2026, 3, 31)

        asyncio.run(
            ArticleClaimSearchUseCase().execute(
                claim_repo=repo,
                entity_ids=[uuid4()],
                date_from=d_from,
                date_to=d_to,
            ),
        )

        call_kwargs = repo.search_claims.call_args.kwargs
        assert call_kwargs["date_from"] == d_from
        assert call_kwargs["date_to"] == d_to

    def test_claim_search_min_confidence(self) -> None:
        """Low confidence excluded — min_confidence forwarded to repo."""
        from knowledge_graph.application.use_cases.claim_search import (
            ArticleClaimSearchUseCase,
        )

        repo = _make_claim_repo()

        asyncio.run(
            ArticleClaimSearchUseCase().execute(
                claim_repo=repo,
                entity_ids=[uuid4()],
                min_confidence=0.70,
            ),
        )

        call_kwargs = repo.search_claims.call_args.kwargs
        assert call_kwargs["min_confidence"] == 0.70
