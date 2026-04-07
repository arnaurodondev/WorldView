"""Unit tests for ContextManager (T-A-3-06).

PRD-0016 §6.5 / §6.7 acceptance criteria:
  - All 3 chunk-cache bypass conditions independently trigger MISS
  - All 3 conditions met simultaneously → HIT, chunks returned
  - assemble_context: total_token_estimate ≤ 6000 for all inputs
  - assemble_context: chunks trimmed by fusion_score (highest kept)
  - assemble_context: oldest summaries trimmed first when over budget
  - load_turn_summaries: missing turns silently skipped
  - generate_turn_summary: stores summary in cache, errors not raised
  - Entity overlap helpers: vacuous, partial, exact
  - Cosine similarity helpers: identical, orthogonal, typical
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from rag_chat.application.pipeline.context_manager import (
    HIT,
    MISS_ENTITY,
    MISS_INTENT,
    MISS_NO_CACHE,
    MISS_SIMILARITY,
    ContextManager,
    _cosine_similarity,
    _entity_overlap,
    _estimate_tokens,
)
from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType, QueryIntent

pytestmark = pytest.mark.unit

# ── UUIDs ─────────────────────────────────────────────────────────────────────

_T = UUID("01900000-0000-7000-8000-000000000001")  # thread_id
_E1 = UUID("01900000-0000-7000-8000-000000000002")
_E2 = UUID("01900000-0000-7000-8000-000000000003")
_E3 = UUID("01900000-0000-7000-8000-000000000004")


# ── In-process fake cache (no Valkey dependency) ──────────────────────────────


class _FakeCache:
    """Simple dict-backed ChunkCachePort for unit tests."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self._store.get(key)

    async def set(self, key: str, value: dict[str, Any], ttl: int) -> None:
        self._store[key] = value

    def has(self, key: str) -> bool:
        return key in self._store


# ── Fake LLM provider ─────────────────────────────────────────────────────────


class _FakeLLM:
    """Fake streaming LLM that yields a fixed response."""

    def __init__(self, response: str = "Turn summary text.") -> None:
        self._response = response

    async def stream(  # type: ignore[override]
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.1,
    ):
        yield self._response


class _EmptyLLM:
    """Fake LLM that yields nothing (empty response)."""

    async def stream(  # type: ignore[override]
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.1,
    ):
        return
        yield  # make it an async generator


class _ErrorLLM:
    """Fake LLM that raises on stream."""

    async def stream(  # type: ignore[override]
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.1,
    ):
        raise RuntimeError("LLM unavailable")
        yield  # make it an async generator


# ── RetrievedItem factory ─────────────────────────────────────────────────────


def _make_chunk(
    text: str = "chunk text",
    score: float = 0.9,
    trust_weight: float = 0.7,
    published_at: datetime | None = None,
) -> RetrievedItem:
    return RetrievedItem.create(
        item_id="item-1",
        item_type=ItemType.chunk,
        text=text,
        score=score,
        trust_weight=trust_weight,
        citation_meta=CitationMeta(
            title="Test Doc",
            url=None,
            source_name="test",
            published_at=published_at or datetime.now(tz=UTC),
            entity_name=None,
        ),
    )


# ── Fixture ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def cache() -> _FakeCache:
    return _FakeCache()


@pytest.fixture()
def llm() -> _FakeLLM:
    return _FakeLLM()


@pytest.fixture()
def manager(cache: _FakeCache, llm: _FakeLLM) -> ContextManager:
    return ContextManager(chunk_cache=cache, llm_provider=llm)


# ── Helper functions ──────────────────────────────────────────────────────────


class TestEntityOverlap:
    def test_both_empty_returns_one(self) -> None:
        """Vacuous case: both empty sets → 1.0."""
        assert _entity_overlap((), ()) == 1.0

    def test_identical_sets_returns_one(self) -> None:
        assert _entity_overlap((_E1, _E2), [str(_E1), str(_E2)]) == 1.0

    def test_disjoint_sets_returns_zero(self) -> None:
        assert _entity_overlap((_E1,), [str(_E2)]) == 0.0

    def test_one_empty_one_non_empty_returns_zero(self) -> None:
        assert _entity_overlap((), [str(_E1)]) == 0.0

    def test_partial_overlap_jaccard(self) -> None:
        # A = {E1, E2}, B = {E1, E3}  → intersection={E1}, union={E1,E2,E3}
        overlap = _entity_overlap((_E1, _E2), [str(_E1), str(_E3)])
        assert abs(overlap - 1 / 3) < 1e-9

    def test_two_thirds_overlap(self) -> None:
        # A = {E1, E2, E3}, B = {E1, E2}  → 2/3
        overlap = _entity_overlap((_E1, _E2, _E3), [str(_E1), str(_E2)])
        assert abs(overlap - 2 / 3) < 1e-9


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        v = [1.0, 0.0, 0.0]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-9

    def test_orthogonal_vectors(self) -> None:
        assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9

    def test_opposite_vectors(self) -> None:
        assert abs(_cosine_similarity([1.0, 0.0], [-1.0, 0.0]) - (-1.0)) < 1e-9

    def test_zero_vector_returns_zero(self) -> None:
        assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_length_mismatch_returns_zero(self) -> None:
        assert _cosine_similarity([1.0, 0.0], [1.0]) == 0.0

    def test_empty_vectors_returns_zero(self) -> None:
        assert _cosine_similarity([], []) == 0.0

    def test_typical_embedding_similarity(self) -> None:
        # Two normalised embeddings with angle ~25° → cos ≈ 0.906
        import math

        angle = math.radians(25)
        a = [1.0, 0.0]
        b = [math.cos(angle), math.sin(angle)]
        sim = _cosine_similarity(a, b)
        assert abs(sim - math.cos(angle)) < 1e-9


# ── Chunk cache — miss conditions ─────────────────────────────────────────────


class TestChunkCacheMissConditions:
    async def test_no_cache_when_key_absent(self, manager: ContextManager) -> None:
        chunks, reason = await manager.try_get_cached_chunks(
            thread_id=_T,
            prev_turn_num=1,
            current_intent=QueryIntent.FACTUAL_LOOKUP,
            current_entities=(_E1,),
            current_query_embedding=[1.0, 0.0],
        )
        assert chunks is None
        assert reason == MISS_NO_CACHE

    async def test_miss_on_intent_mismatch(self, manager: ContextManager, cache: _FakeCache) -> None:
        # Store cache entry with FACTUAL_LOOKUP
        await manager.cache_chunks(
            thread_id=_T,
            turn_num=1,
            intent=QueryIntent.FACTUAL_LOOKUP,
            entities=(_E1,),
            query_embedding=[1.0, 0.0],
            chunks=[_make_chunk()],
        )
        # Request with FINANCIAL_DATA
        chunks, reason = await manager.try_get_cached_chunks(
            thread_id=_T,
            prev_turn_num=1,
            current_intent=QueryIntent.FINANCIAL_DATA,
            current_entities=(_E1,),
            current_query_embedding=[1.0, 0.0],
        )
        assert chunks is None
        assert reason == MISS_INTENT

    async def test_miss_on_entity_mismatch(self, manager: ContextManager) -> None:
        # Cache: entity E1; Query: entity E2 (disjoint sets → overlap 0.0)
        await manager.cache_chunks(
            thread_id=_T,
            turn_num=1,
            intent=QueryIntent.FACTUAL_LOOKUP,
            entities=(_E1,),
            query_embedding=[1.0, 0.0],
            chunks=[_make_chunk()],
        )
        chunks, reason = await manager.try_get_cached_chunks(
            thread_id=_T,
            prev_turn_num=1,
            current_intent=QueryIntent.FACTUAL_LOOKUP,
            current_entities=(_E2,),  # different entity
            current_query_embedding=[1.0, 0.0],
        )
        assert chunks is None
        assert reason == MISS_ENTITY

    async def test_miss_on_low_similarity(self, manager: ContextManager) -> None:
        # Cache: query embedding [1, 0]; New: [0, 1] (orthogonal → sim 0.0)
        await manager.cache_chunks(
            thread_id=_T,
            turn_num=1,
            intent=QueryIntent.FACTUAL_LOOKUP,
            entities=(_E1,),
            query_embedding=[1.0, 0.0],
            chunks=[_make_chunk()],
        )
        chunks, reason = await manager.try_get_cached_chunks(
            thread_id=_T,
            prev_turn_num=1,
            current_intent=QueryIntent.FACTUAL_LOOKUP,
            current_entities=(_E1,),
            current_query_embedding=[0.0, 1.0],  # orthogonal
        )
        assert chunks is None
        assert reason == MISS_SIMILARITY


# ── Chunk cache — hit ─────────────────────────────────────────────────────────


class TestChunkCacheHit:
    async def test_hit_when_all_conditions_met(self, manager: ContextManager) -> None:
        """All 3 conditions satisfied → HIT with reconstructed chunks."""
        original = _make_chunk(text="original text")
        await manager.cache_chunks(
            thread_id=_T,
            turn_num=1,
            intent=QueryIntent.SIGNAL_INTEL,
            entities=(_E1, _E2),
            query_embedding=[1.0, 0.0],
            chunks=[original],
        )
        # Identical intent, full entity overlap, identical embedding
        chunks, reason = await manager.try_get_cached_chunks(
            thread_id=_T,
            prev_turn_num=1,
            current_intent=QueryIntent.SIGNAL_INTEL,
            current_entities=(_E1, _E2),
            current_query_embedding=[1.0, 0.0],
        )
        assert reason == HIT
        assert chunks is not None
        assert len(chunks) == 1
        assert chunks[0].text == "original text"

    async def test_hit_preserves_fusion_score_invariant(self, manager: ContextManager) -> None:
        """Reconstructed chunks must satisfy fusion_score == score * recency * trust."""
        chunk = _make_chunk()
        await manager.cache_chunks(
            thread_id=_T,
            turn_num=1,
            intent=QueryIntent.FACTUAL_LOOKUP,
            entities=(_E1,),
            query_embedding=[1.0, 0.0],
            chunks=[chunk],
        )
        chunks, _ = await manager.try_get_cached_chunks(
            thread_id=_T,
            prev_turn_num=1,
            current_intent=QueryIntent.FACTUAL_LOOKUP,
            current_entities=(_E1,),
            current_query_embedding=[1.0, 0.0],
        )
        assert chunks is not None
        item = chunks[0]
        expected = item.score * item.recency_score * item.trust_weight
        assert abs(item.fusion_score - expected) < 1e-9

    async def test_hit_general_intent_no_entities(self, manager: ContextManager) -> None:
        """GENERAL intent with no entities: vacuous entity overlap → HIT possible."""
        await manager.cache_chunks(
            thread_id=_T,
            turn_num=1,
            intent=QueryIntent.GENERAL,
            entities=(),
            query_embedding=[1.0, 0.0],
            chunks=[_make_chunk()],
        )
        chunks, reason = await manager.try_get_cached_chunks(
            thread_id=_T,
            prev_turn_num=1,
            current_intent=QueryIntent.GENERAL,
            current_entities=(),  # both empty → vacuously 100% overlap
            current_query_embedding=[1.0, 0.0],
        )
        assert reason == HIT
        assert chunks is not None

    async def test_chunk_key_format(self) -> None:
        key = ContextManager.chunk_key(_T, 3)
        assert key == f"s8:ctx:chunks:{_T}:3"

    async def test_summary_key_format(self) -> None:
        key = ContextManager.summary_key(_T, 5)
        assert key == f"s8:ctx:summary:{_T}:5"


# ── Turn summaries ────────────────────────────────────────────────────────────


class TestLoadTurnSummaries:
    async def _populate(self, cache: _FakeCache, turn_num: int, text: str) -> None:
        key = ContextManager.summary_key(_T, turn_num)
        await cache.set(key, {"summary_text": text, "entities_referenced": [], "intent": "GENERAL"}, ttl=86400)

    async def test_empty_when_no_summaries(self, manager: ContextManager) -> None:
        summaries = await manager.load_turn_summaries(_T, up_to_turn=3)
        assert summaries == []

    async def test_returns_present_summaries_only(self, manager: ContextManager, cache: _FakeCache) -> None:
        # Populate turns 1 and 3; turn 2 is missing
        await self._populate(cache, 1, "Summary of turn 1.")
        await self._populate(cache, 3, "Summary of turn 3.")
        summaries = await manager.load_turn_summaries(_T, up_to_turn=3)
        assert summaries == ["Summary of turn 1.", "Summary of turn 3."]

    async def test_returns_all_summaries_in_order(self, manager: ContextManager, cache: _FakeCache) -> None:
        for n in range(1, 4):
            await self._populate(cache, n, f"Turn {n} summary.")
        summaries = await manager.load_turn_summaries(_T, up_to_turn=3)
        assert summaries == ["Turn 1 summary.", "Turn 2 summary.", "Turn 3 summary."]

    async def test_up_to_zero_returns_empty(self, manager: ContextManager) -> None:
        summaries = await manager.load_turn_summaries(_T, up_to_turn=0)
        assert summaries == []


# ── generate_turn_summary ─────────────────────────────────────────────────────


class TestGenerateTurnSummary:
    async def test_summary_stored_in_cache(self, manager: ContextManager, cache: _FakeCache) -> None:
        """Directly testing _do_generate_turn_summary stores the summary."""
        await manager._do_generate_turn_summary(
            thread_id=_T,
            turn_num=2,
            query="What is the P/E ratio of AAPL?",
            response_text="The P/E ratio of AAPL is approximately 28.",
            intent=QueryIntent.FACTUAL_LOOKUP,
            entities=(_E1,),
        )
        key = ContextManager.summary_key(_T, 2)
        payload = await cache.get(key)
        assert payload is not None
        assert "summary_text" in payload
        assert payload["summary_text"] == "Turn summary text."
        assert payload["intent"] == "FACTUAL_LOOKUP"
        assert str(_E1) in payload["entities_referenced"]

    async def test_empty_llm_response_does_not_store(self) -> None:
        """Empty LLM response → nothing stored (no crash)."""
        cache = _FakeCache()
        manager = ContextManager(chunk_cache=cache, llm_provider=_EmptyLLM())
        await manager._do_generate_turn_summary(
            thread_id=_T,
            turn_num=1,
            query="query",
            response_text="response",
            intent=QueryIntent.GENERAL,
            entities=(),
        )
        key = ContextManager.summary_key(_T, 1)
        assert not cache.has(key)

    async def test_llm_error_does_not_raise(self) -> None:
        """LLM exception during summary → logged, not propagated."""
        cache = _FakeCache()
        manager = ContextManager(chunk_cache=cache, llm_provider=_ErrorLLM())
        # Must not raise
        await manager._do_generate_turn_summary(
            thread_id=_T,
            turn_num=1,
            query="query",
            response_text="response",
            intent=QueryIntent.GENERAL,
            entities=(),
        )

    async def test_generate_turn_summary_creates_background_task(self, manager: ContextManager) -> None:
        """generate_turn_summary() creates an asyncio task (fire-and-forget)."""
        assert len(manager._background_tasks) == 0
        await manager.generate_turn_summary(
            thread_id=_T,
            turn_num=3,
            query="query",
            response_text="response",
            intent=QueryIntent.GENERAL,
            entities=(),
        )
        # Task should exist (hasn't run yet because we haven't yielded)
        assert len(manager._background_tasks) == 1
        # Let the task complete
        await asyncio.sleep(0)
        await asyncio.sleep(0)  # two yields to ensure task finishes

    async def test_background_tasks_cleaned_up_after_completion(self, manager: ContextManager) -> None:
        """Task is removed from _background_tasks after completion."""
        await manager.generate_turn_summary(
            thread_id=_T,
            turn_num=4,
            query="query",
            response_text="response",
            intent=QueryIntent.SIGNAL_INTEL,
            entities=(_E1,),
        )
        # Yield until task completes
        for _ in range(5):
            await asyncio.sleep(0)
        assert len(manager._background_tasks) == 0


# ── assemble_context ──────────────────────────────────────────────────────────


class TestAssembleContext:
    def test_token_estimate_within_budget(self, manager: ContextManager) -> None:
        ctx = manager.assemble_context(
            intent=QueryIntent.FACTUAL_LOOKUP,
            system_prompt="You are a financial analyst.",
            turn_summaries=["Turn 1 summary."],
            last_turn_verbatim="Q: revenue? A: $100B.",
            retrieval_chunks=[_make_chunk("Some chunk text.")],
            resolved_entities=(_E1,),
            query="What is the revenue?",
        )
        assert ctx.total_token_estimate <= 6000

    def test_empty_inputs_valid(self, manager: ContextManager) -> None:
        ctx = manager.assemble_context(
            intent=QueryIntent.GENERAL,
            system_prompt="short prompt",
            turn_summaries=[],
            last_turn_verbatim="",
            retrieval_chunks=[],
            resolved_entities=(),
            query="hello",
        )
        assert ctx.total_token_estimate <= 6000
        assert ctx.turn_summaries == ()
        assert ctx.retrieval_chunks == ()

    def test_chunks_trimmed_to_fit_budget(self, manager: ContextManager) -> None:
        """Chunks exceeding the token budget are dropped (lowest fusion_score first)."""
        # Each chunk ~2500 tokens (10000 chars) — far over budget individually
        big_chunk_high = _make_chunk("A" * 10_000, score=0.9)
        big_chunk_low = _make_chunk("B" * 10_000, score=0.1)
        ctx = manager.assemble_context(
            intent=QueryIntent.FACTUAL_LOOKUP,
            system_prompt="short",
            turn_summaries=[],
            last_turn_verbatim="",
            retrieval_chunks=[big_chunk_low, big_chunk_high],
            resolved_entities=(),
            query="query",
        )
        assert ctx.total_token_estimate <= 6000
        # If any chunk is included, it must be the high-score one
        if ctx.retrieval_chunks:
            assert ctx.retrieval_chunks[0].score == 0.9

    def test_oldest_summaries_trimmed_first(self, manager: ContextManager) -> None:
        """When summaries push total over budget, oldest are trimmed first."""
        # 3 large summaries, each ~500 tokens
        summaries = ["S" * 2000 for _ in range(3)]  # ~500 tokens each = ~1500 total
        ctx = manager.assemble_context(
            intent=QueryIntent.REASONING,
            system_prompt="system",
            turn_summaries=summaries,
            last_turn_verbatim="last turn text",
            retrieval_chunks=[],
            resolved_entities=(),
            query="new query",
        )
        assert ctx.total_token_estimate <= 6000
        # Remaining summaries must be the newest (trailing ones)
        if ctx.turn_summaries:
            # The last summary should always be present (newest)
            assert ctx.turn_summaries[-1] == summaries[-1]

    def test_entity_ids_preserved(self, manager: ContextManager) -> None:
        ctx = manager.assemble_context(
            intent=QueryIntent.COMPARISON,
            system_prompt="prompt",
            turn_summaries=[],
            last_turn_verbatim="",
            retrieval_chunks=[],
            resolved_entities=(_E1, _E2),
            query="compare",
        )
        assert _E1 in ctx.resolved_entities
        assert _E2 in ctx.resolved_entities

    def test_chunks_sorted_by_fusion_score(self, manager: ContextManager) -> None:
        """Highest-fusion chunks are selected first when trimming."""
        chunks = [_make_chunk(f"chunk_{i}", score=0.1 * i, trust_weight=0.5) for i in range(1, 6)]
        ctx = manager.assemble_context(
            intent=QueryIntent.FACTUAL_LOOKUP,
            system_prompt="s",
            turn_summaries=[],
            last_turn_verbatim="",
            retrieval_chunks=chunks,
            resolved_entities=(),
            query="q",
        )
        # All small chunks should fit; verify ordering is by fusion_score desc
        if len(ctx.retrieval_chunks) > 1:
            scores = [c.fusion_score for c in ctx.retrieval_chunks]
            assert scores == sorted(scores, reverse=True)

    def test_large_fixed_content_clamped(self, manager: ContextManager) -> None:
        """If fixed content alone exceeds 6000 tokens, total is clamped to 6000."""
        # system_prompt: 12000 chars ≈ 3000 tokens
        # last_turn_verbatim: 12000 chars ≈ 3000 tokens
        # query: 4000 chars ≈ 1000 tokens  → total fixed = 7000 > 6000
        ctx = manager.assemble_context(
            intent=QueryIntent.REASONING,
            system_prompt="S" * 12_000,
            turn_summaries=[],
            last_turn_verbatim="L" * 12_000,
            retrieval_chunks=[],
            resolved_entities=(),
            query="Q" * 4_000,
        )
        # Clamped to 6000 to satisfy ConversationContext invariant
        assert ctx.total_token_estimate == 6000

    @pytest.mark.parametrize("n_turns", [1, 5, 8, 10])
    def test_multi_turn_conversations_stay_under_budget(self, manager: ContextManager, n_turns: int) -> None:
        """Simulate growing conversation history — always ≤ 6000 tokens."""
        summaries = [f"Summary of turn {i}. " * 20 for i in range(1, n_turns)]
        chunks = [_make_chunk(f"chunk {i}", score=0.9) for i in range(12)]
        ctx = manager.assemble_context(
            intent=QueryIntent.SIGNAL_INTEL,
            system_prompt="You are a financial intelligence assistant.",
            turn_summaries=summaries,
            last_turn_verbatim="User: What happened? Assistant: Market dropped 5%.",
            retrieval_chunks=chunks,
            resolved_entities=(_E1,),
            query="Tell me more about the drop.",
        )
        assert ctx.total_token_estimate <= 6000


# ── _estimate_tokens ──────────────────────────────────────────────────────────


class TestEstimateTokens:
    def test_empty_string_returns_one(self) -> None:
        assert _estimate_tokens("") == 1

    def test_four_chars_returns_one(self) -> None:
        assert _estimate_tokens("abcd") == 1

    def test_eight_chars_returns_two(self) -> None:
        assert _estimate_tokens("abcdefgh") == 2

    def test_large_text(self) -> None:
        text = "x" * 400
        assert _estimate_tokens(text) == 100
