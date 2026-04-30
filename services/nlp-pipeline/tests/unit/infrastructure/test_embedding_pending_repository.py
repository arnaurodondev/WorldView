"""Unit tests for EmbeddingPendingRepository (T-D-2-06).

Tests use mocked AsyncSession to avoid DB dependencies.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.domain.models import EmbeddingPendingEntry
from nlp_pipeline.infrastructure.nlp_db.models import EmbeddingPendingModel
from nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending import (
    EmbeddingPendingRepository,
    RetryJob,
)

pytestmark = pytest.mark.unit


def _make_entry(
    *,
    doc_id: uuid.UUID | None = None,
    section_id: uuid.UUID | None = None,
    chunk_id: uuid.UUID | None = None,
    embedding_text: str = "Apple reported earnings.",
    error_detail: str = "section embedding failed",
) -> EmbeddingPendingEntry:
    return EmbeddingPendingEntry(
        doc_id=doc_id or uuid.uuid4(),
        section_id=section_id,
        chunk_id=chunk_id,
        embedding_text=embedding_text,
        error_detail=error_detail,
        created_at=datetime.now(tz=UTC),
    )


def _make_session() -> MagicMock:
    session = MagicMock()
    session.add = MagicMock()
    session.execute = AsyncMock()
    return session


class TestSaveBatch:
    def test_empty_batch_does_nothing(self) -> None:
        """save_batch with an empty list must not call session.add."""
        session = _make_session()
        repo = EmbeddingPendingRepository(session)

        import asyncio

        asyncio.run(repo.save_batch([]))

        session.add.assert_not_called()

    def test_single_entry_calls_session_add(self) -> None:
        """save_batch inserts one EmbeddingPendingModel row per entry."""
        session = _make_session()
        repo = EmbeddingPendingRepository(session)
        entry = _make_entry(embedding_text="Tesla Q1 results.")

        import asyncio

        asyncio.run(repo.save_batch([entry]))

        session.add.assert_called_once()
        added = session.add.call_args[0][0]
        assert isinstance(added, EmbeddingPendingModel)
        assert added.doc_id == entry.doc_id
        assert added.embedding_text == "Tesla Q1 results."
        assert added.retry_count == 0

    def test_batch_of_three_calls_add_three_times(self) -> None:
        """save_batch issues one session.add per entry."""
        session = _make_session()
        repo = EmbeddingPendingRepository(session)
        entries = [_make_entry() for _ in range(3)]

        import asyncio

        asyncio.run(repo.save_batch(entries))

        assert session.add.call_count == 3

    def test_section_failure_populates_section_id(self) -> None:
        """Section-level failure sets section_id and chunk_id=None."""
        section_id = uuid.uuid4()
        session = _make_session()
        repo = EmbeddingPendingRepository(session)
        entry = _make_entry(section_id=section_id, chunk_id=None)

        import asyncio

        asyncio.run(repo.save_batch([entry]))

        added = session.add.call_args[0][0]
        assert added.section_id == section_id
        assert added.chunk_id is None

    def test_chunk_failure_populates_chunk_id(self) -> None:
        """Chunk-level failure sets chunk_id and section_id."""
        chunk_id = uuid.uuid4()
        section_id = uuid.uuid4()
        session = _make_session()
        repo = EmbeddingPendingRepository(session)
        entry = _make_entry(section_id=section_id, chunk_id=chunk_id)

        import asyncio

        asyncio.run(repo.save_batch([entry]))

        added = session.add.call_args[0][0]
        assert added.chunk_id == chunk_id
        assert added.section_id == section_id


class TestClaimBatch:
    @pytest.mark.asyncio
    async def test_returns_retry_jobs_from_rows(self) -> None:
        """claim_batch converts DB rows into RetryJob instances."""
        doc_id = uuid.uuid4()
        section_id = uuid.uuid4()
        pending_id = uuid.uuid4()
        session = _make_session()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (str(pending_id), str(doc_id), str(section_id), None, "Some text", 1),
        ]
        session.execute = AsyncMock(return_value=mock_result)

        repo = EmbeddingPendingRepository(session)
        jobs = await repo.claim_batch(batch_size=8, max_retries=5)

        assert len(jobs) == 1
        assert isinstance(jobs[0], RetryJob)
        assert jobs[0].pending_id == pending_id
        assert jobs[0].doc_id == doc_id
        assert jobs[0].section_id == section_id
        assert jobs[0].chunk_id is None
        assert jobs[0].embedding_text == "Some text"
        assert jobs[0].retry_count == 1

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_list(self) -> None:
        session = _make_session()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        session.execute = AsyncMock(return_value=mock_result)

        repo = EmbeddingPendingRepository(session)
        jobs = await repo.claim_batch()
        assert jobs == []


class TestMarkSuccess:
    @pytest.mark.asyncio
    async def test_executes_delete_with_correct_id(self) -> None:
        """mark_success must issue a DELETE for the given pending_id."""
        pending_id = uuid.uuid4()
        session = _make_session()
        session.execute = AsyncMock(return_value=MagicMock())
        repo = EmbeddingPendingRepository(session)

        await repo.mark_success(pending_id)

        session.execute.assert_called_once()
        call_args = session.execute.call_args
        # The text clause should contain DELETE
        sql_text = str(call_args[0][0])
        assert "DELETE" in sql_text.upper()
        params = call_args[0][1]
        assert params["pending_id"] == str(pending_id)


class TestMarkFailure:
    @pytest.mark.asyncio
    async def test_executes_update_with_backoff(self) -> None:
        """mark_failure must issue an UPDATE with retry_count+1 and new next_retry_at."""
        pending_id = uuid.uuid4()
        session = _make_session()
        session.execute = AsyncMock(return_value=MagicMock())
        repo = EmbeddingPendingRepository(session)

        await repo.mark_failure(pending_id, backoff_seconds=120.0)

        session.execute.assert_called_once()
        call_args = session.execute.call_args
        sql_text = str(call_args[0][0])
        assert "UPDATE" in sql_text.upper()
        params = call_args[0][1]
        assert params["pending_id"] == str(pending_id)
        assert params["backoff"] == 120.0

    @pytest.mark.asyncio
    async def test_mark_failure_stamps_last_attempted_at(self) -> None:
        """PLAN-0057 Wave E-4: mark_failure must also write last_attempted_at = now()."""
        pending_id = uuid.uuid4()
        session = _make_session()
        session.execute = AsyncMock(return_value=MagicMock())
        repo = EmbeddingPendingRepository(session)

        await repo.mark_failure(pending_id, backoff_seconds=60.0)

        sql_text = str(session.execute.call_args[0][0])
        # The column lives behind a SET clause; presence is what we verify since
        # a missing assignment was the regression that the migration guards against.
        assert "last_attempted_at" in sql_text
        assert "now()" in sql_text


class TestCountAbandoned:
    @pytest.mark.asyncio
    async def test_returns_count_of_rows_at_or_above_max_retries(self) -> None:
        """count_abandoned must filter retry_count >= max_retries and return scalar."""
        session = _make_session()
        scalar_result = MagicMock()
        scalar_result.scalar_one.return_value = 7
        session.execute = AsyncMock(return_value=scalar_result)
        repo = EmbeddingPendingRepository(session)

        count = await repo.count_abandoned(max_retries=5)

        assert count == 7
        session.execute.assert_called_once()
        sql_text = str(session.execute.call_args[0][0])
        assert "COUNT(*)" in sql_text.upper()
        assert "retry_count >= :max_retries" in sql_text
        assert session.execute.call_args[0][1] == {"max_retries": 5}

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_abandoned_rows(self) -> None:
        session = _make_session()
        scalar_result = MagicMock()
        scalar_result.scalar_one.return_value = 0
        session.execute = AsyncMock(return_value=scalar_result)
        repo = EmbeddingPendingRepository(session)

        count = await repo.count_abandoned()

        assert count == 0
