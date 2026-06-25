"""Unit tests for GetEntityDetailUseCase (PRD-0073 §9.6).

Covers F-Q13 of the PLAN-0073 QA report — verifies that the use case calls
``CanonicalEntityRepository.get_by_id()`` (which DOES exist on the repo, so
the QA-flagged AttributeError concern is unfounded — see VERIFICATION below).

VERIFICATION (PLAN-0073 F-Q13):
    Read of services/knowledge-graph/src/.../intelligence_db/repositories/
    canonical_entity.py confirms ``get_by_id(entity_id: UUID) -> CanonicalEntity | None``
    is defined (line 86).  The use case is therefore correct as-shipped.

This test suite still builds an end-to-end test that constructs the real
``CanonicalEntityRepository`` (NOT mocked) on top of a session whose execute
returns no rows.  Were ``get_by_id`` ever removed by a future refactor, this
test would surface it as an AttributeError immediately.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from knowledge_graph.application.use_cases.get_entity_detail import (
    GetEntityDetailUseCase,
)
from knowledge_graph.domain.models import CanonicalEntity
from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
    CanonicalEntityRepository,
)

pytestmark = pytest.mark.unit

_ENTITY_ID = UUID("01900000-0000-7000-8000-000000000001")


# ---------------------------------------------------------------------------
# Use case behaviour with a mocked repo
# ---------------------------------------------------------------------------


class TestUseCaseWithMockedRepo:
    async def test_calls_repo_get_by_id_with_entity_id(self) -> None:
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=None)
        uc = GetEntityDetailUseCase(repo)

        await uc.execute(_ENTITY_ID)

        repo.get_by_id.assert_awaited_once_with(_ENTITY_ID)

    async def test_returns_none_when_repo_returns_none(self) -> None:
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=None)
        uc = GetEntityDetailUseCase(repo)

        result = await uc.execute(_ENTITY_ID)
        assert result is None

    async def test_returns_canonical_entity_when_found(self) -> None:
        expected = CanonicalEntity(
            entity_id=_ENTITY_ID,
            canonical_name="Apple Inc.",
            entity_type="financial_instrument",
            ticker="AAPL",
            description="A consumer electronics maker.",
            data_completeness=0.85,
            enrichment_attempts=1,
        )
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=expected)
        uc = GetEntityDetailUseCase(repo)

        result = await uc.execute(_ENTITY_ID)
        # PLAN-0099: execute() now returns the EntityDetailResult aggregate.
        assert result is not None
        assert result.entity is expected
        assert result.entity.canonical_name == "Apple Inc."
        assert result.entity.description == "A consumer electronics maker."
        # No alias/relation repos wired -> empty collections, zero count.
        assert result.aliases == []
        assert result.top_relations == []
        assert result.relation_count == 0


# ---------------------------------------------------------------------------
# End-to-end with a real CanonicalEntityRepository (no mock spec)
# ---------------------------------------------------------------------------


class TestUseCaseEndToEndWithRealRepo:
    """Construct the real repository — surfaces AttributeError if get_by_id is removed."""

    async def test_real_repo_get_by_id_returns_none_when_no_rows(self) -> None:
        """The repo's get_by_id must execute SQL and return None when fetchone()
        returns None.  This tests the full path without mocking the repo class."""
        # Mock the AsyncSession only — keep the real repository class.
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.fetchone = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=result_mock)

        repo = CanonicalEntityRepository(session)
        uc = GetEntityDetailUseCase(repo)

        result = await uc.execute(_ENTITY_ID)

        assert result is None
        # Confirm the SELECT actually ran.
        session.execute.assert_awaited_once()

    async def test_real_repo_get_by_id_returns_entity_when_row_present(self) -> None:
        """End-to-end: the real repo maps a DB row tuple → CanonicalEntity correctly.

        The column order MUST match the repo's SELECT:
            entity_id, canonical_name, entity_type, ticker, isin, exchange,
            metadata, enrichment_attempts, description, data_completeness,
            enriched_at
        """
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.fetchone = MagicMock(
            return_value=(
                str(_ENTITY_ID),
                "Apple Inc.",
                "financial_instrument",
                "AAPL",
                None,  # isin
                "NASDAQ",
                {"sector": "Technology"},  # metadata jsonb
                1,  # enrichment_attempts
                "A consumer electronics maker.",
                0.85,
                None,  # enriched_at
                None,  # health_score (migration 0031)
            )
        )
        session.execute = AsyncMock(return_value=result_mock)

        repo = CanonicalEntityRepository(session)
        uc = GetEntityDetailUseCase(repo)

        result = await uc.execute(_ENTITY_ID)

        assert result is not None
        entity = result.entity  # PLAN-0099: EntityDetailResult aggregate
        assert entity.entity_id == _ENTITY_ID
        assert entity.canonical_name == "Apple Inc."
        assert entity.entity_type == "financial_instrument"
        assert entity.ticker == "AAPL"
        assert entity.exchange == "NASDAQ"
        assert entity.metadata == {"sector": "Technology"}
        assert entity.description == "A consumer electronics maker."
        assert entity.data_completeness == 0.85

    def test_get_by_id_method_exists_on_repo(self) -> None:
        """Compile-time guard against accidental method removal (F-Q13)."""
        assert hasattr(CanonicalEntityRepository, "get_by_id")
        # Must be async — use-case awaits it.
        import inspect

        assert inspect.iscoroutinefunction(CanonicalEntityRepository.get_by_id)


# ---------------------------------------------------------------------------
# PLAN-0099: alias / top-relation aggregation
# ---------------------------------------------------------------------------


class TestEntityDetailAggregation:
    """Aliases, top relations (authority-ranked) and relation_count (PLAN-0099)."""

    @staticmethod
    def _entity() -> CanonicalEntity:
        return CanonicalEntity(
            entity_id=_ENTITY_ID,
            canonical_name="Apple Inc.",
            entity_type="financial_instrument",
            ticker="AAPL",
        )

    @staticmethod
    def _relation_row(rel_id, other_id, *, subject_is_entity=True, confidence=0.5, evidence_count=1):
        return {
            "relation_id": rel_id,
            "subject_entity_id": _ENTITY_ID if subject_is_entity else other_id,
            "object_entity_id": other_id if subject_is_entity else _ENTITY_ID,
            "canonical_type": "competes_with",
            "semantic_mode": "RELATION_STATE",
            "decay_class": "DURABLE",
            "confidence": confidence,
            "confidence_stale": False,
            "evidence_count": evidence_count,
        }

    async def test_aliases_and_relation_count_populated(self) -> None:
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=self._entity())
        repo.get_batch = AsyncMock(return_value=[])
        alias_repo = AsyncMock()
        alias_repo.get_for_entity = AsyncMock(
            return_value=[{"alias_text": "AAPL", "alias_type": "TICKER"}],
        )
        relation_repo = AsyncMock()
        relation_repo.count_for_entity = AsyncMock(return_value=42)
        relation_repo.list_for_entity = AsyncMock(return_value=[])
        summary_repo = AsyncMock()
        summary_repo.get_current_summaries_batch = AsyncMock(return_value={})

        uc = GetEntityDetailUseCase(repo, alias_repo=alias_repo, relation_repo=relation_repo, summary_repo=summary_repo)
        result = await uc.execute(_ENTITY_ID)

        assert result is not None
        assert result.aliases == [{"alias_text": "AAPL", "alias_type": "TICKER"}]
        assert result.relation_count == 42
        alias_repo.get_for_entity.assert_awaited_once_with(_ENTITY_ID)

    async def test_top_relations_ranked_by_authority_with_direction(self) -> None:
        """Relations are ranked by confidence*log1p(evidence_count); direction +
        counterpart names are annotated; summaries merged via single batch."""
        from uuid import uuid4

        rel_weak = uuid4()
        rel_strong = uuid4()
        other_a = uuid4()
        other_b = uuid4()

        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=self._entity())
        repo.get_batch = AsyncMock(
            return_value=[
                {"entity_id": other_a, "canonical_name": "Microsoft", "entity_type": "financial_instrument"},
                {"entity_id": other_b, "canonical_name": "Samsung", "entity_type": "financial_instrument"},
            ]
        )
        alias_repo = AsyncMock()
        alias_repo.get_for_entity = AsyncMock(return_value=[])
        relation_repo = AsyncMock()
        relation_repo.count_for_entity = AsyncMock(return_value=2)
        relation_repo.list_for_entity = AsyncMock(
            return_value=[
                # Weak first in repo order (latest_evidence_at DESC) — ranking must reorder.
                self._relation_row(rel_weak, other_a, subject_is_entity=True, confidence=0.3, evidence_count=1),
                self._relation_row(rel_strong, other_b, subject_is_entity=False, confidence=0.9, evidence_count=50),
            ]
        )
        summary_repo = AsyncMock()
        summary_repo.get_current_summaries_batch = AsyncMock(
            return_value={rel_strong: "Samsung competes with Apple in smartphones."},
        )

        uc = GetEntityDetailUseCase(repo, alias_repo=alias_repo, relation_repo=relation_repo, summary_repo=summary_repo)
        result = await uc.execute(_ENTITY_ID)

        assert result is not None
        assert [r["relation_id"] for r in result.top_relations] == [rel_strong, rel_weak]
        strong = result.top_relations[0]
        # Entity is the OBJECT of the strong relation -> inbound; counterpart = subject.
        assert strong["direction"] == "inbound"
        assert strong["other_entity_id"] == other_b
        assert strong["other_entity_name"] == "Samsung"
        assert strong["relation_summary"] == "Samsung competes with Apple in smartphones."
        weak = result.top_relations[1]
        assert weak["direction"] == "outbound"
        assert weak["other_entity_name"] == "Microsoft"
        assert weak["relation_summary"] is None
        # Counterparts resolved via a single batch call (no N+1).
        repo.get_batch.assert_awaited_once()
