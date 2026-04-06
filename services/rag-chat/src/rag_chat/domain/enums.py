"""Domain enumerations for the RAG-Chat service (S8)."""

from __future__ import annotations

from enum import Enum


class QueryIntent(str, Enum):
    """Intent categories for user queries — drives retrieval strategy selection."""

    FACTUAL_LOOKUP = "FACTUAL_LOOKUP"
    RELATIONSHIP = "RELATIONSHIP"
    SIGNAL_INTEL = "SIGNAL_INTEL"
    FINANCIAL_DATA = "FINANCIAL_DATA"
    COMPARISON = "COMPARISON"
    REASONING = "REASONING"
    PORTFOLIO = "PORTFOLIO"


class ItemType(str, Enum):
    """Type of a retrieved item in the unified retrieval result."""

    chunk = "chunk"
    relation = "relation"
    claim = "claim"
    event = "event"
    financial = "financial"
    cypher_path = "cypher_path"


class MessageRole(str, Enum):
    """Role in a conversation message."""

    user = "user"
    assistant = "assistant"
