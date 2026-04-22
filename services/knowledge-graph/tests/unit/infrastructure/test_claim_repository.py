"""Unit tests for ClaimRepository.fetch_contradictions_for_entity.

Focuses on BP-069 / API-008 fix: the query must never bind a Python ``None``
value as an asyncpg named parameter inside an equality expression.
All tests use mocked AsyncSessions — no DB required.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 22, 10, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(fetchall_return: list | None = None) -> AsyncMock:
    """Mock AsyncSession whose execute() returns configurable fetchall."""
    session = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = fetchall_return or []
    session.execute = AsyncMock(return_value=result)
    return session


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _make_repo(session: AsyncMock | None = None):  # type: ignore[no-untyped-def]
    from knowledge_graph.infrastructure.intelligence_db.repositories.claim_repository import (
        ClaimRepository,
    )

    return ClaimRepository(session or _make_session())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFetchContradictionsForEntity:
    """Tests for the BP-069 fix: no None-valued named params in equality expressions."""

    def test_no_claim_type_filter_executes_without_claim_type_param(self) -> None:
        """When claim_type is None, :claim_type must NOT appear in the params dict.

        BP-069: asyncpg raises AmbiguousParameterError when a None value is
        bound to a named param used in an equality comparison.  The fix builds
        the WHERE clause conditionally, omitting :claim_type entirely.
        """
        session = _make_session()
        repo = _make_repo(session)
        entity_id = uuid4()

        _run(repo.fetch_contradictions_for_entity(entity_id=entity_id))

        # Verify execute was called
        assert session.execute.called
        _, call_kwargs = session.execute.call_args
        # The second positional arg is the params dict
        params: dict = session.execute.call_args[0][1]
        # claim_type must NOT be in params — it would cause asyncpg AmbiguousParameterError
        assert (
            "claim_type" not in params
        ), "claim_type=None must NOT be bound as a named parameter (BP-069: asyncpg AmbiguousParameterError)"
        assert params["entity_id"] == str(entity_id)
        assert "top_k" in params

    def test_no_claim_type_filter_sql_has_no_claim_type_condition(self) -> None:
        """When claim_type is None, the SQL must not contain :claim_type."""
        session = _make_session()
        repo = _make_repo(session)

        _run(repo.fetch_contradictions_for_entity(entity_id=uuid4()))

        # Extract the SQL text from the TextClause object
        sql_text: str = str(session.execute.call_args[0][0].text)
        assert ":claim_type" not in sql_text, "SQL must not reference :claim_type when claim_type is None"

    def test_with_claim_type_filter_adds_condition_and_param(self) -> None:
        """When claim_type='earnings', the SQL condition and param must both be present."""
        session = _make_session()
        repo = _make_repo(session)

        _run(repo.fetch_contradictions_for_entity(entity_id=uuid4(), claim_type="earnings"))

        sql_text: str = str(session.execute.call_args[0][0].text)
        params: dict = session.execute.call_args[0][1]

        # SQL must include the filter condition
        assert "rcl.contradiction_type = :claim_type" in sql_text
        # Param must be bound as a non-None string
        assert params.get("claim_type") == "earnings"

    def test_empty_result_returns_empty_list(self) -> None:
        """Empty DB result → returns empty list (not a 404)."""
        session = _make_session(fetchall_return=[])
        repo = _make_repo(session)

        result = _run(repo.fetch_contradictions_for_entity(entity_id=uuid4()))

        assert result == []

    def test_default_top_k_is_20(self) -> None:
        """Default top_k is 20 when not supplied."""
        session = _make_session()
        repo = _make_repo(session)

        _run(repo.fetch_contradictions_for_entity(entity_id=uuid4()))

        params: dict = session.execute.call_args[0][1]
        assert params["top_k"] == 20

    def test_custom_top_k_forwarded(self) -> None:
        """Explicit top_k is forwarded to the SQL params."""
        session = _make_session()
        repo = _make_repo(session)

        _run(repo.fetch_contradictions_for_entity(entity_id=uuid4(), top_k=5))

        params: dict = session.execute.call_args[0][1]
        assert params["top_k"] == 5
