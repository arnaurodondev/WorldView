"""3-Layer Context Manager for the S8 RAG-Chat pipeline (T-A-3-03, T-A-3-04).

Three-condition chunk cache reuse (ALL must hold, PRD-0016 §F05):
    1. entity_overlap  > 50%   (Jaccard similarity on resolved entity UUID sets)
    2. Same intent class       (QueryIntent enum equality)
    3. query_sim       > 0.85  (cosine similarity of query embeddings)

Context assembly order (optimised for provider-side prefix caching, PRD-0016 §AD-04):
    system_prompt → turn_summaries → last_turn_verbatim → retrieval_chunks → query
    Hard budget: ≤ 6 000 tokens (enforced by ConversationContext invariant).

Turn summary generation (PRD-0016 §F06, §AD-03):
    Fires post-stream as a background asyncio task — not awaited by the caller.
    Stored in Valkey ``s8:ctx:summary:{thread_id}:{turn_num}`` with 24 h TTL.
    Any LLM or Valkey error is logged and swallowed (graceful degradation).
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.entities.context import ConversationContext
from rag_chat.domain.enums import ItemType, QueryIntent

if TYPE_CHECKING:
    from rag_chat.application.ports.chunk_cache import ChunkCachePort
    from rag_chat.application.ports.llm_provider import LlmStreamProvider

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# ── Cache-reuse constants ─────────────────────────────────────────────────────

_CHUNK_TTL: int = 4 * 3600  # 4 hours — mirrors ValkeyChunkCacheAdapter.CHUNK_TTL
_SUMMARY_TTL: int = 24 * 3600  # 24 hours — mirrors ValkeyChunkCacheAdapter.SUMMARY_TTL
_ENTITY_OVERLAP_THRESHOLD: float = 0.5  # exclusive — must be strictly greater
_QUERY_SIM_THRESHOLD: float = 0.85  # exclusive — must be strictly greater
_MAX_CONTEXT_TOKENS: int = 6_000
_CHARS_PER_TOKEN: int = 4  # rough approximation (1 token ≈ 4 chars)

# ── Cache-miss reason labels (also used as Prometheus label values) ───────────

MISS_NO_CACHE: str = "no_cache"
MISS_INTENT: str = "intent_mismatch"
MISS_ENTITY: str = "entity_mismatch"
MISS_SIMILARITY: str = "low_similarity"
HIT: str = "hit"

# ── LLM prompt for turn summary ───────────────────────────────────────────────

_SUMMARY_PROMPT_TEMPLATE = (
    "Summarise the following conversation turn in 2-3 sentences (100-150 words). "
    "Include key entities mentioned, the type of question, and the main conclusion.\n\n"
    "User: {query}\n\n"
    "Assistant: {response_text}"
)
_RESPONSE_TRUNCATION: int = 2_000  # chars fed into the summary prompt


# ── Pure helpers ──────────────────────────────────────────────────────────────


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 characters (English prose)."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length float vectors (pure Python)."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


def _entity_overlap(
    entities_a: tuple[UUID, ...] | list[str],
    entities_b: tuple[UUID, ...] | list[str],
) -> float:
    """Jaccard similarity between two entity-ID sets.

    Special case: both sets empty → returns 1.0 (vacuously satisfied) so that
    intent-only GENERAL queries can still benefit from chunk cache reuse when
    neither turn resolves named entities.
    """
    set_a = {str(e) for e in entities_a}
    set_b = {str(e) for e in entities_b}
    if not set_a and not set_b:
        return 1.0  # vacuously satisfied
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


# ── Serialisation helpers ─────────────────────────────────────────────────────


def _serialize_chunk(item: RetrievedItem) -> dict[str, Any]:
    """Convert a ``RetrievedItem`` to a JSON-serialisable dict."""
    return {
        "item_id": item.item_id,
        "item_type": str(item.item_type),
        "text": item.text,
        "score": item.score,
        "recency_score": item.recency_score,
        "trust_weight": item.trust_weight,
        # fusion_score intentionally NOT stored — recomputed on deserialisation
        # to avoid floating-point divergence from JSON round-trip.
        "entity_id": str(item.entity_id) if item.entity_id else None,
        "doc_id": str(item.doc_id) if item.doc_id else None,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "graph_enrichment": list(item.graph_enrichment),
        "citation_meta": {
            "title": item.citation_meta.title,
            "url": item.citation_meta.url,
            "source_name": item.citation_meta.source_name,
            "published_at": (item.citation_meta.published_at.isoformat() if item.citation_meta.published_at else None),
            "entity_name": item.citation_meta.entity_name,
        },
    }


def _deserialize_chunk(data: dict[str, Any]) -> RetrievedItem:
    """Reconstruct a ``RetrievedItem`` from a cached dict.

    fusion_score is recomputed from stored components (score * recency * trust)
    to keep the RetrievedItem invariant consistent across JSON round-trips.
    """
    cm_data: dict[str, Any] = data.get("citation_meta") or {}
    cm_pub_str: str | None = cm_data.get("published_at")
    citation_meta = CitationMeta(
        title=cm_data.get("title"),
        url=cm_data.get("url"),
        source_name=cm_data.get("source_name"),
        published_at=datetime.fromisoformat(cm_pub_str) if cm_pub_str else None,
        entity_name=cm_data.get("entity_name"),
    )

    pub_str: str | None = data.get("published_at")
    published_at = datetime.fromisoformat(pub_str) if pub_str else None

    score = float(data["score"])
    recency_score = float(data["recency_score"])
    trust_weight = float(data["trust_weight"])
    fusion_score = score * recency_score * trust_weight  # recompute — avoids round-trip drift

    entity_id_str: str | None = data.get("entity_id")
    doc_id_str: str | None = data.get("doc_id")

    return RetrievedItem(
        item_id=data["item_id"],
        item_type=ItemType(data["item_type"]),
        text=data["text"],
        score=score,
        recency_score=recency_score,
        trust_weight=trust_weight,
        fusion_score=fusion_score,
        citation_meta=citation_meta,
        entity_id=UUID(entity_id_str) if entity_id_str else None,
        doc_id=UUID(doc_id_str) if doc_id_str else None,
        published_at=published_at,
        graph_enrichment=tuple(data.get("graph_enrichment") or []),
    )


# ── ContextManager ────────────────────────────────────────────────────────────


class ContextManager:
    """3-layer conversation context service for the S8 RAG-Chat pipeline.

    Layer 1 — Chunk cache (Valkey, TTL 4 h):
        On every turn, check whether cached chunks from the previous turn
        satisfy the triple reuse condition.  Cache miss → full retrieval.

    Layer 2 — Async LLM turn summaries (Valkey, TTL 24 h):
        After each response stream completes, fire a background LLM call to
        compress the turn into a 100-150 word summary.  Stored per turn.

    Layer 3 — Bounded ConversationContext assembly (≤ 6 000 tokens):
        Assembles system prompt + compressed summaries + last-turn verbatim +
        retrieval chunks + query.  Trims chunks and old summaries to fit.

    Args:
        chunk_cache: Async read/write cache (implements :class:`ChunkCachePort`).
        llm_provider: Streaming LLM used exclusively for turn-summary generation.
    """

    def __init__(
        self,
        chunk_cache: ChunkCachePort,
        llm_provider: LlmStreamProvider,
    ) -> None:
        self._cache = chunk_cache
        self._llm = llm_provider
        # Holds strong references to scheduled background tasks (prevents GC).
        self._background_tasks: set[asyncio.Task[None]] = set()

    # ── Valkey key helpers ────────────────────────────────────────────────────

    @staticmethod
    def chunk_key(thread_id: UUID, turn_num: int) -> str:
        """Return the Valkey key for a turn's cached retrieval chunks."""
        return f"s8:ctx:chunks:{thread_id}:{turn_num}"

    @staticmethod
    def summary_key(thread_id: UUID, turn_num: int) -> str:
        """Return the Valkey key for a turn's LLM-generated summary."""
        return f"s8:ctx:summary:{thread_id}:{turn_num}"

    # ── Chunk cache operations ────────────────────────────────────────────────

    async def try_get_cached_chunks(
        self,
        thread_id: UUID,
        prev_turn_num: int,
        current_intent: QueryIntent,
        current_entities: tuple[UUID, ...],
        current_query_embedding: list[float],
    ) -> tuple[list[RetrievedItem] | None, str]:
        """Check 3-condition cache reuse for *prev_turn_num*'s cached chunks.

        Returns ``(chunks, reason)`` where *reason* is one of:
        ``"hit"``, ``"no_cache"``, ``"intent_mismatch"``,
        ``"entity_mismatch"``, ``"low_similarity"``.

        On a cache hit all three conditions hold and *chunks* is the cached
        list; on a miss *chunks* is ``None``.
        """
        key = self.chunk_key(thread_id, prev_turn_num)
        payload: dict[str, Any] | None = await self._cache.get(key)

        if payload is None:
            return None, MISS_NO_CACHE

        # ── Condition 1: same intent ──────────────────────────────────────────
        if payload.get("intent", "") != str(current_intent):
            return None, MISS_INTENT

        # ── Condition 2: entity overlap > 50 % ────────────────────────────────
        cached_entities: list[str] = payload.get("entities", [])
        if _entity_overlap(current_entities, cached_entities) <= _ENTITY_OVERLAP_THRESHOLD:
            return None, MISS_ENTITY

        # ── Condition 3: query similarity > 0.85 ──────────────────────────────
        cached_embedding: list[float] = payload.get("query_embedding", [])
        if _cosine_similarity(current_query_embedding, cached_embedding) <= _QUERY_SIM_THRESHOLD:
            return None, MISS_SIMILARITY

        # ── All conditions met — deserialise cached chunks ────────────────────
        raw_chunks: list[dict[str, Any]] = payload.get("chunks", [])
        try:
            chunks = [_deserialize_chunk(c) for c in raw_chunks]
        except Exception:
            log.warning(
                "chunk_cache_deserialise_failed",
                thread_id=str(thread_id),
                turn_num=prev_turn_num,
            )
            return None, MISS_NO_CACHE

        return chunks, HIT

    async def cache_chunks(
        self,
        thread_id: UUID,
        turn_num: int,
        intent: QueryIntent,
        entities: tuple[UUID, ...],
        query_embedding: list[float],
        chunks: list[RetrievedItem],
    ) -> None:
        """Persist the retrieval chunks for *turn_num* in Valkey (TTL 4 h).

        Errors are logged and swallowed — a write failure degrades to full
        retrieval on the next turn, which is acceptable.
        """
        key = self.chunk_key(thread_id, turn_num)
        payload: dict[str, Any] = {
            "intent": str(intent),
            "entities": [str(e) for e in entities],
            "query_embedding": query_embedding,
            "chunks": [_serialize_chunk(c) for c in chunks],
        }
        try:
            await self._cache.set(key, payload, ttl=_CHUNK_TTL)
        except Exception:
            log.warning(
                "chunk_cache_write_failed",
                thread_id=str(thread_id),
                turn_num=turn_num,
            )

    # ── Turn summary operations ───────────────────────────────────────────────

    async def load_turn_summaries(
        self,
        thread_id: UUID,
        up_to_turn: int,
    ) -> list[str]:
        """Load turn summary texts for turns 1..``up_to_turn`` from Valkey.

        Turns whose summary has expired or was never generated are silently
        skipped — the context assembler gracefully handles partial summary sets.

        Args:
            thread_id: Conversation thread UUID.
            up_to_turn: Inclusive upper bound (e.g. N-2 for assembling turn N).

        Returns:
            Ascending-order list of non-empty summary strings.
        """
        summaries: list[str] = []
        for turn_num in range(1, up_to_turn + 1):
            key = self.summary_key(thread_id, turn_num)
            payload: dict[str, Any] | None = await self._cache.get(key)
            if payload and payload.get("summary_text"):
                summaries.append(payload["summary_text"])
        return summaries

    async def generate_turn_summary(
        self,
        thread_id: UUID,
        turn_num: int,
        query: str,
        response_text: str,
        intent: QueryIntent,
        entities: tuple[UUID, ...],
    ) -> None:
        """Schedule non-blocking LLM turn-summary generation (PRD-0016 §AD-03).

        Creates a background asyncio task that generates a 100-150 word summary
        and stores it in Valkey.  Returns immediately — the caller does not
        need to await the summary result.  All errors are logged, not raised.
        """
        task: asyncio.Task[None] = asyncio.create_task(
            self._do_generate_turn_summary(thread_id, turn_num, query, response_text, intent, entities)
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _do_generate_turn_summary(
        self,
        thread_id: UUID,
        turn_num: int,
        query: str,
        response_text: str,
        intent: QueryIntent,
        entities: tuple[UUID, ...],
    ) -> None:
        """Internal coroutine: generate summary via LLM and store in Valkey."""
        try:
            prompt = _SUMMARY_PROMPT_TEMPLATE.format(
                query=query,
                response_text=response_text[:_RESPONSE_TRUNCATION],
            )
            summary_text = ""
            async for token in self._llm.stream(prompt, max_tokens=200, temperature=0.1):
                summary_text += token
            summary_text = summary_text.strip()

            if not summary_text:
                log.warning(
                    "turn_summary_empty_response",
                    thread_id=str(thread_id),
                    turn_num=turn_num,
                )
                return

            key = self.summary_key(thread_id, turn_num)
            payload: dict[str, Any] = {
                "summary_text": summary_text,
                "entities_referenced": [str(e) for e in entities],
                "intent": str(intent),
            }
            await self._cache.set(key, payload, ttl=_SUMMARY_TTL)

        except Exception:
            log.warning(
                "turn_summary_generation_failed",
                thread_id=str(thread_id),
                turn_num=turn_num,
            )

    # ── Context assembly ──────────────────────────────────────────────────────

    def assemble_context(
        self,
        intent: QueryIntent,
        system_prompt: str,
        turn_summaries: list[str],
        last_turn_verbatim: str,
        retrieval_chunks: list[RetrievedItem],
        resolved_entities: tuple[UUID, ...],
        query: str,
    ) -> ConversationContext:
        """Assemble a :class:`ConversationContext` within the 6 000-token budget.

        Budget allocation (priority order):
        1. Fixed: ``system_prompt`` + ``last_turn_verbatim`` + ``query`` (always kept).
        2. Summaries: trim oldest first until they fit within the remaining budget.
        3. Chunks: highest ``fusion_score`` first; stop when budget exhausted.

        The returned ``total_token_estimate`` is clamped to ``_MAX_CONTEXT_TOKENS``
        as a safety guard when fixed content alone approaches the budget limit.
        """
        # ── Step 1: Fixed token cost ──────────────────────────────────────────
        fixed_tokens = _estimate_tokens(system_prompt) + _estimate_tokens(last_turn_verbatim) + _estimate_tokens(query)
        remaining = _MAX_CONTEXT_TOKENS - fixed_tokens

        # ── Step 2: Fit summaries within remaining budget ─────────────────────
        selected_summaries = list(turn_summaries)
        summary_tokens = sum(_estimate_tokens(s) for s in selected_summaries)
        while summary_tokens > remaining and selected_summaries:
            oldest = selected_summaries.pop(0)
            summary_tokens -= _estimate_tokens(oldest)

        # ── Step 3: Fill remaining budget with top-scoring chunks ─────────────
        chunk_budget = remaining - summary_tokens
        sorted_chunks = sorted(retrieval_chunks, key=lambda c: c.fusion_score, reverse=True)
        selected_chunks: list[RetrievedItem] = []
        used_chunk_tokens = 0
        for chunk in sorted_chunks:
            chunk_tokens = _estimate_tokens(chunk.text)
            if used_chunk_tokens + chunk_tokens <= chunk_budget:
                selected_chunks.append(chunk)
                used_chunk_tokens += chunk_tokens

        total_tokens = min(
            fixed_tokens + summary_tokens + used_chunk_tokens,
            _MAX_CONTEXT_TOKENS,
        )

        return ConversationContext(
            intent=intent,
            system_prompt=system_prompt,
            turn_summaries=tuple(selected_summaries),
            last_turn_verbatim=last_turn_verbatim,
            retrieval_chunks=tuple(selected_chunks),
            resolved_entities=resolved_entities,
            query=query,
            total_token_estimate=total_tokens,
        )
