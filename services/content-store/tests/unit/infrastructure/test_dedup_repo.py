"""Unit tests for DedupHashRepository — ON CONFLICT idempotency (BP-040).

Validates that:
- insert() uses INSERT ... ON CONFLICT DO NOTHING (no UniqueViolationError)
- insert_pair() inserts both hashes idempotently
- Duplicate inserts are silently ignored
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit


def _mock_session() -> MagicMock:
    """Create a mock async session where execute is async."""
    session = MagicMock()
    session.execute = AsyncMock()
    return session


class TestDedupHashInsertIdempotent:
    """Verify insert() uses ON CONFLICT DO NOTHING (BP-040, F-MAJOR-003)."""

    async def test_insert_uses_pg_insert_on_conflict(self) -> None:
        """insert() must use PostgreSQL INSERT ... ON CONFLICT DO NOTHING."""
        from content_store.infrastructure.db.repositories.dedup import DedupHashRepository

        session = _mock_session()
        repo = DedupHashRepository(session)

        doc_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        await repo.insert(doc_id, "raw_sha256", "abc123def456")

        # Verify session.execute was called (not session.add)
        session.execute.assert_called_once()
        # The statement passed to execute should be a PostgreSQL INSERT with ON CONFLICT
        stmt = session.execute.call_args.args[0]
        # Compile the statement to verify it contains ON CONFLICT DO NOTHING
        compiled = stmt.compile(dialect=__import__("sqlalchemy.dialects.postgresql", fromlist=["dialect"]).dialect())
        sql_text = str(compiled)
        assert "ON CONFLICT" in sql_text
        assert "DO NOTHING" in sql_text

    async def test_insert_pair_calls_insert_twice(self) -> None:
        """insert_pair() must call insert() for both raw and normalized hashes."""
        from content_store.infrastructure.db.repositories.dedup import DedupHashRepository

        session = _mock_session()
        repo = DedupHashRepository(session)

        doc_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        await repo.insert_pair(doc_id, "raw_hash_abc", "norm_hash_xyz")

        # Two execute calls: one for raw_sha256, one for normalized_sha256
        assert session.execute.call_count == 2

    async def test_insert_pair_duplicate_is_idempotent(self) -> None:
        """Calling insert_pair twice with the same hashes must NOT raise an error.

        This is the key regression test for BP-040 / F-MAJOR-003: before the fix,
        the second call would raise UniqueViolationError because session.add()
        was used instead of ON CONFLICT DO NOTHING.
        """
        from content_store.infrastructure.db.repositories.dedup import DedupHashRepository

        session = _mock_session()
        repo = DedupHashRepository(session)

        doc_id = UUID("01234567-89ab-cdef-0123-456789abcdef")

        # First insert — should succeed
        await repo.insert_pair(doc_id, "raw_hash_abc", "norm_hash_xyz")
        assert session.execute.call_count == 2

        # Second insert with same hashes — must NOT raise
        # (ON CONFLICT DO NOTHING silently ignores duplicates)
        await repo.insert_pair(doc_id, "raw_hash_abc", "norm_hash_xyz")
        assert session.execute.call_count == 4

        # Verify all calls used execute (not add), confirming ON CONFLICT path
        session.add.assert_not_called()

    async def test_insert_does_not_use_session_add(self) -> None:
        """insert() must use session.execute(), not session.add() (BP-040)."""
        from content_store.infrastructure.db.repositories.dedup import DedupHashRepository

        session = _mock_session()
        repo = DedupHashRepository(session)

        doc_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        await repo.insert(doc_id, "raw_sha256", "some_hash")

        # Must NOT use session.add (the old broken path)
        session.add.assert_not_called()
        # Must use session.execute with the ON CONFLICT statement
        session.execute.assert_called_once()

    async def test_check_exists_returns_none_for_missing(self) -> None:
        """check_exists returns None when hash is not in the database."""
        from content_store.infrastructure.db.repositories.dedup import DedupHashRepository

        session = _mock_session()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=execute_result)

        repo = DedupHashRepository(session)
        result = await repo.check_exists("raw_sha256", "nonexistent_hash")

        assert result is None

    async def test_check_exists_returns_doc_id_for_existing(self) -> None:
        """check_exists returns the doc_id when hash exists."""
        from content_store.infrastructure.db.repositories.dedup import DedupHashRepository

        doc_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        session = _mock_session()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = doc_id
        session.execute = AsyncMock(return_value=execute_result)

        repo = DedupHashRepository(session)
        result = await repo.check_exists("raw_sha256", "existing_hash")

        assert result == doc_id
