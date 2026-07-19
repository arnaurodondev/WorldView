"""BP-719 Mode B — searchable chunks survive an ML-phase failure / watchdog timeout.

End-to-end (block-mocked) test of ``ArticleProcessingConsumer._run_pipeline``:
the searchable artefacts (sections + chunks + embeddings) are committed in their
OWN transaction BEFORE Blocks 8-10, so when the ML phase raises (a proxy for the
900s watchdog cancelling deep extraction on a large 10-Q) the chunks are STILL
persisted and the document remains searchable — only the enrichment transaction
rolls back.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nlp_pipeline.domain.enums import ProcessingPath
from nlp_pipeline.domain.models import Chunk, RoutingDecision, Section
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    ArticleProcessingConsumer,
)

pytestmark = pytest.mark.unit

_MOD = "nlp_pipeline.infrastructure.messaging.consumers.article_consumer"


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.min_word_count = 0
    s.gliner_threshold = 0.35
    s.gliner_batch_size = 32
    s.gliner_section_token_limit = 450
    s.ner_model_id = "gliner"
    s.gliner_mention_floor = 0.6
    s.embedding_model_id = "bge-large-en-v1.5"
    s.embedding_instruction_prefix = "Represent: "
    s.learned_router_mode = "off"  # skip the learned-router shadow entirely
    # VALUE-signal override (feat/value-signal-routing): the consumer reads these in the
    # hot path; a bare MagicMock would make event_value_min_hits a MagicMock and break the
    # ``len(matched) >= min_hits`` comparison. Mirror the real production defaults.
    s.event_value_override_enabled = True
    s.event_value_categories_set = None
    s.event_value_min_hits = 1
    s.event_value_scan_chars = 600
    return s


def _distinct_factory(sessions: list[AsyncMock]) -> MagicMock:
    """Factory returning a FRESH tracked session per call (phase 1 vs phase 2)."""

    def _new_cm() -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        sessions.append(session)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    return MagicMock(side_effect=_new_cm)


def _section() -> Section:
    return Section(
        section_id=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        section_index=0,
        char_start=0,
        char_end=20,
        text="Revenue was strong.",
        section_type="body",
        title="Item 2",
    )


def _chunk(section: Section) -> Chunk:
    return Chunk(
        chunk_id=uuid.uuid4(),
        doc_id=section.doc_id,
        section_id=section.section_id,
        chunk_index=0,
        char_start=0,
        char_end=20,
        token_count=4,
        text="Revenue was strong.",
    )


@pytest.mark.asyncio
async def test_chunks_committed_before_ml_failure() -> None:
    """When run_ml_phase raises, the searchable chunks are ALREADY committed."""
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    nlp_sessions: list[AsyncMock] = []
    intel_sessions: list[AsyncMock] = []
    nlp_sf = _distinct_factory(nlp_sessions)
    intel_sf = _distinct_factory(intel_sessions)

    consumer = ArticleProcessingConsumer(
        config=ConsumerConfig(bootstrap_servers="x:9092", group_id="g", topics=["content.article.stored.v1"]),
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

    section = _section()
    chunk = _chunk(section)

    # Capture the chunk repositories that get created so we can assert the
    # searchable chunk write happened.
    chunk_repos: list[AsyncMock] = []

    def _mk_chunk_repo(_s: object) -> AsyncMock:
        repo = AsyncMock()
        chunk_repos.append(repo)
        return repo

    with (
        patch.object(consumer, "_download_article", new=AsyncMock(return_value="Revenue was strong. " * 10)),
        patch(f"{_MOD}.section_document", return_value=[section]),
        patch(f"{_MOD}.run_ner_block", new=AsyncMock(return_value=([], MagicMock()))),
        patch(f"{_MOD}.compute_routing_score", return_value=MagicMock(spec=RoutingDecision)),
        patch(f"{_MOD}.apply_suppression_gate", return_value=ProcessingPath.FULL_PIPELINE),
        patch(
            f"{_MOD}.run_embeddings_block",
            new=AsyncMock(return_value=([chunk], [(chunk.chunk_id, [0.1])], [], None)),
        ),
        patch(f"{_MOD}.SectionRepository", side_effect=lambda s: AsyncMock()),
        patch(f"{_MOD}.ChunkRepository", side_effect=_mk_chunk_repo),
        # The ML phase blows up — proxy for the 900s watchdog cancelling deep
        # extraction on a large 10-Q. It MUST NOT take the chunks down with it.
        patch(f"{_MOD}.run_ml_phase", new=AsyncMock(side_effect=RuntimeError("deep-extraction timed out"))),
    ):
        with pytest.raises(RuntimeError, match="deep-extraction timed out"):
            await consumer._run_pipeline(
                doc_id=section.doc_id,
                minio_key="bucket/key",
                source_type="sec_edgar",
                published_at=None,
                extracted_at=datetime.now(UTC),
                is_backfill=False,
                correlation_id=None,
                tenant_id=uuid.uuid4(),
                doc_title="Q3 10-Q",
            )

    # ── Phase 1 (searchable) committed BEFORE the ML failure ─────────────────
    # The first nlp session is the standalone searchable transaction.
    assert nlp_sessions, "no nlp session was opened"
    nlp_sessions[0].commit.assert_awaited_once()

    # The chunk row was written in that phase-1 transaction.
    assert any(r.add_batch.await_count == 1 for r in chunk_repos), "searchable chunk add_batch never happened"

    # ── Phase 2 (enrichment) never committed — it raised in run_ml_phase ──────
    # A second nlp session was opened for the enrichment transaction but its
    # commit must NOT have been called (the ML phase raised first).
    assert len(nlp_sessions) >= 2, "enrichment transaction session was not opened"
    nlp_sessions[1].commit.assert_not_awaited()
