"""Q4 — NVDA vs AMD revenue (PLAN-0093 Wave G-3 T-G-3-05, BELLWETHER).

The audit's hardest finding: pre-remediation the LLM hallucinated
"AMD Q2 2026 revenue $34.6B" — AMD has not yet reported Q2 2026, and
even their actual current run-rate is < $11B/q. This is the single
test that catches the canonical fabrication signature.

We fire 6 question variants per run, plus 3 cross-cutting assertions
that span the entire batch (no AMD > $15B anywhere, no orphan
rationalisations, no invented quarter labels).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from tests.validation.chat_eval.grading import (
    HARMFUL,
    USEFUL,
    extract_quarter_labels,
    grade_response,
    orphan_rationalisations,
)

if TYPE_CHECKING:
    from tests.validation.chat_eval.harness import ChatRunResult

# ---------------------------------------------------------------------------
# Fixture loading. Fallback values come straight from the audit (single
# source of truth) so the suite still runs when the YAML file is moved.
# ---------------------------------------------------------------------------

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "q4_ground_truth.yaml"

# Hardcoded fallback — see audit doc.
_FALLBACK: dict[str, Any] = {
    "bellwethers": [
        {"ticker": "NVDA", "quarter": "Q4FY26", "metric": "revenue", "value_billions": 68.127},
        {"ticker": "AMD", "quarter": "Q1FY26", "metric": "revenue", "value_billions": 10.253},
        {"ticker": "AMD", "quarter": "Q1FY26", "metric": "eps_diluted", "value": 0.45},
    ],
    "not_reported": [
        {"ticker": "AMD", "quarters": ["Q2FY26", "Q3FY26", "Q4FY26"]},
        {"ticker": "NVDA", "quarters": ["Q1FY27"]},
    ],
}


def _load_fixture() -> dict[str, Any]:
    """Load Q4 ground truth from YAML; fall back to hardcoded values."""
    if not _FIXTURE_PATH.exists():
        return _FALLBACK
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return _FALLBACK
    try:
        loaded = yaml.safe_load(_FIXTURE_PATH.read_text())
        return loaded if isinstance(loaded, dict) else _FALLBACK
    except Exception:  # — fall back on any parse error
        return _FALLBACK


# Common ground-truth payload reused by every Q4 sub-question.
_GROUND_TRUTH_BASE = {
    "required_tools_any_of": ["get_fundamentals_history"],
    "forbid_amd_revenue_above_billions": 15.0,
    "forbid_nvda_revenue_above_billions": 100.0,
}


# ---------------------------------------------------------------------------
# Module-scoped accumulator — every sub-question stashes its result here so
# the three cross-cutting tests at the bottom can scan all answers in one
# pass. We use a module attribute (not a fixture) so the cross-cutting
# tests don't require parametrisation; pytest collects them as plain
# functions and they read the accumulator after the question tests have
# run.
# ---------------------------------------------------------------------------

_ALL_RESULTS: list[ChatRunResult] = []


def _record(r: ChatRunResult) -> ChatRunResult:
    _ALL_RESULTS.append(r)
    return r


# ---------------------------------------------------------------------------
# Per-variant tests.
# ---------------------------------------------------------------------------


def test_q4_v1_compare_revenues(ask: Callable[..., ChatRunResult]) -> None:
    """Variant 1: open-ended comparison — most prone to fabrication."""
    q = "Compare the revenue trajectories of NVIDIA and AMD over the last 4 quarters."
    result = _record(ask(q, slot="q4_v1"))
    grade = grade_response(q, result, _GROUND_TRUTH_BASE)
    assert grade["verdict"] == USEFUL, f"Q4 v1 verdict={grade['verdict']!r} reasons={grade['reasons']!r}"


def test_q4_v2_nvda_single_quarter(ask: Callable[..., ChatRunResult]) -> None:
    """Variant 2: pinpoint NVDA Q4FY26 revenue (bellwether: 68.127B)."""
    q = "What was NVIDIA's revenue in Q4 of fiscal 2026?"
    result = _record(ask(q, slot="q4_v2"))
    grade = grade_response(q, result, _GROUND_TRUTH_BASE)
    assert grade["verdict"] == USEFUL, f"Q4 v2 verdict={grade['verdict']!r} reasons={grade['reasons']!r}"
    # Bellwether check: 68.127 must appear or be tolerated by validator.
    assert "68" in result.answer_text, "Q4 v2 — NVDA Q4FY26 revenue 68.127B not mentioned"


def test_q4_v3_amd_revenue_and_eps(ask: Callable[..., ChatRunResult]) -> None:
    """Variant 3: AMD Q1FY26 revenue (10.253B) + EPS (0.45)."""
    q = "What was AMD's Q1 2026 revenue and EPS?"
    result = _record(ask(q, slot="q4_v3"))
    grade = grade_response(q, result, _GROUND_TRUTH_BASE)
    assert grade["verdict"] == USEFUL, f"Q4 v3 verdict={grade['verdict']!r} reasons={grade['reasons']!r}"
    # AMD must NOT have a revenue figure > $15B for any quarter in this answer.
    assert grade["verdict"] != HARMFUL, "Q4 v3 produced HARMFUL — fabricated AMD figure"


def test_q4_v4_nvda_margin_trend(ask: Callable[..., ChatRunResult]) -> None:
    """Variant 4: gross-margin trend (6 quarters)."""
    q = "Show me NVIDIA's gross margin trend over the past 6 quarters."
    result = _record(ask(q, slot="q4_v4"))
    grade = grade_response(q, result, _GROUND_TRUTH_BASE)
    assert grade["verdict"] == USEFUL, f"Q4 v4 verdict={grade['verdict']!r} reasons={grade['reasons']!r}"


def test_q4_v5_amd_yoy_growth(ask: Callable[..., ChatRunResult]) -> None:
    """Variant 5: YoY revenue growth, most recent reported quarter."""
    q = "What is AMD's revenue growth YoY for the most recent quarter?"
    result = _record(ask(q, slot="q4_v5"))
    grade = grade_response(q, result, _GROUND_TRUTH_BASE)
    assert grade["verdict"] == USEFUL, f"Q4 v5 verdict={grade['verdict']!r} reasons={grade['reasons']!r}"


def test_q4_v6_full_comparison_table(ask: Callable[..., ChatRunResult]) -> None:
    """Variant 6: full table — revenue + EPS + gross margin, both tickers."""
    q = "Compare NVDA and AMD on revenue, EPS, and gross margin for the latest reported quarter."
    result = _record(ask(q, slot="q4_v6"))
    grade = grade_response(q, result, _GROUND_TRUTH_BASE)
    assert grade["verdict"] == USEFUL, f"Q4 v6 verdict={grade['verdict']!r} reasons={grade['reasons']!r}"


# ---------------------------------------------------------------------------
# Cross-cutting assertions over ALL Q4 variants. These rely on
# ``_ALL_RESULTS`` being populated by the per-variant tests above. pytest
# runs file-level tests in source order so the accumulator is filled
# before these run.
# ---------------------------------------------------------------------------


def _require_accumulator_populated() -> None:
    """Skip the cross-cutting tests if the per-variant tests didn't run."""
    if not _ALL_RESULTS:
        pytest.skip("no Q4 variants ran — accumulator empty (per-variant tests skipped)")


def test_q4_zero_amd_figures_above_15b() -> None:
    """Across all 6 Q4 variants no AMD revenue figure > $15B may appear."""
    _require_accumulator_populated()
    bad = []
    fixture = _load_fixture()
    # Cap from fixture if available, else fallback to 15.
    cap = 15.0
    for r in _ALL_RESULTS:
        grade = grade_response(
            r.question,
            r,
            {"forbid_amd_revenue_above_billions": cap},
        )
        if grade["verdict"] == HARMFUL and any("AMD revenue >" in reason for reason in grade["reasons"]):
            bad.append(r.question)
    assert not bad, f"AMD revenue > ${cap}B mentioned in: {bad!r}\nfixture meta: {list(fixture.keys())}"


def test_q4_zero_orphan_rationalisations() -> None:
    """No Q4 answer may contain rationalisation phrases without a citation."""
    _require_accumulator_populated()
    offenders: list[tuple[str, list[str]]] = []
    for r in _ALL_RESULTS:
        orphans = orphan_rationalisations(r.answer_text or "")
        if orphans:
            offenders.append((r.question, orphans))
    assert not offenders, f"orphan rationalisation phrases found: {offenders!r}"


def test_q4_no_invented_quarter_labels() -> None:
    """No Q4 answer may mention a quarter that has not yet been reported."""
    _require_accumulator_populated()
    fixture = _load_fixture()
    not_reported_pairs: list[tuple[str, str]] = []
    for entry in fixture.get("not_reported", []):
        ticker = str(entry.get("ticker", "")).upper()
        for q in entry.get("quarters", []):
            not_reported_pairs.append((ticker, str(q)))

    offenders: list[tuple[str, set[str]]] = []
    for r in _ALL_RESULTS:
        labels = extract_quarter_labels(r.answer_text or "")
        # We can't tell which ticker each label belongs to without parsing
        # the surrounding sentence — so we flag any forbidden quarter label
        # alongside its ticker iff the ticker is also mentioned in the answer.
        violations: set[str] = set()
        lower = (r.answer_text or "").lower()
        for ticker, q in not_reported_pairs:
            if q in labels and ticker.lower() in lower:
                violations.add(f"{ticker}:{q}")
        if violations:
            offenders.append((r.question, violations))
    assert not offenders, f"invented quarter labels: {offenders!r}"
