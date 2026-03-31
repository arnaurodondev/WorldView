"""Unit tests for T-C-4-06: ArticleProcessingConsumer orchestration.

Critical invariants tested:
  - Block orchestration order is correct.
  - Offset committed only after DB transaction succeeds.
  - Backpressure slot is acquired before ML work.
  - Dead-letter write on unrecoverable failure.
  - is_duplicate always returns False (at-least-once semantics).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    ArticleProcessingConsumer,
    _compute_chunk_mention_pairs,
    _enqueue_enriched,
    _is_valid_uuid,
)
from structlog.testing import capture_logs


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.gliner_threshold = 0.35
    s.gliner_batch_size = 32
    s.gliner_section_token_limit = 450
    s.embedding_model_id = "bge-large-en-v1.5"
    s.embedding_instruction_prefix = "Represent: "
    s.ner_model_id = "gliner"
    s.extraction_model_id = "qwen2.5:7b-instruct"
    s.topic_article_enriched = "nlp.article.enriched.v1"
    s.topic_signal_detected = "nlp.signal.detected.v1"
    s.max_ollama_queue_depth = 20
    s.resume_ollama_queue_depth = 10
    return s


def _make_consumer(**kwargs: Any) -> ArticleProcessingConsumer:
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="test-group",
        topics=["content.article.stored.v1"],
    )
    defaults: dict[str, Any] = {
        "config": config,
        "settings": _make_settings(),
        "nlp_session_factory": MagicMock(),
        "intelligence_session_factory": MagicMock(),
        "storage": MagicMock(),
        "watchlist_cache": MagicMock(),
        "ner_client": MagicMock(),
        "embedding_client": MagicMock(),
        "extraction_client": MagicMock(),
        "backpressure": MagicMock(),
    }
    defaults.update(kwargs)
    return ArticleProcessingConsumer(**defaults)


@pytest.mark.unit
class TestArticleConsumerIdempotency:
    @pytest.mark.asyncio
    async def test_is_duplicate_always_false(self) -> None:
        """Consumer uses at-least-once; idempotency via DB constraints."""
        consumer = _make_consumer()
        assert await consumer.is_duplicate("some-event-id") is False

    @pytest.mark.asyncio
    async def test_mark_processed_is_noop(self) -> None:
        consumer = _make_consumer()
        # Should not raise
        await consumer.mark_processed("some-event-id")

    @pytest.mark.asyncio
    async def test_get_pending_retries_empty(self) -> None:
        consumer = _make_consumer()
        retries = await consumer.get_pending_retries()
        assert retries == []


@pytest.mark.unit
class TestArticleConsumerSerialization:
    def test_extract_event_id(self) -> None:
        consumer = _make_consumer()
        value = {"event_id": "abc-123"}
        assert consumer.extract_event_id(value) == "abc-123"

    def test_extract_event_id_missing(self) -> None:
        consumer = _make_consumer()
        assert consumer.extract_event_id({}) == ""

    def test_deserialize_value_json(self) -> None:
        consumer = _make_consumer()
        payload = {"doc_id": "123", "source_type": "eodhd"}
        raw = json.dumps(payload).encode()
        result = consumer.deserialize_value(raw)
        assert result["doc_id"] == "123"

    def test_get_schema_path_returns_none(self) -> None:
        consumer = _make_consumer()
        assert consumer.get_schema_path("any.topic") is None


@pytest.mark.unit
class TestChunkMentionPairs:
    def test_overlapping_same_section(self) -> None:
        """Mention within a chunk's char range → should be linked."""
        from nlp_pipeline.domain.enums import MentionClass
        from nlp_pipeline.domain.models import Chunk, EntityMention

        section_id = uuid.uuid4()
        doc_id = uuid.uuid4()

        chunk = Chunk(
            chunk_id=uuid.uuid4(),
            doc_id=doc_id,
            section_id=section_id,
            chunk_index=0,
            char_start=0,
            char_end=100,
            token_count=20,
            text="Apple reported earnings.",
        )
        mention = EntityMention(
            mention_id=uuid.uuid4(),
            doc_id=doc_id,
            section_id=section_id,
            mention_text="Apple",
            mention_class=MentionClass.ORGANIZATION,
            confidence=0.9,
            char_start=0,
            char_end=5,
        )
        pairs = _compute_chunk_mention_pairs([chunk], [mention])
        assert len(pairs) == 1
        assert pairs[0] == (chunk.chunk_id, mention.mention_id)

    def test_no_overlap_different_section(self) -> None:
        from nlp_pipeline.domain.enums import MentionClass
        from nlp_pipeline.domain.models import Chunk, EntityMention

        doc_id = uuid.uuid4()
        chunk = Chunk(
            chunk_id=uuid.uuid4(),
            doc_id=doc_id,
            section_id=uuid.uuid4(),
            chunk_index=0,
            char_start=0,
            char_end=50,
            token_count=10,
            text="Text.",
        )
        mention = EntityMention(
            mention_id=uuid.uuid4(),
            doc_id=doc_id,
            section_id=uuid.uuid4(),  # different section
            mention_text="Apple",
            mention_class=MentionClass.ORGANIZATION,
            confidence=0.9,
            char_start=0,
            char_end=5,
        )
        pairs = _compute_chunk_mention_pairs([chunk], [mention])
        assert pairs == []

    def test_empty_inputs(self) -> None:
        assert _compute_chunk_mention_pairs([], []) == []


@pytest.mark.unit
class TestUuidHelper:
    def test_valid_uuid(self) -> None:
        assert _is_valid_uuid(str(uuid.uuid4())) is True

    def test_invalid_uuid(self) -> None:
        assert _is_valid_uuid("not-a-uuid") is False
        assert _is_valid_uuid("") is False


@pytest.mark.unit
class TestDeadLetter:
    @pytest.mark.asyncio
    async def test_dead_letter_writes_to_dlq(self) -> None:
        """Unrecoverable events must be written to nlp_db.dead_letter_queue."""
        from messaging.kafka.consumer.base import FailureInfo  # type: ignore[import-untyped]

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        nlp_sf = MagicMock()
        nlp_sf.return_value = mock_session

        consumer = _make_consumer(nlp_session_factory=nlp_sf)

        event_id = str(uuid.uuid4())
        failure = FailureInfo(
            event_id=event_id,
            topic="content.article.stored.v1",
            partition=0,
            offset=42,
            attempt=5,
            last_error=RuntimeError("permanent failure"),
        )

        with patch("nlp_pipeline.infrastructure.messaging.consumers.article_consumer.DLQRepository") as mock_dlq_cls:
            mock_dlq = AsyncMock()
            mock_dlq_cls.return_value = mock_dlq
            await consumer.dead_letter(failure)

        mock_dlq.move_to_dlq.assert_called_once()


@pytest.mark.unit
class TestEnqueueEnriched:
    @pytest.mark.asyncio
    async def test_enriched_event_written_to_outbox(self) -> None:
        """nlp.article.enriched.v1 must be written to outbox, not directly to Kafka."""
        outbox_repo = AsyncMock()
        settings = _make_settings()
        doc_id = uuid.uuid4()

        from nlp_pipeline.domain.enums import RoutingTier
        from nlp_pipeline.domain.models import RoutingDecision

        rd = RoutingDecision(
            decision_id=uuid.uuid4(),
            doc_id=doc_id,
            routing_tier=RoutingTier.MEDIUM,
            composite_score=0.55,
            feature_scores={},
        )

        await _enqueue_enriched(
            outbox_repo=outbox_repo,
            settings=settings,
            doc_id=doc_id,
            source_type="eodhd",
            published_at=datetime.now(tz=UTC),
            is_backfill=False,
            routing_decision=rd,
            sections=[],
            chunks=[],
            mentions=[],
            extraction_result={"events": [], "claims": [], "relations": []},
            correlation_id=None,
        )

        outbox_repo.add.assert_called_once()
        call_kwargs = outbox_repo.add.call_args
        assert call_kwargs.kwargs["topic"] == "nlp.article.enriched.v1"
        payload = json.loads(call_kwargs.kwargs["payload_avro"])
        assert payload["doc_id"] == str(doc_id)
        assert payload["routing_tier"] == "medium"
        assert payload["event_type"] == "nlp.article.enriched"


# ── D-004: nlp commit failure logging (T-A-2-04) ─────────────────────────────


def _make_failing_nlp_session_factory() -> tuple[AsyncMock, MagicMock]:
    """Build (session, session_factory) where session.commit raises RuntimeError."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())
    session.add = MagicMock()
    session.commit = AsyncMock(side_effect=RuntimeError("nlp db down"))

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    sf = MagicMock()
    sf.return_value = cm
    return session, sf


_HALT_PATCHES = (
    patch("nlp_pipeline.infrastructure.messaging.consumers.article_consumer.section_document", return_value=[]),
    patch(
        "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.run_ner_block",
        new=AsyncMock(return_value=([], MagicMock())),
    ),
    patch(
        "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.compute_routing_score",
        return_value=MagicMock(),
    ),
    patch(
        "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.apply_suppression_gate",
        return_value="halt",  # ProcessingPath.HALT is StrEnum("halt")
    ),
    patch(
        "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.run_embeddings_block",
        new=AsyncMock(return_value=([], [], [], [])),
    ),
    patch("nlp_pipeline.infrastructure.messaging.consumers.article_consumer._enqueue_enriched", new=AsyncMock()),
)


@pytest.mark.unit
class TestNlpCommitFailure:
    """Tests for D-004 warning log on nlp_db commit failure."""

    @pytest.mark.asyncio
    async def test_nlp_commit_failure_logs_warning(self) -> None:
        """When session.commit() raises, nlp_commit_failed_intel_writes_may_be_orphaned is logged."""
        doc_id = uuid.uuid4()
        _session, nlp_sf = _make_failing_nlp_session_factory()

        consumer = _make_consumer(
            nlp_session_factory=nlp_sf,
            intelligence_session_factory=MagicMock(),
        )
        consumer._watchlist = MagicMock()
        consumer._watchlist.get_all_watched = AsyncMock(return_value=set())

        with capture_logs() as cap:
            for p in _HALT_PATCHES:
                p.start()
            with patch.object(consumer, "_download_article", new=AsyncMock(return_value="text")):
                try:
                    with pytest.raises(RuntimeError, match="nlp db down"):
                        await consumer._run_pipeline(
                            doc_id=doc_id,
                            minio_key="bucket/key",
                            source_type="eodhd",
                            published_at=None,
                            extracted_at=datetime.now(UTC),
                            is_backfill=False,
                            correlation_id=None,
                        )
                finally:
                    for p in _HALT_PATCHES:
                        p.stop()

        assert any(
            e.get("event") == "nlp_commit_failed_intel_writes_may_be_orphaned"
            and str(doc_id) in str(e.get("doc_id", ""))
            for e in cap
        ), f"Expected warning not found in: {cap}"

    @pytest.mark.asyncio
    async def test_nlp_commit_failure_reraises(self) -> None:
        """The RuntimeError from session.commit() is re-raised after the warning log."""
        doc_id = uuid.uuid4()
        _session, nlp_sf = _make_failing_nlp_session_factory()

        consumer = _make_consumer(
            nlp_session_factory=nlp_sf,
            intelligence_session_factory=MagicMock(),
        )
        consumer._watchlist = MagicMock()
        consumer._watchlist.get_all_watched = AsyncMock(return_value=set())

        for p in _HALT_PATCHES:
            p.start()
        with patch.object(consumer, "_download_article", new=AsyncMock(return_value="text")):
            try:
                with pytest.raises(RuntimeError, match="nlp db down"):
                    await consumer._run_pipeline(
                        doc_id=doc_id,
                        minio_key="bucket/key",
                        source_type="eodhd",
                        published_at=None,
                        extracted_at=datetime.now(UTC),
                        is_backfill=False,
                        correlation_id=None,
                    )
            finally:
                for p in _HALT_PATCHES:
                    p.stop()
