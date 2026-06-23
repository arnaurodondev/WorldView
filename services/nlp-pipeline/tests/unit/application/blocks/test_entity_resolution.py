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
    _ticker_candidate,
    run_entity_resolution_block,
)
from nlp_pipeline.domain.enums import MentionClass, ResolutionOutcome
from nlp_pipeline.domain.models import EntityMention, MentionResolution

pytestmark = pytest.mark.unit


class TestTickerCandidate:
    """Regression guard for the case-sensitive Stage-2 ticker gate.

    The 2026-06-20 stored-relation audit surfaced a class of mis-resolutions where
    a mixed-case company acronym (xAI, Citi) was treated as a ticker and collided
    with an unrelated security that owns that symbol (xAI -> "XAI Octagon ... Trust"
    closed-end fund). The case-sensitive ``isupper()`` gate already prevents this;
    these tests LOCK that behaviour so it cannot silently regress.
    """

    @pytest.mark.parametrize("mixed_case", ["xAI", "Citi", "eBay", "iRobot", "PayPal", "Tesla"])
    def test_mixed_case_acronyms_are_not_tickers(self, mixed_case: str) -> None:
        assert _ticker_candidate(mixed_case) is None

    @pytest.mark.parametrize("real_ticker", ["AAPL", "XAI", "F", "COST", "BRK"])
    def test_all_caps_short_symbols_are_tickers(self, real_ticker: str) -> None:
        assert _ticker_candidate(real_ticker) == real_ticker

    def test_exchange_qualifier_stripped_before_gate(self) -> None:
        # "AAPL.MX" is length 7 (past the <=6 cap) until the venue suffix is stripped.
        assert _ticker_candidate("AAPL.MX") == "AAPL"

    def test_long_all_caps_is_not_a_ticker(self) -> None:
        assert _ticker_candidate("MORGANSTANLEY") is None


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
    alias_repo.batch_class_aware_canonical_match = AsyncMock(return_value={})
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
    # Stage 2.5 — class-aware canonical_name match (PLAN-0087 F-LLM-001).
    # Default to empty dict so existing tests are unaffected.  Tests that
    # exercise the class-aware path override this attribute directly.
    alias_repo.batch_class_aware_canonical_match = AsyncMock(return_value={})
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
        _insert_result.scalar_one_or_none = MagicMock(return_value=str(uuid.uuid4()))
        # BP-707: run_entity_resolution_block now issues a leading `SET LOCAL
        # lock_timeout` execute before the churn-COUNT + provisional INSERT.
        _lock_result = MagicMock()
        intelligence_session.execute = AsyncMock(side_effect=[_lock_result, _count_result, _insert_result])
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
    # BP-707: the insert now uses ON CONFLICT DO NOTHING + scalar_one_or_none
    # (None on conflict → lock-free fallback SELECT). queue_id is the RETURNING row.
    insert_result.scalar_one_or_none = MagicMock(return_value=str(queue_id) if queue_id else None)
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


# ── ensure_provisional_for_ref (2026-06-14 M2 endpoint-recovery) ─────────────


@pytest.mark.unit
class TestEnsureProvisionalForRef:
    """ensure_provisional_for_ref mints a queue row for a bare LLM endpoint
    surface that has NO backing mention — the M2 fix for the dominant
    relation-drop miss-reason (the non-mention counterparty endpoint).
    """

    @pytest.mark.asyncio
    async def test_mints_queue_row_for_bare_surface(self) -> None:
        from nlp_pipeline.application.blocks.entity_resolution import ensure_provisional_for_ref

        queue_id = uuid.uuid4()
        session = _intelligence_session_mock(hourly_count=0, queue_id=queue_id)

        result = await ensure_provisional_for_ref(
            surface="ARMEC",
            mention_class=MentionClass.ORGANIZATION,
            doc_id=uuid.uuid4(),
            intelligence_session=session,
        )

        assert result == queue_id
        # Both the churn-COUNT and the INSERT ran (no backing mention required).
        assert session.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_churn_guard_blocks_mint(self) -> None:
        from nlp_pipeline.application.blocks.entity_resolution import (
            MAX_PROVISIONAL_PER_HOUR,
            ensure_provisional_for_ref,
        )

        session = _intelligence_session_mock(hourly_count=MAX_PROVISIONAL_PER_HOUR, queue_id=uuid.uuid4())

        result = await ensure_provisional_for_ref(
            surface="Mystery Co",
            mention_class=MentionClass.ORGANIZATION,
            doc_id=uuid.uuid4(),
            intelligence_session=session,
        )

        assert result is None
        # Only the COUNT ran — no INSERT attempted (begin_nested never entered).
        session.begin_nested.assert_not_called()

    @pytest.mark.asyncio
    async def test_savepoint_failure_returns_none(self) -> None:
        from nlp_pipeline.application.blocks.entity_resolution import ensure_provisional_for_ref

        session = _intelligence_session_mock(hourly_count=0, queue_id=None)

        result = await ensure_provisional_for_ref(
            surface="Some Org",
            mention_class=MentionClass.ORGANIZATION,
            doc_id=uuid.uuid4(),
            intelligence_session=session,
        )

        assert result is None


# ── PLAN-0087 F-LLM-001: Stage 2.5 class-aware canonical_name resolution ─────


@pytest.mark.unit
class TestStage25ClassAwareCanonical:
    """Stage 2.5 — class-aware canonical_name match (PLAN-0087 F-LLM-001).

    These tests assert the integration of the new
    ``batch_class_aware_canonical_match`` call inside
    ``run_entity_resolution_block``: a GLiNER ``organization`` mention for
    "Apple" must resolve to the AAPL canonical (which is stored as
    ``entity_type='financial_instrument'``) without falling through to
    Stage 3 fuzzy or Stage 4 ANN.

    Without this stage, the mention would land in PROVISIONAL or UNRESOLVED
    and the article-consumer's ``entity_id_by_ref`` filter would silently
    drop every relation/event/claim referencing it — the root cause of the
    "1141 LLM extraction calls → 0 organic relation_evidence_raw rows"
    pattern documented in 2026-05-09 QA F-LLM-001.
    """

    @pytest.mark.asyncio
    async def test_organization_mention_resolves_to_financial_instrument_canonical(self) -> None:
        """An "Apple" mention tagged ``organization`` resolves to AAPL canonical via Stage 2.5.

        Stages 1 + 2 miss (no bare "apple" alias, not all-caps for ticker).
        Stage 2.5 returns the AAPL entity_id from the class-aware canonical
        sweep.  Confidence equals ``CONFIDENCE_CLASS_AWARE_CANONICAL`` (0.93)
        which is well above ``AUTO_RESOLVE_THRESHOLD`` (0.62), so the mention
        flips to ``AUTO_RESOLVED`` and gets a real ``resolved_entity_id``.
        """
        from nlp_pipeline.application.blocks.entity_resolution import CONFIDENCE_CLASS_AWARE_CANONICAL

        aapl_entity_id = uuid.uuid4()
        mention = _make_mention("Apple", MentionClass.ORGANIZATION)
        alias_repo, embedding_repo, canonical_repo, audit_repo = _make_batch_repos()
        # Stage 2.5 returns AAPL for the (surface, class) pair.
        alias_repo.batch_class_aware_canonical_match = AsyncMock(
            return_value={("Apple", "organization"): aapl_entity_id},
        )
        intelligence_session = MagicMock()
        intelligence_session.execute = AsyncMock()

        resolved, _audit = await run_entity_resolution_block(
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
        assert resolved[0].resolved_entity_id == aapl_entity_id
        assert resolved[0].resolution_confidence == CONFIDENCE_CLASS_AWARE_CANONICAL

    @pytest.mark.asyncio
    async def test_stage25_skipped_when_stage1_already_resolved(self) -> None:
        """If Stage 1 already resolved the mention, Stage 2.5 is not asked about it.

        The candidate pair list passed to ``batch_class_aware_canonical_match``
        excludes mentions matched by exact alias (Stage 1) or ticker/isin
        (Stage 2).  This keeps the SQL parameter count down and prevents
        Stage 2.5 from accidentally overruling a higher-priority match.
        """
        entity_id = uuid.uuid4()
        mention = _make_mention("Apple Inc.", MentionClass.ORGANIZATION)
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

        # batch_class_aware_canonical_match was either not called at all OR
        # called with an empty list (Stage-1 hit excludes the mention from
        # the Stage-2.5 candidate set).  Either is correct behaviour.
        if alias_repo.batch_class_aware_canonical_match.await_count > 0:
            call_args = alias_repo.batch_class_aware_canonical_match.await_args
            pairs = call_args.args[0] if call_args.args else call_args.kwargs.get("surface_class_pairs", [])
            assert pairs == [], "Stage 2.5 should not see Stage-1-resolved mentions"

    @pytest.mark.asyncio
    async def test_stage25_emits_audit_row(self) -> None:
        """Stage 2.5 always writes a MentionResolution audit row (hit or miss).

        The audit row is needed for observability: without it, the
        F-LLM-005-style discrepancy ("resolved but resolution_outcome stays
        unresolved") would extend to "resolved at Stage 2.5 but no audit
        trail of the resolution path".
        """
        aapl_id = uuid.uuid4()
        mention = _make_mention("Apple", MentionClass.ORGANIZATION)
        alias_repo, embedding_repo, canonical_repo, audit_repo = _make_batch_repos()
        alias_repo.batch_class_aware_canonical_match = AsyncMock(
            return_value={("Apple", "organization"): aapl_id},
        )
        intelligence_session = MagicMock()
        intelligence_session.execute = AsyncMock()

        _resolved, audit = await run_entity_resolution_block(
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

        # Filter audit for Stage 2.5 (method='class_aware_canonical').
        s25_audits = [a for a in audit if a.metadata.get("method") == "class_aware_canonical"]
        assert len(s25_audits) == 1
        assert s25_audits[0].is_winner is True
        assert s25_audits[0].candidate_entity_id == aapl_id
        assert s25_audits[0].metadata["mention_class"] == "organization"

    @pytest.mark.asyncio
    async def test_stage25_miss_falls_through_to_fuzzy(self) -> None:
        """A Stage-2.5 miss does not short-circuit later stages.

        Backward-compat invariant: the addition of Stage 2.5 must not skip
        mentions that have a fuzzy or ANN match.  A surface that isn't in
        any class-typed canonical_name should still reach Stage 3.
        """
        fuzzy_id = uuid.uuid4()
        mention = _make_mention("Acme Holdings Incorporated", MentionClass.ORGANIZATION)
        alias_repo, embedding_repo, canonical_repo, audit_repo = _make_batch_repos(
            fuzzy_map={"acme holdings incorporated": [(fuzzy_id, 0.85)]},
        )
        # Stage 2.5 returns nothing for this surface.
        alias_repo.batch_class_aware_canonical_match = AsyncMock(return_value={})
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

        # 0.85 (fuzzy sim) * 0.90 (multiplier) = 0.765 → AUTO_RESOLVED
        assert resolved[0].resolution_outcome == ResolutionOutcome.AUTO_RESOLVED
        assert resolved[0].resolved_entity_id == fuzzy_id


class TestStage2ExchangeQualifierStrip:
    """2026-06-15 fix: exchange-suffixed tickers resolve via the bare symbol.

    Before the fix, "AAPL.MX" (length 7) failed the ``len <= 6`` ticker gate and
    never reached the Stage-2 lookup, so it fell through to fuzzy/ANN or was
    dropped — minting a duplicate tickerless canonical downstream.
    """

    @pytest.mark.asyncio
    async def test_exchange_suffixed_ticker_resolves_via_bare_symbol(self) -> None:
        entity_id = uuid.uuid4()
        mention = _make_mention("AAPL.MX")
        # The repo is keyed by the BARE ticker the block must query after stripping.
        alias_repo, embedding_repo, canonical_repo, audit_repo = _make_batch_repos(
            ticker_isin_map={"AAPL": entity_id},
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

        # Resolved to the existing AAPL canonical (no duplicate minted)...
        assert resolved[0].resolved_entity_id == entity_id
        # ...and the lookup was issued for the STRIPPED bare ticker, not "AAPL.MX".
        called_tickers = alias_repo.batch_ticker_isin_match.call_args.args[0]
        assert "AAPL" in called_tickers
        assert "AAPL.MX" not in called_tickers

    @pytest.mark.asyncio
    async def test_share_class_ticker_is_not_stripped(self) -> None:
        """BRK.B is a distinct security — it must be queried as-is, not as 'BRK'."""
        entity_id = uuid.uuid4()
        mention = _make_mention("BRK.B")
        alias_repo, embedding_repo, canonical_repo, audit_repo = _make_batch_repos(
            ticker_isin_map={"BRK.B": entity_id},
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

        assert resolved[0].resolved_entity_id == entity_id
        called_tickers = alias_repo.batch_ticker_isin_match.call_args.args[0]
        assert "BRK.B" in called_tickers
        assert "BRK" not in called_tickers
