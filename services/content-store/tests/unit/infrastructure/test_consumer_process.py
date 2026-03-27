"""Unit tests for ArticleConsumer.process_message (T-R2-3-02).

Verifies the consumer's orchestration logic with mocked dependencies:
commit/rollback lifecycle, LSH ordering guarantee (post-commit), and
per-message session isolation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from content_store.application.use_cases.process_article import ProcessingSummary
from content_store.domain.entities import DeduplicationDecision
from content_store.domain.enums import DedupOutcome
from content_store.infrastructure.consumer.article_consumer import (
    ArticleConsumer,
    ArticleConsumerConfig,
)

pytestmark = pytest.mark.unit

_SAMPLE_MESSAGE: dict = {
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


def _make_config() -> ArticleConsumerConfig:
    settings = MagicMock()
    settings.kafka_bootstrap_servers = "localhost:9092"
    settings.kafka_consumer_group = "content-store-consumer"
    settings.kafka_input_topic = "content.article.raw.v1"
    settings.kafka_output_topic = "content.article.stored.v1"
    settings.minio_bronze_bucket = "worldview-bronze"
    settings.minio_silver_bucket = "worldview-silver"
    settings.minhash_num_perm = 128
    return ArticleConsumerConfig(settings)


def _make_consumer(
    *,
    session: AsyncMock | None = None,
    lsh_client: AsyncMock | None = None,
) -> tuple[ArticleConsumer, AsyncMock]:
    """Build consumer with mock session factory that returns the given session."""
    mock_session = session or AsyncMock()
    session_factory = MagicMock()

    # Make session_factory() return an async context manager yielding mock_session
    ctx = AsyncMock()
    ctx.__aenter__.return_value = mock_session
    ctx.__aexit__.return_value = None
    session_factory.return_value = ctx

    consumer = ArticleConsumer(
        config=_make_config(),
        session_factory=session_factory,
        object_store=AsyncMock(),
        lsh_client=lsh_client or AsyncMock(),
    )
    return consumer, mock_session


class TestProcessMessage:
    @patch("content_store.infrastructure.consumer.article_consumer.ProcessArticleUseCase")
    async def test_successful_message_commits_session(self, mock_uc_cls: MagicMock) -> None:
        """Successful processing → session.commit called, no rollback."""
        consumer, mock_session = _make_consumer()

        mock_uc = AsyncMock()
        mock_uc.execute.return_value = ProcessingSummary(
            article_id="doc-001",
            decision=DeduplicationDecision(outcome=DedupOutcome.UNIQUE, stage="stage_c"),
            doc_id=None,
            suppressed=True,
        )
        mock_uc_cls.return_value = mock_uc

        await consumer.process_message(_SAMPLE_MESSAGE)

        mock_session.commit.assert_called_once()
        mock_session.rollback.assert_not_called()

    @patch("content_store.infrastructure.consumer.article_consumer.ProcessArticleUseCase")
    async def test_processing_failure_rolls_back_and_raises(self, mock_uc_cls: MagicMock) -> None:
        """Processing failure → session.rollback called, exception re-raised."""
        consumer, mock_session = _make_consumer()

        mock_uc = AsyncMock()
        mock_uc.execute.side_effect = RuntimeError("Processing failed")
        mock_uc_cls.return_value = mock_uc

        with pytest.raises(RuntimeError, match="Processing failed"):
            await consumer.process_message(_SAMPLE_MESSAGE)

        mock_session.rollback.assert_called_once()
        mock_session.commit.assert_not_called()

    @patch("content_store.infrastructure.consumer.article_consumer.ProcessArticleUseCase")
    async def test_lsh_index_called_after_commit(self, mock_uc_cls: MagicMock) -> None:
        """LSH index must be called AFTER session.commit, not before (CR-3 fix)."""
        lsh_client = AsyncMock()
        consumer, mock_session = _make_consumer(lsh_client=lsh_client)

        doc_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        mock_uc = AsyncMock()
        mock_uc.execute.return_value = ProcessingSummary(
            article_id="doc-001",
            decision=DeduplicationDecision(outcome=DedupOutcome.UNIQUE, stage="stage_c"),
            doc_id=doc_id,
            suppressed=False,
            signature=[1, 2, 3, 4],
            source_type="eodhd",
        )
        mock_uc_cls.return_value = mock_uc

        # Track call order
        call_order: list[str] = []
        mock_session.commit.side_effect = lambda: call_order.append("commit")
        lsh_client.index.side_effect = lambda *a, **kw: call_order.append("lsh_index")

        await consumer.process_message(_SAMPLE_MESSAGE)

        assert "commit" in call_order, "session.commit was not called"
        assert "lsh_index" in call_order, "lsh.index was not called"
        assert call_order.index("commit") < call_order.index(
            "lsh_index"
        ), f"LSH index called BEFORE commit — order: {call_order}"

    @patch("content_store.infrastructure.consumer.article_consumer.ProcessArticleUseCase")
    async def test_each_message_gets_own_session(self, mock_uc_cls: MagicMock) -> None:
        """Each process_message call opens a new session via session_factory."""
        sessions: list[AsyncMock] = []

        def make_ctx() -> AsyncMock:
            s = AsyncMock()
            sessions.append(s)
            ctx = AsyncMock()
            ctx.__aenter__.return_value = s
            ctx.__aexit__.return_value = None
            return ctx

        session_factory = MagicMock(side_effect=make_ctx)

        consumer = ArticleConsumer(
            config=_make_config(),
            session_factory=session_factory,
            object_store=AsyncMock(),
            lsh_client=AsyncMock(),
        )

        mock_uc = AsyncMock()
        mock_uc.execute.return_value = ProcessingSummary(
            article_id="doc-001",
            decision=DeduplicationDecision(outcome=DedupOutcome.UNIQUE, stage="stage_c"),
            doc_id=None,
            suppressed=True,
        )
        mock_uc_cls.return_value = mock_uc

        await consumer.process_message(_SAMPLE_MESSAGE)
        await consumer.process_message(_SAMPLE_MESSAGE)

        assert session_factory.call_count == 2, "Each message should get its own session"
        assert len(sessions) == 2
        # Verify they are different session objects
        assert sessions[0] is not sessions[1]

    @patch("content_store.infrastructure.consumer.article_consumer.ProcessArticleUseCase")
    async def test_lsh_index_failure_is_best_effort(self, mock_uc_cls: MagicMock) -> None:
        """LSH index failure should not raise — best-effort only."""
        lsh_client = AsyncMock()
        lsh_client.index.side_effect = RuntimeError("Valkey down")
        consumer, mock_session = _make_consumer(lsh_client=lsh_client)

        doc_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        mock_uc = AsyncMock()
        mock_uc.execute.return_value = ProcessingSummary(
            article_id="doc-001",
            decision=DeduplicationDecision(outcome=DedupOutcome.UNIQUE, stage="stage_c"),
            doc_id=doc_id,
            suppressed=False,
            signature=[1, 2, 3],
            source_type="eodhd",
        )
        mock_uc_cls.return_value = mock_uc

        # Should NOT raise despite LSH failure
        await consumer.process_message(_SAMPLE_MESSAGE)

        mock_session.commit.assert_called_once()
        mock_session.rollback.assert_not_called()
