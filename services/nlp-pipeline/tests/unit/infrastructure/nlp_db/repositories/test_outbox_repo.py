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


# ── BUG-3: failed-record retry reachability + cap ──────────────────────────────
#
# Root cause: mark_failed set status='failed' while claim_batch only selected
# status='pending', so a record that failed ONCE was permanently stranded (the
# 5-attempt retry + the DLQ-move were unreachable dead code → silent loss).
# These tests prove (a) a failed record is re-claimable (retry REACHABLE) and
# (b) it flips to terminal 'failed' only at MAX_DISPATCH_ATTEMPTS (CAPPED).


def _compile(stmt: Any) -> str:
    """Render a SQLAlchemy statement to its postgres SQL text for inspection.

    ``literal_binds=True`` inlines the CASE branch values ('pending'/'failed') and
    the cap so the assertions can see them (otherwise they render as bind params).
    """
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def _make_session_returning(scalar_value: int) -> MagicMock:
    """Session whose SELECT execute() returns a result with ``scalar_one``.

    ``mark_failed`` issues an UPDATE then a SELECT to read back the new
    retry_count; the SELECT result must expose ``scalar_one()``.
    """
    executed: list[Any] = []

    async def _fake_execute(stmt: Any, *args: Any, **kwargs: Any) -> MagicMock:
        executed.append(stmt)
        result = MagicMock()
        result.scalar_one = MagicMock(return_value=scalar_value)
        return result

    session = MagicMock()
    session.execute = _fake_execute
    session._executed = executed
    return session


@pytest.mark.asyncio
async def test_claim_batch_reclaims_failed_pending_after_backoff() -> None:
    """claim_batch must re-select failed-but-pending rows (BUG-3 retry REACHABLE).

    The WHERE clause must keep status='pending' AND admit rows whose failed_at is
    NULL (fresh) OR older than the backoff window — otherwise a retried record is
    never re-claimed.
    """
    session, executed = _make_session()
    repo = OutboxRepository(session)

    await repo.claim_batch(batch_size=10)

    sql = _compile(executed[0])
    assert "status =" in sql
    # The backoff predicate: failed_at IS NULL OR failed_at <= cutoff.
    assert "failed_at IS NULL" in sql
    assert "failed_at <=" in sql
    assert " OR " in sql
    # Concurrency-safe claim is preserved.
    assert "FOR UPDATE" in sql
    assert "SKIP LOCKED" in sql


@pytest.mark.asyncio
async def test_mark_failed_stays_pending_below_cap() -> None:
    """Below the cap, mark_failed keeps the record 'pending' so it is retried.

    The UPDATE must use a server-side CASE (race-free under SKIP LOCKED) that
    only yields the terminal 'failed' status when retry_count+1 >= MAX.
    """
    session = _make_session_returning(scalar_value=1)
    repo = OutboxRepository(session)

    returned = await repo.mark_failed(_FIXED_ID)

    update_sql = _compile(session._executed[0]).upper()
    assert "CASE" in update_sql, "terminal/retry decision must be a server-side CASE"
    assert "PENDING" in update_sql, "below-cap path must keep the record pending"
    assert "FAILED" in update_sql, "CASE must flip to terminal failed at the cap"
    # Authoritative post-increment count is returned for the dispatcher's DLQ call.
    assert returned == 1


@pytest.mark.asyncio
async def test_mark_failed_returns_post_increment_count_at_cap() -> None:
    """At the cap, mark_failed returns the authoritative count (== MAX).

    The dispatcher uses THIS return (not the stale claim-time retry_count) to
    decide the DLQ-move, so it must reflect the post-increment value.
    """
    from nlp_pipeline.infrastructure.nlp_db.repositories.outbox import MAX_DISPATCH_ATTEMPTS

    session = _make_session_returning(scalar_value=MAX_DISPATCH_ATTEMPTS)
    repo = OutboxRepository(session)

    returned = await repo.mark_failed(_FIXED_ID)

    assert returned == MAX_DISPATCH_ATTEMPTS
    # mark_failed must issue UPDATE then a read-back SELECT (2 statements).
    assert len(session._executed) == 2
