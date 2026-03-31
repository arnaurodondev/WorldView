"""Unit tests for ArticleConsumer message handling (T-R2-3-02).

Updated for BaseKafkaConsumer[dict] refactor: the session lifecycle is now
managed by the UoW inside _handle_message (base class), not inside
process_message. Tests drive the full pipeline via _handle_message with a
mock Kafka message so the UoW + commit/rollback ordering is exercised.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from content_store.application.use_cases.process_article import ProcessingSummary
from content_store.domain.entities import DeduplicationDecision
from content_store.domain.enums import DedupOutcome
from content_store.infrastructure.messaging.consumers.article_consumer import (
    ArticleConsumer,
    ArticleConsumerConfig,
)

pytestmark = pytest.mark.unit

_SAMPLE_VALUE: dict = {
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


def _make_mock_msg(value: dict | None = None) -> MagicMock:
    """Build a mock Confluent Kafka message."""
    msg = MagicMock()
    payload = json.dumps(value or _SAMPLE_VALUE).encode()
    msg.topic.return_value = "content.article.raw.v1"
    msg.value.return_value = payload
    msg.key.return_value = None
    msg.headers.return_value = []
    return msg


def _make_consumer(
    *,
    lsh_client: AsyncMock | None = None,
    commit_side_effect: object = None,
) -> tuple[ArticleConsumer, AsyncMock]:
    """Build consumer with mock session factory that returns a fresh session."""
    mock_session = AsyncMock()
    if commit_side_effect is not None:
        mock_session.commit.side_effect = commit_side_effect

    @asynccontextmanager  # type: ignore[arg-type]
    async def _session_cm():
        yield mock_session

    session_factory = MagicMock(side_effect=_session_cm)
    consumer = ArticleConsumer(
        config=_make_config(),
        session_factory=session_factory,
        object_store=AsyncMock(),
        lsh_client=lsh_client or AsyncMock(),
    )
    return consumer, mock_session


class TestProcessMessage:
    @patch("content_store.infrastructure.messaging.consumers.article_consumer.ProcessArticleUseCase")
    @patch("content_store.infrastructure.messaging.consumers.article_consumer.ProcessedEventsRepository")
    async def test_successful_message_commits_session(
        self, mock_pe_repo_cls: MagicMock, mock_uc_cls: MagicMock
    ) -> None:
        """Successful processing → session.commit called via UoW."""
        # ProcessedEventsRepository: not a duplicate, mark_processed no-ops
        mock_pe_repo = AsyncMock()
        mock_pe_repo.is_duplicate.return_value = False
        mock_pe_repo.mark_processed.return_value = None
        mock_pe_repo_cls.return_value = mock_pe_repo

        mock_uc = AsyncMock()
        mock_uc.execute.return_value = ProcessingSummary(
            article_id="doc-001",
            decision=DeduplicationDecision(outcome=DedupOutcome.UNIQUE, stage="stage_c"),
            doc_id=None,
            suppressed=True,
        )
        mock_uc_cls.return_value = mock_uc

        consumer, mock_session = _make_consumer()
        await consumer._handle_message(_make_mock_msg())

        mock_session.commit.assert_called_once()
        mock_session.rollback.assert_not_called()

    @patch("content_store.infrastructure.messaging.consumers.article_consumer.ProcessArticleUseCase")
    @patch("content_store.infrastructure.messaging.consumers.article_consumer.ProcessedEventsRepository")
    async def test_processing_failure_rolls_back_and_raises(
        self, mock_pe_repo_cls: MagicMock, mock_uc_cls: MagicMock
    ) -> None:
        """Processing failure → session.rollback called via UoW, exception re-raised."""
        mock_pe_repo = AsyncMock()
        mock_pe_repo.is_duplicate.return_value = False
        mock_pe_repo_cls.return_value = mock_pe_repo

        mock_uc = AsyncMock()
        mock_uc.execute.side_effect = RuntimeError("Processing failed")
        mock_uc_cls.return_value = mock_uc

        consumer, mock_session = _make_consumer()

        # BaseKafkaConsumer re-raises; ensure it propagates
        with pytest.raises((RuntimeError, Exception)):
            await consumer._handle_message(_make_mock_msg())

        mock_session.rollback.assert_called_once()
        mock_session.commit.assert_not_called()

    @patch("content_store.infrastructure.messaging.consumers.article_consumer.ProcessArticleUseCase")
    @patch("content_store.infrastructure.messaging.consumers.article_consumer.ProcessedEventsRepository")
    async def test_lsh_index_called_after_commit(self, mock_pe_repo_cls: MagicMock, mock_uc_cls: MagicMock) -> None:
        """LSH index must be called AFTER session.commit (CR-3 fix)."""
        lsh_client = AsyncMock()
        consumer, mock_session = _make_consumer(lsh_client=lsh_client)

        mock_pe_repo = AsyncMock()
        mock_pe_repo.is_duplicate.return_value = False
        mock_pe_repo.mark_processed.return_value = None
        mock_pe_repo_cls.return_value = mock_pe_repo

        doc_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        call_order: list[str] = []

        mock_session.commit.side_effect = lambda: call_order.append("commit")
        lsh_client.index.side_effect = lambda *a, **kw: call_order.append("lsh_index")

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

        await consumer._handle_message(_make_mock_msg())

        assert "commit" in call_order, "session.commit was not called"
        assert "lsh_index" in call_order, "lsh.index was not called"
        assert call_order.index("commit") < call_order.index(
            "lsh_index"
        ), f"LSH index called BEFORE commit — order: {call_order}"

    @patch("content_store.infrastructure.messaging.consumers.article_consumer.ProcessArticleUseCase")
    @patch("content_store.infrastructure.messaging.consumers.article_consumer.ProcessedEventsRepository")
    async def test_each_message_gets_own_session(self, mock_pe_repo_cls: MagicMock, mock_uc_cls: MagicMock) -> None:
        """Each _handle_message call opens a new session via session_factory."""
        sessions: list[AsyncMock] = []

        def _make_session_cm() -> object:
            s = AsyncMock()
            sessions.append(s)

            @asynccontextmanager  # type: ignore[arg-type]
            async def _cm():
                yield s

            return _cm()

        session_factory = MagicMock(side_effect=_make_session_cm)

        mock_pe_repo = AsyncMock()
        mock_pe_repo.is_duplicate.return_value = False
        mock_pe_repo.mark_processed.return_value = None
        mock_pe_repo_cls.return_value = mock_pe_repo

        mock_uc = AsyncMock()
        mock_uc.execute.return_value = ProcessingSummary(
            article_id="doc-001",
            decision=DeduplicationDecision(outcome=DedupOutcome.UNIQUE, stage="stage_c"),
            doc_id=None,
            suppressed=True,
        )
        mock_uc_cls.return_value = mock_uc

        consumer = ArticleConsumer(
            config=_make_config(),
            session_factory=session_factory,
            object_store=AsyncMock(),
            lsh_client=AsyncMock(),
        )

        await consumer._handle_message(_make_mock_msg())
        msg2_value = {**_SAMPLE_VALUE, "event_id": "evt-002"}
        await consumer._handle_message(_make_mock_msg(msg2_value))

        # Each message opens 2 sessions: 1 for is_duplicate check + 1 for UoW.
        # 2 messages x 2 sessions = 4 total session_factory calls.
        assert (
            session_factory.call_count == 4
        ), f"Expected 4 session_factory calls (2 per message), got {session_factory.call_count}"
        assert len(sessions) == 4
        # Verify session isolation: no two messages share the same UoW session
        assert sessions[0] is not sessions[2]  # UoW sessions for msg1 vs msg2

    @patch("content_store.infrastructure.messaging.consumers.article_consumer.ProcessArticleUseCase")
    @patch("content_store.infrastructure.messaging.consumers.article_consumer.ProcessedEventsRepository")
    async def test_commit_failure_rolls_back_and_raises(
        self, mock_pe_repo_cls: MagicMock, mock_uc_cls: MagicMock
    ) -> None:
        """DB commit failure → rollback called, exception propagates (F-104)."""
        mock_pe_repo = AsyncMock()
        mock_pe_repo.is_duplicate.return_value = False
        mock_pe_repo.mark_processed.return_value = None
        mock_pe_repo_cls.return_value = mock_pe_repo

        mock_uc = AsyncMock()
        mock_uc.execute.return_value = ProcessingSummary(
            article_id="doc-001",
            decision=DeduplicationDecision(outcome=DedupOutcome.UNIQUE, stage="stage_c"),
            doc_id=None,
            suppressed=True,
        )
        mock_uc_cls.return_value = mock_uc

        consumer, mock_session = _make_consumer(commit_side_effect=RuntimeError("DB connection lost"))

        with pytest.raises((RuntimeError, Exception)):
            await consumer._handle_message(_make_mock_msg())

        mock_session.rollback.assert_called_once()

    @patch("content_store.infrastructure.messaging.consumers.article_consumer.ProcessArticleUseCase")
    @patch("content_store.infrastructure.messaging.consumers.article_consumer.ProcessedEventsRepository")
    async def test_lsh_index_failure_is_best_effort(self, mock_pe_repo_cls: MagicMock, mock_uc_cls: MagicMock) -> None:
        """LSH index failure should not raise — best-effort only."""
        lsh_client = AsyncMock()
        lsh_client.index.side_effect = RuntimeError("Valkey down")
        consumer, mock_session = _make_consumer(lsh_client=lsh_client)

        mock_pe_repo = AsyncMock()
        mock_pe_repo.is_duplicate.return_value = False
        mock_pe_repo.mark_processed.return_value = None
        mock_pe_repo_cls.return_value = mock_pe_repo

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
        await consumer._handle_message(_make_mock_msg())

        mock_session.commit.assert_called_once()
        mock_session.rollback.assert_not_called()
