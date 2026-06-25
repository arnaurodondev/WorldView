"""Unit tests for the PLAN-0110 W1 substantiation cross-check (MUST-1).

These cover ``evaluate_substantiation`` (T-W1-02) and the ``SubstantiationCheck``
value object. The check is deterministic + LLM-free: it REUSES the grounding
helpers (one claim regex, one tolerance) and adds the ``unsupported`` class —
a number asserted for a field the tool NAMED but never quantified.

INVARIANT under test: coverage=="presumed" ⟹ all counts 0 (a no-sample run is
byte-identical to the pre-W1 baseline and can never fire the gate).

We also pin that ``cross_check_grounding`` is BYTE-IDENTICAL to its pre-W1
behaviour on the same synthetic fixtures (substantiation is purely additive).
"""

from __future__ import annotations

import os
import sys

import pytest

# scripts/ is not a package and not on sys.path during pytest.
_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from chat_quality_judge import (  # — sys.path mutation must precede the import
    GroundingCheck,
    InvariantCode,
    Rubric,
    SubstantiationCheck,
    cross_check_grounding,
    evaluate_invariants,
    evaluate_substantiation,
    first_fired_invariant,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures: synthetic grounding samples (the W2 {fields, ...} shape).
# ---------------------------------------------------------------------------


def _tool_result_with_sample(tool: str, fields: dict[str, str]) -> dict[str, object]:
    """A captured tool_result entry carrying a W2 grounding_sample block."""
    return {
        "tool": tool,
        "status": "ok",
        "item_count": 1,
        "grounding_sample": {
            "fields": fields,
            "sampled_rows": 1,
            "total_rows": 1,
            "truncated": False,
        },
    }


# ---------------------------------------------------------------------------
# 1) matched claim → substantiated
# ---------------------------------------------------------------------------


def test_matched_claim_is_substantiated() -> None:
    """A claim within tolerance of the sampled value is ``substantiated``."""
    results = [_tool_result_with_sample("get_fundamentals_history", {"revenue": "46.7B"})]
    check = evaluate_substantiation("Apple's revenue was $46.7B last year.", results)
    assert check.coverage == "verified"
    assert check.substantiated == 1
    assert check.unsupported == 0
    assert check.contradicted == 0
    assert check.unmatched == 0


# ---------------------------------------------------------------------------
# 2) field present, value absent → unsupported
# ---------------------------------------------------------------------------


def test_field_present_value_absent_is_unsupported() -> None:
    """A claim for a NAMED but value-less sampled field is ``unsupported``.

    The sample carries the ``revenue`` field name but a non-numeric, unparseable
    value (``"N/A"``) — so there is nothing to match AND nothing to contradict.
    The agent stating a revenue number is an UNSUPPORTED assertion.
    """
    results = [_tool_result_with_sample("get_fundamentals_history", {"revenue": "N/A"})]
    check = evaluate_substantiation("Apple's revenue was $46.7B last year.", results)
    assert check.coverage == "verified"
    assert check.substantiated == 0
    assert check.unsupported == 1
    assert check.contradicted == 0
    assert check.unmatched == 0
    # The example records the field + kind so the report can explain the failure.
    assert check.examples[0]["field"] == "revenue"
    assert check.examples[0]["kind"] == "unsupported"


def test_out_of_tolerance_claim_is_contradicted() -> None:
    """A claim outside tolerance of every sampled value is ``contradicted``."""
    results = [_tool_result_with_sample("get_fundamentals_history", {"revenue": "46.7B"})]
    check = evaluate_substantiation("Apple's revenue was $5.4B last year.", results)
    assert check.coverage == "verified"
    assert check.contradicted == 1
    assert check.substantiated == 0
    assert check.unsupported == 0
    assert check.examples[0]["kind"] == "contradicted"


# ---------------------------------------------------------------------------
# 3) no associated field → unmatched (neutral, never a failure)
# ---------------------------------------------------------------------------


def test_claim_with_no_associated_field_is_unmatched() -> None:
    """A number that names no sampled field is ``unmatched`` (neutral)."""
    results = [_tool_result_with_sample("get_fundamentals_history", {"revenue": "46.7B"})]
    # The EPS number names a field that is NOT in the sample → no association.
    check = evaluate_substantiation("The dividend was raised by 12 cents.", results)
    assert check.coverage == "verified"
    assert check.unmatched == 1
    assert check.substantiated == 0
    assert check.unsupported == 0
    assert check.contradicted == 0


# ---------------------------------------------------------------------------
# 4) no samples → presumed, all-0 (the W1 INVARIANT)
# ---------------------------------------------------------------------------


def test_no_samples_is_presumed_all_zero() -> None:
    """With NO grounding sample the check is ``presumed`` with every count 0."""
    check = evaluate_substantiation("Revenue was $46.7B and EPS was $5.40.", [])
    assert check.coverage == "presumed"
    assert check.substantiated == 0
    assert check.unsupported == 0
    assert check.contradicted == 0
    assert check.unmatched == 0
    assert check.examples == []


def test_presumed_invariant_holds_for_none_tool_results() -> None:
    """``None`` tool_results is also ``presumed`` all-0 (defensive)."""
    check = evaluate_substantiation("Revenue was $46.7B.", None)
    assert check.coverage == "presumed"
    assert (check.substantiated, check.unsupported, check.contradicted, check.unmatched) == (0, 0, 0, 0)


# ---------------------------------------------------------------------------
# 5) cross_check_grounding is unchanged (substantiation is purely additive)
# ---------------------------------------------------------------------------


def test_cross_check_grounding_unchanged_match() -> None:
    """``cross_check_grounding`` still matches a within-tolerance claim (byte-identical)."""
    results = [_tool_result_with_sample("get_fundamentals_history", {"revenue": "46.7B"})]
    gc = cross_check_grounding("Revenue was $46.7B.", results)
    assert gc.matched == 1
    assert gc.contradicted == 0
    assert gc.evidence_mode == "verified"


def test_cross_check_grounding_unchanged_no_samples() -> None:
    """``cross_check_grounding`` still returns presumed/zeroed with no samples."""
    gc = cross_check_grounding("Revenue was $46.7B.", [])
    assert gc.evidence_mode == "presumed"
    assert gc.matched == 0 and gc.contradicted == 0 and gc.unmatched == 0


# ---------------------------------------------------------------------------
# 6) percent claims
# ---------------------------------------------------------------------------


def test_percent_claim_substantiated() -> None:
    """A percent claim is compared as a plain number → substantiated within tol."""
    results = [_tool_result_with_sample("get_entity_health", {"confidence": "92"})]
    check = evaluate_substantiation("Our confidence in this is 92%.", results)
    assert check.substantiated == 1
    assert check.unsupported == 0
    assert check.contradicted == 0


# ---------------------------------------------------------------------------
# 7) B/M/K scale suffixes scale identically on claim + sample
# ---------------------------------------------------------------------------


def test_scale_suffix_matching() -> None:
    """``$46,742,000,000`` claim matches a ``46.7B`` sample (B/M/K parsing)."""
    results = [_tool_result_with_sample("get_fundamentals_history", {"revenue": "46.7B"})]
    check = evaluate_substantiation("Revenue came in at $46,742,000,000.", results)
    assert check.substantiated == 1
    assert check.contradicted == 0


def test_million_suffix_matching() -> None:
    """A spelled-out ``million`` claim scales the same as the sampled ``500M``."""
    results = [_tool_result_with_sample("get_market_movers", {"price": "500M"})]
    check = evaluate_substantiation("price of 500 million", results)
    assert check.substantiated == 1


# ---------------------------------------------------------------------------
# 8) year-like integers are excluded
# ---------------------------------------------------------------------------


def test_yearlike_integers_excluded() -> None:
    """A bare 4-digit year (2024) near a sampled field is NOT a magnitude claim."""
    results = [_tool_result_with_sample("get_fundamentals_history", {"revenue": "46.7B"})]
    # "revenue ... in 2024" — the 2024 is a year, not a revenue magnitude claim.
    check = evaluate_substantiation("revenue in 2024 was strong", results)
    # 2024 is filtered as year-like → no claim → nothing classified.
    assert check.substantiated == 0
    assert check.unsupported == 0
    assert check.contradicted == 0
    assert check.unmatched == 0


# ---------------------------------------------------------------------------
# 9) numbers inside code spans are excluded
# ---------------------------------------------------------------------------


def test_code_spans_excluded() -> None:
    """A number inside an inline-code span is not treated as a prose claim."""
    results = [_tool_result_with_sample("get_fundamentals_history", {"revenue": "46.7B"})]
    check = evaluate_substantiation("The revenue field is `revenue=5400000000` in the schema.", results)
    # The 5.4e9 lives inside `...` so it is blanked → no contradiction.
    assert check.contradicted == 0
    assert check.unsupported == 0


# ---------------------------------------------------------------------------
# 10) to_dict shape + value-object defaults
# ---------------------------------------------------------------------------


def test_substantiation_check_defaults_and_to_dict() -> None:
    """The default value object is presumed/zeroed and serialises every field."""
    sc = SubstantiationCheck()
    assert sc.coverage == "presumed"
    assert (sc.substantiated, sc.unsupported, sc.contradicted, sc.unmatched) == (0, 0, 0, 0)
    assert sc.examples == []
    d = sc.to_dict()
    assert set(d.keys()) == {
        "substantiated",
        "unsupported",
        "contradicted",
        "unmatched",
        "coverage",
        "examples",
    }
    assert d["coverage"] == "presumed"


# ===========================================================================
# T3 — SUBSTANTIATION_UNSUPPORTED invariant gate wiring
# ===========================================================================


def _verified_unsupported() -> SubstantiationCheck:
    """A ``verified`` substantiation check with one unsupported claim."""
    return SubstantiationCheck(
        unsupported=1, coverage="verified", examples=[{"field": "revenue", "kind": "unsupported"}]
    )


def test_gate_fires_when_unsupported_and_verified() -> None:
    """The gate fires (False) when unsupported>0 AND coverage=='verified'."""
    gates = evaluate_invariants(
        "Revenue was $46.7B.",
        [],
        Rubric(),
        GroundingCheck(),
        substantiation_check=_verified_unsupported(),
    )
    assert gates[InvariantCode.SUBSTANTIATION_UNSUPPORTED] is False


def test_gate_silent_in_presumed_mode() -> None:
    """A presumed substantiation check (all-0) NEVER fires the gate.

    This is the W1 byte-identical-baseline guarantee: a flag-off / no-sample run
    classifies everything as presumed, so the gate cannot fire.
    """
    presumed = SubstantiationCheck(coverage="presumed")
    gates = evaluate_invariants(
        "Revenue was $46.7B.",
        [],
        Rubric(),
        GroundingCheck(),
        substantiation_check=presumed,
    )
    assert gates[InvariantCode.SUBSTANTIATION_UNSUPPORTED] is True


def test_gate_not_fired_when_check_absent() -> None:
    """No substantiation_check passed → gate cannot fire (back-compat callers)."""
    gates = evaluate_invariants("Revenue was $46.7B.", [], Rubric(), GroundingCheck())
    assert gates[InvariantCode.SUBSTANTIATION_UNSUPPORTED] is True


def test_gate_disableable() -> None:
    """The gate is suppressed when not in the ``enabled`` set (FR-3 toggleability)."""
    enabled = {c for c in InvariantCode if c is not InvariantCode.SUBSTANTIATION_UNSUPPORTED}
    gates = evaluate_invariants(
        "Revenue was $46.7B.",
        [],
        Rubric(),
        GroundingCheck(),
        enabled=enabled,
        substantiation_check=_verified_unsupported(),
    )
    # Disabled → reported as passed (True), never fires.
    assert gates[InvariantCode.SUBSTANTIATION_UNSUPPORTED] is True


def test_contradicted_outranks_unsupported_priority() -> None:
    """When both GROUNDING_CONTRADICTED and SUBSTANTIATION_UNSUPPORTED fire, the
    contradiction is the reported fail_reason (higher priority)."""
    gates = evaluate_invariants(
        "Revenue was $5.4B.",
        [],
        Rubric(),
        GroundingCheck(contradicted=1, evidence_mode="verified"),
        substantiation_check=_verified_unsupported(),
    )
    assert gates[InvariantCode.GROUNDING_CONTRADICTED] is False
    assert gates[InvariantCode.SUBSTANTIATION_UNSUPPORTED] is False
    # The single reported reason is the more-severe contradiction.
    assert first_fired_invariant(gates) is InvariantCode.GROUNDING_CONTRADICTED


def test_unsupported_outranks_phantom_priority() -> None:
    """SUBSTANTIATION_UNSUPPORTED outranks PHANTOM_CITATION in the priority order."""
    gates = {c: True for c in InvariantCode}
    gates[InvariantCode.SUBSTANTIATION_UNSUPPORTED] = False
    gates[InvariantCode.PHANTOM_CITATION] = False
    assert first_fired_invariant(gates) is InvariantCode.SUBSTANTIATION_UNSUPPORTED
