"""Unit tests for the refactored ArticleConsumer (T-R3-2-05).

Verifies:
1. ArticleConsumer IS a subclass of BaseKafkaConsumer
2. is_duplicate returns False when no record exists
3. is_duplicate returns True when a record exists
4. process_message delegates to ProcessArticleUseCase and stores summary
5. extract_event_id returns str(value["event_id"])
6. dead_letter logs and writes to DLQ (best-effort, doesn't raise)
7. get_pending_retries always returns []
8. deserialize_value falls back to JSON when schema_path is None
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_store.infrastructure.messaging.consumers.article_consumer import (
    ArticleConsumer,
    ArticleConsumerConfig,
)

from messaging.kafka.consumer.base import BaseKafkaConsumer, FailureInfo  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_config(**overrides: object) -> ArticleConsumerConfig:
    """Build a mock ArticleConsumerConfig."""
    config = MagicMock(spec=ArticleConsumerConfig)
    config.bootstrap_servers = "localhost:9092"
    config.group_id = "content-store-consumer"
    config.input_topic = "content.article.raw.v1"
    config.output_topic = "content.article.stored.v1"
    config.bronze_bucket = "worldview-bronze"
    config.silver_bucket = "worldview-silver"
    config.num_perm = 128
    for k, v in overrides.items():
        setattr(config, k, v)
    return config  # type: ignore[return-value]


def _make_consumer(
    config: ArticleConsumerConfig | None = None,
    session_factory: object = None,
    object_store: object = None,
    lsh_client: object = None,
) -> ArticleConsumer:
    """Build an ArticleConsumer with injected mocks."""
    from contextlib import asynccontextmanager

    if session_factory is None:
        session = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        @asynccontextmanager  # type: ignore[arg-type]
        async def _factory():
            yield session

        session_factory = MagicMock(side_effect=_factory)

    return ArticleConsumer(
        config=config or _make_config(),
        session_factory=session_factory,  # type: ignore[arg-type]
        object_store=object_store or AsyncMock(),
        lsh_client=lsh_client or AsyncMock(),
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestArticleConsumerInheritance:
    def test_is_subclass_of_base_kafka_consumer(self) -> None:
        """ArticleConsumer must extend BaseKafkaConsumer (T-R3-2-01 acceptance)."""
        assert issubclass(ArticleConsumer, BaseKafkaConsumer)

    def test_has_no_abstract_methods(self) -> None:
        """Instantiation must succeed — all 12 abstract methods implemented."""
        consumer = _make_consumer()
        assert consumer is not None


class TestExtractEventId:
    def test_returns_event_id_as_string(self) -> None:
        consumer = _make_consumer()
        value = {"event_id": "abc-123", "other": "data"}
        assert consumer.extract_event_id(value) == "abc-123"

    def test_casts_non_string_to_str(self) -> None:
        consumer = _make_consumer()
        import uuid

        uid = uuid.uuid4()
        value = {"event_id": uid}
        assert consumer.extract_event_id(value) == str(uid)


class TestDeserializeValue:
    def test_falls_back_to_json_when_no_schema(self) -> None:
        consumer = _make_consumer()
        data = {"event_id": "x", "doc_id": "y"}
        import json

        raw = json.dumps(data).encode()
        result = consumer.deserialize_value(raw, schema_path=None)
        assert result["event_id"] == "x"
        assert result["doc_id"] == "y"


class TestIsDuplicate:
    async def test_returns_false_for_unknown_event_id(self) -> None:
        """is_duplicate must return False when event not in processed_events."""
        consumer = _make_consumer()

        with patch(
            "content_store.infrastructure.messaging.consumers.article_consumer.ProcessedEventsRepository"
        ) as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.is_duplicate.return_value = False
            MockRepo.return_value = mock_repo

            # Simulate a current UoW with a session
            consumer._current_uow = MagicMock()
            consumer._current_uow.session = AsyncMock()

            result = await consumer.is_duplicate("some-event-id")
            assert result is False

    async def test_returns_true_for_known_event_id(self) -> None:
        """is_duplicate must return True when event exists in processed_events."""
        consumer = _make_consumer()

        with patch(
            "content_store.infrastructure.messaging.consumers.article_consumer.ProcessedEventsRepository"
        ) as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.is_duplicate.return_value = True
            MockRepo.return_value = mock_repo

            consumer._current_uow = MagicMock()
            consumer._current_uow.session = AsyncMock()

            result = await consumer.is_duplicate("known-event-id")
            assert result is True


class TestProcessMessage:
    async def test_process_message_stores_summary(self) -> None:
        """process_message must delegate to ProcessArticleUseCase and store summary."""
        from content_store.application.use_cases.process_article import ProcessingSummary
        from content_store.domain.entities import DeduplicationDecision
        from content_store.domain.enums import DedupOutcome

        import common.ids

        doc_id = common.ids.new_uuid7()
        mock_summary = ProcessingSummary(
            article_id="doc-001",
            decision=DeduplicationDecision(outcome=DedupOutcome.UNIQUE, stage="stage_c"),
            doc_id=doc_id,
            suppressed=False,
            signature=[1, 2, 3],
            source_type="eodhd",
        )

        consumer = _make_consumer()
        consumer._current_uow = MagicMock()
        consumer._current_uow.session = AsyncMock()

        with patch(
            "content_store.infrastructure.messaging.consumers.article_consumer.ProcessArticleUseCase.execute",
            new=AsyncMock(return_value=mock_summary),
        ):
            value = {
                "event_id": "evt-001",
                "doc_id": "doc-001",
                "source_type": "eodhd",
                "source_url": None,
                "minio_bronze_key": "key",
                "content_hash": "hash",
            }
            await consumer.process_message(None, value, {})

        assert consumer._current_summary is mock_summary


class TestDeadLetter:
    async def test_dead_letter_does_not_raise(self) -> None:
        """dead_letter must be best-effort — never raise."""
        consumer = _make_consumer()

        failure: FailureInfo[dict] = FailureInfo(  # type: ignore[type-arg]
            event_id="bad-event",
            topic="content.article.raw.v1",
            partition=0,
            offset=42,
            attempt=5,
            last_error=RuntimeError("fatal error"),
        )

        # Should not raise even if session fails
        with patch.object(consumer, "_session_factory", side_effect=Exception("db down")):
            await consumer.dead_letter(failure)  # must not propagate


class TestGetPendingRetries:
    async def test_always_returns_empty_list(self) -> None:
        consumer = _make_consumer()
        result = await consumer.get_pending_retries()
        assert result == []
