"""Aggregate score gate test (PLAN-0093 Wave G-3 T-G-3-10).

This is the **final acceptance gate** for PLAN-0093:

* ≥ 6 of 8 audit questions verdicts in {USEFUL}
* 0 HARMFUL verdicts
* median latency ≤ 30s
* p99 latency ≤ 60s

The test loads every question from ``questions.yaml``, fires it through
the shared ``ask`` fixture, regrades the result, and asserts on the
distribution. It deliberately re-fires the questions (rather than reading
the per-test artefacts) so it can run *standalone* — `pytest
tests/validation/chat_eval/test_aggregate_score.py` is a one-command
acceptance check that doesn't depend on the other test files having run
first.

PLAN-0095 W2 T-W2-04 acceptance gate (DEFERRED to Phase D)
----------------------------------------------------------
The wave-level acceptance for PLAN-0095 W2 (latency reduction: batch tool +
classifier reorder) is the SAME ``p99 latency ≤ 60s`` invariant asserted on
line ~103 below — the gate is unchanged, only the projected value moves
(ITER-8 baseline 91.9 s → projected ~45 s after T-W1-03 index + T-W2-02
batch tool + T-W2-03 cache-hit fast path).

Per-run artefacts written by this harness live at::

    tests/validation/chat_eval/runs/<timestamp>/q_<slot>.json

When ``_P99_LATENCY_MAX_S`` fires on a future run, the diagnostic summary
emitted in the assert message above (``p99_latency=<float>s``) is the
field to read. There is no separate ``summary.json`` written today; if a
future change adds one, the field name MUST be ``latency.p99_seconds`` so
T-W2-04's compounding gate (PLAN-0095 W2 acceptance row) lines up
verbatim. Anyone wiring such a writer should update this docstring to
match and bump the gate row in ``docs/plans/TRACKING.md``.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest

from tests.validation.chat_eval.grading import HARMFUL, USEFUL, grade_response
from tests.validation.chat_eval.harness import load_questions

if TYPE_CHECKING:
    from tests.validation.chat_eval.harness import ChatRunResult

# Latency SLOs from the audit + PLAN-0093 README.
_MEDIAN_LATENCY_MAX_S = 30.0
_P99_LATENCY_MAX_S = 60.0

# Useful-count gate from PLAN-0093 Done Definition.
_MIN_USEFUL = 6
_MAX_HARMFUL = 0


def _percentile(values: list[float], pct: float) -> float:
    """Tiny linear-interp percentile (no numpy dep)."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def test_aggregate_score_gate(ask: Callable[..., ChatRunResult]) -> None:
    """The PLAN-0093 final gate: ≥ 6 USEFUL, 0 HARMFUL, latency SLOs met."""
    try:
        questions = load_questions()
    except pytest.skip.Exception:
        raise
    except FileNotFoundError:
        pytest.skip("questions.yaml not found")

    verdicts: list[str] = []
    latencies: list[float] = []
    per_question: list[dict[str, Any]] = []

    for q in questions:
        qid = q.get("id", "?")
        prompt = q["prompt"]
        gt = q.get("ground_truth_assertions") or {}
        result = ask(prompt, slot=f"agg_{qid}")
        grade = grade_response(prompt, result, gt)
        verdicts.append(grade["verdict"])
        latencies.append(result.latency_s)
        per_question.append({"id": qid, "verdict": grade["verdict"], "reasons": grade["reasons"]})

    counts = Counter(verdicts)
    useful_count = counts.get(USEFUL, 0)
    harmful_count = counts.get(HARMFUL, 0)

    median = statistics.median(latencies) if latencies else 0.0
    p99 = _percentile(latencies, 0.99)

    # Build a single multi-line message so a failure surfaces everything.
    summary = (
        f"verdicts={counts!r}\n"
        f"USEFUL={useful_count} (need ≥ {_MIN_USEFUL})\n"
        f"HARMFUL={harmful_count} (need ≤ {_MAX_HARMFUL})\n"
        f"median_latency={median:.2f}s (max {_MEDIAN_LATENCY_MAX_S}s)\n"
        f"p99_latency={p99:.2f}s (max {_P99_LATENCY_MAX_S}s)\n"
        f"per_question={per_question!r}"
    )

    # All four gates as one assert: the test report will show every failing
    # gate at once instead of bailing on the first.
    failures: list[str] = []
    if useful_count < _MIN_USEFUL:
        failures.append(f"USEFUL count {useful_count} < {_MIN_USEFUL}")
    if harmful_count > _MAX_HARMFUL:
        failures.append(f"HARMFUL count {harmful_count} > {_MAX_HARMFUL}")
    if median > _MEDIAN_LATENCY_MAX_S:
        failures.append(f"median latency {median:.2f}s > {_MEDIAN_LATENCY_MAX_S}s")
    if p99 > _P99_LATENCY_MAX_S:
        failures.append(f"p99 latency {p99:.2f}s > {_P99_LATENCY_MAX_S}s")

    assert not failures, f"PLAN-0093 acceptance gate FAILED:\n{summary}\nfailures={failures!r}"
