"""Unit tests for EntityAliasRepository — BP-449 regression suite.

Specifically tests the two bugs fixed in BP-449:

  A. Global uidx_entity_aliases_normalized index (EXACT aliases) not handled
     by the ON CONFLICT clause — a UniqueViolationError from a different entity
     owning the same EXACT alias must be caught inside insert() and return None
     without aborting the outer session transaction.

  B. asyncpg DatatypeMismatchError in apply_retry_transition CASE expression
     when :base_now lacks an explicit CAST — confirmed by checking the SQL
     string contains CAST(:base_now AS timestamptz).

Coverage:
  EntityAliasRepository.insert:
    - test_insert_happy_path              — RETURNING alias_id → UUID
    - test_insert_per_entity_conflict     — ON CONFLICT DO NOTHING → None
    - test_insert_global_exact_conflict   — 23505 on global index → None (BP-449 A)
    - test_insert_other_integrity_error   — non-23505 IntegrityError re-raises

  apply_retry_transition SQL:
    - test_retry_sql_casts_base_now       — SQL must contain CAST(:base_now AS timestamptz)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.unit

_ENTITY_ID = UUID("01234567-89ab-7def-8012-aaaaaaaaaaaa")
_OTHER_ENTITY_ID = UUID("01234567-89ab-7def-8012-bbbbbbbbbbbb")
_ALIAS_ID = UUID("01234567-89ab-7def-8012-cccccccccccc")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(returning_row: tuple | None) -> AsyncMock:
    """Return an AsyncMock session whose execute().fetchone() yields ``returning_row``."""
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.fetchone.return_value = returning_row

    # begin_nested() must return an async context manager that works correctly
    nested_cm = AsyncMock()
    nested_cm.__aenter__ = AsyncMock(return_value=nested_cm)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin_nested = MagicMock(return_value=nested_cm)
    session.execute = AsyncMock(return_value=result_mock)
    return session


def _make_failing_session(pgcode: str) -> AsyncMock:
    """Return a session whose execute() raises IntegrityError with the given pgcode."""
    session = AsyncMock()

    # Simulate the error being raised inside begin_nested().__aexit__
    orig = MagicMock()
    orig.pgcode = pgcode
    err = IntegrityError("duplicate key", {}, orig)

    # begin_nested().__aenter__ succeeds; execute raises; __aexit__ sees the exc
    nested_cm = AsyncMock()
    nested_cm.__aenter__ = AsyncMock(return_value=nested_cm)
    # Make __aexit__ re-raise the IntegrityError (simulates SAVEPOINT rollback)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin_nested = MagicMock(return_value=nested_cm)
    session.execute = AsyncMock(side_effect=err)
    return session


# ---------------------------------------------------------------------------
# EntityAliasRepository.insert
# ---------------------------------------------------------------------------


class TestEntityAliasRepositoryInsert:
    async def test_insert_happy_path(self) -> None:
        """Happy path: INSERT RETURNING returns the new alias_id UUID."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_alias import (
            EntityAliasRepository,
        )

        session = _make_session(returning_row=(str(_ALIAS_ID),))
        repo = EntityAliasRepository(session)

        result = await repo.insert(_ENTITY_ID, "Apple Inc.", "apple inc.", "EXACT")

        assert result == _ALIAS_ID
        session.execute.assert_awaited_once()

    async def test_insert_per_entity_conflict_returns_none(self) -> None:
        """ON CONFLICT DO NOTHING on per-entity index → RETURNING empty → None."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_alias import (
            EntityAliasRepository,
        )

        # RETURNING empty = conflict handled by ON CONFLICT clause
        session = _make_session(returning_row=None)
        repo = EntityAliasRepository(session)

        result = await repo.insert(_ENTITY_ID, "Apple Inc.", "apple inc.", "EXACT")

        # None means the conflict was absorbed silently — correct behavior
        assert result is None

    async def test_insert_global_exact_conflict_returns_none(self) -> None:
        """BP-449A regression: UniqueViolation on global EXACT index must return None.

        This simulates the case where a DIFFERENT entity already owns the same
        EXACT alias. The global uidx_entity_aliases_normalized index fires with
        pgcode='23505', which is NOT handled by the ON CONFLICT clause. Without
        the begin_nested() SAVEPOINT fix, this would abort the outer session.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_alias import (
            EntityAliasRepository,
        )

        session = _make_failing_session(pgcode="23505")
        repo = EntityAliasRepository(session)

        # Must NOT raise — must return None (soft conflict)
        result = await repo.insert(_ENTITY_ID, "Apple Inc.", "apple inc.", "EXACT")

        assert result is None

    async def test_insert_non_23505_integrity_error_reraises(self) -> None:
        """Non-23505 IntegrityError (e.g. FK violation) must propagate up."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_alias import (
            EntityAliasRepository,
        )

        session = _make_failing_session(pgcode="23503")  # FK violation
        repo = EntityAliasRepository(session)

        with pytest.raises(IntegrityError):
            await repo.insert(_ENTITY_ID, "Apple Inc.", "apple inc.", "EXACT")


# ---------------------------------------------------------------------------
# apply_retry_transition — BP-449B: CAST(:base_now AS timestamptz)
# ---------------------------------------------------------------------------


class TestApplyRetryTransitionTypecast:
    async def test_retry_sql_casts_base_now_as_timestamptz(self) -> None:
        """BP-449B regression: SQL must contain CAST(:base_now AS timestamptz).

        Without the explicit cast, asyncpg infers :base_now as interval type
        from the CASE ELSE branch context (interval + interval context), causing
        DatatypeMismatchError when a Python datetime is bound.
        """
        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        # Session that returns a non-terminal row so the full CASE is exercised
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.fetchone.return_value = (False, 1, None)
        session.execute = AsyncMock(return_value=result_mock)

        queue_id = UUID("01234567-89ab-7def-8012-000000000099")
        await core.apply_retry_transition(session, queue_id, max_retries=5)

        sql_str = str(session.execute.call_args.args[0])
        assert (
            "CAST(:base_now AS timestamptz)" in sql_str
        ), "SQL must explicitly cast :base_now to timestamptz to prevent asyncpg DatatypeMismatchError (BP-449B)"
