"""W1-01 (BUG-001) regression tests: SUPPRESS-tier articles must NOT emit
``nlp.article.enriched.v1`` (nor signal/temporal events) downstream.

Before this fix, ``_enqueue_enriched`` was called unconditionally at the end of
``ArticleProcessingConsumer._run_pipeline`` regardless of ``ml.final_path``.
SUPPRESS articles have an empty extraction result, so S7 was consuming a
zero-extraction document and polluting the knowledge graph with dead-weight
relations.

These tests stub out every Block 3-10 ML call so we can drive ``_run_pipeline``
through the suppression gate without any real ML/DB infra.  The fixture style
mirrors ``test_d004_dual_db_commit.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nlp_pipeline.application.blocks.suppression import ProcessingPath
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    ArticleProcessingConsumer,
)
from nlp_pipeline.infrastructure.messaging.consumers.blocks.ml_phase import MLPhaseResult
from structlog.testing import capture_logs

pytestmark = pytest.mark.unit


# ── Shared helpers ───────────────────────────────────────────────────────────


def _make_settings() -> MagicMock:
    """Build a minimal Settings mock — the consumer reads many attributes."""
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


def _make_session_factory() -> tuple[AsyncMock, MagicMock]:
    """Build (session, factory) pair where factory() is an async CM yielding the session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = cm
    return session, factory


def _make_consumer() -> ArticleProcessingConsumer:
    """Build an ArticleProcessingConsumer with stubbed factories + watchlist."""
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    _nlp_s, nlp_sf = _make_session_factory()
    _intel_s, intel_sf = _make_session_factory()

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="test-group",
        topics=["content.article.stored.v1"],
    )
    consumer = ArticleProcessingConsumer(
        config=config,
        settings=_make_settings(),
        nlp_session_factory=nlp_sf,
        intelligence_session_factory=intel_sf,
        storage=MagicMock(),
        watchlist_cache=MagicMock(),
        ner_client=MagicMock(),
        embedding_client=MagicMock(),
        extraction_client=MagicMock(),
        backpressure=MagicMock(),
    )
    consumer._watchlist = MagicMock()
    consumer._watchlist.get_all_watched = AsyncMock(return_value=frozenset())
    return consumer


def _make_ml_phase_result(final_path: ProcessingPath) -> MLPhaseResult:
    """Build an MLPhaseResult with a configurable ``final_path``.

    Mirrors the post-suppression / post-novelty state of the real pipeline:
    SUPPRESS articles arrive here with an empty extraction_result and no signals.
    """
    return MLPhaseResult(
        routing_decision=MagicMock(),
        final_path=final_path,
        final_mentions=[],
        pending_resolution_audit=[],
        extraction_result={"events": [], "relations": [], "claims": []},
        signals=[],
    )


# Pipeline-wide patches: short-circuit every Block 3-10 call so we exercise
# only the outbox-emission tail of ``_run_pipeline``.  ``run_ml_phase`` is
# patched per-test because its return value (HALT vs FULL_PIPELINE) is the
# thing we are asserting on.
def _common_patches() -> tuple[Any, ...]:
    return (
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.section_document",
            return_value=[],
        ),
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
            return_value=ProcessingPath.HALT,
        ),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.run_embeddings_block",
            new=AsyncMock(return_value=([], [], [], [])),
        ),
        # persist_artifacts is patched to return its inputs unchanged so the
        # outbox-emission tail runs against the same (mocked) repos.
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.persist_artifacts",
            new=AsyncMock(
                return_value=(
                    MagicMock(),  # routing_decision
                    [],  # chunks
                    [],  # final_mentions
                    AsyncMock(),  # outbox_repo
                )
            ),
        ),
    )


async def _drive_run_pipeline(
    consumer: ArticleProcessingConsumer,
    *,
    ml_phase_result: MLPhaseResult,
) -> None:
    """Helper: invoke ``_run_pipeline`` with all Block 3-10 calls stubbed.

    ``run_ml_phase`` is patched to return ``ml_phase_result`` so the caller
    controls ``ml.final_path``.
    """
    patches = (
        *_common_patches(),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.run_ml_phase",
            new=AsyncMock(return_value=ml_phase_result),
        ),
    )
    for p in patches:
        p.start()
    try:
        with patch.object(consumer, "_download_article", new=AsyncMock(return_value="text")):
            await consumer._run_pipeline(
                doc_id=uuid.uuid4(),
                minio_key="bucket/key",
                source_type="eodhd",
                published_at=None,
                extracted_at=datetime.now(UTC),
                is_backfill=False,
                correlation_id=None,
            )
    finally:
        for p in patches:
            p.stop()


# ── Test 1: HALT must NOT emit the enriched event ────────────────────────────


@pytest.mark.unit
class TestHaltSkipsEnrichedEvent:
    """W1-01 (BUG-001): articles whose final_path==HALT must not emit
    ``nlp.article.enriched.v1`` — S7 would pollute the KG with dead-weight."""

    @pytest.mark.asyncio
    async def test_halt_skips_enqueue_enriched(self) -> None:
        consumer = _make_consumer()
        ml = _make_ml_phase_result(ProcessingPath.HALT)

        with (
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer._enqueue_enriched",
                new=AsyncMock(),
            ) as enq_enriched,
            capture_logs() as cap,
        ):
            await _drive_run_pipeline(consumer, ml_phase_result=ml)

        # The enriched-event emission MUST NOT have been called on HALT.
        enq_enriched.assert_not_called()

        # And the explicit skip log line must have been emitted so operators
        # can detect the gate is firing as intended.
        assert any(
            e.get("event") == "article_suppressed_skipping_enriched_event" for e in cap
        ), f"Expected 'article_suppressed_skipping_enriched_event' log not found in: {cap}"


# ── Test 2: FULL_PIPELINE still emits (non-regression) ───────────────────────


@pytest.mark.unit
class TestFullPipelineStillEmits:
    """Non-regression: articles whose final_path==FULL_PIPELINE (MEDIUM/DEEP)
    must continue to emit the enriched event — the gate must be HALT-only."""

    @pytest.mark.asyncio
    async def test_full_pipeline_emits_enqueue_enriched(self) -> None:
        consumer = _make_consumer()
        ml = _make_ml_phase_result(ProcessingPath.FULL_PIPELINE)

        with patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer._enqueue_enriched",
            new=AsyncMock(),
        ) as enq_enriched:
            await _drive_run_pipeline(consumer, ml_phase_result=ml)

        enq_enriched.assert_called_once()


# ── Test 3: HALT also skips signal + temporal event emission ────────────────


@pytest.mark.unit
class TestHaltSkipsSignalAndTemporalEvents:
    """Contract test: the HALT gate must cover all three downstream emissions
    (enriched, signal, temporal).  Even though ``ml.signals`` is empty on HALT
    (so ``if ml.signals`` would already skip the signal call) and
    ``_maybe_emit_temporal_events`` short-circuits on empty events, this test
    pins the contract explicitly so a future refactor that loosens the inner
    guards cannot regress BUG-001.
    """

    @pytest.mark.asyncio
    async def test_halt_skips_signal_and_temporal(self) -> None:
        consumer = _make_consumer()
        ml = _make_ml_phase_result(ProcessingPath.HALT)

        with (
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer._enqueue_enriched",
                new=AsyncMock(),
            ) as enq_enriched,
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer._enqueue_signal_events",
                new=AsyncMock(),
            ) as enq_signal,
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer._maybe_emit_temporal_events",
                new=AsyncMock(),
            ) as emit_temporal,
        ):
            await _drive_run_pipeline(consumer, ml_phase_result=ml)

        enq_enriched.assert_not_called()
        enq_signal.assert_not_called()
        emit_temporal.assert_not_called()
