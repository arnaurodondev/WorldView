"""Unit tests for EntityContradictionsUseCase (Wave C-1)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)


def _make_claim_repo(contradictions: list | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.fetch_contradictions_for_entity = AsyncMock(return_value=contradictions or [])
    return repo


def _contradiction(strength: float = 0.75) -> object:
    from knowledge_graph.application.ports.claim_repository import (
        ContradictionData,
        ContradictionSideData,
    )

    return ContradictionData(
        link_id=uuid4(),
        claim_type="polarity_flip",
        strength=strength,
        detected_at=_NOW,
        sides=[
            ContradictionSideData(
                polarity="positive",
                confidence=0.80,
                doc_id=uuid4(),
                claim_text="Positive claim",
                evidence_date=_NOW,
            ),
            ContradictionSideData(
                polarity="negative",
                confidence=0.70,
                doc_id=uuid4(),
                claim_text="Negative claim",
                evidence_date=_NOW,
            ),
        ],
    )


class TestEntityContradictionsUseCase:
    def test_contradictions_returned_for_entity(self) -> None:
        """Returns contradictions when they exist."""
        from knowledge_graph.application.use_cases.contradiction_lookup import (
            EntityContradictionsUseCase,
        )

        entity_id = uuid4()
        expected = [_contradiction()]
        repo = _make_claim_repo(contradictions=expected)

        result = asyncio.run(
            EntityContradictionsUseCase().execute(
                claim_repo=repo,
                entity_id=entity_id,
            )
        )

        assert result == expected
        repo.fetch_contradictions_for_entity.assert_called_once()
        call_kwargs = repo.fetch_contradictions_for_entity.call_args.kwargs
        assert call_kwargs["entity_id"] == entity_id

    def test_contradictions_returns_empty_list_on_no_results(self) -> None:
        """Empty list returned when entity has no contradictions (NOT 404)."""
        from knowledge_graph.application.use_cases.contradiction_lookup import (
            EntityContradictionsUseCase,
        )

        repo = _make_claim_repo(contradictions=[])

        result = asyncio.run(
            EntityContradictionsUseCase().execute(
                claim_repo=repo,
                entity_id=uuid4(),
            )
        )

        assert result == []

    def test_contradictions_claim_type_filter_forwarded(self) -> None:
        """claim_type filter is forwarded to the repository."""
        from knowledge_graph.application.use_cases.contradiction_lookup import (
            EntityContradictionsUseCase,
        )

        repo = _make_claim_repo()

        asyncio.run(
            EntityContradictionsUseCase().execute(
                claim_repo=repo,
                entity_id=uuid4(),
                claim_type="polarity_flip",
            )
        )

        call_kwargs = repo.fetch_contradictions_for_entity.call_args.kwargs
        assert call_kwargs["claim_type"] == "polarity_flip"

    def test_contradictions_top_k_forwarded(self) -> None:
        """top_k is forwarded to the repository."""
        from knowledge_graph.application.use_cases.contradiction_lookup import (
            EntityContradictionsUseCase,
        )

        repo = _make_claim_repo()

        asyncio.run(
            EntityContradictionsUseCase().execute(
                claim_repo=repo,
                entity_id=uuid4(),
                top_k=5,
            )
        )

        call_kwargs = repo.fetch_contradictions_for_entity.call_args.kwargs
        assert call_kwargs["top_k"] == 5
