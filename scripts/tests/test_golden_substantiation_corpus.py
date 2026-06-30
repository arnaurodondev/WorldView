"""GOLDEN real-case regression net for the typed numeric matcher (PLAN-0116 W4.1).

Unlike the synthetic unit tests (``test_substantiation_check.py`` /
``test_grounding_cross_check.py``), every case here is a REAL ``(answer, sampled
fields)`` pair lifted verbatim from the strategic-subset run
``runs/run_20260626T185654Z/`` — the same run whose diagnosis drove PLAN-0116.
The expected substantiation outcome was HAND-DERIVED (see each case's
``derivation`` field in the JSON) by comparing the answer's numbers to the
captured sample under the typed multi-period matcher rules.

These two properties are what make the corpus the regression net "against
reality":
  * the ``34 %`` growth claim must NOT contradict the ``revenue`` absolute field
    (ru_nvda_amd_revenue_4q) — the exact observed false contradiction;
  * a multi-period revenue answer must produce ZERO contradictions while still
    substantiating the periods that WERE sampled.

If the matcher regresses on any real case, THIS file fails first.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

# scripts/ is not a package and not on sys.path during pytest.
_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from chat_quality_judge import (  # — sys.path mutation must precede the import
    cross_check_grounding,
    evaluate_substantiation,
)

pytestmark = pytest.mark.unit

# The golden corpus lives next to the run it was derived from.
_CORPUS_PATH = (
    Path(_SCRIPTS_DIR).parent / "tests" / "validation" / "chat_quality_benchmark" / "golden_substantiation_cases.json"
)


def _load_cases() -> list[dict[str, Any]]:
    data = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))
    cases = data["cases"]
    assert cases, "golden corpus must not be empty"
    return cases


_CASES = _load_cases()
_CASE_IDS = [c["id"] for c in _CASES]


def _assert_count(actual: int, expected: Any, *, case_id: str, name: str) -> None:
    """Assert one count, allowing the sentinel ``"ANY"`` (don't-care, but >= 0).

    ``"ANY"`` is used for the ``unmatched`` count on the multi-period cases where
    the exact number of neutral leftovers is an implementation detail (table
    pipes, range dashes, etc.) — what we assert there is only the load-bearing
    counts (substantiated / contradicted / unsupported).
    """
    if expected == "ANY":
        assert actual >= 0, f"[{case_id}] {name} should be a non-negative count, got {actual}"
        return
    assert actual == expected, f"[{case_id}] {name}: expected {expected}, got {actual}"


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_golden_substantiation_case(case: dict[str, Any]) -> None:
    """The typed matcher's substantiation output equals the hand-derived expected."""
    answer = case["answer_text"]
    tool_results = case["tool_results"]
    expected = case["expected"]

    check = evaluate_substantiation(answer, tool_results)

    assert (
        check.coverage == expected["coverage"]
    ), f"[{case['id']}] coverage: expected {expected['coverage']}, got {check.coverage}"
    _assert_count(check.substantiated, expected["substantiated"], case_id=case["id"], name="substantiated")
    _assert_count(check.unsupported, expected["unsupported"], case_id=case["id"], name="unsupported")
    _assert_count(check.contradicted, expected["contradicted"], case_id=case["id"], name="contradicted")
    if "unmatched" in expected:
        _assert_count(check.unmatched, expected["unmatched"], case_id=case["id"], name="unmatched")


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_golden_grounding_contradiction_parity(case: dict[str, Any]) -> None:
    """The shared pipeline (W1.1): the veto's contradicted count matches expected.

    ``cross_check_grounding`` and ``evaluate_substantiation`` run ONE shared
    claim pipeline, so the ``contradicted`` count the grounding veto would fire
    must equal the substantiation check's ``contradicted`` — and both must equal
    the hand-derived golden value.  This is the property whose ABSENCE produced
    the original divergence (veto found 9, substantiation 0 on the SAME answer).
    """
    answer = case["answer_text"]
    tool_results = case["tool_results"]
    expected = case["expected"]

    ground = cross_check_grounding(answer, tool_results)
    _assert_count(ground.contradicted, expected["contradicted"], case_id=case["id"], name="ground.contradicted")
