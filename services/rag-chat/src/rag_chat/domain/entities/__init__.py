"""Domain entities for the RAG-Chat service (S8)."""

from __future__ import annotations

from rag_chat.domain.entities.chat import (
    ChatContext,
    ChatRequest,
    CitationMeta,
    ResolvedEntity,
    ResolvedQuery,
    RetrievalPlan,
    RetrievedItem,
    compute_recency_score,
)
from rag_chat.domain.entities.context import ConversationContext, TurnSummary
from rag_chat.domain.entities.conversation import (
    Citation,
    ContradictionRef,
    ConversationThread,
    Message,
)

__all__ = [
    "ChatContext",
    "ChatRequest",
    "Citation",
    "CitationMeta",
    "ContradictionRef",
    "ConversationContext",
    "ConversationThread",
    "Message",
    "ResolvedEntity",
    "ResolvedQuery",
    "RetrievalPlan",
    "RetrievedItem",
    "TurnSummary",
    "compute_recency_score",
]
