"""Context assembler + contradiction assembler - Steps 9-10 of the RAG pipeline (T-F-2-02).

Builds the numbered context block from top-12 reranked items,
assembles contradiction evidence, and prepares prompt components.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rag_chat.domain.entities.chat import RetrievedItem
    from rag_chat.domain.entities.conversation import ContradictionRef

_TOKEN_BUDGET_CHARS = 32_000  # ~8000 tokens at 0.25 tokens/char
_ITEM_TEMPLATE = "[{n}] {text}\n    Source: {source} ({date})\n    Confidence: {score:.2f}"
_GRAPH_ENRICHMENT_LINE = "\n    Graph context: {summary}"


@dataclass
class ContradictionBlock:
    """Assembled contradiction evidence for the prompt."""

    text: str
    refs: list[ContradictionRef]

    @property
    def has_contradictions(self) -> bool:
        return bool(self.refs)


class ContradictionAssembler:
    """Build a formatted contradiction block from retrieved contradiction items."""

    def build(self, contradiction_refs: list[ContradictionRef]) -> ContradictionBlock:
        """Return a ContradictionBlock from a list of ContradictionRef domain objects."""
        if not contradiction_refs:
            return ContradictionBlock(text="", refs=[])

        lines: list[str] = []
        for ref in contradiction_refs:
            sides = list(ref.sides)[:2]
            side_texts = " vs. ".join(s.get("text", "")[:200] for s in sides)
            lines.append(f"  - {ref.claim_type} (strength={ref.strength:.2f}): {side_texts}")

        text = "\u26a0\ufe0f CONFLICTING EVIDENCE detected:\n" + "\n".join(lines)
        return ContradictionBlock(text=text, refs=contradiction_refs)


class ContextAssembler:
    """Build the numbered context block from reranked items.

    Token budget: 8000 context tokens (~32,000 chars at 0.25 tok/char).
    Truncation strategy: trim trailing (lowest-ranked) items first — the
    caller passes items already ranked best-first (BP-669 order contract).
    """

    def assemble(self, items: list[RetrievedItem]) -> str:
        """Return the numbered context block string for injection into the prompt.

        ORDER CONTRACT (BP-669, 2026-06-11): items are numbered [1..N] in the
        EXACT order given. The caller passes the reranked list and later maps
        the LLM's ``[N]`` citation markers back into the SAME list
        (``OutputProcessor.process``). This method previously re-sorted by
        ``fusion_score`` before numbering, so the prompt said "[5] = Morgan
        Stanley article" while the citation builder resolved ``[5]`` to a
        different item in cross-encoder order — every citation pointed at the
        wrong source whenever rerank order != fusion order. Do NOT re-sort
        here; ordering is the caller's responsibility.
        """
        if not items:
            return ""

        # BP-669: trust the caller's order — see ORDER CONTRACT above.
        ranked = items

        lines: list[str] = []
        total_chars = 0
        for n, item in enumerate(ranked, start=1):
            date_str = (
                item.citation_meta.published_at.strftime("%Y-%m-%d")
                if item.citation_meta.published_at
                else "unknown date"
            )
            source = item.citation_meta.source_name or "unknown source"
            block = _ITEM_TEMPLATE.format(
                n=n,
                text=item.text[:1000],  # cap individual item text
                source=source,
                date=date_str,
                score=item.score,
            )
            if item.graph_enrichment:
                summary = item.graph_enrichment[0].get("summary", "")[:200]
                block += _GRAPH_ENRICHMENT_LINE.format(summary=summary)

            if total_chars + len(block) > _TOKEN_BUDGET_CHARS:
                break
            lines.append(block)
            total_chars += len(block)

        return "\n\n".join(lines)
