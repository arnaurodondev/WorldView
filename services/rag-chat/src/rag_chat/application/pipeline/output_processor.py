"""Output processor - Steps 12-13 of the RAG pipeline (T-F-4-01).

Strips LLM reasoning blocks, detects PII in output,
parses [N] citation markers, and builds the citations list.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import structlog

from rag_chat.domain.entities.conversation import Citation

if TYPE_CHECKING:
    from rag_chat.domain.entities.chat import RetrievedItem

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Strip <think>, <reasoning>, <scratchpad> blocks (DeepSeek R1 style)
_THINK_RE = re.compile(
    r"<(think|reasoning|scratchpad)>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)

# Match [N] citation markers in the output (e.g. [1], [12])
_CITATION_RE = re.compile(r"\[(\d+)\]")

# Match [NX] style markers — DeepSeek R1 sometimes emits [N6] meaning "citation 6".
# WHY: The model uses the letter N as a prefix for numeric citation references
# (e.g. [N6], [N7]) instead of plain [6].  We normalise these to [6] before
# citation extraction so _CITATION_RE can match them.
# Do NOT strip — convert them to plain [digit] form first.
_CITATION_N_PREFIX_RE = re.compile(r"\[N(\d+)\]")

# Match [N:X] style markers that DeepSeek R1 sometimes emits instead of plain [N].
# These are not part of our citation protocol — always strip them.
_CITATION_N_COLON_RE = re.compile(r"\s*\[N:\d+\]")

# Basic PII patterns — email, phone, SSN, credit card
_PII_PATTERNS = [
    re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),  # email
    re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),  # phone
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN
    re.compile(r"\b(?:\d[ -]?){13,16}\b"),  # credit card (rough)
]


def _contains_pii(text: str) -> bool:
    return any(p.search(text) for p in _PII_PATTERNS)


def _redact_pii(text: str) -> str:
    for pattern in _PII_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


class OutputProcessor:
    """Process raw LLM output into a clean answer with citations.

    Pipeline:
    1. Strip <think>/<reasoning>/<scratchpad> blocks.
    2. PII scan on output (log warning + redact if detected).
    3. Parse [N] citation markers.
    4. Build citations[] array from retrieved items.
    """

    def process(
        self,
        raw_output: str,
        retrieved_items: list[RetrievedItem],
    ) -> tuple[str, list[Citation]]:
        """Return ``(clean_answer, citations)`` from raw LLM output.

        Args:
            raw_output:       Raw streaming output accumulated from LLM.
            retrieved_items:  Items in the order they were presented in the prompt (index 0 = [1]).
        """
        # 1. Strip reasoning blocks
        text = _THINK_RE.sub("", raw_output).strip()

        # 1b. Normalise [NX] markers → [X] so _CITATION_RE can extract them.
        # WHY: DeepSeek R1 often emits [N6] meaning "citation 6" rather than [6].
        # Converting them first lets the standard regex handle all citation styles.
        text = _CITATION_N_PREFIX_RE.sub(r"[\1]", text)

        # 1c. Strip [N:X] markers — DeepSeek R1 occasionally emits these instead of
        # the standard [N] format. They are never part of our citation protocol and
        # have no corresponding citation entry in retrieved_items (F-CH-009 fix).
        text = _CITATION_N_COLON_RE.sub("", text)

        # 2. PII scan on output
        if _contains_pii(text):
            log.warning("pii_in_llm_output", text_len=len(text))  # type: ignore[no-any-return]
            text = _redact_pii(text)

        # 3. Parse [N] citation markers (1-based)
        refs: set[int] = {int(m) for m in _CITATION_RE.findall(text)}

        # Coherence guard: if no retrieved items were provided (citations will be empty)
        # but the LLM still emitted [N] markers, strip those orphaned markers from the
        # text.  Without this, the user sees "[1] [2]" inline references that point to
        # nothing — worse than having no citations at all.
        if not retrieved_items:
            text = re.sub(r"\s*\[\d+\]", "", text)

        # 4. Build citations list
        citations: list[Citation] = []
        for ref in sorted(refs):
            idx = ref - 1
            if idx < 0 or idx >= len(retrieved_items):
                continue
            item = retrieved_items[idx]
            citations.append(
                Citation(
                    ref=ref,
                    item_type=item.item_type.value,
                    id=item.item_id,
                    title=item.citation_meta.title,
                    url=item.citation_meta.url,
                    source_name=item.citation_meta.source_name,
                    published_at=item.citation_meta.published_at,
                    entity_name=item.citation_meta.entity_name,
                    confidence=item.score,
                )
            )

        return text, citations
