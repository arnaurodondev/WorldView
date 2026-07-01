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
