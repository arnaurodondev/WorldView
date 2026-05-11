"""IntentClassifierPort — Protocol for query intent classification.

Extracted from PLAN-0084 Wave D-3 (F-A05).

Both concrete implementations in the pipeline layer
(``OllamaIntentClassifier`` and ``DeepInfraIntentClassifier``) satisfy this
interface structurally — no base-class changes are required.

Why a Protocol here rather than an ABC:
- The classifiers live in ``application/pipeline/``, which is still part of the
  application layer — an ABC import cycle would form if they imported from
  ``application/ports/`` while ``ports/`` imported from ``pipeline/``.
  A Protocol gives static-typing without any import dependency.
- ``runtime_checkable`` lets tests assert ``isinstance(obj, IntentClassifierPort)``
  without mypy errors.

Deletion path (PLAN-0067 W11-3): removing the IntentClassifier entirely becomes
a 1-file removal (this file) plus 2 import-line removals in the use cases,
rather than a sed-and-pray search across the whole application layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from rag_chat.domain.entities.chat import ResolvedEntity
    from rag_chat.domain.enums import QueryIntent


@runtime_checkable
class IntentClassifierPort(Protocol):
    """Classify a user message into a ``QueryIntent``.

    All implementations must return a ``(intent, sub_questions, rephrased_query)``
    triple and MUST NOT raise — they fall back internally so the pipeline is
    never blocked by classification failures.

    Args:
        message:              The raw user query text.
        conversation_history: Recent conversation turns as ``{"role": ..., "content": ...}``
                              dicts, newest-last.  Classifiers may truncate to the last N.
        resolved_entities:    Entities resolved from the query by S6 NER lookup.

    Returns:
        ``(intent, sub_questions, rephrased_query)`` where:
        - ``intent`` is the ``QueryIntent`` enum value for the message.
        - ``sub_questions`` is a (possibly empty) list of per-entity sub-questions
          for COMPARISON intents.
        - ``rephrased_query`` is the classifier's standalone re-statement of the
          query using conversation context, or ``""`` if not applicable.
    """

    async def classify(
        self,
        message: str,
        conversation_history: list[dict[str, Any]],
        resolved_entities: list[ResolvedEntity],
    ) -> tuple[QueryIntent, list[str], str]: ...
