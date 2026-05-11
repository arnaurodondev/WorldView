"""Unit tests for DocumentDeletionConsumer (PLAN-0086 Wave F-1, T-F-1-01).

Tests verify:
1. DELETE statements fire in the correct order (entity_mentions → sections → chunks)
   to avoid FK violations.
2. The consumer is idempotent — re-delivering the same event does not raise an
   error (the DELETE WHERE clauses return zero rows but succeed cleanly).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.infrastructure.messaging.consumers.document_deletion_consumer import (
    DocumentDeletionConsumer,
)

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_consumer(mock_session: AsyncMock) -> DocumentDeletionConsumer:
    """Build a DocumentDeletionConsumer with a mocked session factory."""

    @asynccontextmanager  # type: ignore[misc]
    async def _factory():
        yield mock_session

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="s6-document-deletion",
        topics=["content.document.deleted.v1"],
    )
    consumer = DocumentDeletionConsumer(
        config=config,
        nlp_session_factory=_factory,  # type: ignore[arg-type]
        valkey_client=None,  # at-least-once mode; deletes are idempotent
    )
    return consumer


def _make_session() -> AsyncMock:
    """Build a minimal AsyncMock session that tracks execute() call order."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())
    session.commit = AsyncMock()
    return session


def _make_event(
    doc_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "content.document.deleted",
        "schema_version": 1,
        "occurred_at": "2026-05-08T10:00:00+00:00",
        "doc_id": str(doc_id or uuid.uuid4()),
        "tenant_id": str(tenant_id or uuid.uuid4()),
    }


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_document_deletion_consumer_deletes_in_order() -> None:
    """DELETE order must be entity_mentions → sections → chunks.

    This order avoids FK violations: entity_mentions may reference sections
    and chunks (via section_id / chunk_id), and chunk_embeddings cascade from
    chunks (ON DELETE CASCADE).  Deleting mentions first ensures no dangling
    FK references remain when sections and chunks are deleted.
    """
    doc_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    session = _make_session()
    consumer = _make_consumer(session)

    event = _make_event(doc_id=doc_id, tenant_id=tenant_id)
    await consumer.process_message(key=None, value=event, headers={})

    # Verify execute was called exactly 3 times in the expected order.
    assert session.execute.call_count == 3, f"Expected 3 DELETE execute() calls; got {session.execute.call_count}"

    # Extract the raw SQL string from each call's first positional arg.
    call_sqls = []
    for c in session.execute.call_args_list:
        # First positional arg to execute() is the `text(...)` expression.
        sql_clause = c.args[0]
        call_sqls.append(str(sql_clause))

    assert "entity_mentions" in call_sqls[0], f"Expected entity_mentions DELETE first; got: {call_sqls[0]!r}"
    assert "sections" in call_sqls[1], f"Expected sections DELETE second; got: {call_sqls[1]!r}"
    assert "chunks" in call_sqls[2], f"Expected chunks DELETE third; got: {call_sqls[2]!r}"

    # Commit must be called exactly once after all three deletes.
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_document_deletion_consumer_idempotent() -> None:
    """Delivering the same deletion event twice must not raise any error.

    DELETE WHERE clauses return zero rows on the second delivery (already
    deleted on first delivery) — this is a no-op, not an error.
    The consumer commits successfully in both cases.
    """
    doc_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    session = _make_session()
    consumer = _make_consumer(session)

    event = _make_event(doc_id=doc_id, tenant_id=tenant_id)

    # First delivery — artifacts exist and are deleted.
    await consumer.process_message(key=None, value=event, headers={})
    # Second delivery — artifacts no longer exist; DELETE returns zero rows.
    await consumer.process_message(key=None, value=event, headers={})

    # No exception should have been raised on either call.
    # Session was used twice — factory creates a new session per context manager.
    # execute called 3 times per delivery = 6 total.
    assert (
        session.execute.call_count == 6
    ), f"Expected 6 execute() calls (3 per delivery x 2); got {session.execute.call_count}"
