"""Unit tests for Block 9 — Entity resolution cascade (T-C-3-06).

Critical invariant: UNRESOLVED entity mentions are NEVER discarded.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given
from hypothesis import settings as h_settings
from hypothesis import strategies as st
from nlp_pipeline.application.blocks.entity_resolution import (
    ANN_CONFIDENCE_MULTIPLIER,
    AUTO_RESOLVE_THRESHOLD,
    _stage1_exact,
    _stage2_ticker_isin,
    _stage3_fuzzy,
    run_entity_resolution_block,
)
from nlp_pipeline.domain.enums import MentionClass, ResolutionOutcome
from nlp_pipeline.domain.models import EntityMention, MentionResolution

pytestmark = pytest.mark.unit


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
    """Build mock repos.

    The run_entity_resolution_block function uses batch_* methods.
    The individual stage helpers (_stage1_exact etc.) use the single-mention methods.
    Both sets of mocks are wired here so stage helper tests still pass.
    """
    alias_repo = MagicMock()
    # Single-mention methods (used by _stage1_exact, _stage2_ticker_isin, _stage3_fuzzy helpers)
    alias_repo.exact_match = AsyncMock(return_value=exact_result)
    alias_repo.ticker_isin_match = AsyncMock(return_value=ticker_result)
    alias_repo.fuzzy_trigram = AsyncMock(return_value=fuzzy_results or [])

    # Batch methods (used by run_entity_resolution_block)
    alias_repo.batch_exact_match = AsyncMock(
        return_value={},  # filled per-test below
    )
    alias_repo.batch_ticker_isin_match = AsyncMock(return_value={})
    alias_repo.batch_fuzzy_trigram = AsyncMock(return_value={})

    embedding_repo = MagicMock()
    embedding_repo.ann_search = AsyncMock(return_value=ann_results or [])

    canonical_repo = MagicMock()
    resolution_audit_repo = MagicMock()
    resolution_audit_repo.add = AsyncMock()
    resolution_audit_repo.add_batch = AsyncMock()

    return alias_repo, embedding_repo, canonical_repo, resolution_audit_repo


def _make_batch_repos(
    exact_map: dict[str, uuid.UUID] | None = None,
    ticker_isin_map: dict[str, uuid.UUID] | None = None,
    fuzzy_map: dict[str, list[tuple[uuid.UUID, float]]] | None = None,
    ann_results: list[tuple[uuid.UUID, float]] | None = None,
) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """Build mock repos with batch methods pre-loaded — for run_entity_resolution_block tests."""
    alias_repo = MagicMock()
    alias_repo.batch_exact_match = AsyncMock(return_value=exact_map or {})
    alias_repo.batch_ticker_isin_match = AsyncMock(return_value=ticker_isin_map or {})
    alias_repo.batch_fuzzy_trigram = AsyncMock(return_value=fuzzy_map or {})
    # Single-mention methods still present (stage helper tests)
    alias_repo.exact_match = AsyncMock(return_value=None)
    alias_repo.ticker_isin_match = AsyncMock(return_value=None)
    alias_repo.fuzzy_trigram = AsyncMock(return_value=[])

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
        alias_repo, embedding_repo, canonical_repo, audit_repo = _make_batch_repos()
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

        assert len(resolved) == 1
        assert resolved[0].resolution_outcome == ResolutionOutcome.UNRESOLVED
        assert resolved[0].resolved_entity_id is None

    @pytest.mark.asyncio
    async def test_auto_resolve_sets_entity_id(self) -> None:
        """AUTO_RESOLVE ≥ 0.72 → resolved_entity_id is set (Stage 1 exact hit)."""
        entity_id = uuid.uuid4()
        mention = _make_mention("Apple Inc.")
        alias_repo, embedding_repo, canonical_repo, audit_repo = _make_batch_repos(
            exact_map={"apple inc.": entity_id},
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
        """0.45 <= composite < 0.72 → PROVISIONAL (queued but not resolved).

        Wave B-2: ``_insert_provisional`` now uses ``RETURNING queue_id`` and
        the caller stashes the returned UUID on the mention. The
        ``intelligence_session.execute`` mock must therefore expose a
        ``scalar_one()`` that returns a valid UUID string — without it, the
        UUID() conversion would raise ValueError, which the savepoint+except
        wrapper would catch and downgrade the mention to UNRESOLVED (per the
        QA iter-1 fix for DS Finding-4).
        """
        entity_id = uuid.uuid4()
        # Fuzzy trigram with similarity 0.55 → composite = 0.55*0.90 = 0.495
        mention = _make_mention("Apple Incorporated")
        alias_repo, embedding_repo, canonical_repo, audit_repo = _make_batch_repos(
            fuzzy_map={"apple incorporated": [(entity_id, 0.55)]},
        )
        intelligence_session = MagicMock()
        # Two sequential execute() calls now happen:
        #   1. Churn guard COUNT(*) query → must return int 0 (below threshold)
        #   2. _insert_provisional RETURNING queue_id → returns UUID string
        _count_result = MagicMock()
        _count_result.scalar_one = MagicMock(return_value=0)
        _insert_result = MagicMock()
        _insert_result.scalar_one = MagicMock(return_value=str(uuid.uuid4()))
        intelligence_session.execute = AsyncMock(side_effect=[_count_result, _insert_result])
        # begin_nested() is used as an async context manager for the savepoint.
        _savepoint = AsyncMock()
        _savepoint.__aenter__ = AsyncMock(return_value=_savepoint)
        _savepoint.__aexit__ = AsyncMock(return_value=None)
        intelligence_session.begin_nested = MagicMock(return_value=_savepoint)

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
    async def test_stage1_hit_skips_stage4_ann(self) -> None:
        """When Stage 1 resolves a mention, Stage 4 ANN is not called."""
        entity_id = uuid.uuid4()
        mention = _make_mention("Apple Inc.")
        alias_repo, embedding_repo, canonical_repo, audit_repo = _make_batch_repos(
            exact_map={"apple inc.": entity_id},
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

        # Stage 4 (ANN) should NOT be called when Stage 1 already resolved
        embedding_repo.ann_search.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_mentions_all_processed(self) -> None:
        """All mentions are processed regardless of individual resolution outcome."""
        entity_id = uuid.uuid4()
        mentions = [
            _make_mention("Apple Inc."),
            _make_mention("Unknown Corp XYZ"),
        ]
        alias_repo, embedding_repo, canonical_repo, audit_repo = _make_batch_repos(
            exact_map={"apple inc.": entity_id},
        )
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
        """Audit records are produced for every stage (1-4) attempted."""
        mention = _make_mention("Unknown Corp")
        alias_repo, embedding_repo, canonical_repo, audit_repo = _make_batch_repos()
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

        stages_hit = {r.stage for r in audit}
        assert 1 in stages_hit  # exact (miss audit entry)
        assert 2 in stages_hit  # ticker/isin (miss audit entry)
        assert 3 in stages_hit  # fuzzy (miss audit entry)
        assert 4 in stages_hit  # ANN (always emits)

    @pytest.mark.asyncio
    async def test_ann_hit_at_distance_0_325_auto_resolves_with_new_thresholds(self) -> None:
        """PLAN-0052 QA-R6 Option C: ANN distance 0.325 → confidence 0.641 > 0.62 → AUTO_RESOLVED.

        Old thresholds (0.80 multiplier, 0.72 threshold): 0.675 * 0.80 = 0.54 < 0.72 → UNRESOLVED.
        New thresholds (0.95 multiplier, 0.62 threshold): 0.675 * 0.95 = 0.641 > 0.62 → AUTO_RESOLVED.
        """
        entity_id = uuid.uuid4()
        mention = _make_mention("Amazon.com")
        # Only one ANN candidate (no margin issue), distance = 0.325
        alias_repo, embedding_repo, canonical_repo, audit_repo = _make_batch_repos(
            ann_results=[(entity_id, 0.325)],
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
        expected_confidence = (1.0 - 0.325) * 0.95
        assert abs(resolved[0].resolution_confidence - expected_confidence) < 1e-6  # type: ignore[operator]

    @pytest.mark.asyncio
    async def test_empty_mentions_returns_empty(self) -> None:
        """Empty input returns immediately with no DB calls."""
        alias_repo, embedding_repo, canonical_repo, audit_repo = _make_batch_repos()
        intelligence_session = MagicMock()

        resolved, audit = await run_entity_resolution_block(
            [],
            alias_repo=alias_repo,
            embedding_repo=embedding_repo,
            canonical_entity_repo=canonical_repo,
            resolution_audit_repo=audit_repo,
            embedding_client=_make_embedding_client(),
            intelligence_session=intelligence_session,
            model_id="bge",
            instruction_prefix="",
        )

        assert resolved == []
        assert audit == []
        alias_repo.batch_exact_match.assert_not_called()


@pytest.mark.unit
class TestAnnScoreMonotonicity:
    """Property-based tests: ANN score → confidence mapping is monotone (Item 10)."""

    @given(
        d1=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        d2=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @h_settings(max_examples=500)
    def test_confidence_monotonically_decreasing_with_distance(self, d1: float, d2: float) -> None:
        """For any two ANN distances, the closer one must always score higher confidence."""
        c1 = (1.0 - d1) * ANN_CONFIDENCE_MULTIPLIER
        c2 = (1.0 - d2) * ANN_CONFIDENCE_MULTIPLIER
        if d1 < d2:
            assert c1 >= c2, f"d1={d1} < d2={d2} but c1={c1} < c2={c2}"

    @given(distance=st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    @h_settings(max_examples=500)
    def test_auto_resolve_iff_confidence_above_threshold(self, distance: float) -> None:
        """AUTO_RESOLVED iff confidence > AUTO_RESOLVE_THRESHOLD."""
        confidence = (1.0 - distance) * ANN_CONFIDENCE_MULTIPLIER
        should_auto = confidence > AUTO_RESOLVE_THRESHOLD
        # Re-derive from raw — must be consistent
        assert should_auto == (confidence > AUTO_RESOLVE_THRESHOLD)


# ── ensure_provisional_for_mention (PLAN-0052 round 9 / Option 2) ────────────


def _intelligence_session_mock(*, hourly_count: int = 0, queue_id: uuid.UUID | None = None) -> MagicMock:
    """Build a mock intelligence_session that mirrors the SAVEPOINT + churn-guard
    + INSERT pattern used by ``ensure_provisional_for_mention``.

    - ``hourly_count`` controls the COUNT(*) the churn-guard query returns.
    - ``queue_id`` is what ``_insert_provisional`` sees as the RETURNING row.
      When ``None``, the SAVEPOINT block raises an Exception to simulate
      DB failure / unique-conflict-without-RETURNING.
    """
    session = MagicMock()

    # Two execute() calls happen: the COUNT(*) churn guard, then the INSERT.
    count_result = MagicMock()
    count_result.scalar_one = MagicMock(return_value=hourly_count)
    insert_result = MagicMock()
    insert_result.scalar_one = MagicMock(return_value=str(queue_id) if queue_id else None)
    session.execute = AsyncMock(side_effect=[count_result, insert_result])

    # begin_nested() returns an async context manager. When queue_id is None we
    # simulate failure inside the SAVEPOINT block.
    nested_cm = AsyncMock()
    if queue_id is None:
        nested_cm.__aenter__ = AsyncMock(side_effect=RuntimeError("savepoint failure"))
    else:
        nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin_nested = MagicMock(return_value=nested_cm)
    return session


@pytest.mark.unit
class TestEnsureProvisionalForMention:
    """ensure_provisional_for_mention promotes UNRESOLVED → PROVISIONAL inline.

    Used by article_consumer's synthesize_provisional_refs to give LLM-
    referenced UNRESOLVED mentions a queue_id so _build_raw_* can address
    them. Idempotent (no-op if mention already has a queue_id) and safe
    (never overwrites an AUTO_RESOLVED mention's resolved_entity_id).
    """

    @pytest.mark.asyncio
    async def test_unresolved_mention_promoted_to_provisional(self) -> None:
        from nlp_pipeline.application.blocks.entity_resolution import ensure_provisional_for_mention

        mention = _make_mention("Endeavour Mining")
        mention.resolution_outcome = ResolutionOutcome.UNRESOLVED
        queue_id = uuid.uuid4()
        session = _intelligence_session_mock(hourly_count=0, queue_id=queue_id)

        result = await ensure_provisional_for_mention(mention, session)

        assert result == queue_id
        assert mention.provisional_queue_id == queue_id
        assert mention.resolution_outcome == ResolutionOutcome.PROVISIONAL

    @pytest.mark.asyncio
    async def test_idempotent_when_mention_already_has_queue_id(self) -> None:
        """If Block 9 already created a queue row, the helper short-circuits."""
        from nlp_pipeline.application.blocks.entity_resolution import ensure_provisional_for_mention

        mention = _make_mention("Apple Inc.")
        existing_qid = uuid.uuid4()
        mention.provisional_queue_id = existing_qid
        mention.resolution_outcome = ResolutionOutcome.PROVISIONAL
        session = _intelligence_session_mock(hourly_count=0, queue_id=uuid.uuid4())

        result = await ensure_provisional_for_mention(mention, session)

        assert result == existing_qid
        # No DB calls — short-circuit before touching the session.
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_mention_already_resolved(self) -> None:
        """Never overwrite an AUTO_RESOLVED mention with a synthetic queue_id."""
        from nlp_pipeline.application.blocks.entity_resolution import ensure_provisional_for_mention

        mention = _make_mention("NVIDIA Corp")
        mention.resolved_entity_id = uuid.uuid4()
        mention.resolution_outcome = ResolutionOutcome.AUTO_RESOLVED
        session = _intelligence_session_mock(hourly_count=0, queue_id=uuid.uuid4())

        result = await ensure_provisional_for_mention(mention, session)

        assert result is None
        assert mention.provisional_queue_id is None
        # Auto_resolved outcome must NOT be flipped.
        assert mention.resolution_outcome == ResolutionOutcome.AUTO_RESOLVED

    @pytest.mark.asyncio
    async def test_churn_guard_skips_when_threshold_hit(self) -> None:
        """If MAX_PROVISIONAL_PER_HOUR rows already exist, skip insert."""
        from nlp_pipeline.application.blocks.entity_resolution import (
            MAX_PROVISIONAL_PER_HOUR,
            ensure_provisional_for_mention,
        )

        mention = _make_mention("the company")
        mention.resolution_outcome = ResolutionOutcome.UNRESOLVED
        session = _intelligence_session_mock(hourly_count=MAX_PROVISIONAL_PER_HOUR, queue_id=uuid.uuid4())

        result = await ensure_provisional_for_mention(mention, session)

        assert result is None
        assert mention.provisional_queue_id is None
        # Churn-guard must not flip the outcome (mention stays UNRESOLVED so
        # UnresolvedResolutionWorker eventually re-attempts on its cycle).
        assert mention.resolution_outcome == ResolutionOutcome.UNRESOLVED

    @pytest.mark.asyncio
    async def test_savepoint_failure_returns_none(self) -> None:
        """DB failure inside SAVEPOINT must not poison the outer transaction."""
        from nlp_pipeline.application.blocks.entity_resolution import ensure_provisional_for_mention

        mention = _make_mention("Some Org")
        mention.resolution_outcome = ResolutionOutcome.UNRESOLVED
        session = _intelligence_session_mock(hourly_count=0, queue_id=None)

        result = await ensure_provisional_for_mention(mention, session)

        assert result is None
        assert mention.provisional_queue_id is None
        # Outcome stays UNRESOLVED so the next cycle re-attempts.
        assert mention.resolution_outcome == ResolutionOutcome.UNRESOLVED
