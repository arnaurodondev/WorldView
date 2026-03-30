"""Unit tests for ChunkRepository — ON CONFLICT DO NOTHING idempotency (T-A-1-01)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.infrastructure.nlp_db.repositories.chunk import ChunkRepository


def _make_chunk(chunk_id: uuid.UUID | None = None) -> MagicMock:
    c = MagicMock()
    c.chunk_id = chunk_id or uuid.uuid4()
    c.doc_id = uuid.uuid4()
    c.section_id = uuid.uuid4()
    c.chunk_index = 0
    c.char_start = 0
    c.char_end = 80
    c.token_count = 40
    c.sentence_start_idx = None
    c.sentence_end_idx = None
    c.speaker = None
    c.heading_path = None
    return c


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


class TestChunkRepository:
    @pytest.mark.unit
    async def test_add_uses_execute_not_session_add(self) -> None:
        """add() must call session.execute(), never session.add() (regression guard)."""
        session = _make_session()
        repo = ChunkRepository(session)

        await repo.add(_make_chunk())

        session.execute.assert_awaited_once()
        session.add.assert_not_called()

    @pytest.mark.unit
    async def test_add_chunk_idempotent(self) -> None:
        """Calling add() twice with the same chunk_id does not raise."""
        chunk_id = uuid.uuid4()
        chunk = _make_chunk(chunk_id=chunk_id)
        session = _make_session()
        repo = ChunkRepository(session)

        await repo.add(chunk)
        await repo.add(chunk)

        assert session.execute.await_count == 2
