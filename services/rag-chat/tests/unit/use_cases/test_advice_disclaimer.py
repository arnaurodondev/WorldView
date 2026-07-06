"""Tests for the Point 2 not-financial-advice disclaimer (owner-requested).

For liability coverage as we unlock what-if / projection / analytical answers, a
canonical, model-independent disclaimer is appended DETERMINISTICALLY at
finalisation to analytical / hypothetical turns. It is a single constant, added
once (deduped), and the stub detector discounts it so it can never inflate a
leaked planning stub past the size gate.
"""

from __future__ import annotations

import pytest
from rag_chat.application.use_cases.chat_orchestrator import (
    _CANONICAL_NOT_FINANCIAL_ADVICE_DISCLAIMER,
    _CANONICAL_UNVERIFIED_DISCLAIMER,
    _append_advice_disclaimer,
    _is_tool_call_stub,
)

pytestmark = pytest.mark.unit


def test_append_adds_disclaimer_once() -> None:
    """An analytical answer gets exactly one trailing disclaimer line."""
    text = "Bull case: nvda revenue could accelerate on data-centre demand."
    out = _append_advice_disclaimer(text)
    assert out.count(_CANONICAL_NOT_FINANCIAL_ADVICE_DISCLAIMER) == 1
    assert out.rstrip().endswith(_CANONICAL_NOT_FINANCIAL_ADVICE_DISCLAIMER)
    # Original answer body is preserved verbatim.
    assert out.startswith(text)


def test_append_is_idempotent_dedup() -> None:
    """A second finalisation pass never doubles the disclaimer."""
    text = "Scenario analysis: if the deal closes, upside is material."
    once = _append_advice_disclaimer(text)
    twice = _append_advice_disclaimer(once)
    assert twice == once
    assert twice.count(_CANONICAL_NOT_FINANCIAL_ADVICE_DISCLAIMER) == 1


def test_append_noop_on_empty() -> None:
    assert _append_advice_disclaimer("") == ""
    assert _append_advice_disclaimer("   ") == "   "


def test_append_sits_after_grounding_note() -> None:
    """When a grounding note is already present, the advice line follows it."""
    text = f"Some analysis here.\n\n{_CANONICAL_UNVERIFIED_DISCLAIMER}"
    out = _append_advice_disclaimer(text)
    # Both notes present; the advice disclaimer is last.
    assert _CANONICAL_UNVERIFIED_DISCLAIMER in out
    assert out.rstrip().endswith(_CANONICAL_NOT_FINANCIAL_ADVICE_DISCLAIMER)
    assert out.index(_CANONICAL_UNVERIFIED_DISCLAIMER) < out.index(_CANONICAL_NOT_FINANCIAL_ADVICE_DISCLAIMER)


def test_stub_detection_discounts_advice_disclaimer() -> None:
    """A leaked planning stub carrying the disclaimer is STILL flagged as a stub.

    The disclaimer must be discounted like the canonical unverified note so it
    cannot pad a stub past the collapse/size gate.
    """
    stub = "I will fetch the fundamentals for you.\n\n" + _CANONICAL_NOT_FINANCIAL_ADVICE_DISCLAIMER
    assert _is_tool_call_stub(stub) is True


def test_real_analytical_answer_with_disclaimer_not_a_stub() -> None:
    """A genuine analytical answer + disclaimer is NOT mistaken for a stub."""
    answer = (
        "Bear case for nvda: margin compression from rising competition, a "
        "cyclical data-centre digestion, and export-control exposure to China "
        "each argue against the current multiple. Revenue growth may decelerate "
        "as comparisons toughen through the year.\n\n" + _CANONICAL_NOT_FINANCIAL_ADVICE_DISCLAIMER
    )
    assert _is_tool_call_stub(answer) is False
