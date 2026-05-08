"""Unit tests for EntityMentionRepository new re-resolution methods (PLAN-0033 T-C-1-01).

Tests:
  - get_unresolved_batch()        — SELECT with FOR UPDATE SKIP LOCKED
  - update_resolution_outcome()   — UPDATE outcome + processed_at
  - mark_batch_escalated()        — bulk UPDATE to 'escalated'
  - recover_stale_escalated()     — resets stuck 'escalated' rows
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention import (
    EntityMentionRepository,
)

pytestmark = pytest.mark.unit


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


def _make_result(fetchall_rows: list[object], scalar_rows: list[object] | None = None) -> MagicMock:
    """Build a mock CursorResult with .fetchall() and .scalars().all().

    get_unresolved_batch() calls execute() TWICE:
      1st: raw SQL → result.fetchall() for mention IDs
      2nd: ORM SELECT → result.scalars().all() for ORM objects
    recover_stale_escalated() calls result.fetchall() and takes len().
    """
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=scalar_rows if scalar_rows is not None else fetchall_rows)
    result = MagicMock()
    result.fetchall = MagicMock(return_value=fetchall_rows)
    result.scalars = MagicMock(return_value=scalars)
    return result


@pytest.mark.unit
class TestGetUnresolvedBatch:
    async def test_calls_execute_when_empty(self) -> None:
        """get_unresolved_batch() with no unresolved rows returns [] with one execute()."""
        session = _make_session()
        # First call: fetchall() → [] means no rows to load → early return
        result_empty = _make_result(fetchall_rows=[])
        session.execute = AsyncMock(return_value=result_empty)
        repo = EntityMentionRepository(session)

        rows = await repo.get_unresolved_batch(batch_size=10)

        # One execute() for the raw SQL query; early return means no second execute()
        assert session.execute.await_count >= 1
        assert rows == []

    async def test_lock_false_no_error(self) -> None:
        """lock=False should not raise."""
        session = _make_session()
        result = _make_result(fetchall_rows=[])
        session.execute = AsyncMock(return_value=result)
        repo = EntityMentionRepository(session)

        rows = await repo.get_unresolved_batch(batch_size=10, lock=False)
        assert rows == []


@pytest.mark.unit
class TestGetUnresolvedBatchWithContext:
    """PLAN-0057 T-B-3-01: new variant returns mention + doc/section context."""

    async def test_empty_batch_returns_empty_list(self) -> None:
        """No unresolved rows → empty list, no second/third query issued."""
        session = _make_session()
        result_empty = _make_result(fetchall_rows=[])
        session.execute = AsyncMock(return_value=result_empty)
        repo = EntityMentionRepository(session)

        rows = await repo.get_unresolved_batch_with_context(batch_size=5)

        assert rows == []
        # Only the locking SELECT runs; ORM hydrate + context JOIN are skipped.
        assert session.execute.await_count == 1

    async def test_non_empty_batch_returns_dataclass_with_context(self) -> None:
        """When mentions are returned, each row is wrapped with a context_sentence.

        We mock three execute() calls in sequence:
          1. lock SELECT  → returns one mention_id row
          2. ORM hydrate  → returns one EntityMentionModel-like mock
          3. context JOIN → returns one (mention_id, doc_title, section_title) row
        """
        session = _make_session()
        mention_id = uuid.uuid4()

        # Result #1: lock SELECT → fetchall returns [(mention_id,)]
        lock_row = MagicMock()
        lock_row.__getitem__ = MagicMock(return_value=mention_id)
        result_lock = _make_result(fetchall_rows=[lock_row])

        # Result #2: ORM hydrate → scalars().all() returns one mock with .mention_id
        orm_row = MagicMock()
        orm_row.mention_id = mention_id
        result_orm = _make_result(fetchall_rows=[], scalar_rows=[orm_row])

        # Result #3: context JOIN → fetchall returns one row with doc_title + section_title
        ctx_row = MagicMock()
        ctx_row.mention_id = mention_id
        ctx_row.doc_title = "Apple Q3 Earnings Release"
        ctx_row.section_title = "Risk Factors"
        result_ctx = _make_result(fetchall_rows=[ctx_row])

        session.execute = AsyncMock(side_effect=[result_lock, result_orm, result_ctx])
        repo = EntityMentionRepository(session)

        rows = await repo.get_unresolved_batch_with_context(batch_size=10, lock=False)

        assert len(rows) == 1
        assert rows[0].mention is orm_row
        # Both titles are concatenated with " | " separator (in order).
        assert rows[0].context_sentence == "Apple Q3 Earnings Release | Risk Factors"
        assert session.execute.await_count == 3

    async def test_missing_titles_yields_none_context(self) -> None:
        """When both doc and section titles are NULL, context_sentence is None."""
        session = _make_session()
        mention_id = uuid.uuid4()

        lock_row = MagicMock()
        lock_row.__getitem__ = MagicMock(return_value=mention_id)
        result_lock = _make_result(fetchall_rows=[lock_row])

        orm_row = MagicMock()
        orm_row.mention_id = mention_id
        result_orm = _make_result(fetchall_rows=[], scalar_rows=[orm_row])

        ctx_row = MagicMock()
        ctx_row.mention_id = mention_id
        ctx_row.doc_title = None
        ctx_row.section_title = None
        result_ctx = _make_result(fetchall_rows=[ctx_row])

        session.execute = AsyncMock(side_effect=[result_lock, result_orm, result_ctx])
        repo = EntityMentionRepository(session)

        rows = await repo.get_unresolved_batch_with_context(batch_size=10, lock=False)

        assert len(rows) == 1
        # No context available → None (not empty string) so the worker can
        # substitute its own "(no surrounding context available)" placeholder.
        assert rows[0].context_sentence is None


@pytest.mark.unit
class TestUpdateResolutionOutcome:
    async def test_calls_execute_with_mention_id(self) -> None:
        """update_resolution_outcome() must execute an UPDATE for the given mention_id."""
        session = _make_session()
        repo = EntityMentionRepository(session)
        mention_id = uuid.uuid4()

        await repo.update_resolution_outcome(mention_id, "noise", noise_reason="Not a real entity")

        session.execute.assert_awaited_once()

    async def test_no_noise_reason_ok(self) -> None:
        """noise_reason=None should not raise."""
        session = _make_session()
        repo = EntityMentionRepository(session)

        await repo.update_resolution_outcome(uuid.uuid4(), "entity_created")

        session.execute.assert_awaited_once()


@pytest.mark.unit
class TestMarkBatchEscalated:
    async def test_empty_batch_skips_execute(self) -> None:
        """An empty mention_ids list should not call session.execute()."""
        session = _make_session()
        repo = EntityMentionRepository(session)

        await repo.mark_batch_escalated([])

        session.execute.assert_not_awaited()

    async def test_non_empty_batch_calls_execute(self) -> None:
        """A non-empty list should call session.execute() exactly once."""
        session = _make_session()
        repo = EntityMentionRepository(session)
        ids = [uuid.uuid4(), uuid.uuid4()]

        await repo.mark_batch_escalated(ids)

        session.execute.assert_awaited_once()


@pytest.mark.unit
class TestRecoverStaleEscalated:
    async def test_calls_execute(self) -> None:
        """recover_stale_escalated() must call session.execute()."""
        session = _make_session()
        # recover_stale_escalated() calls result.fetchall() and takes len()
        result = _make_result(fetchall_rows=[])
        session.execute = AsyncMock(return_value=result)
        repo = EntityMentionRepository(session)

        count = await repo.recover_stale_escalated(stale_minutes=30)

        session.execute.assert_awaited_once()
        assert count == 0

    async def test_custom_stale_minutes(self) -> None:
        """Custom stale_minutes should be accepted without error."""
        session = _make_session()
        result = _make_result(fetchall_rows=[MagicMock(), MagicMock()])  # 2 rows reset
        session.execute = AsyncMock(return_value=result)
        repo = EntityMentionRepository(session)

        count = await repo.recover_stale_escalated(stale_minutes=60)

        session.execute.assert_awaited_once()
        assert count == 2
