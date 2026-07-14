"""Unit tests for the explicit relations backfill — PLAN-0123 Wave 3, T-A-3-03.

Regression guard for the review's elevated OQ-7: "lazy refresh picks up new
alphas" is false (relations.decay_alpha denormalizes only on upsert) — this
module's job is to make the backfill explicit rather than assumed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from knowledge_graph.application.analytics.decay_fitting.backfill import backfill_relations_for_type

pytestmark = pytest.mark.unit


def _make_session(rowcount: int) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.rowcount = rowcount
    session.execute = AsyncMock(return_value=result)
    return session


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


class TestBackfillUpdatesExistingRelations:
    def test_backfill_updates_existing_relations_of_type(self) -> None:
        """Relations of the fitted type that received no new evidence still get decay_alpha updated."""
        session = _make_session(rowcount=42)

        updated = _run(backfill_relations_for_type("analyst_rating", 0.0231, session))

        assert updated == 42
        session.execute.assert_awaited_once()
        params = session.execute.call_args[0][1]
        assert params["decay_alpha"] == pytest.approx(0.0231)
        assert params["canonical_type"] == "analyst_rating"

    def test_backfill_sets_confidence_stale(self) -> None:
        """confidence_stale flips true so the existing refresh mechanism recomputes confidence."""
        session = _make_session(rowcount=10)

        _run(backfill_relations_for_type("price_target", 0.05, session))

        executed_sql = str(session.execute.call_args[0][0])
        assert "confidence_stale = true" in executed_sql

    def test_backfill_scoped_to_single_type(self) -> None:
        """The UPDATE is WHERE-scoped to one canonical_type — never a blind full-table scan."""
        session = _make_session(rowcount=5)

        _run(backfill_relations_for_type("sentiment_signal", 0.2, session))

        executed_sql = str(session.execute.call_args[0][0])
        assert "WHERE canonical_type = :canonical_type" in executed_sql

    def test_zero_rows_updated_returns_zero_not_error(self) -> None:
        session = _make_session(rowcount=0)

        updated = _run(backfill_relations_for_type("credit_rating", 0.001, session))

        assert updated == 0

    def test_none_rowcount_treated_as_zero(self) -> None:
        """Some drivers report rowcount=None for certain statement shapes — treat as 0, not crash."""
        session = _make_session(rowcount=0)
        session.execute.return_value.rowcount = None

        updated = _run(backfill_relations_for_type("issues_debt", 0.01, session))

        assert updated == 0
