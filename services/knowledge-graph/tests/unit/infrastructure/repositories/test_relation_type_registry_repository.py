"""Unit tests for RelationTypeRegistryRepository — PLAN-0123 Wave 1 (PRD-0120 FR-2).

Verifies the registry-first/class-fallback COALESCE change: the SQL text of
both `find_exact` and `find_by_embedding` must resolve `decay_alpha` via
`COALESCE(rtr.decay_alpha, dcc.decay_alpha)` rather than the old class-only
`dcc.decay_alpha` projection, and that row-mapping into the returned dict is
unaffected (the value at row index 5 is still mapped to key "decay_alpha").

`find_exact_simple` is verified untouched (still no COALESCE/decay_alpha at
all) — it is explicitly out of scope for PRD-0120 (plan Wave 1, T-A-1-02).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from knowledge_graph.infrastructure.intelligence_db.repositories.relation_type_registry import (
    RelationTypeRegistryRepository,
)

pytestmark = pytest.mark.unit


def _make_session(fetchone_return: object = None) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.fetchone.return_value = fetchone_return
    session.execute = AsyncMock(return_value=result)
    return session


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


class TestFindExact:
    def test_query_resolves_decay_alpha_via_coalesce(self) -> None:
        """The SQL text must COALESCE the per-type override over the class prior."""
        session = _make_session(fetchone_return=None)
        repo = RelationTypeRegistryRepository(session)

        _run(repo.find_exact("analyst_rating"))

        executed_sql = str(session.execute.call_args[0][0])
        assert "COALESCE(rtr.decay_alpha, dcc.decay_alpha)" in executed_sql
        assert "AS decay_alpha" in executed_sql
        # The class-only projection must be gone.
        assert "dcc.decay_alpha\n" not in executed_sql.replace("COALESCE(rtr.decay_alpha, dcc.decay_alpha)", "")

    def test_returns_resolved_decay_alpha_from_row(self) -> None:
        """Row mapping is unaffected: index 5 still maps to 'decay_alpha'."""
        row = ("type-id-1", "analyst_rating", "TEMPORAL_CLAIM", "FAST", 0.6, 0.0123)
        session = _make_session(fetchone_return=row)
        repo = RelationTypeRegistryRepository(session)

        result = _run(repo.find_exact("analyst_rating"))

        assert result is not None
        assert result["decay_alpha"] == pytest.approx(0.0123)
        assert result["canonical_type"] == "analyst_rating"

    def test_returns_none_when_no_match(self) -> None:
        session = _make_session(fetchone_return=None)
        repo = RelationTypeRegistryRepository(session)

        result = _run(repo.find_exact("nonexistent_type"))

        assert result is None


class TestFindByEmbedding:
    def test_query_resolves_decay_alpha_via_coalesce(self) -> None:
        session = _make_session(fetchone_return=None)
        repo = RelationTypeRegistryRepository(session)

        _run(repo.find_by_embedding([0.1, 0.2, 0.3]))

        executed_sql = str(session.execute.call_args[0][0])
        assert "COALESCE(rtr.decay_alpha, dcc.decay_alpha)" in executed_sql
        assert "AS decay_alpha" in executed_sql

    def test_returns_resolved_decay_alpha_within_threshold(self) -> None:
        row = ("type-id-2", "price_target", "TEMPORAL_CLAIM", "FAST", 0.55, 0.049510, 0.10)
        session = _make_session(fetchone_return=row)
        repo = RelationTypeRegistryRepository(session)

        result = _run(repo.find_by_embedding([0.1, 0.2], distance_threshold=0.35))

        assert result is not None
        assert result["decay_alpha"] == pytest.approx(0.049510)

    def test_returns_none_when_beyond_distance_threshold(self) -> None:
        row = ("type-id-3", "sentiment_signal", "TEMPORAL_CLAIM", "EPHEMERAL", 0.4, 0.231049, 0.99)
        session = _make_session(fetchone_return=row)
        repo = RelationTypeRegistryRepository(session)

        result = _run(repo.find_by_embedding([0.1, 0.2], distance_threshold=0.35))

        assert result is None


class TestFindExactSimpleUnaffected:
    def test_find_exact_simple_has_no_decay_alpha_or_coalesce(self) -> None:
        """Out of scope for PRD-0120 (plan Wave 1 codebase-state table) — untouched."""
        session = _make_session(fetchone_return=None)
        repo = RelationTypeRegistryRepository(session)

        _run(repo.find_exact_simple("analyst_rating"))

        executed_sql = str(session.execute.call_args[0][0])
        assert "decay_alpha" not in executed_sql
        assert "COALESCE" not in executed_sql
        assert "decay_class_config" not in executed_sql
