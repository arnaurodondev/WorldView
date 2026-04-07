"""Context management domain entities for S8 RAG-Chat (PRD-0016 §6.5, Wave A-2).

ConversationContext is the fully assembled per-turn context passed to the LLM.
TurnSummary is an LLM-compressed record of a completed turn, stored in Valkey.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from rag_chat.domain.entities.chat import RetrievedItem
    from rag_chat.domain.enums import QueryIntent

_MAX_CONTEXT_TOKENS: int = 6000


@dataclass(frozen=True)
class TurnSummary:
    """LLM-generated compressed summary of one completed conversation turn.

    Stored in Valkey at ``s8:ctx:summary:{thread_id}:{turn_num}`` with a 24h TTL.
    Used during context assembly for turn N to represent older turns without
    requiring the full verbatim exchange.

    Attributes:
        summary_text: Compressed narrative, target 100-150 tokens.
        entities_referenced: Entity UUIDs mentioned in this turn.
        intent: QueryIntent that was resolved for this turn.
    """

    summary_text: str
    entities_referenced: tuple[UUID, ...]
    intent: QueryIntent


@dataclass(frozen=True)
class ConversationContext:
    """Assembled context passed to the LLM for a single conversation turn.

    Invariant: ``total_token_estimate ≤ 6000`` (NF05 — PRD-0016 §4).
    Raising ``ValueError`` on construction prevents context overflow from
    silently reaching the LLM layer.

    Context assembly order (optimised for provider-side prefix caching):
    1. ``system_prompt``          — static, cacheable
    2. ``turn_summaries``         — grows slowly, cacheable once computed
    3. ``last_turn_verbatim``     — dynamic but deterministic per turn
    4. ``retrieval_chunks``       — fresh per query, never cached
    5. ``query``                  — current user message

    Attributes:
        intent: Resolved QueryIntent for this turn.
        system_prompt: Intent-specific prompt template from prompt modules.
        turn_summaries: Compressed summaries of turns 1..N-2.
        last_turn_verbatim: Full Q+A text of turn N-1 (empty string on first turn).
        retrieval_chunks: Top-12 reranked RetrievedItem results.
        resolved_entities: Entity UUIDs resolved from the current query.
        query: The user's raw (HTML-stripped) query for this turn.
        total_token_estimate: Estimated token budget for the assembled prompt.
    """

    intent: QueryIntent
    system_prompt: str
    turn_summaries: tuple[str, ...]
    last_turn_verbatim: str
    retrieval_chunks: tuple[RetrievedItem, ...]
    resolved_entities: tuple[UUID, ...]
    query: str
    total_token_estimate: int

    def __post_init__(self) -> None:
        if self.total_token_estimate > _MAX_CONTEXT_TOKENS:
            raise ValueError(
                f"ConversationContext.total_token_estimate exceeds budget: "
                f"{self.total_token_estimate} > {_MAX_CONTEXT_TOKENS}"
            )
