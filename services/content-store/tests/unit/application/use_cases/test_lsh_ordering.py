"""Tests for LSH index ordering (CR-3 fix).

Verifies that:
1. ProcessArticleUseCase.execute() does NOT call lsh.index()
2. ArticleConsumer calls lsh.index() AFTER session.commit()
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from content_store.application.use_cases.process_article import (
    ProcessArticleUseCase,
    RawArticleEvent,
)
from content_store.domain.entities import DeduplicationDecision
from content_store.domain.enums import DedupOutcome

pytestmark = pytest.mark.unit


def _make_article(**overrides: object) -> RawArticleEvent:
    defaults = {
        "event_id": "evt-001",
        "doc_id": "doc-001",
        "source_type": "eodhd",
        "source_url": "https://example.com/article",
        "minio_bronze_key": "content-ingestion/eodhd/abc123/raw/v1.json",
        "content_hash": "deadbeef" * 8,
        "title": "Test Article",
        "published_at": "2026-03-01T12:00:00Z",
        "is_backfill": False,
    }
    defaults.update(overrides)
    return RawArticleEvent(**defaults)  # type: ignore[arg-type]


class TestLSHOrderingUseCase:
    async def test_execute_does_not_call_lsh_index(self) -> None:
        """ProcessArticleUseCase.execute must NOT call lsh.index() (CR-3)."""
        dedup_repo = AsyncMock()
        dedup_repo.check_exists.return_value = None

        store = AsyncMock()
        store.get_bytes.return_value = (
            b"<html><body>Apple stock price rose significantly"
            b" after quarterly earnings report was released today</body></html>"
        )
        store.put_bytes.return_value = None

        lsh_client = AsyncMock()
        lsh_client.query.return_value = DeduplicationDecision(
            outcome=DedupOutcome.UNIQUE,
            stage="stage_c",
        )

        silver_storage = AsyncMock()
        silver_storage.put_canonical.return_value = "content-store/canonical/test/body.json"
        uc = ProcessArticleUseCase(
            document_repo=AsyncMock(),
            dedup_repo=dedup_repo,
            minhash_repo=AsyncMock(),
            outbox_repo=AsyncMock(),
            bronze_store=store,
            bronze_bucket="worldview-bronze",
            silver_storage=silver_storage,
            lsh_client=lsh_client,
        )
        summary = await uc.execute(_make_article())

        # execute() must NOT call lsh.index — that's the consumer's job
        lsh_client.index.assert_not_called()

        # But it should return the signature for post-commit indexing
        assert summary.signature is not None
        assert summary.source_type == "eodhd"
        assert summary.doc_id is not None


class TestLSHOrderingConsumer:
    async def test_consumer_calls_lsh_after_commit(self) -> None:
        """ArticleConsumer must call lsh.index() AFTER session.commit() (CR-3).

        We drive the test via _handle_message (the full pipeline) rather than
        process_message directly, so we exercise the real commit→lsh ordering.
        """
        from contextlib import asynccontextmanager
        from unittest.mock import MagicMock

        from content_store.infrastructure.messaging.consumers.article_consumer import (
            ArticleConsumer,
            ArticleConsumerConfig,
        )

        # Build a mock config
        config = MagicMock(spec=ArticleConsumerConfig)
        config.bootstrap_servers = "localhost:9092"
        config.group_id = "content-store-consumer"
        config.input_topic = "content.article.raw.v1"
        config.output_topic = "content.article.stored.v1"
        config.bronze_bucket = "worldview-bronze"
        config.silver_bucket = "worldview-silver"
        config.num_perm = 128
        # PLAN-0113 FIX-2: static-membership identity (empty = dynamic default).
        config.group_instance_id = ""

        # Build session with proper async context manager
        session = AsyncMock()
        call_order: list[str] = []

        async def _track_commit() -> None:
            call_order.append("commit")

        session.commit.side_effect = _track_commit

        @asynccontextmanager
        async def _session_cm():  # type: ignore[no-untyped-def]
            yield session

        session_factory = MagicMock(side_effect=_session_cm)

        lsh_client = AsyncMock()

        async def _track_index(*args: object, **kwargs: object) -> None:
            call_order.append("lsh_index")

        lsh_client.index.side_effect = _track_index

        consumer = ArticleConsumer(
            config=config,
            session_factory=session_factory,
            object_store=AsyncMock(),
            lsh_client=lsh_client,
        )

        import common.ids

        mock_doc_id = common.ids.new_uuid7()

        from content_store.application.use_cases.process_article import ProcessingSummary

        mock_summary = ProcessingSummary(
            article_id="doc-001",
            decision=DeduplicationDecision(outcome=DedupOutcome.UNIQUE, stage="stage_c"),
            doc_id=mock_doc_id,
            suppressed=False,
            signature=[1, 2, 3, 4],
            source_type="eodhd",
        )

        import json

        raw_value = json.dumps(
            {
                "event_id": "evt-001",
                "doc_id": "doc-001",
                "source_type": "eodhd",
                "minio_bronze_key": "key",
                "content_hash": "hash",
            }
        ).encode()

        # Build a mock Kafka message
        mock_msg = MagicMock()
        mock_msg.topic.return_value = "content.article.raw.v1"
        mock_msg.value.return_value = raw_value
        mock_msg.key.return_value = None
        mock_msg.headers.return_value = []

        # Patch use case execute + is_duplicate + mark_processed
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "content_store.infrastructure.messaging.consumers.article_consumer.ProcessArticleUseCase.execute",
                AsyncMock(return_value=mock_summary),
            )
            mp.setattr(
                "content_store.infrastructure.messaging.consumers.article_consumer.ProcessedEventsRepository.is_duplicate",
                AsyncMock(return_value=False),
            )
            mp.setattr(
                "content_store.infrastructure.messaging.consumers.article_consumer.ProcessedEventsRepository.mark_processed",
                AsyncMock(return_value=None),
            )

            await consumer._handle_message(mock_msg)

        # Verify ordering: commit BEFORE lsh_index
        assert call_order == ["commit", "lsh_index"], f"Expected commit before lsh_index, got {call_order}"

        # lsh.index must have been called with correct args
        lsh_client.index.assert_called_once()
        call_args = lsh_client.index.call_args
        assert call_args.args[0] == mock_doc_id
        assert call_args.args[1] == [1, 2, 3, 4]
