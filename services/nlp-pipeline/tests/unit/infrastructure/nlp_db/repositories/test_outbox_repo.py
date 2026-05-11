"""Tests for OutboxRepository ON CONFLICT DO NOTHING idempotency — F-011.

PLAN-0084 B-3 (T-B-3-02): OutboxRepository.add() uses pg_insert with
on_conflict_do_nothing so that deterministic event_ids are silently swallowed
on Kafka replay. These tests verify the insert uses the correct SQLAlchemy dialect.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from nlp_pipeline.infrastructure.nlp_db.repositories.outbox import OutboxRepository
from sqlalchemy.dialects import postgresql

pytestmark = pytest.mark.unit

_FIXED_ID = UUID("12345678-0000-0000-0000-000000000001")
_TOPIC = "nlp.article.enriched.v1"
_PARTITION_KEY = "doc-123"
_PAYLOAD = b"{}"


def _make_session() -> tuple[MagicMock, list[Any]]:
    """Return (session mock, list of executed statements)."""
    executed: list[Any] = []

    async def _fake_execute(stmt: Any, *args: Any, **kwargs: Any) -> MagicMock:
        executed.append(stmt)
        return MagicMock()

    session = MagicMock()
    session.execute = _fake_execute
    return session, executed


@pytest.mark.asyncio
async def test_outbox_add_uses_on_conflict_do_nothing() -> None:
    """add() must use pg_insert with on_conflict_do_nothing to guard replays (F-011)."""
    from sqlalchemy.dialects.postgresql import Insert as PgInsert

    session, executed = _make_session()
    repo = OutboxRepository(session)

    await repo.add(_TOPIC, _PARTITION_KEY, _PAYLOAD)

    assert len(executed) == 1
    stmt = executed[0]
    assert isinstance(stmt, PgInsert), "add() must use pg_insert (dialect-level ON CONFLICT DO NOTHING)"
    compiled = stmt.compile(dialect=postgresql.dialect())
    sql_text = str(compiled)
    assert "ON CONFLICT" in sql_text
    assert "DO NOTHING" in sql_text


@pytest.mark.asyncio
async def test_outbox_add_passes_deterministic_event_id() -> None:
    """When event_id kwarg is provided it must appear in the INSERT values."""
    session, executed = _make_session()
    repo = OutboxRepository(session)

    await repo.add(_TOPIC, _PARTITION_KEY, _PAYLOAD, event_id=_FIXED_ID)

    vals = {col.key: bp.value for col, bp in executed[0]._values.items()}
    assert vals["event_id"] == _FIXED_ID, "Deterministic event_id must be threaded through to pg_insert"


@pytest.mark.asyncio
async def test_outbox_add_generates_uuid_when_event_id_none() -> None:
    """When event_id is None, a new UUID7 must be generated and returned."""
    session, executed = _make_session()
    repo = OutboxRepository(session)

    returned_id = await repo.add(_TOPIC, _PARTITION_KEY, _PAYLOAD, event_id=None)

    assert returned_id is not None
    assert isinstance(returned_id, UUID)
    vals = {col.key: bp.value for col, bp in executed[0]._values.items()}
    assert vals["event_id"] == returned_id, "Generated event_id must match the returned value"


@pytest.mark.asyncio
async def test_outbox_add_sets_pending_status() -> None:
    """Newly inserted outbox rows must have status='pending'."""
    session, executed = _make_session()
    repo = OutboxRepository(session)

    await repo.add(_TOPIC, _PARTITION_KEY, _PAYLOAD)

    vals = {col.key: bp.value for col, bp in executed[0]._values.items()}
    assert vals["status"] == "pending"
