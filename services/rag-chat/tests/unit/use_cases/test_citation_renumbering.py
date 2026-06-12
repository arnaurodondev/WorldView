"""BP-669 — dense citation renumbering in the chat orchestrator.

The LLM cites a sparse subset of the [1..N] context enumeration (e.g. [5],
[6], [8] out of 10 items) but the frontend renders the citation list
positionally — pill k is labelled "[k]". Sparse body markers therefore
pointed "past" the visible source list (live Apple-news failure: body cited
[5][6][8], the citations event carried 4 entries labelled [1]-[4]).

``_renumber_citations_dense`` rewrites the final answer's plain ``[N]``
markers AND the citation refs to a dense 1..K so both sides agree. It also
REMOVES markers with no matching citation — the legacy orphan scrub only
matched the ``[N7]`` prefix form which ``OutputProcessor`` normalises away
before the scrub runs, so out-of-range plain markers used to leak to users.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from rag_chat.application.use_cases.chat_orchestrator import _renumber_citations_dense

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class _Cit:
    """Minimal Citation stand-in — only the ``ref`` field is read/replaced."""

    ref: int
    id: str = "tool:entity_news:x"


def test_sparse_refs_become_dense() -> None:
    text = "Morgan Stanley warns [5]. EU delay [6]. BofA take [8]."
    citations = [_Cit(ref=5, id="a"), _Cit(ref=6, id="b"), _Cit(ref=8, id="c")]

    new_text, new_cits = _renumber_citations_dense(text, citations)

    assert new_text == "Morgan Stanley warns [1]. EU delay [2]. BofA take [3]."
    assert [(c.ref, c.id) for c in new_cits] == [(1, "a"), (2, "b"), (3, "c")]


def test_already_dense_is_identity() -> None:
    text = "First [1] and second [2]."
    citations = [_Cit(ref=1, id="a"), _Cit(ref=2, id="b")]

    new_text, new_cits = _renumber_citations_dense(text, citations)

    assert new_text == text
    assert [(c.ref, c.id) for c in new_cits] == [(1, "a"), (2, "b")]


def test_orphan_marker_without_citation_is_removed() -> None:
    """A plain [9] with no citation entry must not survive to the user."""
    text = "Grounded claim [5]. Fabricated marker [9]."
    citations = [_Cit(ref=5, id="a")]

    new_text, new_cits = _renumber_citations_dense(text, citations)

    assert new_text == "Grounded claim [1]. Fabricated marker ."
    assert [(c.ref, c.id) for c in new_cits] == [(1, "a")]


def test_repeated_markers_share_one_citation() -> None:
    text = "Claim A [7]. Claim B also [7]."
    citations = [_Cit(ref=7, id="a")]

    new_text, new_cits = _renumber_citations_dense(text, citations)

    assert new_text == "Claim A [1]. Claim B also [1]."
    assert [(c.ref, c.id) for c in new_cits] == [(1, "a")]


def test_bracketed_years_are_untouched() -> None:
    """3+ digit bracketed numbers are not citation markers (e.g. [2026])."""
    text = "Forecast for [2026] remains [3]."
    citations = [_Cit(ref=3, id="a")]

    new_text, _ = _renumber_citations_dense(text, citations)

    assert "[2026]" in new_text
    assert "[1]" in new_text
