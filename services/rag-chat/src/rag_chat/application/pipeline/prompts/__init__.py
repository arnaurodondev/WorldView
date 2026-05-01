"""Intent-specific LLM prompt modules for the RAG-Chat pipeline (T-A-1-03).

Public API: ``get_system_prompt(intent)`` returns the system prompt string
for the given QueryIntent. EMAIL_DEEP_BRIEF is exposed as a special mode
constant for the internal briefing endpoint.
"""

from rag_chat.application.pipeline.prompts.intent_prompts import (
    EMAIL_DEEP_BRIEF_PROMPT,
    RetrievalCounts,
    get_system_prompt,
)

__all__ = ["EMAIL_DEEP_BRIEF_PROMPT", "RetrievalCounts", "get_system_prompt"]
