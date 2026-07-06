"""NEW-3 refinement (2026-07-06) — deterministic filing-citation backfill.

Citation assembly is marker-driven: ``process_output`` only emits a citation for
an item the model referenced with a ``[N]`` marker. For short filing answers the
model quotes the real 10-Q figures but intermittently omits the marker, so the
SAME correct Apple figures shipped 1 citation on one run and 0 on the next
(docs/audits/2026-07-06-r1-final-exhaustive-qa.md, NEW-3).

``_backfill_filing_citations`` makes it deterministic: when a retrieved sec_edgar
filing's material figure appears verbatim in the answer and the filing is not
already cited, its positional marker + citation are appended. These tests pin
that guarantee (and its guards) — they FAIL against the pure marker-driven path.
"""

from __future__ import annotations

import pytest
from rag_chat.application.use_cases.chat_orchestrator import (
    _backfill_filing_citations,
    _material_figure_keys,
)
from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.entities.conversation import Citation
from rag_chat.domain.enums import ItemType

pytestmark = pytest.mark.unit

_EDGAR_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193"


def _filing_item(doc_id: str, text: str, *, title: str = "10-Q filing — Apple Inc. (2025-01-31)") -> RetrievedItem:
    return RetrievedItem.create(
        item_id=f"tool:filing:{doc_id}",
        item_type=ItemType.chunk,
        text=text,
        score=0.9,
        trust_weight=0.95,
        source_type="sec_edgar",
        citation_meta=CitationMeta(
            title=title,
            url=_EDGAR_URL,
            source_name="sec_edgar",
            published_at=None,
            entity_name="AAPL",
        ),
    )


def _news_item(text: str) -> RetrievedItem:
    return RetrievedItem.create(
        item_id="tool:news:x",
        item_type=ItemType.chunk,
        text=text,
        score=0.8,
        trust_weight=0.7,
        source_type="news",
        citation_meta=CitationMeta(
            title="A story", url="http://x", source_name="news", published_at=None, entity_name=None
        ),
    )


def test_material_figure_keys_ignores_years_and_small_counts() -> None:
    keys = _material_figure_keys("In 2026 the company had 3 segments and $124,300 million revenue, plus 97,960.")
    assert "124300" in keys
    assert "97960" in keys
    assert "2026" not in keys  # 4-digit year is not material
    assert "3" not in keys


def test_backfill_emits_citation_when_figure_used_but_uncited() -> None:
    """Correct Apple figures quoted, model omitted the marker → citation backfilled."""
    item = _filing_item("aapl-10q", "Total net sales $124,300 million. Services revenue $26,340 million.")
    answer = "Apple reported total net sales of $124,300 million and Services revenue of $26,340 million."

    new_answer, new_citations = _backfill_filing_citations(answer, [], [item])

    assert len(new_citations) == 1
    c = new_citations[0]
    assert c.ref == 1
    assert c.id == "tool:filing:aapl-10q"
    assert c.url == _EDGAR_URL
    assert c.entity_name == "AAPL"
    # An inline marker anchors the citation for the frontend.
    assert new_answer.rstrip().endswith("[1]")


def test_backfill_is_noop_when_already_cited() -> None:
    item = _filing_item("aapl-10q", "Total net sales $124,300 million.")
    existing = Citation(ref=1, item_type="chunk", id="tool:filing:aapl-10q", title="t", url=_EDGAR_URL)
    answer = "Total net sales were $124,300 million [1]."

    new_answer, new_citations = _backfill_filing_citations(answer, [existing], [item])

    # No duplicate citation, answer untouched.
    assert new_citations == [existing]
    assert new_answer == answer


def test_backfill_ignores_non_filing_items() -> None:
    """A news item whose number appears in the answer is NOT backfilled — the
    backfill only promotes sec_edgar filings (news relies on its own markers)."""
    item = _news_item("Shares jumped after $124,300 million was mentioned.")
    answer = "The figure $124,300 million came up."

    new_answer, new_citations = _backfill_filing_citations(answer, [], [item])

    assert new_citations == []
    assert new_answer == answer


def test_backfill_skips_when_figure_not_used() -> None:
    """A filing whose figures do NOT appear in the answer is not cited (no
    fabricated provenance)."""
    item = _filing_item("aapl-10q", "Total net sales $124,300 million.")
    answer = "Apple's filing did not disclose the specific figures in the retrieved excerpt."

    new_answer, new_citations = _backfill_filing_citations(answer, [], [item])

    assert new_citations == []
    assert new_answer == answer


def test_backfill_is_deterministic_across_calls() -> None:
    """Two identical inputs yield identical citations — the run-to-run 1-vs-0
    flakiness (NEW-3) is gone."""
    item = _filing_item("aapl-10q", "Services revenue $26,340 million; Products $97,960 million.")
    answer = "Services revenue was $26,340 million and Products revenue was $97,960 million."

    a1, c1 = _backfill_filing_citations(answer, [], [item])
    a2, c2 = _backfill_filing_citations(answer, [], [item])

    assert a1 == a2
    assert [c.id for c in c1] == [c.id for c in c2] == ["tool:filing:aapl-10q"]
