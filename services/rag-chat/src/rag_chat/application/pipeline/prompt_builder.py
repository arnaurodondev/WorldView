"""Prompt builder - Step 10 of the RAG pipeline (T-F-2-02).

Assembles the full LLM prompt from all components:
  - Intent-specific system instruction (PRD-0016 §3.1 F01)
  - Context block (top-12 numbered items)
  - Contradiction block (if any)
  - Financial data block (if financial items retrieved)
  - Conversation history (last 5 turns)
  - User query + sub-questions
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rag_chat.application.pipeline.prompts import get_system_prompt
from rag_chat.domain.enums import QueryIntent

if TYPE_CHECKING:
    from rag_chat.application.pipeline.context_assembler import ContradictionBlock
    from rag_chat.domain.entities.chat import RetrievedItem
    from rag_chat.domain.entities.conversation import Message

_MAX_HISTORY_TURNS = 5


class PromptBuilder:
    """Assemble the full LLM prompt from pipeline components."""

    def build(
        self,
        context_block: str,
        conversation_history: list[Message],
        rephrased_query: str,
        sub_questions: tuple[str, ...],
        contradiction_block: ContradictionBlock,
        financial_items: list[RetrievedItem] | None = None,
        intent: QueryIntent = QueryIntent.FACTUAL_LOOKUP,
    ) -> str:
        """Return the complete prompt string to be sent to the LLM.

        Args:
            context_block:         Numbered evidence context from ContextAssembler.
            conversation_history:  Recent messages (last N turns will be used).
            rephrased_query:       Rephrased/expanded user question.
            sub_questions:         Sub-questions for COMPARISON/REASONING intents.
            contradiction_block:   Pre-built contradiction evidence block.
            financial_items:       Optional financial data items for dedicated block.
            intent:                Query intent — selects the system prompt module.
        """
        system_prompt = get_system_prompt(intent)
        parts: list[str] = [f"System:\n{system_prompt}"]

        if context_block:
            parts.append(f"Context:\n{context_block}")

        if contradiction_block.has_contradictions:
            parts.append(f"Conflicts:\n{contradiction_block.text}")

        if financial_items:
            fin_texts = "\n".join(item.text for item in financial_items[:3])
            parts.append(f"Financial Data:\n{fin_texts}")

        if conversation_history:
            recent = list(conversation_history)[-_MAX_HISTORY_TURNS:]
            history_lines: list[str] = []
            for msg in recent:
                role = "User" if msg.role == "user" else "Assistant"
                history_lines.append(f"{role}: {msg.content[:500]}")
            parts.append("Conversation History:\n" + "\n".join(history_lines))

        query_section = f"Query: {rephrased_query}"
        if sub_questions:
            sub_q_text = "\n".join(f"  - {q}" for q in sub_questions)
            query_section += f"\nSub-questions:\n{sub_q_text}"
        parts.append(query_section)

        return "\n\n".join(parts)
