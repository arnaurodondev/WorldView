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


# ── Stage C: DuplicateClusterRepository ──────────────────────────────────────


class TestDuplicateClusterRepository:
    """Verify DuplicateClusterRepository canonical-pair ordering and idempotency."""

    async def test_insert_pair_uses_on_conflict_do_nothing(self) -> None:
        """insert_pair() must use ON CONFLICT DO NOTHING for idempotency (BP-040)."""
        from content_store.infrastructure.db.repositories.dedup import DuplicateClusterRepository

        session = _mock_session()
        repo = DuplicateClusterRepository(session)

        doc_a = UUID("00000000-0000-0000-0000-000000000001")
        doc_b = UUID("00000000-0000-0000-0000-000000000002")
        await repo.insert_pair(doc_a, doc_b, similarity=0.85)

        session.execute.assert_called_once()
        stmt = session.execute.call_args.args[0]
        compiled = stmt.compile(dialect=__import__("sqlalchemy.dialects.postgresql", fromlist=["dialect"]).dialect())
        assert "ON CONFLICT" in str(compiled)

    async def test_insert_pair_canonical_ordering(self) -> None:
        """Pairs are always stored with the lexicographically smaller UUID as primary.

        This prevents (A, B) and (B, A) duplicate rows when both docs are
        processed.
        """
        from content_store.infrastructure.db.repositories.dedup import DuplicateClusterRepository

        session = _mock_session()
        repo = DuplicateClusterRepository(session)

        # B > A lexicographically — passing (B, A) should still produce (A, B).
        doc_a = UUID("00000000-0000-0000-0000-000000000001")
        doc_b = UUID("00000000-0000-0000-0000-000000000002")

        await repo.insert_pair(doc_b, doc_a, similarity=0.75)

        stmt = session.execute.call_args.args[0]
        # Inspect the VALUES dict to confirm ordering was normalised.
        # PostgreSQL INSERT statement stores values in the compiled params.
        compiled = stmt.compile(dialect=__import__("sqlalchemy.dialects.postgresql", fromlist=["dialect"]).dialect())
        params = compiled.params
        # After canonical ordering, primary_doc_id should be doc_a (smaller).
        assert params["primary_doc_id"] == doc_a
        assert params["duplicate_doc_id"] == doc_b


# ── Stage C: _estimate_jaccard ────────────────────────────────────────────────


class TestEstimateJaccard:
    """Unit tests for the MinHash Jaccard estimator."""

    def test_identical_signatures(self) -> None:
        """Identical signatures should give similarity 1.0."""
        from content_store.infrastructure.messaging.consumers.stored_article_dedup_consumer import (
            _estimate_jaccard,
        )

        sig = list(range(128))
        assert _estimate_jaccard(sig, sig) == 1.0

    def test_completely_different_signatures(self) -> None:
        """Non-overlapping signatures should give similarity 0.0."""
        from content_store.infrastructure.messaging.consumers.stored_article_dedup_consumer import (
            _estimate_jaccard,
        )

        sig_a = [0] * 128
        sig_b = [1] * 128
        assert _estimate_jaccard(sig_a, sig_b) == 0.0

    def test_partial_overlap(self) -> None:
        """Half-matching signature gives ~0.5 similarity."""
        from content_store.infrastructure.messaging.consumers.stored_article_dedup_consumer import (
            _estimate_jaccard,
        )

        sig_a = [0] * 64 + [1] * 64
        sig_b = [0] * 64 + [2] * 64  # First 64 match, last 64 differ
        result = _estimate_jaccard(sig_a, sig_b)
        assert abs(result - 0.5) < 1e-6

    def test_empty_signatures_return_zero(self) -> None:
        """Empty signatures should return 0.0, not raise."""
        from content_store.infrastructure.messaging.consumers.stored_article_dedup_consumer import (
            _estimate_jaccard,
        )

        assert _estimate_jaccard([], []) == 0.0
        assert _estimate_jaccard([], [1, 2, 3]) == 0.0

    def test_mismatched_length_returns_zero(self) -> None:
        """Signatures of different length must return 0.0 (safety guard)."""
        from content_store.infrastructure.messaging.consumers.stored_article_dedup_consumer import (
            _estimate_jaccard,
        )

        assert _estimate_jaccard([1, 2, 3], [1, 2]) == 0.0


# ── get_cluster_sizes: regression for asyncpg "function min(uuid) does not exist" ──


class TestGetClusterSizes:
    """Regression tests for DuplicateClusterRepository.get_cluster_sizes.

    BUG: Previously executed a bare ``union_all(...)`` selectable, which made
    SQLAlchemy wrap the labeled UUID column with an implicit ``min(doc_id)``
    aggregate. Postgres has no ``min(uuid)`` function → the endpoint
    ``POST /api/v1/documents/cluster-sizes`` returned 500 every call with
    ``asyncpg.exceptions.UndefinedFunctionError: function min(uuid) does not exist``.

    Fix: wrap the union_all in an explicit ``.subquery()`` and aggregate with
    ``func.count()`` + ``group_by(doc_id)`` in an outer SELECT.
    """

    async def test_get_cluster_sizes_returns_empty_for_no_doc_ids(self) -> None:
        from content_store.infrastructure.db.repositories.dedup import DuplicateClusterRepository

        session = _mock_session()
        repo = DuplicateClusterRepository(session)
        assert await repo.get_cluster_sizes([]) == {}
        # No DB roundtrip for empty input.
        session.execute.assert_not_called()

    async def test_get_cluster_sizes_emits_no_min_uuid_call(self) -> None:
        """The compiled SQL MUST NOT contain ``min(...)`` (regression for min(uuid) error).

        Compiling against the PostgreSQL dialect mimics what asyncpg would
        receive at runtime.
        """
        from content_store.infrastructure.db.repositories.dedup import DuplicateClusterRepository
        from sqlalchemy.dialects import postgresql as pg_dialect

        session = _mock_session()
        # Empty result is fine — we only need to capture the compiled statement.
        execute_result = MagicMock()
        execute_result.__iter__ = MagicMock(return_value=iter([]))
        session.execute = AsyncMock(return_value=execute_result)

        repo = DuplicateClusterRepository(session)
        doc_ids = [
            UUID("00000000-0000-0000-0000-000000000001"),
            UUID("00000000-0000-0000-0000-000000000002"),
        ]
        sizes = await repo.get_cluster_sizes(doc_ids)

        # Default cluster_size for docs with no duplicates is 1 (just self).
        assert sizes == {doc_ids[0]: 1, doc_ids[1]: 1}

        session.execute.assert_called_once()
        stmt = session.execute.call_args.args[0]
        compiled = stmt.compile(
            dialect=pg_dialect.dialect(),
            compile_kwargs={"literal_binds": True},
        )
        sql_text = str(compiled).lower()

        # Regression assertions: no min(uuid) wrap; must use count + GROUP BY
        # over a subquery of the union_all.
        assert (
            "min(" not in sql_text
        ), f"SQL must not contain min() — would trigger min(uuid) error on Postgres.\nSQL:\n{sql_text}"
        assert "count(" in sql_text
        assert "union all" in sql_text
        assert "group by" in sql_text

    async def test_get_cluster_sizes_aggregates_counts_from_db(self) -> None:
        """Sizes come from the DB row counts (cnt + 1 for self)."""
        from content_store.infrastructure.db.repositories.dedup import DuplicateClusterRepository

        doc_a = UUID("00000000-0000-0000-0000-000000000001")
        doc_b = UUID("00000000-0000-0000-0000-000000000002")
        doc_c = UUID("00000000-0000-0000-0000-000000000003")

        # Simulate the DB returning: doc_a appears in 2 pair-rows, doc_b in 1,
        # doc_c not in the result set at all (so it stays at size 1).
        rows = [
            MagicMock(doc_id=doc_a, cnt=2),
            MagicMock(doc_id=doc_b, cnt=1),
        ]
        execute_result = MagicMock()
        execute_result.__iter__ = MagicMock(return_value=iter(rows))

        session = _mock_session()
        session.execute = AsyncMock(return_value=execute_result)

        repo = DuplicateClusterRepository(session)
        sizes = await repo.get_cluster_sizes([doc_a, doc_b, doc_c])

        assert sizes == {doc_a: 3, doc_b: 2, doc_c: 1}
