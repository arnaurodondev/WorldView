"""2026-07-08 Track-1 — informal ``[tool row N]`` tool-name resolution.

run_20260708T211838Z found two fully-grounded drafts DISCARDED by the phantom-
citation gate because the model referenced legitimate tool rows with an INFORMAL
tool name:

  * ``chain_portfolio_worst_fundamentals`` — ``[fundamentals_history_batch row 2]``
    while the tool that ran was ``get_fundamentals_history_batch`` (dropped
    ``get_`` prefix);
  * ``chain_top_mover_fundamentals`` — a spelling typo ``[query_fundmamentals
    row 0]`` (real tool ``query_fundamentals``) / ``functions.``-prefixed variants.

Under an EXACT tool-name match these look like citations to a never-called tool,
so the material-phantom gate refused the WHOLE grounded answer. These tests pin
the fix:

  * :func:`resolve_tool_name` maps the informal variant back to the real called
    tool, and leaves a genuinely fabricated (never-called) name unresolved;
  * :func:`partition_phantom_tool_citations` no longer flags a resolvable tag as
    material fabrication (the two chain_* cases are recovered), while a genuine
    never-called tool tag next to a material figure STILL refuses;
  * :func:`normalize_tool_row_citations` promotes a resolvable informal tag to a
    numbered ``[n]`` citation, and a tag for a tool that returned 0 rows is NOT
    fabricated into a citation.
"""

from __future__ import annotations

import pytest
from rag_chat.application.services.numeric_grounding import (
    find_phantom_tool_citations,
    normalize_tool_row_citations,
    partition_phantom_tool_citations,
    resolve_tool_name,
)

pytestmark = pytest.mark.unit


# Tools that ACTUALLY ran in each recovered chain_* case (from the run logs).
_TOP_MOVER_CALLED = ["get_market_movers", "query_fundamentals", "get_entity_news", "search_documents"]
_PORTFOLIO_WORST_CALLED = ["get_fundamentals_history_batch", "get_portfolio_context", "query_fundamentals"]


# ── resolve_tool_name ─────────────────────────────────────────────────────────


def test_resolve_dropped_get_prefix() -> None:
    """``fundamentals_history_batch`` → ``get_fundamentals_history_batch`` (chain_portfolio_worst)."""
    assert resolve_tool_name("fundamentals_history_batch", _PORTFOLIO_WORST_CALLED) == "get_fundamentals_history_batch"


def test_resolve_spelling_typo() -> None:
    """``query_fundmamentals`` (typo) → ``query_fundamentals`` (chain_top_mover)."""
    assert resolve_tool_name("query_fundmamentals", _TOP_MOVER_CALLED) == "query_fundamentals"


def test_resolve_functions_namespace_prefix() -> None:
    """A ``functions.`` namespace prefix is stripped before matching."""
    assert resolve_tool_name("functions.query_fundamentals", _TOP_MOVER_CALLED) == "query_fundamentals"


def test_resolve_exact_match() -> None:
    assert resolve_tool_name("get_market_movers", _TOP_MOVER_CALLED) == "get_market_movers"


@pytest.mark.parametrize(
    ("name", "called"),
    [
        # A real-shaped but NEVER-CALLED tool must stay unresolved (fabrication guard).
        ("query_fundamentals", ["get_entity_news", "get_prediction_markets"]),
        ("supplier_list", ["get_entity_intelligence", "search_documents"]),
        ("query_macro", ["get_economic_calendar", "search_documents", "get_entity_news"]),
        # A prose word is not a tool.
        ("commentary", ["get_prediction_markets"]),
    ],
)
def test_resolve_never_called_is_none(name: str, called: list[str]) -> None:
    """A fabricated / unrelated tool name must NOT resolve to any called tool."""
    assert resolve_tool_name(name, called) is None


def test_resolve_empty_called_set_is_none() -> None:
    assert resolve_tool_name("query_fundamentals", []) is None


# ── partition_phantom_tool_citations — recovered chain_* cases ────────────────


def test_chain_portfolio_worst_grounded_draft_not_refused() -> None:
    """The ``[fundamentals_history_batch row 2]`` tag must NOT be material phantom.

    Real tool ``get_fundamentals_history_batch`` ran; the tag is a dropped-prefix
    variant, so the whole grounded draft must survive (material == set()).
    """
    draft = (
        "Worst performer AAPL: revenue $62.6B [fundamentals_history_batch row 2], "
        "EPS $3.65 [query_fundamentals row 0]."
    )
    material, benign = partition_phantom_tool_citations(draft, _PORTFOLIO_WORST_CALLED)
    assert material == set(), "a dropped-prefix variant of a called tool must not refuse the answer"
    assert benign == [], "a resolvable tag is not a benign strip either — it is a real citation"


def test_chain_top_mover_grounded_draft_not_refused() -> None:
    """A typo'd ``[query_fundmamentals row 0]`` must NOT refuse the grounded draft."""
    draft = "Top mover NVDA: revenue $130.5B [query_fundmamentals row 0] per [get_market_movers row 0]."
    material, benign = partition_phantom_tool_citations(draft, _TOP_MOVER_CALLED)
    assert material == set()
    assert benign == []


def test_never_called_tool_next_to_material_still_refuses() -> None:
    """The fabrication guarantee survives: a genuinely never-called tool stays material."""
    draft = "AMD revenue was $34.6B [query_fundamentals row 4]."
    material, benign = partition_phantom_tool_citations(draft, ["get_entity_news"])
    assert material == {"query_fundamentals"}
    assert benign == []


def test_find_phantom_finder_unchanged_for_informal_variant() -> None:
    """The strict finder is intentionally UNCHANGED — it still flags the informal name.

    ``partition`` is the resolution-aware gate the orchestrator uses; the strict
    ``find_phantom_tool_citations`` keeps its exact-match contract (regression
    suite depends on it), so an informal variant is still in its disjoint set.
    """
    draft = "AAPL revenue $62.6B [fundamentals_history_batch row 2]."
    assert find_phantom_tool_citations(draft, _PORTFOLIO_WORST_CALLED) == {"fundamentals_history_batch"}


# ── normalize_tool_row_citations — informal tag promotion ─────────────────────


def _resolver_for(row_items: dict[tuple[str, int], int]):
    """Build a position_resolver keyed on (real_tool_lower, row)."""

    def _resolve(tool: str, row: int) -> int | None:
        return row_items.get((tool, row))

    return _resolve


def test_normalize_promotes_dropped_prefix_tag() -> None:
    """``[fundamentals_history_batch row 2]`` → ``[3]`` via the name resolver."""
    row_items = {("get_fundamentals_history_batch", 2): 3}
    counts = {"get_fundamentals_history_batch": 3}
    out = normalize_tool_row_citations(
        "AAPL revenue $62.6B [fundamentals_history_batch row 2].",
        _resolver_for(row_items),
        counts.get,
        lambda t: resolve_tool_name(t, _PORTFOLIO_WORST_CALLED),
    )
    assert out == "AAPL revenue $62.6B [3]."


def test_normalize_promotes_typo_tag() -> None:
    """A typo'd ``[query_fundmamentals row 0]`` promotes to the real tool's position."""
    row_items = {("query_fundamentals", 0): 1}
    counts = {"query_fundamentals": 1}
    out = normalize_tool_row_citations(
        "NVDA revenue $130.5B [query_fundmamentals row 0].",
        _resolver_for(row_items),
        counts.get,
        lambda t: resolve_tool_name(t, _TOP_MOVER_CALLED),
    )
    assert out == "NVDA revenue $130.5B [1]."


def test_normalize_leaves_empty_tool_tag_verbatim() -> None:
    """A tag for a tool that returned 0 rows is NOT fabricated into a citation.

    ``search_documents`` ran but returned nothing (count 0, no row items). Even
    though the name resolves to a real called tool, there is no position to map
    to and the clamp is gated on count > 0 — so the tag is left verbatim for the
    downstream out-of-range / D-a strip guards.
    """
    counts = {"search_documents": 0}
    text = "Some claim [search_documents row 7]."
    out = normalize_tool_row_citations(
        text,
        _resolver_for({}),
        counts.get,
        lambda t: resolve_tool_name(t, ["search_documents"]),
    )
    assert out == text, "an empty-tool citation must never be promoted to a numbered citation"
