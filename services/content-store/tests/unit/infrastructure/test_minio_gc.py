"""Unit tests for S5 ArticleConsumer MinIO orphan GC on DB commit failure (T-R3-3-02)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_store.infrastructure.messaging.consumers.article_consumer import (
    ArticleConsumer,
    ArticleConsumerConfig,
)

pytestmark = pytest.mark.unit

_SILVER_KEY = "content-store/canonical/eodhd/abc123/v1.json"
_SILVER_BUCKET = "worldview-silver"


def _make_config() -> ArticleConsumerConfig:
    config = MagicMock(spec=ArticleConsumerConfig)
    config.bootstrap_servers = "localhost:9092"
    config.group_id = "content-store-consumer"
    config.input_topic = "content.article.raw.v1"
    config.output_topic = "content.article.stored.v1"
    config.bronze_bucket = "worldview-bronze"
    config.silver_bucket = _SILVER_BUCKET
    config.num_perm = 128
    return config  # type: ignore[return-value]


def _make_consumer(object_store: object = None) -> ArticleConsumer:
    from contextlib import asynccontextmanager

    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    @asynccontextmanager  # type: ignore[arg-type]
    async def _factory():
        yield session

    return ArticleConsumer(
        config=_make_config(),
        session_factory=MagicMock(side_effect=_factory),  # type: ignore[arg-type]
        object_store=object_store or AsyncMock(),
        lsh_client=AsyncMock(),
    )


def _make_msg() -> MagicMock:
    msg = MagicMock()
    msg.topic.return_value = "content.article.raw.v1"
    msg.value.return_value = b"{}"
    msg.key.return_value = None
    msg.headers.return_value = []
    return msg


def _make_test_summary(silver_key: str | None = _SILVER_KEY) -> object:
    """Build a ProcessingSummary for testing."""
    from content_store.application.use_cases.process_article import ProcessingSummary
    from content_store.domain.entities import DeduplicationDecision
    from content_store.domain.enums import DedupOutcome

    import common.ids

    return ProcessingSummary(
        article_id="doc-001",
        decision=DeduplicationDecision(outcome=DedupOutcome.UNIQUE, stage="stage_c"),
        doc_id=common.ids.new_uuid7(),
        suppressed=False,
        signature=[1, 2, 3],
        source_type="eodhd",
        minio_silver_key=silver_key,
    )


class TestArticleConsumerMinioGC:
    async def test_gc_called_when_commit_fails(self) -> None:
        """If DB commit fails (super raises), delete the orphaned silver object."""
        from messaging.kafka.consumer.base import BaseKafkaConsumer

        mock_summary = _make_test_summary()
        store = AsyncMock()
        consumer = _make_consumer(object_store=store)

        # Patch BaseKafkaConsumer._handle_message to simulate: process_message ran
        # (setting _current_summary), then commit failed.
        async def _fake_base(self: object, msg: object) -> None:
            consumer._current_summary = mock_summary  # simulate process_message
            raise RuntimeError("commit failed")

        with patch.object(BaseKafkaConsumer, "_handle_message", _fake_base):
            with pytest.raises(RuntimeError, match="commit failed"):
                await consumer._handle_message(_make_msg())

        store.delete.assert_called_once_with(_SILVER_BUCKET, _SILVER_KEY)

    async def test_gc_not_called_when_no_silver_key(self) -> None:
        """If summary has no silver key (suppressed article), delete is NOT called."""
        from messaging.kafka.consumer.base import BaseKafkaConsumer

        mock_summary = _make_test_summary(silver_key=None)
        store = AsyncMock()
        consumer = _make_consumer(object_store=store)

        async def _fake_base(self: object, msg: object) -> None:
            consumer._current_summary = mock_summary
            raise RuntimeError("commit failed")

        with patch.object(BaseKafkaConsumer, "_handle_message", _fake_base):
            with pytest.raises(RuntimeError):
                await consumer._handle_message(_make_msg())

        store.delete.assert_not_called()

    async def test_gc_failure_does_not_mask_original_exception(self) -> None:
        """If delete also fails, the original commit exception must still propagate."""
        from messaging.kafka.consumer.base import BaseKafkaConsumer

        mock_summary = _make_test_summary()
        store = AsyncMock()
        store.delete = AsyncMock(side_effect=RuntimeError("MinIO down"))
        consumer = _make_consumer(object_store=store)

        async def _fake_base(self: object, msg: object) -> None:
            consumer._current_summary = mock_summary
            raise RuntimeError("commit failed")

        with patch.object(BaseKafkaConsumer, "_handle_message", _fake_base):
            with pytest.raises(RuntimeError, match="commit failed"):
                await consumer._handle_message(_make_msg())

    async def test_no_gc_after_successful_commit(self) -> None:
        """On successful processing, silver delete must NOT be called."""
        from messaging.kafka.consumer.base import BaseKafkaConsumer

        store = AsyncMock()
        consumer = _make_consumer(object_store=store)

        async def _fake_base(self: object, msg: object) -> None:
            return None  # success — no exception

        with patch.object(BaseKafkaConsumer, "_handle_message", _fake_base):
            await consumer._handle_message(_make_msg())

        store.delete.assert_not_called()

    async def test_current_summary_cleared_on_failure(self) -> None:
        """_current_summary must be None after a failed _handle_message."""
        from messaging.kafka.consumer.base import BaseKafkaConsumer

        mock_summary = _make_test_summary()
        consumer = _make_consumer()

        async def _fake_base(self: object, msg: object) -> None:
            consumer._current_summary = mock_summary
            raise RuntimeError("fail")

        with patch.object(BaseKafkaConsumer, "_handle_message", _fake_base):
            with pytest.raises(RuntimeError):
                await consumer._handle_message(_make_msg())

        assert consumer._current_summary is None
