"""Unit tests for DocumentReadyConsumer (PLAN-0086 Wave F-1, T-F-1-02).

Tests verify:
1. set_ready() is called with the correct arguments extracted from the event payload.
2. Re-delivering the same event calls set_ready() again (UPDATE is idempotent).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_event(
    doc_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    chunk_count: int = 5,
    word_count: int = 1000,
) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "nlp.document.ready",
        "schema_version": 1,
        "occurred_at": "2026-05-08T10:00:00+00:00",
        "doc_id": str(doc_id or uuid.uuid4()),
        "tenant_id": str(tenant_id or uuid.uuid4()),
        "chunk_count": chunk_count,
        "word_count": word_count,
    }


def _make_mock_upload_repo() -> AsyncMock:
    """Return an AsyncMock that behaves like TenantDocumentUploadRepository."""
    repo = AsyncMock()
    repo.set_ready = AsyncMock(return_value=None)
    return repo


def _make_consumer(mock_session: AsyncMock):
    """Build a DocumentReadyConsumer with an injected session mock."""
    from content_ingestion.infrastructure.messaging.consumers.document_ready_consumer import (
        DocumentReadyConsumer,
    )

    @asynccontextmanager  # type: ignore[misc]
    async def _factory():
        yield mock_session

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="s4-document-ready",
        topics=["nlp.document.ready.v1"],
    )
    consumer = DocumentReadyConsumer(
        config=config,
        session_factory=_factory,  # type: ignore[arg-type]
        valkey_client=None,  # at-least-once mode; set_ready is idempotent
    )
    return consumer


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_document_ready_consumer_calls_set_ready() -> None:
    """set_ready() must be called with (doc_id, tenant_id, chunk_count, word_count).

    The consumer extracts these four values from the Kafka event payload and
    passes them directly to TenantDocumentUploadRepository.set_ready().
    """
    doc_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    chunk_count = 7
    word_count = 1234

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_upload_repo = _make_mock_upload_repo()
    consumer = _make_consumer(mock_session)

    event = _make_event(
        doc_id=doc_id,
        tenant_id=tenant_id,
        chunk_count=chunk_count,
        word_count=word_count,
    )

    # Patch TenantDocumentUploadRepository at the source module where the
    # lazy import resolves it inside process_message.
    with patch(
        "content_ingestion.infrastructure.db.repositories.tenant_upload" ".TenantDocumentUploadRepository",
        return_value=mock_upload_repo,
    ):
        await consumer.process_message(key=None, value=event, headers={})

    mock_upload_repo.set_ready.assert_called_once_with(
        doc_id=doc_id,
        tenant_id=tenant_id,
        chunk_count=chunk_count,
        word_count=word_count,
    )
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_document_ready_consumer_idempotent() -> None:
    """Delivering the same event twice must call set_ready() twice without error.

    set_ready() is a WHERE (doc_id, tenant_id) UPDATE — re-running it with
    the same values is safe (produces the same final state).  The consumer
    must not attempt to deduplicate at the application level; idempotency is
    provided by the DB UPDATE semantics.
    """
    doc_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    chunk_count = 3
    word_count = 500

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_upload_repo = _make_mock_upload_repo()
    consumer = _make_consumer(mock_session)

    event = _make_event(
        doc_id=doc_id,
        tenant_id=tenant_id,
        chunk_count=chunk_count,
        word_count=word_count,
    )

    with patch(
        "content_ingestion.infrastructure.db.repositories.tenant_upload" ".TenantDocumentUploadRepository",
        return_value=mock_upload_repo,
    ):
        # First delivery
        await consumer.process_message(key=None, value=event, headers={})
        # Second delivery (re-delivery / at-least-once)
        await consumer.process_message(key=None, value=event, headers={})

    # set_ready() is called twice — both calls succeed (no error raised).
    assert (
        mock_upload_repo.set_ready.call_count == 2
    ), f"Expected set_ready() called twice; got {mock_upload_repo.set_ready.call_count}"
