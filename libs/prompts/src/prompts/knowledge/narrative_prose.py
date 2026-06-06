"""Narrative-prose system prompt (S7 knowledge-graph — PLAN-0088 P0-7).

Migrated from ``services/knowledge-graph/src/knowledge_graph/infrastructure/
llm/narrative_chat.py`` (Phase 2C, 2026-06-05).

This is the **system** message anchoring the model into a journalistic-prose
voice for ``DeepInfraNarrativeChatClient``. Without this anchor the 8B model
occasionally emits JSON or repeats the prompt header verbatim.

Versioning: ``1.0`` is the first migrated revision — the wording is
byte-identical to the inline string it replaces.
"""

from __future__ import annotations

from prompts._base import PromptTemplate

NARRATIVE_PROSE = PromptTemplate(
    name="narrative_prose",
    version="1.0",
    description=(
        "System message anchoring an LLM into a 2-4 sentence factual narrative "
        "voice for the GenerateNarrativeUseCase flow. Used by "
        "NarrativeRefreshWorker, NarrativeGenerationWorker, and the manual "
        "trigger endpoint to produce prose summaries of structured entity "
        "profiles WITHOUT JSON mode."
    ),
    template=(
        "You are a financial intelligence analyst. Given a structured "
        "entity profile, write a concise factual 2-4 sentence narrative. "
        "Output ONLY the narrative prose — no JSON, no preamble, no headers."
    ),
    # System-only message — caller supplies the structured profile via the
    # user role at the chat-completion layer.
    parameters=frozenset(),
)
