"""PLAN-0098 W2 T-W2-01 (BP-586) — tenant_id propagation regression tests.

The ``entity_mentions.tenant_id`` column is ``NOT NULL`` (migration 0020).
PLAN-0096 W4 added a ``PUBLIC_TENANT_ID`` sentinel substitution for legacy
Avro payloads that lack a ``tenant_id`` field, but the per-mention stamp at
``_run_pipeline`` was guarded by ``if tenant_id is not None`` — a redundant
check that made the intent unclear and risked future regression.

These tests pin three invariants:

1. **Real-tenant pass-through**: a payload carrying a real ``tenant_id`` ⇒
   every mention in ``ml.final_mentions`` reaches ``persist_artifacts`` with
   that exact tenant.
2. **Sentinel pass-through**: a legacy payload with no ``tenant_id`` ⇒ every
   mention is stamped with ``PUBLIC_TENANT_ID``.
3. **Pre-persist guard**: a buggy upstream block that constructs a mention
   with ``tenant_id=None`` (simulating future regression in entity-resolution
   or deep-extraction code paths) ⇒ the pre-persist safety net substitutes
   the fallback tenant AND emits a structured WARN log naming the
   substitution event.

We exercise ``_run_pipeline`` directly with all blocks patched so the test
stays a true unit test (no DB, no Kafka, no MinIO, no ML).  The boundary we
observe is the ``persist_artifacts`` call: by patching it we can capture the
exact ``ml.final_mentions`` list at persistence time and assert every
``tenant_id`` is non-None.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nlp_pipeline.domain.enums import MentionClass
from nlp_pipeline.domain.models import EntityMention
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    ArticleProcessingConsumer,
)
from structlog.testing import capture_logs

from common.ids import PUBLIC_TENANT_ID  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


# ── Shared helpers (mirrors test_d004_dual_db_commit style) ──────────────────


def _make_settings() -> MagicMock:
    """Settings stub with the minimum fields _run_pipeline reads."""
    s = MagicMock()
    s.gliner_threshold = 0.35
    s.gliner_batch_size = 32
    s.gliner_section_token_limit = 450
    s.gliner_mention_floor = 0.5
    s.min_persist_floor = 0.0  # don't filter mentions out in this test
    s.embedding_model_id = "bge-large-en-v1.5"
    s.embedding_instruction_prefix = "Represent: "
    s.ner_model_id = "gliner"
    s.extraction_model_id = "qwen2.5:7b-instruct"
    s.topic_article_enriched = "nlp.article.enriched.v1"
    s.topic_signal_detected = "nlp.signal.detected.v1"
    s.max_ollama_queue_depth = 20
    s.resume_ollama_queue_depth = 10
    s.min_word_count = 0
    s.routing_tier_deep = 0.7
    s.routing_tier_medium = 0.4
    s.routing_tier_light = 0.1
    s.novelty_minhash_threshold = 0.9
    s.novelty_embedding_threshold = 0.9
    s.entity_resolution_auto_resolve_threshold = 0.9
    s.entity_resolution_provisional_threshold = 0.5
    return s


def _make_session_factory() -> tuple[AsyncMock, MagicMock]:
    """Async session-factory pair (factory() yields an async context manager)."""
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
    """Build an ArticleProcessingConsumer with everything I/O mocked."""
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


def _make_mention(doc_id: uuid.UUID, *, tenant_id: uuid.UUID | None = None) -> EntityMention:
    """Build a minimal EntityMention for use as NER-block output."""
    return EntityMention(
        mention_id=uuid.uuid4(),
        doc_id=doc_id,
        section_id=None,
        mention_text="Acme Corp",
        mention_class=MentionClass.ORGANIZATION,
        confidence=0.95,
        char_start=0,
        char_end=9,
        tenant_id=tenant_id,
    )


async def _drive_pipeline(
    consumer: ArticleProcessingConsumer,
    *,
    doc_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    ner_mentions: list[EntityMention],
    ml_final_mentions: list[EntityMention] | None = None,
) -> list[EntityMention]:
    """Patch all blocks + persist_artifacts and run _run_pipeline.

    Returns the ``final_mentions`` list captured at the moment
    ``persist_artifacts`` was invoked — this is the boundary we care about.

    If ``ml_final_mentions`` is None, the MLPhaseResult re-uses the NER
    mentions (the common Block-9-skipped path).
    """
    from nlp_pipeline.application.blocks.suppression import ProcessingPath
    from nlp_pipeline.infrastructure.messaging.consumers.blocks.ml_phase import MLPhaseResult

    captured: dict[str, object] = {}

    # Routing decision stub: hit DEEP so entity resolution + deep extraction
    # would run, but we'll patch run_ml_phase directly anyway.
    routing_decision = MagicMock()
    routing_decision.routing_tier = MagicMock(value="deep")
    routing_decision.final_routing_tier = None
    routing_decision.processing_path = None

    ml_result = MLPhaseResult(
        routing_decision=routing_decision,
        final_path=ProcessingPath.HALT,  # HALT to skip outbox-emission branch entirely
        final_mentions=ml_final_mentions if ml_final_mentions is not None else list(ner_mentions),
        pending_resolution_audit=[],
        extraction_result={"events": [], "claims": [], "relations": []},
        signals=[],
    )

    async def _capture_persist(**kwargs: object) -> tuple[object, list[object], list[EntityMention], object]:
        ml = kwargs["ml"]
        # ml is MLPhaseResult — capture final_mentions at persist time.
        captured["final_mentions"] = list(ml.final_mentions)  # type: ignore[attr-defined]
        return routing_decision, [], list(ml.final_mentions), MagicMock()  # type: ignore[attr-defined]

    patches = [
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.section_document",
            return_value=[],
        ),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.run_ner_block",
            new=AsyncMock(return_value=(list(ner_mentions), MagicMock())),
        ),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.compute_routing_score",
            return_value=routing_decision,
        ),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.apply_suppression_gate",
            return_value=ProcessingPath.HALT,
        ),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.run_embeddings_block",
            new=AsyncMock(return_value=([], [], [], [])),
        ),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.run_ml_phase",
            new=AsyncMock(return_value=ml_result),
        ),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.persist_artifacts",
            new=AsyncMock(side_effect=_capture_persist),
        ),
        # The outbox enqueue helpers touch serialize_confluent_avro + a real
        # repo; HALT skips the article-enriched branch but the
        # document-ready emission still fires for any non-None tenant.
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer._enqueue_document_ready",
            new=AsyncMock(),
        ),
    ]

    for p in patches:
        p.start()
    try:
        with patch.object(consumer, "_download_article", new=AsyncMock(return_value="text " * 200)):
            await consumer._run_pipeline(
                doc_id=doc_id,
                minio_key="bucket/key",
                source_type="eodhd",
                published_at=None,
                extracted_at=datetime.now(UTC),
                is_backfill=False,
                correlation_id=None,
                tenant_id=tenant_id,
            )
    finally:
        for p in patches:
            p.stop()

    return captured["final_mentions"]  # type: ignore[return-value]


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestTenantIdPropagation:
    """T-W2-01: tenant_id must reach persist_artifacts on every code path."""

    @pytest.mark.asyncio
    async def test_real_tenant_propagates_to_all_mentions_at_persist(self) -> None:
        """When the message carries a real tenant_id, every EntityMention in
        ml.final_mentions must arrive at persist_artifacts with that exact
        tenant_id — never None, never the sentinel."""
        consumer = _make_consumer()
        doc_id = uuid.uuid4()
        real_tenant = uuid.uuid4()

        # NER returns mentions with tenant_id=None (simulating the GLiNER
        # output before the post-stamp at line 583-585 in article_consumer).
        ner_mentions = [_make_mention(doc_id, tenant_id=None) for _ in range(3)]

        final_mentions = await _drive_pipeline(
            consumer,
            doc_id=doc_id,
            tenant_id=real_tenant,
            ner_mentions=ner_mentions,
        )

        assert len(final_mentions) == 3
        for m in final_mentions:
            assert m.tenant_id == real_tenant, f"expected {real_tenant}, got {m.tenant_id!r}"

    @pytest.mark.asyncio
    async def test_legacy_tenant_propagates_sentinel_to_all_mentions(self) -> None:
        """When the message has no tenant_id (process_message substitutes the
        PUBLIC_TENANT_ID sentinel before calling _run_pipeline), every mention
        at persist time must carry that sentinel."""
        consumer = _make_consumer()
        doc_id = uuid.uuid4()

        ner_mentions = [_make_mention(doc_id, tenant_id=None) for _ in range(2)]

        # process_message would have substituted PUBLIC_TENANT_ID before reaching
        # _run_pipeline; we simulate that by passing the sentinel directly.
        final_mentions = await _drive_pipeline(
            consumer,
            doc_id=doc_id,
            tenant_id=PUBLIC_TENANT_ID,
            ner_mentions=ner_mentions,
        )

        assert len(final_mentions) == 2
        for m in final_mentions:
            assert m.tenant_id == PUBLIC_TENANT_ID, f"expected sentinel, got {m.tenant_id!r}"

    @pytest.mark.asyncio
    async def test_pre_persist_guard_substitutes_none_tenant_and_warns(self) -> None:
        """Defence-in-depth: if an upstream block (e.g. a future entity-resolution
        refactor) constructs a mention with tenant_id=None and that mention
        survives into ml.final_mentions, the pre-persist guard MUST substitute
        the request-scoped tenant_id AND emit a structured WARN naming the
        offending mention so an operator can identify the regressed block."""
        consumer = _make_consumer()
        doc_id = uuid.uuid4()
        real_tenant = uuid.uuid4()

        # NER stamps tenant_id correctly on its outputs.
        ner_mentions = [_make_mention(doc_id, tenant_id=None) for _ in range(2)]

        # But the ML phase "leaks" a buggy mention with tenant_id=None that
        # was constructed somewhere downstream (entity resolution, deep
        # extraction, novelty backfill, etc.).  The post-stamp in
        # _run_pipeline at line 583-585 only covers the NER output — it does
        # not iterate ml.final_mentions.  Without the pre-persist guard, this
        # mention would reach the INSERT, hit the NOT NULL constraint, the
        # exception would be treated as retryable, and the topic would stall.
        buggy_mention = _make_mention(doc_id, tenant_id=None)
        ml_final_mentions = [*ner_mentions, buggy_mention]
        # Pre-stamp the NER ones (mimicking the post-NER loop in _run_pipeline)
        # so only the "leaked" mention has tenant_id=None at the ML boundary.
        for m in ner_mentions:
            m.tenant_id = real_tenant

        with capture_logs() as cap:
            final_mentions = await _drive_pipeline(
                consumer,
                doc_id=doc_id,
                tenant_id=real_tenant,
                ner_mentions=ner_mentions,
                ml_final_mentions=ml_final_mentions,
            )

        # Every mention at persist time must have a non-None tenant_id.
        for m in final_mentions:
            assert m.tenant_id is not None, f"pre-persist guard failed: {m.mention_id} has tenant_id=None"

        # The buggy mention specifically must have been stamped with the
        # request's real tenant (not the sentinel — the guard prefers the
        # request tenant when one is available).
        assert buggy_mention.tenant_id == real_tenant

        # A WARN log must have been emitted with the substitution metadata.
        warns = [e for e in cap if e.get("event") == "article_consumer.pre_persist_tenant_id_substituted"]
        assert len(warns) == 1, f"expected exactly one pre-persist warn, got: {cap}"
        warn = warns[0]
        assert warn["log_level"] == "warning"
        assert warn["doc_id"] == str(doc_id)
        assert warn["missing_count"] == 1
        assert warn["total_mentions"] == 3
        assert str(buggy_mention.mention_id) in warn["sample_mention_ids"]
