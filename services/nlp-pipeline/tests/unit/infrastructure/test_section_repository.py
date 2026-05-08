"""Unit tests for SectionRepository — ON CONFLICT DO NOTHING idempotency (T-A-1-01)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.infrastructure.nlp_db.repositories.section import SectionRepository

pytestmark = pytest.mark.unit


def _make_section(section_id: uuid.UUID | None = None, doc_id: uuid.UUID | None = None) -> MagicMock:
    s = MagicMock()
    s.section_id = section_id or uuid.uuid4()
    s.doc_id = doc_id or uuid.uuid4()
    s.section_index = 0
    s.section_type = "body"
    s.title = None
    s.speaker = None
    s.char_start = 0
    s.char_end = 100
    s.token_count = 50
    return s


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


class TestSectionRepository:
    @pytest.mark.unit
    async def test_add_uses_execute_not_session_add(self) -> None:
        """add() must call session.execute(), never session.add() (regression guard)."""
        session = _make_session()
        repo = SectionRepository(session)

        await repo.add(_make_section())

        session.execute.assert_awaited_once()
        session.add.assert_not_called()

    @pytest.mark.unit
    async def test_add_section_idempotent(self) -> None:
        """Calling add() twice with the same section_id does not raise."""
        section_id = uuid.uuid4()
        section = _make_section(section_id=section_id)
        session = _make_session()
        repo = SectionRepository(session)

        # Neither call should raise; session.execute returns the mock's default (no conflict)
        await repo.add(section)
        await repo.add(section)

        assert session.execute.await_count == 2

    @pytest.mark.unit
    async def test_add_batch_partial_redelivery(self) -> None:
        """add_batch() calls add() once per section, regardless of existing rows."""
        sections = [_make_section() for _ in range(3)]
        session = _make_session()
        repo = SectionRepository(session)

        await repo.add_batch(sections)

        # One session.execute call per section
        assert session.execute.await_count == 3
