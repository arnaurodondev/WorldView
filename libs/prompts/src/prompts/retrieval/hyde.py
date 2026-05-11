"""HyDE (Hypothetical Document Embedding) prompt template.

Generates a conceptual passage for semantic search — explicitly avoids
inventing specific financial figures to prevent embedding poisoning.
"""

from __future__ import annotations

from prompts._base import PromptTemplate

HYDE_EXPANSION = PromptTemplate(
    name="hyde_expansion",
    version="2.0",
    description=(
        "Hypothetical Document Embedding expansion. Generates a conceptual passage "
        "for semantic search — explicitly avoids inventing specific financial figures."
    ),
    template=(
        "Write an 80-120 word factual passage that would plausibly appear in a financial "
        "research document when answering this question. Use conceptual and qualitative "
        "language — do not invent specific prices, percentages, dates, or earnings figures. "
        "The passage will be used for semantic search, not shown to the user.\n\n"
        "Question: {query}"
    ),
    parameters=frozenset({"query"}),
)
