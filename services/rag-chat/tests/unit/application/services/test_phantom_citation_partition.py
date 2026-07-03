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
