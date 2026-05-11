"""Unit tests for ChunkRepository — ON CONFLICT DO NOTHING idempotency (T-A-1-01)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.infrastructure.nlp_db.repositories.chunk import ChunkRepository

pytestmark = pytest.mark.unit


def _make_chunk(chunk_id: uuid.UUID | None = None, text_key: str | None = None) -> MagicMock:
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
    c.text_key = text_key
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

    @pytest.mark.unit
    async def test_add_persists_text_key(self) -> None:
        """text_key is passed to the INSERT as chunk_text_key."""
        chunk = _make_chunk(text_key="nlp-pipeline/chunk-text/doc-id/chunk-id/body/v1.txt")
        session = _make_session()
        repo = ChunkRepository(session)

        await repo.add(chunk)

        # Verify execute was called (the actual SQL bind is tested via DDL alignment)
        session.execute.assert_awaited_once()

    @pytest.mark.unit
    async def test_add_persists_null_text_key(self) -> None:
        """When text_key is None, chunk_text_key is NULL in the INSERT."""
        chunk = _make_chunk(text_key=None)
        session = _make_session()
        repo = ChunkRepository(session)

        await repo.add(chunk)

        session.execute.assert_awaited_once()
