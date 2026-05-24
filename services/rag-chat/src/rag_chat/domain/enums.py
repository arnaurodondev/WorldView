"""Domain enumerations for the RAG-Chat service (S8)."""

from __future__ import annotations

from enum import StrEnum


class QueryIntent(StrEnum):
    """Intent categories for user queries — drives retrieval strategy selection."""

    FACTUAL_LOOKUP = "FACTUAL_LOOKUP"
    GENERAL = "GENERAL"
    COMPARISON = "COMPARISON"
    FINANCIAL_DATA = "FINANCIAL_DATA"
    PORTFOLIO = "PORTFOLIO"
    REASONING = "REASONING"
    RELATIONSHIP = "RELATIONSHIP"
    SIGNAL_INTEL = "SIGNAL_INTEL"
    # PLAN-0093 Wave E-1: dedicated intent for macro/calendar queries so the
    # per-intent rerank weights and prompt addendum can differentiate macro
    # questions ("ECB meeting next week") from generic factual lookups.
    MACRO = "MACRO"


class ItemType(StrEnum):
    """Type of a retrieved item in the unified retrieval result."""

    chunk = "chunk"
    relation = "relation"
    claim = "claim"
    event = "event"
    financial = "financial"
    cypher_path = "cypher_path"
    # PLAN-0082 Wave B: write-action tools return an action_pending item so the
    # pipeline can detect it and emit a pending_action SSE event for confirmation.
    action_pending = "action_pending"


class MessageRole(StrEnum):
    """Role in a conversation message."""

    user = "user"
    assistant = "assistant"


class BriefingType(StrEnum):
    """Type of AI briefing — drives prompt selection and context gathering."""

    MORNING = "MORNING"
    INSTRUMENT = "INSTRUMENT"
