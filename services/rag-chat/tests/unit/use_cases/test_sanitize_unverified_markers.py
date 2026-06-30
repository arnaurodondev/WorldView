"""Tests for `_sanitize_unverified_markers` (C2 — FINAL-67 phantom-citation FAIL).

The grounding validator marks unpinned numbers/names with a literal
``[unverified]`` token and appends a ``⚠ Some … could not be verified`` banner.
Both leak into the user-facing answer and the quality judge reads the bracketed
``[unverified]`` token as a fabricated provenance/citation tag. The sanitizer
converts these into a single neutral disclaimer so the phantom-citation gate no
longer trips, while preserving the hedge.
"""

from __future__ import annotations

import pytest
from rag_chat.application.use_cases.chat_orchestrator import (
    _CANONICAL_UNVERIFIED_DISCLAIMER,
    _sanitize_unverified_markers,
)

pytestmark = pytest.mark.unit


def test_noop_on_clean_answer() -> None:
    """An answer with no marker/banner is returned byte-for-byte unchanged."""
    text = "Apple revenue was $111.184B for Q4 FY2024 [1]."
    assert _sanitize_unverified_markers(text) == text


def test_noop_on_empty() -> None:
    assert _sanitize_unverified_markers("") == ""


def test_inline_tag_rewritten_to_prose() -> None:
    """The bracketed ``[unverified]`` token is replaced by neutral prose."""
    # Mirrors q_iter3_apple_revenue_precision.
    text = "Apple's revenue was **$111.200 B** [unverified]【1】"
    out = _sanitize_unverified_markers(text)
    assert "[unverified]" not in out
    assert "(source unverified)" in out
    # The neutral marker reads as prose, not a citation.
    assert "**$111.200 B** (source unverified)【1】" in out


def test_trailing_banner_collapsed_to_single_disclaimer() -> None:
    """The ⚠ banner is removed and replaced by one canonical disclaimer."""
    # Mirrors q_tc_entity_narrative_anthropic.
    text = (
        "AnthropicAI is a research organization. Founded in 2021 [unverified] "
        "by Dario Amodei. [1]\n\n"
        "⚠ Some figures could not be verified against retrieved data."
    )
    out = _sanitize_unverified_markers(text)
    assert "⚠" not in out
    assert "[unverified]" not in out
    assert "(source unverified)" in out
    assert out.rstrip().endswith(_CANONICAL_UNVERIFIED_DISCLAIMER)
    # Exactly one disclaimer line (no duplication).
    assert out.count(_CANONICAL_UNVERIFIED_DISCLAIMER) == 1


def test_multiple_banners_collapse_to_one() -> None:
    """Several stacked banners collapse to a single disclaimer."""
    text = (
        "Some prose [unverified].\n\n"
        "⚠ Some numbers could not be verified against retrieved data.\n"
        "⚠ Some entity references could not be verified against retrieved data."
    )
    out = _sanitize_unverified_markers(text)
    assert out.count(_CANONICAL_UNVERIFIED_DISCLAIMER) == 1
    assert "⚠" not in out


def test_banner_only_no_inline_tag() -> None:
    """A banner with no inline tag is still normalised to the disclaimer."""
    text = "Revenue was $24.7B.\n\n⚠ Some numbers could not be verified (validator timeout)."
    out = _sanitize_unverified_markers(text)
    assert "⚠" not in out
    assert out.rstrip().endswith(_CANONICAL_UNVERIFIED_DISCLAIMER)


def test_case_insensitive_tag() -> None:
    """``[UNVERIFIED]`` (any case) is also rewritten."""
    text = "Founded in 2021 [UNVERIFIED]."
    out = _sanitize_unverified_markers(text)
    assert "UNVERIFIED" not in out.upper().replace("(SOURCE UNVERIFIED)", "")
