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


class ItemType(StrEnum):
    """Type of a retrieved item in the unified retrieval result."""

    chunk = "chunk"
    relation = "relation"
    claim = "claim"
    event = "event"
    financial = "financial"
    cypher_path = "cypher_path"


class MessageRole(StrEnum):
    """Role in a conversation message."""

    user = "user"
    assistant = "assistant"


class BriefingType(StrEnum):
    """Type of AI briefing — drives prompt selection and context gathering."""

    MORNING = "MORNING"
    INSTRUMENT = "INSTRUMENT"
