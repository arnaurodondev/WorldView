"""Unit tests for PLAN-0093 Sub-Plan C Wave C-2 — entity_mentions persistence floor.

Covers the ``settings.min_persist_floor`` enforcement added in
``infrastructure/messaging/consumers/blocks/persist.py``. The full pipeline
already has heavy-mocked tests in test_consumer.py; here we test the filter
logic in isolation by calling ``persist_artifacts`` with a hand-built
``MLPhaseResult`` so the assertion is unambiguous.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.config import Settings
from nlp_pipeline.domain.enums import MentionClass, RoutingTier
from nlp_pipeline.domain.models import (
    Chunk,
    EntityMention,
    MentionResolution,
    RoutingDecision,
    Section,
)
from nlp_pipeline.infrastructure.messaging.consumers.blocks.ml_phase import MLPhaseResult
from nlp_pipeline.infrastructure.messaging.consumers.blocks.persist import persist_artifacts

pytestmark = pytest.mark.unit


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_settings(min_persist_floor: float = 0.6) -> Settings:
    """Build a Settings instance with the two required-no-default fields satisfied.

    Both ``database_url`` and ``intelligence_database_url`` are SecretStr with
    no defaults (DEF-027); they must be set or pydantic raises ValidationError.
    Values are dummies — the tests never open a real DB connection.
    """
    os.environ.setdefault("NLP_PIPELINE_DATABASE_URL", "postgresql+asyncpg://x:y@localhost/test")
    os.environ.setdefault(
        "NLP_PIPELINE_INTELLIGENCE_DATABASE_URL",
        "postgresql+asyncpg://x:y@localhost/intel_test",
    )
    s = Settings()
    # Override only the field under test
    object.__setattr__(s, "min_persist_floor", min_persist_floor)
    return s


def _mention(confidence: float) -> EntityMention:
    """Build a minimal EntityMention with the given confidence."""
    return EntityMention(
        mention_id=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        section_id=uuid.uuid4(),
        mention_text=f"mention_conf_{confidence}",
        mention_class=MentionClass.ORGANIZATION,
        confidence=confidence,
        char_start=0,
        char_end=10,
    )


def _routing_decision() -> RoutingDecision:
    return RoutingDecision(
        decision_id=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        routing_tier=RoutingTier.LIGHT,
        composite_score=0.3,
        feature_scores={"entity_density": 0.0},
    )


def _ml_result(
    mentions: list[EntityMention],
    audit: list[MentionResolution] | None = None,
) -> MLPhaseResult:
    """Build an MLPhaseResult skeleton that ``persist_artifacts`` consumes."""
    rd = _routing_decision()
    return MLPhaseResult(
        final_mentions=mentions,
        routing_decision=rd,
        final_path=MagicMock(),  # processing_path enum — never inspected by these tests
        pending_resolution_audit=list(audit or []),
        extraction_result={},  # type: ignore[arg-type]
        signals=[],
    )


def _stub_async_repo() -> MagicMock:
    """Build an async-method-bearing repo stub that accepts any call."""
    repo = MagicMock()
    repo.add = AsyncMock()
    repo.add_batch = AsyncMock()
    repo.upsert = AsyncMock()
    repo.link_batch = AsyncMock()
    repo.save_batch = AsyncMock()
    return repo


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sub_floor_mentions_not_persisted() -> None:
    """PLAN-0093 C-2: mention at confidence=0.5 must NOT be written to entity_mentions."""
    settings = _make_settings(min_persist_floor=0.6)
    sub_floor = _mention(0.5)
    above_floor = _mention(0.8)

    entity_mention_repo = _stub_async_repo()
    section_repo = _stub_async_repo()
    chunk_repo = _stub_async_repo()
    outbox_repo = _stub_async_repo()
    routing_repo = _stub_async_repo()
    doc_stats_repo = _stub_async_repo()
    chunk_em_repo = _stub_async_repo()
    mention_res_repo = _stub_async_repo()

    nlp_session = AsyncMock()
    nlp_session.execute = AsyncMock()

    await persist_artifacts(
        nlp_session=nlp_session,
        section_repo=section_repo,
        chunk_repo=chunk_repo,
        outbox_repo=outbox_repo,
        routing_decision_repo=routing_repo,
        entity_mention_repo=entity_mention_repo,
        doc_entity_stats_repo=doc_stats_repo,
        chunk_entity_mention_repo=chunk_em_repo,
        mention_resolution_repo=mention_res_repo,
        doc_id=uuid.uuid4(),
        sections=[],
        stats=MagicMock(),
        chunks=[],
        chunk_embs=[],
        section_embs=[],
        pending=None,
        gliner_mention_floor=settings.gliner_mention_floor,
        settings=settings,
        ml=_ml_result([sub_floor, above_floor]),
    )

    # Only the above-floor mention should be persisted.
    entity_mention_repo.add_batch.assert_awaited_once()
    persisted_batch = entity_mention_repo.add_batch.await_args.args[0]
    persisted_ids = [m.mention_id for m in persisted_batch]
    assert above_floor.mention_id in persisted_ids
    assert sub_floor.mention_id not in persisted_ids


@pytest.mark.asyncio
async def test_above_floor_mentions_persisted() -> None:
    """PLAN-0093 C-2: mention at confidence=0.7 must be written to entity_mentions."""
    settings = _make_settings(min_persist_floor=0.6)
    above_floor = _mention(0.7)

    entity_mention_repo = _stub_async_repo()
    repos = {k: _stub_async_repo() for k in range(8)}

    nlp_session = AsyncMock()
    nlp_session.execute = AsyncMock()

    await persist_artifacts(
        nlp_session=nlp_session,
        section_repo=repos[0],
        chunk_repo=repos[1],
        outbox_repo=repos[2],
        routing_decision_repo=repos[3],
        entity_mention_repo=entity_mention_repo,
        doc_entity_stats_repo=repos[4],
        chunk_entity_mention_repo=repos[5],
        mention_resolution_repo=repos[6],
        doc_id=uuid.uuid4(),
        sections=[],
        stats=MagicMock(),
        chunks=[],
        chunk_embs=[],
        section_embs=[],
        pending=None,
        gliner_mention_floor=settings.gliner_mention_floor,
        settings=settings,
        ml=_ml_result([above_floor]),
    )

    entity_mention_repo.add_batch.assert_awaited_once()
    persisted_batch = entity_mention_repo.add_batch.await_args.args[0]
    assert len(persisted_batch) == 1
    assert persisted_batch[0].mention_id == above_floor.mention_id


@pytest.mark.asyncio
async def test_floor_configurable_via_settings() -> None:
    """PLAN-0093 C-2: changing min_persist_floor changes the filter cutoff."""
    # Set the floor higher than default (0.6) so even confidence=0.7 is rejected.
    settings = _make_settings(min_persist_floor=0.85)
    just_below = _mention(0.7)
    above = _mention(0.95)

    entity_mention_repo = _stub_async_repo()
    repos = {k: _stub_async_repo() for k in range(8)}

    nlp_session = AsyncMock()
    nlp_session.execute = AsyncMock()

    await persist_artifacts(
        nlp_session=nlp_session,
        section_repo=repos[0],
        chunk_repo=repos[1],
        outbox_repo=repos[2],
        routing_decision_repo=repos[3],
        entity_mention_repo=entity_mention_repo,
        doc_entity_stats_repo=repos[4],
        chunk_entity_mention_repo=repos[5],
        mention_resolution_repo=repos[6],
        doc_id=uuid.uuid4(),
        sections=[],
        stats=MagicMock(),
        chunks=[],
        chunk_embs=[],
        section_embs=[],
        pending=None,
        gliner_mention_floor=settings.gliner_mention_floor,
        settings=settings,
        ml=_ml_result([just_below, above]),
    )

    persisted_batch = entity_mention_repo.add_batch.await_args.args[0]
    persisted_ids = [m.mention_id for m in persisted_batch]
    # 0.7 is below the 0.85 floor → must be filtered out
    assert just_below.mention_id not in persisted_ids
    # 0.95 is above → must be kept
    assert above.mention_id in persisted_ids


def test_min_persist_floor_default_is_06() -> None:
    """PLAN-0093 C-2: default floor matches the GLiNER mention floor (0.6)."""
    settings = _make_settings()
    assert settings.min_persist_floor == 0.6


def test_min_persist_floor_env_override() -> None:
    """PLAN-0093 C-2: NLP_PIPELINE_MIN_PERSIST_FLOOR overrides the default."""
    os.environ["NLP_PIPELINE_MIN_PERSIST_FLOOR"] = "0.75"
    try:
        # Force a fresh Settings load so pydantic re-reads the env.
        os.environ["NLP_PIPELINE_DATABASE_URL"] = "postgresql+asyncpg://x:y@localhost/test"
        os.environ["NLP_PIPELINE_INTELLIGENCE_DATABASE_URL"] = "postgresql+asyncpg://x:y@localhost/intel"
        s = Settings()
        assert s.min_persist_floor == 0.75
    finally:
        del os.environ["NLP_PIPELINE_MIN_PERSIST_FLOOR"]


# ── Defense-in-depth: resolver query filter ──────────────────────────────────


def test_get_unresolved_batch_includes_confidence_filter() -> None:
    """PLAN-0093 C-2 T-C-2-02: the resolver SQL now filters on confidence floor."""
    import inspect

    from nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention import (
        EntityMentionRepository,
    )

    src = inspect.getsource(EntityMentionRepository.get_unresolved_batch)
    # Both the SQL fragment and the bind parameter must be present
    assert "confidence >= :min_confidence" in src
    assert "min_confidence" in src


def test_get_unresolved_batch_with_context_includes_confidence_filter() -> None:
    """PLAN-0093 C-2 T-C-2-02: same filter on the with-context variant."""
    import inspect

    from nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention import (
        EntityMentionRepository,
    )

    src = inspect.getsource(EntityMentionRepository.get_unresolved_batch_with_context)
    assert "confidence >= :min_confidence" in src


# ── F-DB-NEW-001 (BP-587): resolution-audit FK floor filter ──────────────────


@pytest.mark.asyncio
async def test_resolution_audit_for_sub_floor_mentions_not_persisted() -> None:
    """F-DB-NEW-001 (BP-587): mention_resolutions rows whose ``mention_id``
    belongs to a sub-floor mention (filtered out of ``entity_mentions``) must
    NOT be sent to ``MentionResolutionRepository.add_batch`` — otherwise
    PostgreSQL raises ``ForeignKeyViolationError`` on
    ``mention_resolutions_mention_id_fkey`` and the article consumer stalls.

    This regression guards the chunk_entity_mention pattern (already applied at
    line 149) against being silently re-introduced for the audit table.
    """
    settings = _make_settings(min_persist_floor=0.6)
    sub_floor = _mention(0.5)
    above_floor = _mention(0.8)
    audit_for_sub = MentionResolution(mention_id=sub_floor.mention_id, stage=1, score=0.0, is_winner=False)
    audit_for_above = MentionResolution(mention_id=above_floor.mention_id, stage=1, score=0.9, is_winner=True)

    entity_mention_repo = _stub_async_repo()
    section_repo = _stub_async_repo()
    chunk_repo = _stub_async_repo()
    outbox_repo = _stub_async_repo()
    routing_repo = _stub_async_repo()
    doc_stats_repo = _stub_async_repo()
    chunk_em_repo = _stub_async_repo()
    mention_res_repo = _stub_async_repo()

    nlp_session = AsyncMock()
    nlp_session.execute = AsyncMock()

    await persist_artifacts(
        nlp_session=nlp_session,
        section_repo=section_repo,
        chunk_repo=chunk_repo,
        outbox_repo=outbox_repo,
        routing_decision_repo=routing_repo,
        entity_mention_repo=entity_mention_repo,
        doc_entity_stats_repo=doc_stats_repo,
        chunk_entity_mention_repo=chunk_em_repo,
        mention_resolution_repo=mention_res_repo,
        doc_id=uuid.uuid4(),
        sections=[],
        stats=MagicMock(),
        chunks=[],
        chunk_embs=[],
        section_embs=[],
        pending=None,
        gliner_mention_floor=settings.gliner_mention_floor,
        settings=settings,
        ml=_ml_result([sub_floor, above_floor], audit=[audit_for_sub, audit_for_above]),
    )

    # Only the audit row whose mention survived the floor filter should be
    # written — otherwise the FK to entity_mentions cannot resolve.
    mention_res_repo.add_batch.assert_awaited_once()
    written_audit = mention_res_repo.add_batch.await_args.args[0]
    written_ids = [r.mention_id for r in written_audit]
    assert above_floor.mention_id in written_ids
    assert sub_floor.mention_id not in written_ids


# Unused imports kept to satisfy module load (some test-only models used by helpers).
_ = (Section, Chunk, datetime, UTC)
