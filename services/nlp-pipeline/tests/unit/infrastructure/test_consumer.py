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
    _build_raw_claims,
    _compute_chunk_mention_pairs,
    _enqueue_enriched,
    _enqueue_signal_events,
    _is_valid_uuid,
)
from structlog.testing import capture_logs

pytestmark = pytest.mark.unit


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


def _make_async_cm_session_factory() -> MagicMock:
    """Build a session factory that returns a proper async context manager.

    D-004: _run_pipeline opens both nlp_session and intel_session via
    ``async with self._nlp_sf() as nlp_session, self._intel_sf() as intel_session``
    so every session factory used in tests must support __aenter__/__aexit__.
    """
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    sf = MagicMock()
    sf.return_value = cm
    return sf


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
        "intelligence_session_factory": _make_async_cm_session_factory(),
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
class TestBackpressureSemaphoreIdempotency:
    """F-MAJOR-001: backpressure slot must NOT be acquired when the message is a duplicate."""

    @pytest.mark.asyncio
    async def test_duplicate_message_does_not_acquire_semaphore(self) -> None:
        """When a duplicate message is received (routing_decision exists), the
        backpressure semaphore count must not decrease — the slot is never acquired.
        """
        from nlp_pipeline.infrastructure.backpressure.controller import BackpressureController

        bp = BackpressureController(max_depth=2, resume_depth=1)
        assert bp.current_depth == 0

        # Build a mock session factory where the routing check returns an
        # existing routing_decision (i.e. duplicate doc_id).
        mock_routing_decision = MagicMock()  # non-None → duplicate
        _exec_result = MagicMock()
        _exec_result.scalar_one_or_none = MagicMock(return_value=mock_routing_decision)

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=_exec_result)
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        nlp_sf = MagicMock(return_value=mock_cm)

        consumer = _make_consumer(nlp_session_factory=nlp_sf, backpressure=bp)

        doc_id = uuid.uuid4()
        value = {
            "doc_id": str(doc_id),
            "minio_silver_key": "bucket/key",
            "source_type": "eodhd",
            "event_id": str(uuid.uuid4()),
        }
        with patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.RoutingDecisionRepository"
        ) as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.get_by_doc = AsyncMock(return_value=mock_routing_decision)
            mock_repo_cls.return_value = mock_repo

            await consumer.process_message(key=None, value=value, headers={})

        # Semaphore depth must remain at 0 — no slot was acquired for a duplicate.
        assert (
            bp.current_depth == 0
        ), f"Expected semaphore depth to remain 0 for duplicate message, got {bp.current_depth}"


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

    def test_get_schema_path_returns_none_for_unknown_topic(self) -> None:
        consumer = _make_consumer()
        assert consumer.get_schema_path("any.unknown.topic") is None

    def test_get_schema_path_returns_path_for_article_topic(self) -> None:
        """get_schema_path must return the .avsc path for the article stored topic."""
        consumer = _make_consumer()
        path = consumer.get_schema_path("content.article.stored.v1")
        assert path is not None
        assert path.endswith("content.article.stored.v1.avsc")

    def test_deserialize_value_json_fallback_without_magic_byte(self) -> None:
        """Plain JSON bytes (no 0x00 magic byte) always fall back to JSON decoding."""
        consumer = _make_consumer()
        payload = {"doc_id": "xyz", "source_type": "sec"}
        raw = json.dumps(payload).encode()
        # Even when schema_path is provided, lack of magic byte → JSON path
        result = consumer.deserialize_value(raw, schema_path="/some/schema.avsc")
        assert result["doc_id"] == "xyz"

    def test_deserialize_value_confluent_avro(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Consumer decodes Confluent Avro wire format (magic byte + 4-byte schema_id + payload)."""
        import io

        import fastavro

        schema = {
            "type": "record",
            "name": "ArticleStored",
            "fields": [
                {"name": "event_id", "type": "string"},
                {"name": "doc_id", "type": "string"},
            ],
        }
        schema_file = tmp_path / "article.avsc"
        schema_file.write_text(json.dumps(schema))

        parsed = fastavro.parse_schema(schema)
        record = {"event_id": "ev-001", "doc_id": "doc-abc"}
        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, parsed, record)
        payload = buf.getvalue()

        # Confluent wire format: 0x00 magic + 4-byte big-endian schema_id
        schema_id = 3
        confluent_bytes = b"\x00" + schema_id.to_bytes(4, "big") + payload

        consumer = _make_consumer()
        result = consumer.deserialize_value(confluent_bytes, schema_path=str(schema_file))
        assert result["event_id"] == "ev-001"
        assert result["doc_id"] == "doc-abc"


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
        # PLAN-0062 Wave B: payload is now Confluent-Avro wire format (5-byte
        # magic header + Avro body) — decode via the same helper the consumer
        # uses.  Empty raw_* arrays serialise as ``raw_*_json = None`` per
        # ``encode_raw_array``'s contract (the Avro union picks the null branch).
        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import _SCHEMA_DIR

        from messaging.kafka.serialization_utils import deserialize_confluent_avro

        wire_bytes = call_kwargs.kwargs["payload_avro"]
        assert wire_bytes[:1] == b"\x00", "Confluent-Avro magic byte missing"
        schema_path = str(_SCHEMA_DIR / "nlp.article.enriched.v1.avsc")
        payload = deserialize_confluent_avro(schema_path, wire_bytes)
        assert payload["doc_id"] == str(doc_id)
        assert payload["routing_tier"] == "medium"
        assert payload["event_type"] == "nlp.article.enriched"
        # KG-001 / KG-002 closure: enriched payload MUST carry the extracted
        # arrays so S7 can materialise relations, events, and claims.  Under
        # Avro encoding they are transported as JSON-string fields (PLAN-0062
        # Wave B); empty arrays serialise as None per the encode_raw_array
        # contract.
        assert "raw_relations_json" in payload
        assert "raw_events_json" in payload
        assert "raw_claims_json" in payload
        assert payload["raw_relations_json"] is None
        assert payload["raw_events_json"] is None
        assert payload["raw_claims_json"] is None

    # ── D-INIT-6 (2026-05-09): source_name propagation regression tests ──
    #
    # Behaviour change: ``_enqueue_enriched`` now accepts ``source_name`` and
    # serialises it onto the ``nlp.article.enriched.v1`` payload. The KG
    # consumer reads it directly (no DB fallback). These tests guard the
    # producer side of the contract — if the field is dropped here the KG side
    # will silently lose source provenance, which previously caused the entire
    # intelligence layer to produce zero narratives.

    @pytest.mark.asyncio
    async def test_enriched_payload_includes_source_name_when_provided(self) -> None:
        """When the inbound event carried a source_name, it rides through to the outbox payload."""
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
            source_name="EODHD News",
            published_at=datetime.now(tz=UTC),
            is_backfill=False,
            routing_decision=rd,
            sections=[],
            chunks=[],
            mentions=[],
            extraction_result={"events": [], "claims": [], "relations": []},
            correlation_id=None,
        )

        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import _SCHEMA_DIR

        from messaging.kafka.serialization_utils import deserialize_confluent_avro

        wire_bytes = outbox_repo.add.call_args.kwargs["payload_avro"]
        schema_path = str(_SCHEMA_DIR / "nlp.article.enriched.v1.avsc")
        payload = deserialize_confluent_avro(schema_path, wire_bytes)
        # Critical assertion: source_name made it onto the wire.
        assert payload["source_name"] == "EODHD News", (
            "D-INIT-6 regression: source_name was supplied to _enqueue_enriched but did not "
            "appear in the serialised Avro payload — KG consumer will fall back to None."
        )
        # source_type is the existing field; both should coexist.
        assert payload["source_type"] == "eodhd"

    @pytest.mark.asyncio
    async def test_enriched_payload_source_name_is_null_when_not_provided(self) -> None:
        """When the inbound event lacked source_name, the payload carries the Avro null branch.

        We default ``source_name`` to None at the function signature level so legacy
        callers (and unit tests that don't yet supply the new kwarg) keep working.
        The Avro union ``["null", "string"]`` then encodes as null on the wire.
        """
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

        # Note: source_name omitted — exercises the default-None branch.
        await _enqueue_enriched(
            outbox_repo=outbox_repo,
            settings=settings,
            doc_id=doc_id,
            source_type="rss",
            published_at=datetime.now(tz=UTC),
            is_backfill=False,
            routing_decision=rd,
            sections=[],
            chunks=[],
            mentions=[],
            extraction_result={"events": [], "claims": [], "relations": []},
            correlation_id=None,
        )

        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import _SCHEMA_DIR

        from messaging.kafka.serialization_utils import deserialize_confluent_avro

        wire_bytes = outbox_repo.add.call_args.kwargs["payload_avro"]
        schema_path = str(_SCHEMA_DIR / "nlp.article.enriched.v1.avsc")
        payload = deserialize_confluent_avro(schema_path, wire_bytes)
        # Avro decodes null union branch back to Python None.
        assert payload["source_name"] is None
        assert payload["source_type"] == "rss"


# ── D-004: nlp commit failure logging (T-A-2-04) ─────────────────────────────


def _make_intel_session_factory() -> tuple[AsyncMock, MagicMock]:
    """Build (intel_session, session_factory) that returns a proper async context manager.

    D-004: _run_pipeline now opens intel_session at the top level via
    ``async with self._intel_sf() as intel_session``, so the factory must
    return an object that supports ``__aenter__``/``__aexit__``.
    """
    intel_session = AsyncMock()
    intel_session.add = MagicMock()
    intel_session.commit = AsyncMock()

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=intel_session)
    cm.__aexit__ = AsyncMock(return_value=False)

    sf = MagicMock()
    sf.return_value = cm
    return intel_session, sf


def _make_failing_nlp_session_factory() -> tuple[AsyncMock, MagicMock]:
    """Build (session, session_factory) where session.commit raises RuntimeError."""
    session = AsyncMock()
    # scalar_one_or_none must return None so the idempotency guard in _run_pipeline
    # does not short-circuit before the pipeline runs (and commit fails as intended).
    _exec_result = MagicMock()
    _exec_result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=_exec_result)
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
        """When session.commit() raises, nlp_commit_failed_intel_writes_rolled_back is logged."""
        doc_id = uuid.uuid4()
        _session, nlp_sf = _make_failing_nlp_session_factory()
        _intel_session, intel_sf = _make_intel_session_factory()

        consumer = _make_consumer(
            nlp_session_factory=nlp_sf,
            intelligence_session_factory=intel_sf,
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
            e.get("event") == "nlp_commit_failed_intel_writes_rolled_back" and str(doc_id) in str(e.get("doc_id", ""))
            for e in cap
        ), f"Expected warning not found in: {cap}"

    @pytest.mark.asyncio
    async def test_nlp_commit_failure_reraises(self) -> None:
        """The RuntimeError from session.commit() is re-raised after the warning log."""
        doc_id = uuid.uuid4()
        _session, nlp_sf = _make_failing_nlp_session_factory()
        _intel_session, intel_sf = _make_intel_session_factory()

        consumer = _make_consumer(
            nlp_session_factory=nlp_sf,
            intelligence_session_factory=intel_sf,
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


# ── T-B-1-04: source metadata write tests ────────────────────────────────────


@pytest.mark.unit
class TestSourceMetadataWrite:
    @pytest.mark.asyncio
    async def test_consumer_writes_metadata_on_success(self) -> None:
        """_write_source_metadata calls repo.upsert with correct field values."""
        doc_id = uuid.uuid4()

        upsert_calls: list[object] = []

        async def _fake_upsert(metadata: object) -> None:
            upsert_calls.append(metadata)

        mock_repo = AsyncMock()
        mock_repo.upsert = _fake_upsert

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        nlp_sf = MagicMock(return_value=mock_cm)

        consumer = _make_consumer(nlp_session_factory=nlp_sf)

        with patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer"
            ".SQLAlchemyDocumentSourceMetadataRepository",
            return_value=mock_repo,
        ):
            await consumer._write_source_metadata(
                doc_id=doc_id,
                title="Earnings Report",
                url="https://sec.gov/doc",
                published_at=None,
                source_name="SEC EDGAR",
                source_type="sec_10q",
                word_count=8000,
            )

        assert len(upsert_calls) == 1
        m = upsert_calls[0]
        assert hasattr(m, "doc_id") and m.doc_id == doc_id  # type: ignore[union-attr]
        assert hasattr(m, "title") and m.title == "Earnings Report"  # type: ignore[union-attr]
        assert hasattr(m, "source_type") and m.source_type == "sec_10q"  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_consumer_continues_on_metadata_failure(self) -> None:
        """If the metadata repo raises, _write_source_metadata logs a warning and does not re-raise."""
        doc_id = uuid.uuid4()

        mock_repo = AsyncMock()
        mock_repo.upsert = AsyncMock(side_effect=RuntimeError("db unavailable"))

        mock_session = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        nlp_sf = MagicMock(return_value=mock_cm)

        consumer = _make_consumer(nlp_session_factory=nlp_sf)

        with patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer"
            ".SQLAlchemyDocumentSourceMetadataRepository",
            return_value=mock_repo,
        ):
            with capture_logs() as cap:
                # Must NOT raise
                await consumer._write_source_metadata(
                    doc_id=doc_id,
                    title=None,
                    url=None,
                    published_at=None,
                    source_name=None,
                    source_type="eodhd_news",
                    word_count=None,
                )

        assert any(
            e.get("event") == "source_metadata_write_failed" for e in cap
        ), f"Expected warning not found in logs: {cap}"


# ── T-A-4-02: price_impact signal wiring tests ───────────────────────────────


def _make_ok_nlp_session_factory() -> MagicMock:
    """Build a mock session factory whose session always commits successfully."""
    session = AsyncMock()
    # scalar_one_or_none must return None so the idempotency guard in _run_pipeline
    # does not short-circuit before the pipeline runs.
    _exec_result = MagicMock()
    _exec_result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=_exec_result)
    session.add = MagicMock()
    session.commit = AsyncMock()

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    return MagicMock(return_value=cm)


_PIPELINE_PATCHES_NO_ROUTING = (
    patch("nlp_pipeline.infrastructure.messaging.consumers.article_consumer.section_document", return_value=[]),
    patch(
        "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.run_ner_block",
        new=AsyncMock(return_value=([], MagicMock())),
    ),
    patch(
        "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.apply_suppression_gate",
        return_value="halt",
    ),
    patch(
        "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.run_embeddings_block",
        new=AsyncMock(return_value=([], [], [], [])),
    ),
    patch("nlp_pipeline.infrastructure.messaging.consumers.article_consumer._enqueue_enriched", new=AsyncMock()),
)


@pytest.mark.unit
class TestPriceImpactSignalLookup:
    """Tests for T-A-4-02: price_impact signal wiring into Block 5 (PRD-0026 §6.7)."""

    @pytest.mark.asyncio
    async def test_consumer_uses_price_impact_zero_when_no_label(self) -> None:
        """When article_impact_windows has no row, price_impact_score=0.0 is passed to routing."""
        from decimal import Decimal

        doc_id = uuid.uuid4()
        nlp_sf = _make_ok_nlp_session_factory()

        consumer = _make_consumer(nlp_session_factory=nlp_sf)
        consumer._watchlist = MagicMock()
        consumer._watchlist.get_all_watched = AsyncMock(return_value=frozenset())

        routing_kwargs: list[dict] = []

        def _capture_routing(*args: object, **kwargs: object) -> MagicMock:
            routing_kwargs.append(kwargs)  # type: ignore[arg-type]
            return MagicMock()

        mock_impact_repo = AsyncMock()
        mock_impact_repo.get_max_impact_for_doc = AsyncMock(return_value=Decimal("0.0"))

        run_patches = [
            *_PIPELINE_PATCHES_NO_ROUTING,
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.compute_routing_score",
                side_effect=_capture_routing,
            ),
            patch(
                "nlp_pipeline.infrastructure.nlp_db.repositories.impact_window.ArticleImpactWindowRepository",
                return_value=mock_impact_repo,
            ),
        ]

        with patch.object(consumer, "_download_article", new=AsyncMock(return_value="text")):
            for p in run_patches:
                p.start()
            try:
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
                for p in run_patches:
                    p.stop()

        assert routing_kwargs, "compute_routing_score was not called"
        assert routing_kwargs[0].get("price_impact_score") == 0.0

    @pytest.mark.asyncio
    async def test_consumer_uses_max_price_impact_across_entities(self) -> None:
        """When article_impact_windows repo returns 0.7, price_impact_score=0.7 is passed to routing."""
        from decimal import Decimal

        doc_id = uuid.uuid4()
        nlp_sf = _make_ok_nlp_session_factory()

        consumer = _make_consumer(nlp_session_factory=nlp_sf)
        consumer._watchlist = MagicMock()
        consumer._watchlist.get_all_watched = AsyncMock(return_value=frozenset())

        routing_kwargs: list[dict] = []

        def _capture_routing(*args: object, **kwargs: object) -> MagicMock:
            routing_kwargs.append(kwargs)  # type: ignore[arg-type]
            return MagicMock()

        mock_impact_repo = AsyncMock()
        mock_impact_repo.get_max_impact_for_doc = AsyncMock(return_value=Decimal("0.7"))

        run_patches = [
            *_PIPELINE_PATCHES_NO_ROUTING,
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.compute_routing_score",
                side_effect=_capture_routing,
            ),
            patch(
                "nlp_pipeline.infrastructure.nlp_db.repositories.impact_window.ArticleImpactWindowRepository",
                return_value=mock_impact_repo,
            ),
        ]

        with patch.object(consumer, "_download_article", new=AsyncMock(return_value="text")):
            for p in run_patches:
                p.start()
            try:
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
                for p in run_patches:
                    p.stop()

        assert routing_kwargs, "compute_routing_score was not called"
        assert abs(float(routing_kwargs[0].get("price_impact_score", -1)) - 0.7) < 1e-9


# ── D-3: signal event emission tests ─────────────────────────────────────────


def _make_signal_event(entity_id: uuid.UUID | None = None) -> object:
    """Build a mock SignalEvent-like object matching the domain model fields."""
    from nlp_pipeline.domain.models import SignalEvent

    return SignalEvent(
        signal_id=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        entity_id=entity_id or uuid.uuid4(),
        signal_type="earnings_beat",
        confidence=0.92,
        evidence_text="Company beat consensus estimates by 15%.",
        detected_at=datetime(2026, 4, 11, 12, 0, 0, tzinfo=UTC),
    )


@pytest.mark.unit
class TestEnqueueSignalEvents:
    """Tests for D-3 bug fix: _enqueue_signal_events writes outbox records."""

    @pytest.mark.asyncio
    async def test_signal_event_written_to_outbox(self) -> None:
        """Each SignalEvent produces one outbox.add call with correct payload fields."""
        signal = _make_signal_event()
        outbox_repo = AsyncMock()
        settings = _make_settings()

        await _enqueue_signal_events(
            outbox_repo=outbox_repo,
            settings=settings,
            signals=[signal],
            doc_id=signal.doc_id,  # type: ignore[union-attr]
            is_backfill=False,
            correlation_id="corr-abc",
        )

        outbox_repo.add.assert_called_once()
        kwargs = outbox_repo.add.call_args.kwargs
        assert kwargs["topic"] == "nlp.signal.detected.v1"
        assert kwargs["partition_key"] == str(signal.entity_id)  # type: ignore[union-attr]

        # PLAN-0062 F-006: outbox payload is Confluent-Avro framed bytes
        # (5-byte ``\x00<schema-id>`` header + Avro body), not raw JSON.
        from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]
        from messaging.kafka.serialization_utils import (  # type: ignore[import-untyped]
            deserialize_confluent_avro,
        )

        raw_payload = kwargs["payload_avro"]
        assert raw_payload[:1] == b"\x00", "expected Confluent-Avro framed bytes"
        payload = deserialize_confluent_avro(
            get_schema_path("nlp.signal.detected.v1.avsc"),
            raw_payload,
        )
        assert payload["event_type"] == "nlp.signal.detected"
        assert payload["claim_id"] == str(signal.signal_id)  # type: ignore[union-attr]
        assert payload["subject_entity_id"] == str(signal.entity_id)  # type: ignore[union-attr]
        assert payload["claim_type"] == signal.signal_type  # type: ignore[union-attr]
        assert payload["market_impact_score"] == 0.0
        assert payload["polarity"] == "neutral"
        assert payload["extraction_confidence"] == pytest.approx(signal.confidence)  # type: ignore[union-attr]
        assert payload["is_backfill"] is False
        assert payload["correlation_id"] == "corr-abc"
        assert payload["schema_version"] == 1

    @pytest.mark.asyncio
    async def test_multiple_signals_produce_multiple_outbox_calls(self) -> None:
        """Two signals → two outbox.add calls, each with distinct entity partition keys."""
        entity_a = uuid.uuid4()
        entity_b = uuid.uuid4()
        signals = [_make_signal_event(entity_a), _make_signal_event(entity_b)]
        outbox_repo = AsyncMock()
        settings = _make_settings()

        await _enqueue_signal_events(
            outbox_repo=outbox_repo,
            settings=settings,
            signals=signals,
            doc_id=uuid.uuid4(),
            is_backfill=True,
            correlation_id=None,
        )

        assert outbox_repo.add.call_count == 2
        keys = {c.kwargs["partition_key"] for c in outbox_repo.add.call_args_list}
        assert str(entity_a) in keys
        assert str(entity_b) in keys

    @pytest.mark.asyncio
    async def test_empty_signals_list_skips_outbox(self) -> None:
        """No signals → outbox.add is never called."""
        outbox_repo = AsyncMock()
        settings = _make_settings()

        await _enqueue_signal_events(
            outbox_repo=outbox_repo,
            settings=settings,
            signals=[],
            doc_id=uuid.uuid4(),
            is_backfill=False,
            correlation_id=None,
        )

        outbox_repo.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_consumer_emits_signal_events_when_deep_extraction_returns_signals(self) -> None:
        """article_consumer calls _enqueue_signal_events when run_deep_extraction_block
        returns a non-empty signal list (integration of the full _run_pipeline path)."""
        from decimal import Decimal

        doc_id = uuid.uuid4()
        nlp_sf = _make_ok_nlp_session_factory()
        signal = _make_signal_event()

        consumer = _make_consumer(nlp_session_factory=nlp_sf)
        consumer._watchlist = MagicMock()
        consumer._watchlist.get_all_watched = AsyncMock(return_value=frozenset())

        deep_extraction_mock = AsyncMock(return_value=({"events": [], "claims": [], "relations": []}, [signal]))
        mock_impact_repo = AsyncMock()
        mock_impact_repo.get_max_impact_for_doc = AsyncMock(return_value=Decimal("0.0"))

        captured_signal_calls: list[dict] = []

        async def _capture_enqueue_signal(**kwargs: Any) -> None:
            captured_signal_calls.append(kwargs)

        run_patches = [
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
                return_value="full_pipeline",
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.should_run_deep_extraction",
                return_value=True,
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.run_embeddings_block",
                new=AsyncMock(return_value=([], [], [], [])),
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.run_deep_extraction_block",
                new=deep_extraction_mock,
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer._enqueue_enriched",
                new=AsyncMock(),
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer._enqueue_signal_events",
                new=AsyncMock(side_effect=_capture_enqueue_signal),
            ),
            patch(
                "nlp_pipeline.infrastructure.nlp_db.repositories.impact_window.ArticleImpactWindowRepository",
                return_value=mock_impact_repo,
            ),
        ]

        with patch.object(consumer, "_download_article", new=AsyncMock(return_value="text")):
            for p in run_patches:
                p.start()
            try:
                await consumer._run_pipeline(
                    doc_id=doc_id,
                    minio_key="bucket/key",
                    source_type="eodhd",
                    published_at=None,
                    extracted_at=datetime.now(UTC),
                    is_backfill=False,
                    correlation_id="corr-123",
                )
            finally:
                for p in run_patches:
                    p.stop()

        assert len(captured_signal_calls) == 1, "Expected _enqueue_signal_events to be called once"
        call_kwargs = captured_signal_calls[0]
        assert call_kwargs["signals"] == [signal]
        assert call_kwargs["doc_id"] == doc_id
        assert call_kwargs["is_backfill"] is False
        assert call_kwargs["correlation_id"] == "corr-123"

    @pytest.mark.asyncio
    async def test_consumer_skips_signal_emission_when_deep_extraction_returns_empty(self) -> None:
        """article_consumer does NOT call _enqueue_signal_events when signals list is empty."""
        from decimal import Decimal

        doc_id = uuid.uuid4()
        nlp_sf = _make_ok_nlp_session_factory()

        consumer = _make_consumer(nlp_session_factory=nlp_sf)
        consumer._watchlist = MagicMock()
        consumer._watchlist.get_all_watched = AsyncMock(return_value=frozenset())

        deep_extraction_mock = AsyncMock(return_value=({"events": [], "claims": [], "relations": []}, []))
        mock_impact_repo = AsyncMock()
        mock_impact_repo.get_max_impact_for_doc = AsyncMock(return_value=Decimal("0.0"))

        enqueue_signal_spy = AsyncMock()

        run_patches = [
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
                return_value="full_pipeline",
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.should_run_deep_extraction",
                return_value=True,
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.run_embeddings_block",
                new=AsyncMock(return_value=([], [], [], [])),
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.run_deep_extraction_block",
                new=deep_extraction_mock,
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer._enqueue_enriched",
                new=AsyncMock(),
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer._enqueue_signal_events",
                new=enqueue_signal_spy,
            ),
            patch(
                "nlp_pipeline.infrastructure.nlp_db.repositories.impact_window.ArticleImpactWindowRepository",
                return_value=mock_impact_repo,
            ),
        ]

        with patch.object(consumer, "_download_article", new=AsyncMock(return_value="text")):
            for p in run_patches:
                p.start()
            try:
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
                for p in run_patches:
                    p.stop()

        enqueue_signal_spy.assert_not_called()


# ---------------------------------------------------------------------------
# KG-002 closure: _build_raw_claims() unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildRawClaims:
    """Validate that _build_raw_claims() correctly converts LLM extraction
    claims into the dict format S7 expects, resolving entity refs and skipping
    unresolved ones."""

    def test_basic_claim_conversion(self) -> None:
        """A claim with a resolvable entity_ref produces the correct dict."""
        entity_id = str(uuid.uuid4())
        claims = [
            {
                "entity_ref": "AAPL",
                "claim_type": "analyst_rating",
                "polarity": "positive",
                "evidence_text": "Analyst upgraded AAPL to Buy",
                "confidence": 0.92,
            },
        ]
        entity_id_by_ref = {"aapl": entity_id}

        result = _build_raw_claims(claims, entity_id_by_ref, set())

        assert len(result) == 1
        claim = result[0]
        assert claim["subject_entity_id"] == entity_id
        assert claim["claim_type"] == "analyst_rating"
        assert claim["polarity"] == "positive"
        assert claim["claim_text"] == "Analyst upgraded AAPL to Buy"
        assert claim["extraction_confidence"] == pytest.approx(0.92)

    def test_unresolved_entity_ref_is_skipped(self) -> None:
        """Claims whose entity_ref is not in the resolution map are dropped."""
        claims = [
            {
                "entity_ref": "UNKNOWN_TICKER",
                "claim_type": "revenue_guidance",
                "polarity": "negative",
                "evidence_text": "Revenue missed expectations",
                "confidence": 0.7,
            },
        ]
        entity_id_by_ref = {"aapl": str(uuid.uuid4())}

        result = _build_raw_claims(claims, entity_id_by_ref, set())

        assert len(result) == 0

    def test_multiple_claims_mixed_resolution(self) -> None:
        """Only claims with resolved entity refs are included in the output."""
        entity_id_a = str(uuid.uuid4())
        entity_id_b = str(uuid.uuid4())
        claims = [
            {"entity_ref": "AAPL", "claim_type": "buy_rating", "confidence": 0.9},
            {"entity_ref": "UNKNOWN", "claim_type": "sell_rating", "confidence": 0.8},
            {"entity_ref": "MSFT", "claim_type": "hold_rating", "confidence": 0.85},
        ]
        entity_id_by_ref = {"aapl": entity_id_a, "msft": entity_id_b}

        result = _build_raw_claims(claims, entity_id_by_ref, set())

        assert len(result) == 2
        assert result[0]["subject_entity_id"] == entity_id_a
        assert result[1]["subject_entity_id"] == entity_id_b

    def test_defaults_for_missing_optional_fields(self) -> None:
        """Missing polarity defaults to 'neutral', confidence to 0.5, etc."""
        entity_id = str(uuid.uuid4())
        claims = [{"entity_ref": "AAPL", "claim_type": "general"}]
        entity_id_by_ref = {"aapl": entity_id}

        result = _build_raw_claims(claims, entity_id_by_ref, set())

        assert len(result) == 1
        claim = result[0]
        assert claim["polarity"] == "neutral"
        assert claim["extraction_confidence"] == pytest.approx(0.5)
        assert claim["claim_text"] == ""

    def test_entity_ref_case_insensitive(self) -> None:
        """Entity ref lookup is case-insensitive (lowered before lookup)."""
        entity_id = str(uuid.uuid4())
        claims = [{"entity_ref": "AaPl", "claim_type": "rating"}]
        entity_id_by_ref = {"aapl": entity_id}

        result = _build_raw_claims(claims, entity_id_by_ref, set())

        assert len(result) == 1
        assert result[0]["subject_entity_id"] == entity_id

    def test_empty_claims_returns_empty_list(self) -> None:
        """Empty input produces empty output."""
        result = _build_raw_claims([], {"aapl": str(uuid.uuid4())}, set())
        assert result == []


# ── PLAN-0057 B-1 (F-CRIT-07): provisional flow in _build_raw_* helpers ──────


class TestBuildRawRelationsProvisional:
    """Wave B-1: relations referring to provisional surfaces are emitted
    with ``entity_provisional=True`` and ``provisional_queue_id`` set, instead
    of being silently dropped (the pre-fix behaviour for ~100% of relations
    on under-resolved articles).
    """

    @pytest.mark.unit
    def test_both_endpoints_resolved_no_provisional_flag(self) -> None:
        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
            _build_raw_relations,
        )

        aapl = str(uuid.uuid4())
        msft = str(uuid.uuid4())
        relations = [
            {"subject_ref": "Apple", "object_ref": "Microsoft", "predicate": "competes_with", "confidence": 0.9}
        ]
        out = _build_raw_relations(relations, {"apple": aapl, "microsoft": msft}, set())
        assert len(out) == 1
        assert out[0]["entity_provisional"] is False
        assert out[0]["provisional_queue_id"] is None
        assert out[0]["subject_entity_id"] == aapl
        assert out[0]["object_entity_id"] == msft

    @pytest.mark.unit
    def test_subject_provisional_emits_flag_and_queue_id(self) -> None:
        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
            _build_raw_relations,
        )

        aapl = str(uuid.uuid4())
        ecb_qid = str(uuid.uuid4())  # synthetic queue UUID for unresolved "ECB"
        relations = [{"subject_ref": "ECB", "object_ref": "Apple", "predicate": "regulates", "confidence": 0.7}]
        out = _build_raw_relations(relations, {"ecb": ecb_qid, "apple": aapl}, {"ecb"})
        assert len(out) == 1
        assert out[0]["entity_provisional"] is True
        assert out[0]["provisional_queue_id"] == ecb_qid

    @pytest.mark.unit
    def test_object_provisional_emits_flag_and_queue_id(self) -> None:
        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
            _build_raw_relations,
        )

        aapl = str(uuid.uuid4())
        fed_qid = str(uuid.uuid4())
        relations = [{"subject_ref": "Apple", "object_ref": "Fed", "predicate": "complies_with", "confidence": 0.6}]
        out = _build_raw_relations(relations, {"apple": aapl, "fed": fed_qid}, {"fed"})
        assert out[0]["entity_provisional"] is True
        assert out[0]["provisional_queue_id"] == fed_qid

    @pytest.mark.unit
    def test_both_provisional_emits_subject_queue_id(self) -> None:
        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
            _build_raw_relations,
        )

        a_qid = str(uuid.uuid4())
        b_qid = str(uuid.uuid4())
        relations = [{"subject_ref": "A", "object_ref": "B", "predicate": "x", "confidence": 0.5}]
        out = _build_raw_relations(relations, {"a": a_qid, "b": b_qid}, {"a", "b"})
        assert out[0]["entity_provisional"] is True
        # Convention: subject queue id wins when both are provisional.
        assert out[0]["provisional_queue_id"] == a_qid

    @pytest.mark.unit
    def test_truly_unresolved_ref_still_dropped(self) -> None:
        """A ref that's neither resolved nor in provisional_refs is still skipped."""
        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
            _build_raw_relations,
        )

        aapl = str(uuid.uuid4())
        relations = [{"subject_ref": "Apple", "object_ref": "UnknownCorp", "predicate": "x", "confidence": 0.5}]
        out = _build_raw_relations(relations, {"apple": aapl}, set())
        assert out == []

    @pytest.mark.unit
    def test_evidence_date_propagated_from_published_at(self) -> None:
        """SA-3 regression (2026-05-10): evidence_date must be published_at's ISO string.

        Without this, KG ``_parse_dt`` receives None and stamps every relation row with
        today's UTC datetime — all evidence clusters on the ingestion day and the
        90-day confidence trend chart shows a single point instead of a multi-day curve.
        """

        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
            _build_raw_relations,
        )

        aapl = str(uuid.uuid4())
        msft = str(uuid.uuid4())
        pub = datetime(2025, 3, 15, 8, 0, 0, tzinfo=UTC)
        relations = [
            {"subject_ref": "Apple", "object_ref": "Microsoft", "predicate": "competes_with", "confidence": 0.8}
        ]
        out = _build_raw_relations(
            relations,
            {"apple": aapl, "microsoft": msft},
            set(),
            published_at=pub,
        )
        assert len(out) == 1
        assert out[0]["evidence_date"] == pub.isoformat()

    @pytest.mark.unit
    def test_evidence_date_none_when_no_published_at(self) -> None:
        """Without published_at, evidence_date must be None (KG falls back to utc_now)."""
        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
            _build_raw_relations,
        )

        aapl = str(uuid.uuid4())
        msft = str(uuid.uuid4())
        relations = [
            {"subject_ref": "Apple", "object_ref": "Microsoft", "predicate": "competes_with", "confidence": 0.8}
        ]
        out = _build_raw_relations(relations, {"apple": aapl, "microsoft": msft}, set())
        assert len(out) == 1
        assert out[0]["evidence_date"] is None


class TestBuildRawEventsProvisional:
    @pytest.mark.unit
    def test_provisional_subject_emits_flag(self) -> None:
        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
            _build_raw_events,
        )

        ecb_qid = str(uuid.uuid4())
        events = [{"event_type": "MACRO", "description": "ECB hike", "entity_refs": ["ECB"], "confidence": 0.9}]
        out = _build_raw_events(events, {"ecb": ecb_qid}, {"ecb"})
        assert len(out) == 1
        assert out[0]["entity_provisional"] is True
        assert out[0]["provisional_queue_id"] == ecb_qid

    @pytest.mark.unit
    def test_resolved_subject_no_flag(self) -> None:
        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
            _build_raw_events,
        )

        aapl = str(uuid.uuid4())
        events = [
            {"event_type": "EARNINGS_RELEASE", "description": "Apple Q1", "entity_refs": ["Apple"], "confidence": 0.95}
        ]
        out = _build_raw_events(events, {"apple": aapl}, set())
        assert out[0]["entity_provisional"] is False
        assert out[0]["provisional_queue_id"] is None


class TestBuildRawClaimsProvisional:
    @pytest.mark.unit
    def test_provisional_subject_emits_flag(self) -> None:
        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
            _build_raw_claims,
        )

        ecb_qid = str(uuid.uuid4())
        claims = [
            {
                "entity_ref": "ECB",
                "claim_type": "GUIDANCE_RAISE",
                "polarity": "neutral",
                "confidence": 0.8,
                "evidence_text": "ECB guides higher",
            }
        ]
        out = _build_raw_claims(claims, {"ecb": ecb_qid}, {"ecb"})
        assert len(out) == 1
        assert out[0]["entity_provisional"] is True
        assert out[0]["provisional_queue_id"] == ecb_qid

    @pytest.mark.unit
    def test_resolved_subject_no_flag(self) -> None:
        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
            _build_raw_claims,
        )

        aapl = str(uuid.uuid4())
        claims = [
            {
                "entity_ref": "Apple",
                "claim_type": "EPS_BEAT",
                "polarity": "positive",
                "confidence": 0.95,
                "evidence_text": "beat",
            }
        ]
        out = _build_raw_claims(claims, {"apple": aapl}, set())
        assert out[0]["entity_provisional"] is False
        assert out[0]["provisional_queue_id"] is None
