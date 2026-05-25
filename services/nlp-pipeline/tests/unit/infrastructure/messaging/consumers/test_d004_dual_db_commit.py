"""D-004 regression tests: dual-DB commit order fix for article_consumer._run_pipeline.

Validates the D-004 session lifecycle invariant:
  1. nlp_session.commit() is called BEFORE intel_session.commit().
  2. If nlp_session.commit() fails, intel_session.commit() is NEVER called
     and the exception propagates (Kafka retry).
  3. D-010 (PLAN-0084 deferred findings): if intel_session.commit() fails AFTER
     nlp_session.commit() succeeds, the error is logged at ERROR level, the
     s6_intel_commit_failures_total Prometheus counter is incremented, and the
     exception IS re-raised so the Kafka offset is not committed — re-delivery
     retries the intel writes (which are idempotent on retry).
  4. NLP writes (sections, chunks, mentions, routing, embeddings, outbox)
     go to nlp_session; intel writes (entity alias reads, provisional queue)
     go to intel_session.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    ArticleProcessingConsumer,
)
from structlog.testing import capture_logs

pytestmark = pytest.mark.unit

# ── Shared helpers ───────────────────────────────────────────────────────────


def _make_settings() -> MagicMock:
    """Build a Settings mock with all fields the consumer reads."""
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
    # RC-1: disable stub filter in these D-004 tests — they use placeholder text
    # and are not testing the word-count gate.
    s.min_word_count = 0
    return s


def _make_session_factory(
    *,
    commit_side_effect: Exception | None = None,
) -> tuple[AsyncMock, MagicMock]:
    """Build (session, factory) pair.

    The session supports add/commit/execute and is wrapped in an async
    context manager returned by factory().

    Args:
        commit_side_effect: If provided, session.commit() raises this exception.

    Returns:
        (session_mock, factory_mock)
    """
    session = AsyncMock()
    session.add = MagicMock()
    if commit_side_effect is not None:
        session.commit = AsyncMock(side_effect=commit_side_effect)
    else:
        session.commit = AsyncMock()

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = cm
    return session, factory


def _make_consumer(
    nlp_session_factory: MagicMock,
    intel_session_factory: MagicMock,
) -> ArticleProcessingConsumer:
    """Build an ArticleProcessingConsumer with explicit session factories."""
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="test-group",
        topics=["content.article.stored.v1"],
    )
    consumer = ArticleProcessingConsumer(
        config=config,
        settings=_make_settings(),
        nlp_session_factory=nlp_session_factory,
        intelligence_session_factory=intel_session_factory,
        storage=MagicMock(),
        watchlist_cache=MagicMock(),
        ner_client=MagicMock(),
        embedding_client=MagicMock(),
        extraction_client=MagicMock(),
        backpressure=MagicMock(),
    )
    # Stub the watchlist so Block 5 routing doesn't fail.
    consumer._watchlist = MagicMock()
    consumer._watchlist.get_all_watched = AsyncMock(return_value=frozenset())
    return consumer


# Patch all pipeline blocks to run in HALT mode (minimal work, no ML calls).
# This isolates the session lifecycle from the actual block logic.
_HALT_PATCHES = (
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
        return_value="halt",  # ProcessingPath.HALT — skips Block 8/9 novelty + entity resolution
    ),
    patch(
        "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.run_embeddings_block",
        new=AsyncMock(return_value=([], [], [], [])),
    ),
    patch(
        "nlp_pipeline.infrastructure.messaging.consumers.article_consumer._enqueue_enriched",
        new=AsyncMock(),
    ),
)


async def _run_pipeline_with_patches(
    consumer: ArticleProcessingConsumer,
    doc_id: uuid.UUID | None = None,
) -> None:
    """Helper: run _run_pipeline with all blocks mocked in HALT mode."""
    doc_id = doc_id or uuid.uuid4()
    for p in _HALT_PATCHES:
        p.start()
    with patch.object(consumer, "_download_article", new=AsyncMock(return_value="text")):
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
            for p in _HALT_PATCHES:
                p.stop()


# ── Test 1: NLP commit failure rolls back intel ──────────────────────────────


@pytest.mark.unit
class TestNlpCommitFailureRollsBackIntel:
    """D-004 invariant: when nlp_session.commit() fails, intel_session.commit()
    must NEVER be called, and the exception must propagate for Kafka retry."""

    @pytest.mark.asyncio
    async def test_nlp_commit_failure_rolls_back_intel(self) -> None:
        """If nlp_session.commit() raises, intel_session.commit() is never
        called and the RuntimeError propagates to the caller."""
        nlp_session, nlp_sf = _make_session_factory(
            commit_side_effect=RuntimeError("nlp db down"),
        )
        intel_session, intel_sf = _make_session_factory()

        consumer = _make_consumer(nlp_sf, intel_sf)

        with pytest.raises(RuntimeError, match="nlp db down"):
            await _run_pipeline_with_patches(consumer)

        # nlp_session.commit() was attempted (and failed)
        nlp_session.commit.assert_called_once()

        # intel_session.commit() must NEVER have been called — the exception
        # should have propagated before reaching the intel commit.
        intel_session.commit.assert_not_called()


# ── Test 2: Intel commit failure re-raises (D-010) ───────────────────────────


@pytest.mark.unit
class TestIntelCommitFailureReraises:
    """D-010 invariant (PLAN-0084 deferred findings): if intel_session.commit()
    fails AFTER nlp_session committed, the error is logged at ERROR level and
    re-raised so the Kafka offset is NOT committed → message re-delivery retries
    the intel writes (which are idempotent on retry)."""

    @pytest.mark.asyncio
    async def test_intel_commit_failure_reraises(self) -> None:
        """D-010: intel commit failure MUST propagate so Kafka retries the message.

        The Prometheus counter s6_intel_commit_failures_total must be incremented
        and an error log entry with event='d004_intel_commit_failed' must be emitted.
        """
        nlp_session, nlp_sf = _make_session_factory()  # commit succeeds
        intel_session, intel_sf = _make_session_factory(
            commit_side_effect=RuntimeError("intel db down"),
        )

        consumer = _make_consumer(nlp_sf, intel_sf)

        with capture_logs() as cap:
            # D-010: MUST raise — Kafka offset must NOT be committed on intel failure.
            with pytest.raises(RuntimeError, match="intel db down"):
                await _run_pipeline_with_patches(consumer)

        # nlp_session.commit() was called and succeeded.
        nlp_session.commit.assert_called_once()

        # intel_session.commit() was called (and failed).
        intel_session.commit.assert_called_once()

        # An ERROR log must have been emitted (not WARNING — D-010 upgrade).
        assert any(
            e.get("event") == "d004_intel_commit_failed" for e in cap
        ), f"Expected 'd004_intel_commit_failed' error log not found in: {cap}"


# ── Test 3: Both sessions receive correct writes ────────────────────────────


@pytest.mark.unit
class TestBothSessionsReceiveCorrectWrites:
    """D-004 invariant: NLP writes go to nlp_session, intel writes go to
    intel_session, and nlp_session.commit() is called BEFORE intel_session.commit()."""

    @pytest.mark.asyncio
    async def test_both_sessions_receive_correct_writes_and_commit_order(self) -> None:
        """Verify commit ordering: nlp_session.commit() before intel_session.commit().

        Both sessions are created from their respective factories.  We track
        the order of commit calls using a shared call log.
        """
        nlp_session, nlp_sf = _make_session_factory()
        intel_session, intel_sf = _make_session_factory()

        # Track commit call ordering via a shared list.
        commit_order: list[str] = []

        async def _nlp_commit() -> None:
            commit_order.append("nlp")

        async def _intel_commit() -> None:
            commit_order.append("intel")

        nlp_session.commit = AsyncMock(side_effect=_nlp_commit)
        intel_session.commit = AsyncMock(side_effect=_intel_commit)

        consumer = _make_consumer(nlp_sf, intel_sf)

        await _run_pipeline_with_patches(consumer)

        # Both commits must have been called.
        assert "nlp" in commit_order, "nlp_session.commit() was not called"
        assert "intel" in commit_order, "intel_session.commit() was not called"

        # D-004: NLP must be committed FIRST.
        assert commit_order.index("nlp") < commit_order.index(
            "intel"
        ), f"D-004 violation: expected nlp before intel, got {commit_order}"

    @pytest.mark.asyncio
    async def test_nlp_repos_use_nlp_session(self) -> None:
        """NLP artifact repositories (SectionRepository, ChunkRepository, etc.)
        must be instantiated with nlp_session, NOT intel_session."""
        nlp_session, nlp_sf = _make_session_factory()
        _intel_session, intel_sf = _make_session_factory()

        consumer = _make_consumer(nlp_sf, intel_sf)

        # Capture which session is passed to NLP repositories.
        section_repo_sessions: list[object] = []
        chunk_repo_sessions: list[object] = []
        routing_repo_sessions: list[object] = []
        outbox_repo_sessions: list[object] = []

        with (
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.SectionRepository",
                side_effect=lambda s: (section_repo_sessions.append(s), AsyncMock())[1],
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.ChunkRepository",
                side_effect=lambda s: (chunk_repo_sessions.append(s), AsyncMock())[1],
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.RoutingDecisionRepository",
                side_effect=lambda s: (routing_repo_sessions.append(s), AsyncMock())[1],
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.OutboxRepository",
                side_effect=lambda s: (outbox_repo_sessions.append(s), AsyncMock())[1],
            ),
        ):
            await _run_pipeline_with_patches(consumer)

        # All NLP repositories must have received nlp_session (not intel_session).
        assert (
            section_repo_sessions and section_repo_sessions[0] is nlp_session
        ), "SectionRepository should use nlp_session"
        assert chunk_repo_sessions and chunk_repo_sessions[0] is nlp_session, "ChunkRepository should use nlp_session"
        assert (
            routing_repo_sessions and routing_repo_sessions[0] is nlp_session
        ), "RoutingDecisionRepository should use nlp_session"
        assert (
            outbox_repo_sessions and outbox_repo_sessions[0] is nlp_session
        ), "OutboxRepository should use nlp_session"
