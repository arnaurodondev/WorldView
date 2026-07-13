"""P0 (2026-07-01) regression — benign bracket labels must NOT refuse the answer.

The phantom-citation gate refuses the WHOLE answer over any ``[name row N]`` tag
whose ``name`` was never a called tool. The live ``gpt-oss-120b`` model tags its
own editorial prose as ``[commentary row 1]`` on plain news answers — a benign,
non-tool label — and the strict gate nuked the entire "latest news on NVIDIA"
answer (regression from a previously-PASSing flow).

These tests pin :func:`partition_phantom_tool_citations` + :func:`strip_tool_row_tags`:

  * a benign ``[commentary row 1]`` label on prose is classified benign (stripped,
    NOT refused);
  * a genuine fabricated numeric tool-citation (``[query_fundamentals row 4]``
    next to an invented ``$34.6B``) is STILL classified material → refuse.

The numeric-fabrication GUARANTEE must survive: material phantom citations remain
refusable exactly as before.
"""

from __future__ import annotations

import pytest
from rag_chat.application.services.numeric_grounding import (
    find_phantom_tool_citations,
    partition_phantom_tool_citations,
    strip_tool_row_tags,
)

pytestmark = pytest.mark.unit


# ── Benign prose label (the P0 regression) ────────────────────────────────────


def test_commentary_label_on_prose_is_benign_not_material() -> None:
    """A ``[commentary row N]`` label on pure prose must be benign (no refusal)."""
    # A realistic news answer: no material figure anywhere near the tag.
    response = (
        "NVIDIA continues to dominate the AI accelerator market and analysts remain "
        "broadly positive on its outlook. [commentary row 1] Recent headlines focus on "
        "new data-center partnerships rather than fresh guidance."
    )
    called = ["get_entity_news"]  # the tool that actually ran

    material, benign = partition_phantom_tool_citations(response, called)

    assert material == set(), "benign prose label must NOT be treated as material fabrication"
    assert benign == ["[commentary row 1]"], "the benign tag should be surfaced for stripping"


def test_benign_tag_is_stripped_cleanly() -> None:
    """Stripping removes the tag and the orphaned space, leaving readable prose."""
    response = "NVIDIA remains the AI leader. [commentary row 1] Momentum is strong."
    stripped = strip_tool_row_tags(response, ["[commentary row 1]"])
    assert "[commentary row 1]" not in stripped
    assert "  " not in stripped  # no double space left behind
    assert stripped == "NVIDIA remains the AI leader. Momentum is strong."


def test_benign_tag_before_punctuation_no_dangling_space() -> None:
    response = "Analysts are positive on the stock [commentary row 0]."
    stripped = strip_tool_row_tags(response, ["[commentary row 0]"])
    assert stripped == "Analysts are positive on the stock."


# ── Genuine fabricated numeric citation (guarantee must survive) ──────────────


def test_fabricated_numeric_tool_citation_is_material() -> None:
    """A phantom tag next to an invented material figure stays refusable."""
    # query_fundamentals was NEVER called, yet the answer cites it for a $34.6B
    # revenue figure — the AMD fabrication class. This MUST be material.
    response = "AMD reported revenue of $34.6B last quarter [query_fundamentals row 4]."
    called = ["get_entity_news"]  # query_fundamentals absent

    material, benign = partition_phantom_tool_citations(response, called)

    assert "query_fundamentals" in material, "fabricated numeric citation must stay refusable"
    assert benign == [], "a material phantom tag must not be silently stripped"


def test_real_called_tool_is_never_phantom() -> None:
    """A ``[name row N]`` for a tool that WAS called is not phantom at all."""
    response = "AMD reported revenue of $34.6B [get_fundamentals_history row 0]."
    called = ["get_fundamentals_history"]

    material, benign = partition_phantom_tool_citations(response, called)

    assert material == set()
    assert benign == []


def test_mixed_benign_and_material_only_refuses_on_material() -> None:
    """A benign label FAR from any figure stays benign; the fabricated one is material.

    The benign ``[commentary row 1]`` sits in its own paragraph with no material
    number within the proximity window, while ``[query_fundamentals row 4]`` abuts
    an invented ``$34.6B``. The partition must split them.
    """
    response = (
        "NVIDIA leads the AI accelerator market and analysts remain broadly "
        "positive about its long-term data-center roadmap. [commentary row 1]\n\n"
        "Separately, on the fundamentals front, AMD reported quarterly revenue of "
        "$34.6B [query_fundamentals row 4]."
    )
    called = ["get_entity_news"]

    material, benign = partition_phantom_tool_citations(response, called)

    assert material == {"query_fundamentals"}, "the fabricated numeric citation must be material"
    assert benign == ["[commentary row 1]"], "the far-away prose label must stay benign"


def test_strict_finder_flags_both_partition_splits_them() -> None:
    """Sanity: the strict finder (unchanged API) still flags every phantom tag.

    ``find_phantom_tool_citations`` is intentionally preserved; the partition is
    the P0-aware refinement that splits the SAME tags into refuse-vs-strip.
    """
    response = (
        "AMD reported revenue of $34.6B [query_fundamentals row 4]. "
        "In broader industry news, chip demand stayed resilient across the sector "
        "as hyperscalers kept building out capacity. [commentary row 1]"
    )
    called = ["get_entity_news"]

    strict = find_phantom_tool_citations(response, called)
    material, benign = partition_phantom_tool_citations(response, called)

    # Strict finder flags BOTH (its old behaviour); partition splits them.
    assert strict == {"query_fundamentals", "commentary"}
    assert material == {"query_fundamentals"}
    assert "commentary" not in material
    assert benign == ["[commentary row 1]"]


# ── (2026-07-03) Deterministic allowlist backstop — prediction-market refusal ──


def test_prose_label_adjacent_to_material_number_is_benign() -> None:
    """A prediction-market odds answer ``Yes 63% [commentary row 0]`` must NOT refuse.

    This is the residual prediction-market false-refusal
    (docs/audits/2026-07-03-prediction-market-refusal.md): the ``[commentary row 0]``
    tag sits INSIDE the material-number window of ``63%``, so a proximity-only
    discriminator would misclassify it material → hard refusal. The known-non-tool
    allowlist classifies it benign regardless of proximity.
    """
    response = "The market currently implies Yes 63% [commentary row 0] for the outcome."
    called = ["get_prediction_markets"]

    material, benign = partition_phantom_tool_citations(response, called)

    assert material == set(), "an allowlisted prose label next to odds must NOT be material"
    assert benign == ["[commentary row 0]"], "the prose tag should be stripped, not refused"


@pytest.mark.parametrize(
    "word",
    ["commentary", "analysis", "note", "interpretation", "summary", "context", "caveat"],
)
def test_allowlisted_words_adjacent_to_number_are_benign(word: str) -> None:
    """Every allowlisted prose word stays benign even abutting a material figure."""
    response = f"Revenue was $34.6B [{word} row 2] according to consensus."
    called = ["get_prediction_markets"]

    material, benign = partition_phantom_tool_citations(response, called)

    assert material == set()
    assert benign == [f"[{word} row 2]"]


def test_fabricated_tool_next_to_number_still_refuses_despite_allowlist() -> None:
    """The fabrication guard is INTACT: a real-shaped tool name is NOT allowlisted.

    ``query_fundamentals`` was never called yet is cited next to an invented
    ``$34.6B`` — it must STILL be classified material (refuse). The allowlist only
    exempts plain-English prose words, never snake_case tool identifiers.
    """
    response = "Revenue was $34.6B [query_fundamentals row 9]."
    called = ["get_prediction_markets"]  # query_fundamentals absent

    material, benign = partition_phantom_tool_citations(response, called)

    assert material == {"query_fundamentals"}, "fabricated tool citation must stay refusable"
    assert benign == [], "a material phantom tag must not be silently stripped"


def test_real_prediction_markets_citation_is_untouched() -> None:
    """A genuine ``[get_prediction_markets row 1]`` (tool WAS called) is not phantom."""
    response = "The market implies Yes 63% [get_prediction_markets row 1] on the outcome."
    called = ["get_prediction_markets"]

    material, benign = partition_phantom_tool_citations(response, called)

    assert material == set(), "a real called-tool citation must never be flagged"
    assert benign == [], "a real called-tool citation must never be stripped"


# ── (2026-07-09 Area 2 P4) FUNDAMENTALS-FAMILY tool aliasing ──────────────────
#
# The three fundamentals tools (query_fundamentals / get_fundamentals_history /
# get_fundamentals_history_batch) are DISTINCT registered tools that surface the
# SAME rows. The live model tags a fundamentals figure as ``[query_fundamentals
# row 0]`` even when ``get_fundamentals_history_batch`` actually ran and returned
# it — resolve_tool_name cannot bridge them (no shared prefix/substring/typo), so
# the phantom gate refused a strong grounded answer (ripple_aapl_shared_suppliers
# _nvda scored 0). Family aliasing recovers it WITHOUT weakening the guarantee:
# gated on a family tool having run AND the cited value appearing in that tool's
# result pool.

# TSMC Q1 2025 revenue as the answer renders it ("$839.25B") in base units, and
# the matching value the fundamentals-family tool returned.
_TSMC_REVENUE = 839.25e9


def test_ripple_aapl_query_fundamentals_alias_resolves_when_batch_ran() -> None:
    """RECOVERED CASE: ``[query_fundamentals row 0]`` next to a figure that the
    sibling ``get_fundamentals_history_batch`` returned is NOT phantom."""
    response = "| Revenue | $839.25B TWD [query_fundamentals row 0] |"
    called = ["get_fundamentals_history_batch", "get_entity_news"]
    pool = {_TSMC_REVENUE}

    material, benign = partition_phantom_tool_citations(response, called, fundamentals_value_pool=pool)

    assert material == set(), "family-aliased citation to a value a sibling tool returned must resolve"
    assert benign == [], "an aliased family citation is a real citation — not stripped"


def test_family_alias_still_phantom_when_no_family_tool_ran() -> None:
    """A fundamentals-family citation with NO family tool called stays phantom."""
    response = "Revenue was $839.25B [query_fundamentals row 0]."
    called = ["get_entity_news"]  # no fundamentals-family tool ran
    pool: set[float] = set()

    material, _benign = partition_phantom_tool_citations(response, called, fundamentals_value_pool=pool)

    assert material == {"query_fundamentals"}, "never-run family tool citation must stay phantom"


def test_family_alias_still_phantom_when_result_empty() -> None:
    """A family tool that RAN but returned an EMPTY pool cannot ground the tag."""
    response = "Revenue was $839.25B [query_fundamentals row 0]."
    called = ["get_fundamentals_history_batch"]  # ran, but returned nothing
    pool: set[float] = set()

    material, _benign = partition_phantom_tool_citations(response, called, fundamentals_value_pool=pool)

    assert material == {"query_fundamentals"}, "empty-result family citation must stay phantom"


def test_family_alias_still_phantom_when_cited_value_absent_from_pool() -> None:
    """A family tool ran and returned data, but NOT the fabricated figure → phantom."""
    response = "Revenue was $839.25B [query_fundamentals row 0]."
    called = ["get_fundamentals_history_batch"]
    pool = {12.3e9}  # some other real value, not the fabricated $839.25B

    material, _benign = partition_phantom_tool_citations(response, called, fundamentals_value_pool=pool)

    assert material == {"query_fundamentals"}, "fabricated figure absent from pool must stay phantom"


def test_family_alias_not_applied_to_non_family_tool() -> None:
    """A non-fundamentals phantom tag never benefits from the family pool."""
    response = "The Fed decision moved rates $2.00B [query_macro row 0]."
    called = ["get_fundamentals_history_batch"]  # a family tool ran…
    pool = {2.0e9}  # …and the value even happens to be in its pool

    material, _benign = partition_phantom_tool_citations(response, called, fundamentals_value_pool=pool)

    # query_macro is NOT a fundamentals-family tool, so aliasing must not apply.
    assert material == {"query_macro"}, "non-family phantom tag must stay phantom regardless of pool"


def test_family_alias_backward_compatible_without_pool() -> None:
    """With NO pool supplied, behaviour is unchanged: family tag stays phantom."""
    response = "Revenue was $839.25B [query_fundamentals row 0]."
    called = ["get_fundamentals_history_batch"]

    material, _benign = partition_phantom_tool_citations(response, called)

    assert material == {"query_fundamentals"}, "no pool → no aliasing → unchanged phantom behaviour"


def test_fundamentals_family_value_pool_flattens_structured_rows() -> None:
    """The pool builder extracts base-unit values from structured fundamentals rows."""
    from rag_chat.application.services.numeric_grounding import fundamentals_family_value_pool

    from contracts.numeric_grounding import FieldKind

    class _Row:
        def __init__(self, value: float, kind: FieldKind) -> None:
            self.value = value
            self.field_kind = kind

    rows = [_Row(_TSMC_REVENUE, FieldKind.REVENUE), _Row(0.581, FieldKind.RATIO)]
    pool = fundamentals_family_value_pool(rows)

    assert _TSMC_REVENUE in pool
    assert fundamentals_family_value_pool([]) == set(), "empty results → empty pool (keeps citations phantom)"
