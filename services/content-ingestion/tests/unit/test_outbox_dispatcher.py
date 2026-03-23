"""Unit tests for OutboxDispatcher."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from content_ingestion.infrastructure.db.models import OutboxEventModel
from content_ingestion.infrastructure.outbox.dispatcher import OutboxDispatcher

pytestmark = pytest.mark.unit

_EVENT_ID = UUID("00000000-0000-0000-0000-000000000001")
_AGGREGATE_ID = UUID("00000000-0000-0000-0000-000000000002")

_PAYLOAD = {
    "article_id": str(_AGGREGATE_ID),
    "source_type": "eodhd",
    "url": "https://example.com/news",
    "url_hash": "abc123",
    "minio_key": "content-ingestion/eodhd/abc123/raw/v1.json",
    "fetched_at": "2026-03-22T12:00:00+00:00",
    "byte_size": 512,
}


def _make_event() -> OutboxEventModel:
    return OutboxEventModel(
        id=_EVENT_ID,
        aggregate_type="RawArticle",
        aggregate_id=_AGGREGATE_ID,
        event_type="article.raw.v1",
        payload=_PAYLOAD,
        status="pending",
        retry_count=0,
    )


def _make_settings() -> MagicMock:
    settings = MagicMock()
    settings.OUTBOX_BATCH_SIZE = 100
    settings.KAFKA_OUTBOX_TOPIC = "content.article.raw.v1"
    settings.OUTBOX_POLL_INTERVAL_SECONDS = 5
    settings.MAX_RETRIES = 3
    return settings


class TestOutboxDispatcher:
    async def test_dispatch_success_calls_send_and_wait(self) -> None:
        """Successful dispatch: send_and_wait called, mark_dispatched called."""
        event = _make_event()
        kafka_producer = AsyncMock()
        settings = _make_settings()

        with (
            patch("content_ingestion.infrastructure.outbox.dispatcher.get_db_session") as mock_ctx,
            patch("content_ingestion.infrastructure.outbox.dispatcher.OutboxRepository") as mock_repo_cls,
        ):
            mock_session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            repo_instance = AsyncMock()
            repo_instance.fetch_pending = AsyncMock(return_value=[event])
            repo_instance.mark_dispatched = AsyncMock()
            mock_repo_cls.return_value = repo_instance

            dispatcher = OutboxDispatcher(
                session_factory=MagicMock(),
                kafka_producer=kafka_producer,
                settings=settings,
            )
            await dispatcher.run_once()

        kafka_producer.send_and_wait.assert_awaited_once()
        call_kwargs = kafka_producer.send_and_wait.await_args
        assert call_kwargs.args[0] == "content.article.raw.v1"
        assert call_kwargs.kwargs["key"] == str(_AGGREGATE_ID).encode()

    async def test_dispatch_kafka_failure_marks_failed(self) -> None:
        """Kafka failure: mark_failed called; no move_to_dlq if under retry limit."""
        event = _make_event()
        kafka_producer = AsyncMock()
        kafka_producer.send_and_wait = AsyncMock(side_effect=RuntimeError("broker down"))
        settings = _make_settings()
        settings.MAX_RETRIES = 3

        with (
            patch("content_ingestion.infrastructure.outbox.dispatcher.get_db_session") as mock_ctx,
            patch("content_ingestion.infrastructure.outbox.dispatcher.OutboxRepository") as mock_repo_cls,
        ):
            mock_session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            failed_event = OutboxEventModel(
                id=_EVENT_ID,
                aggregate_type="RawArticle",
                aggregate_id=_AGGREGATE_ID,
                event_type="article.raw.v1",
                payload=_PAYLOAD,
                status="failed",
                retry_count=1,  # under MAX_RETRIES
            )
            repo_instance = AsyncMock()
            repo_instance.fetch_pending = AsyncMock(return_value=[event])
            repo_instance.mark_failed = AsyncMock()
            repo_instance.get_by_id = AsyncMock(return_value=failed_event)
            repo_instance.move_to_dlq = AsyncMock()
            mock_repo_cls.return_value = repo_instance

            dispatcher = OutboxDispatcher(
                session_factory=MagicMock(),
                kafka_producer=kafka_producer,
                settings=settings,
            )
            await dispatcher.run_once()

        repo_instance.mark_failed.assert_awaited_once_with(_EVENT_ID, "broker down")
        repo_instance.move_to_dlq.assert_not_awaited()
