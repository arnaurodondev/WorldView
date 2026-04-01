"""Unit tests for Block 9 — Entity resolution cascade (T-C-3-06).

Critical invariant: UNRESOLVED entity mentions are NEVER discarded.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.application.blocks.entity_resolution import (
    _stage1_exact,
    _stage2_ticker_isin,
    _stage3_fuzzy,
    run_entity_resolution_block,
)
from nlp_pipeline.domain.enums import MentionClass, ResolutionOutcome
from nlp_pipeline.domain.models import EntityMention, MentionResolution


def _make_mention(text: str, mention_class: MentionClass = MentionClass.ORGANIZATION) -> EntityMention:
    return EntityMention(
        mention_id=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        section_id=uuid.uuid4(),
        mention_text=text,
        mention_class=mention_class,
        confidence=0.90,
        char_start=0,
        char_end=len(text),
    )


def _make_repos(
    exact_result: uuid.UUID | None = None,
    ticker_result: uuid.UUID | None = None,
    fuzzy_results: list[tuple[uuid.UUID, float]] | None = None,
    ann_results: list[tuple[uuid.UUID, float]] | None = None,
) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    alias_repo = MagicMock()
    alias_repo.exact_match = AsyncMock(return_value=exact_result)
    alias_repo.ticker_isin_match = AsyncMock(return_value=ticker_result)
    alias_repo.fuzzy_trigram = AsyncMock(return_value=fuzzy_results or [])

    embedding_repo = MagicMock()
    embedding_repo.ann_search = AsyncMock(return_value=ann_results or [])

    canonical_repo = MagicMock()
    resolution_audit_repo = MagicMock()
    resolution_audit_repo.add = AsyncMock()
    resolution_audit_repo.add_batch = AsyncMock()

    return alias_repo, embedding_repo, canonical_repo, resolution_audit_repo


def _make_embedding_client(embedding: list[float] | None = None) -> MagicMock:
    from ml_clients.dataclasses import EmbeddingOutput  # type: ignore[import-not-found]

    vec = embedding or [0.1] * 1024
    output = EmbeddingOutput(embedding=vec, model_id="bge", dimension=len(vec))
    client = MagicMock()
    client.embed = AsyncMock(return_value=[output])
    return client


@pytest.mark.unit
class TestStage1Exact:
    @pytest.mark.asyncio
    async def test_exact_match_returns_entity_id_with_full_confidence(self) -> None:
        entity_id = uuid.uuid4()
        mention = _make_mention("Apple Inc.")
        alias_repo = MagicMock()
        alias_repo.exact_match = AsyncMock(return_value=entity_id)
        audit: list[MentionResolution] = []

        result_id, confidence = await _stage1_exact(mention, alias_repo, audit)

        assert result_id == entity_id
        assert confidence == 1.0
        assert len(audit) == 1
        assert audit[0].is_winner is True

    @pytest.mark.asyncio
    async def test_no_exact_match_returns_none(self) -> None:
        mention = _make_mention("Unknown Corp")
        alias_repo = MagicMock()
        alias_repo.exact_match = AsyncMock(return_value=None)
        audit: list[MentionResolution] = []

        result_id, confidence = await _stage1_exact(mention, alias_repo, audit)

        assert result_id is None
        assert confidence == 0.0
        assert audit[0].is_winner is False


@pytest.mark.unit
class TestStage2TickerIsin:
    @pytest.mark.asyncio
    async def test_ticker_match_returns_entity_id(self) -> None:
        entity_id = uuid.uuid4()
        mention = _make_mention("AAPL", MentionClass.FINANCIAL_INSTRUMENT)
        alias_repo = MagicMock()
        alias_repo.ticker_isin_match = AsyncMock(return_value=entity_id)
        audit: list[MentionResolution] = []

        result_id, confidence = await _stage2_ticker_isin(mention, alias_repo, audit)

        assert result_id == entity_id
        assert confidence == 0.95

    @pytest.mark.asyncio
    async def test_no_ticker_match_returns_none(self) -> None:
        mention = _make_mention("some text")
        alias_repo = MagicMock()
        alias_repo.ticker_isin_match = AsyncMock(return_value=None)
        audit: list[MentionResolution] = []

        result_id, confidence = await _stage2_ticker_isin(mention, alias_repo, audit)

        assert result_id is None
        assert confidence == 0.0


@pytest.mark.unit
class TestStage3Fuzzy:
    @pytest.mark.asyncio
    async def test_fuzzy_match_returns_best_candidate(self) -> None:
        entity_id = uuid.uuid4()
        mention = _make_mention("Apple Incorporated")
        alias_repo = MagicMock()
        alias_repo.fuzzy_trigram = AsyncMock(return_value=[(entity_id, 0.90)])
        audit: list[MentionResolution] = []

        result_id, confidence = await _stage3_fuzzy(mention, alias_repo, audit)

        assert result_id == entity_id
        assert confidence == pytest.approx(0.90 * 0.90)

    @pytest.mark.asyncio
    async def test_no_fuzzy_match_returns_none(self) -> None:
        mention = _make_mention("Completely Unknown Entity Name")
        alias_repo = MagicMock()
        alias_repo.fuzzy_trigram = AsyncMock(return_value=[])
        audit: list[MentionResolution] = []

        result_id, confidence = await _stage3_fuzzy(mention, alias_repo, audit)

        assert result_id is None
        assert confidence == 0.0
        assert audit[0].is_winner is False


@pytest.mark.unit
class TestRunEntityResolutionBlock:
    @pytest.mark.asyncio
    async def test_unresolved_mentions_never_discarded(self) -> None:
        """CRITICAL: UNRESOLVED mentions must remain in the output list."""
        mention = _make_mention("Completely Unknown Corp")
        alias_repo, embedding_repo, canonical_repo, audit_repo = _make_repos(
            exact_result=None,
            ticker_result=None,
            fuzzy_results=[],
            ann_results=[],
        )
        embedding_client = MagicMock()
        embedding_client.embed = AsyncMock(return_value=[])

        intelligence_session = MagicMock()
        intelligence_session.execute = AsyncMock()

        resolved, _audit = await run_entity_resolution_block(
            [mention],
            alias_repo=alias_repo,
            embedding_repo=embedding_repo,
            canonical_entity_repo=canonical_repo,
            resolution_audit_repo=audit_repo,
            embedding_client=embedding_client,
            intelligence_session=intelligence_session,
            model_id="bge",
            instruction_prefix="",
        )

        # Mention must still be in output
        assert len(resolved) == 1
        assert resolved[0].resolution_outcome == ResolutionOutcome.UNRESOLVED
        assert resolved[0].resolved_entity_id is None

    @pytest.mark.asyncio
    async def test_auto_resolve_sets_entity_id(self) -> None:
        """AUTO_RESOLVE ≥ 0.72 → resolved_entity_id is set."""
        entity_id = uuid.uuid4()
        mention = _make_mention("Apple Inc.")
        alias_repo, embedding_repo, canonical_repo, audit_repo = _make_repos(
            exact_result=entity_id,  # Stage 1 returns entity (confidence 1.0)
        )
        intelligence_session = MagicMock()
        intelligence_session.execute = AsyncMock()

        resolved, _ = await run_entity_resolution_block(
            [mention],
            alias_repo=alias_repo,
            embedding_repo=embedding_repo,
            canonical_entity_repo=canonical_repo,
            resolution_audit_repo=audit_repo,
            embedding_client=_make_embedding_client(),
            intelligence_session=intelligence_session,
            model_id="bge",
            instruction_prefix="",
        )

        assert resolved[0].resolution_outcome == ResolutionOutcome.AUTO_RESOLVED
        assert resolved[0].resolved_entity_id == entity_id
        assert resolved[0].resolution_confidence == 1.0

    @pytest.mark.asyncio
    async def test_provisional_outcome_for_mid_range_confidence(self) -> None:
        """0.45 ≤ composite < 0.72 → PROVISIONAL (queued but not resolved)."""
        entity_id = uuid.uuid4()
        # Fuzzy trigram match with similarity ~0.55 → composite = 0.55*0.90 = 0.495 (>= 0.45, < 0.72)
        mention = _make_mention("Apple Incorporated")
        alias_repo, embedding_repo, canonical_repo, audit_repo = _make_repos(
            exact_result=None,
            ticker_result=None,
            fuzzy_results=[(entity_id, 0.55)],  # 0.55 * 0.90 = 0.495
        )
        intelligence_session = MagicMock()
        intelligence_session.execute = AsyncMock()

        resolved, _ = await run_entity_resolution_block(
            [mention],
            alias_repo=alias_repo,
            embedding_repo=embedding_repo,
            canonical_entity_repo=canonical_repo,
            resolution_audit_repo=audit_repo,
            embedding_client=_make_embedding_client(),
            intelligence_session=intelligence_session,
            model_id="bge",
            instruction_prefix="",
        )

        assert resolved[0].resolution_outcome == ResolutionOutcome.PROVISIONAL
        assert resolved[0].resolved_entity_id is None

    @pytest.mark.asyncio
    async def test_cascade_stops_at_first_hit(self) -> None:
        """Cascade stops at Stage 1 if exact match found — Stage 2/3/4 not called."""
        entity_id = uuid.uuid4()
        mention = _make_mention("Apple Inc.")
        alias_repo, embedding_repo, canonical_repo, audit_repo = _make_repos(
            exact_result=entity_id,
        )
        intelligence_session = MagicMock()
        intelligence_session.execute = AsyncMock()

        await run_entity_resolution_block(
            [mention],
            alias_repo=alias_repo,
            embedding_repo=embedding_repo,
            canonical_entity_repo=canonical_repo,
            resolution_audit_repo=audit_repo,
            embedding_client=_make_embedding_client(),
            intelligence_session=intelligence_session,
            model_id="bge",
            instruction_prefix="",
        )

        # Stage 2 and 3 should NOT have been called
        alias_repo.ticker_isin_match.assert_not_called()
        alias_repo.fuzzy_trigram.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_mentions_all_processed(self) -> None:
        """All mentions are processed, regardless of individual resolution outcome."""
        mentions = [
            _make_mention("Apple Inc."),
            _make_mention("Unknown Corp XYZ"),
        ]
        entity_id = uuid.uuid4()
        alias_repo = MagicMock()
        # First call returns entity, second returns None
        alias_repo.exact_match = AsyncMock(side_effect=[entity_id, None])
        alias_repo.ticker_isin_match = AsyncMock(return_value=None)
        alias_repo.fuzzy_trigram = AsyncMock(return_value=[])

        embedding_repo, canonical_repo, audit_repo = MagicMock(), MagicMock(), MagicMock()
        embedding_repo.ann_search = AsyncMock(return_value=[])
        audit_repo.add = AsyncMock()

        intelligence_session = MagicMock()
        intelligence_session.execute = AsyncMock()

        resolved, _ = await run_entity_resolution_block(
            mentions,
            alias_repo=alias_repo,
            embedding_repo=embedding_repo,
            canonical_entity_repo=canonical_repo,
            resolution_audit_repo=audit_repo,
            embedding_client=_make_embedding_client(),
            intelligence_session=intelligence_session,
            model_id="bge",
            instruction_prefix="",
        )

        assert len(resolved) == 2
        assert resolved[0].resolution_outcome == ResolutionOutcome.AUTO_RESOLVED
        assert resolved[1].resolution_outcome == ResolutionOutcome.UNRESOLVED

    @pytest.mark.asyncio
    async def test_audit_trail_written_for_each_stage_attempted(self) -> None:
        """Audit records are produced for every stage that is attempted."""
        mention = _make_mention("Unknown Corp")
        alias_repo, embedding_repo, canonical_repo, audit_repo = _make_repos(
            exact_result=None,
            ticker_result=None,
            fuzzy_results=[],
            ann_results=[],
        )
        intelligence_session = MagicMock()
        intelligence_session.execute = AsyncMock()

        _, audit = await run_entity_resolution_block(
            [mention],
            alias_repo=alias_repo,
            embedding_repo=embedding_repo,
            canonical_entity_repo=canonical_repo,
            resolution_audit_repo=audit_repo,
            embedding_client=_make_embedding_client(),
            intelligence_session=intelligence_session,
            model_id="bge",
            instruction_prefix="",
        )

        # All 4 stages should have audit entries (stages 1-4)
        stages_hit = {r.stage for r in audit}
        assert 1 in stages_hit  # exact
        assert 2 in stages_hit  # ticker/isin
        assert 3 in stages_hit  # fuzzy
        assert 4 in stages_hit  # ANN
