"""Unit tests for ``scripts/run_chat_quality_benchmark.py``.

These tests intentionally do NOT hit the network. They exercise the pure
helpers (argparse, YAML filtering, heuristics derivation) so a regression
in the script's plumbing is caught before the next live benchmark run.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "run_chat_quality_benchmark.py"


@pytest.fixture(scope="module")
def script_mod():
    """Import the script as a module so we can call its helpers directly."""
    # Make sure relative imports inside the script (chat_eval.*) resolve.
    sys.path.insert(0, str(_REPO_ROOT))
    sys.path.insert(0, str(_REPO_ROOT / "tests" / "validation"))
    spec = importlib.util.spec_from_file_location("run_chat_quality_benchmark", _SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parse_args_defaults(script_mod) -> None:
    ns = script_mod.parse_args([])
    assert ns.base_url == "http://localhost:8000"
    assert ns.tags == ""
    assert ns.ids == ""
    # Eval-v2 default: 3 runs per question for variance/stddev metrics.
    assert ns.max_runs_per_q == 3


def test_filter_questions_by_tag(script_mod) -> None:
    qs = [
        {"id": "a", "tags": ["smoke", "real_user"]},
        {"id": "b", "tags": ["aggregate"]},
        {"id": "c", "tags": ["smoke"]},
    ]
    out = script_mod.filter_questions(qs, tags=["smoke"], ids=None)
    assert [q["id"] for q in out] == ["a", "c"]


def test_filter_questions_by_id(script_mod) -> None:
    qs = [{"id": "a", "tags": []}, {"id": "b", "tags": []}]
    out = script_mod.filter_questions(qs, tags=None, ids=["b"])
    assert [q["id"] for q in out] == ["b"]


def test_filter_questions_tag_and_id_intersect(script_mod) -> None:
    qs = [
        {"id": "a", "tags": ["smoke"]},
        {"id": "b", "tags": ["smoke"]},
    ]
    out = script_mod.filter_questions(qs, tags=["smoke"], ids=["a"])
    assert [q["id"] for q in out] == ["a"]


def test_derive_pass_fail_clean_path(script_mod) -> None:
    # PLAN-0099-W4: removed must_not_say_hits, entities_missing, and
    # answer_meets_min_words from the heuristic dict — the v2.0 LLM judge
    # replaced those checks (semantic, not substring). The remaining bucket
    # logic is purely infrastructure (HTTP status, empty answer, refusal
    # classifier, latency-budget breach, zero-tools-called).
    heur = {
        "status_code": 200,
        "error": None,
        "is_empty": False,
        "is_refusal": False,
        "latency_within_budget": True,
        "missing_expected_tools": [],
        "distinct_tools_called": ["get_entity_news"],
        "word_count": 200,
        "latency_s": 10.0,
    }
    bucket, reasons = script_mod.derive_pass_fail(heur)
    assert bucket == "PASS"
    assert reasons == []


def test_derive_pass_fail_http_error_is_fail(script_mod) -> None:
    # An HTTP-layer error short-circuits everything → FAIL (was implicit
    # before; pinning it explicitly now that the forbidden-phrase test
    # is gone).
    heur = {
        "status_code": 500,
        "error": {"code": "HTTP_ERROR", "message": "internal"},
        "is_empty": False,
        "is_refusal": False,
        "latency_within_budget": True,
        "missing_expected_tools": [],
        "distinct_tools_called": [],
        "word_count": 0,
        "latency_s": 5.0,
    }
    bucket, reasons = script_mod.derive_pass_fail(heur)
    assert bucket == "FAIL"
    assert any("http_status=500" in r for r in reasons)


def test_derive_pass_fail_latency_budget_breach_is_warn(script_mod) -> None:
    # PLAN-0099-W4: the latency budget is now the only top-level advisory
    # signal that can still bump PASS→WARN (in addition to refusal +
    # zero-tools). Pin the new behaviour so a future refactor can't quietly
    # drop the budget check.
    heur = {
        "status_code": 200,
        "error": None,
        "is_empty": False,
        "is_refusal": False,
        "latency_within_budget": False,
        "missing_expected_tools": [],
        "distinct_tools_called": ["get_entity_news"],
        "word_count": 200,
        "latency_s": 120.0,
    }
    bucket, reasons = script_mod.derive_pass_fail(heur)
    assert bucket == "WARN"
    assert any("slow" in r for r in reasons)


def test_compute_heuristics_reads_rubric_and_budgets(script_mod) -> None:
    # PLAN-0099-W4: expected_tools moved into rubric.expected_tools and
    # expected_max_latency_s moved into budgets.max_latency_s. The
    # heuristic dict must source from the new locations — pinning the
    # contract so a regression to top-level reads can't slip through.
    # Minimal ChatRunResult-shaped stub via SimpleNamespace — avoids RUF012
    # noise about mutable class attributes on a one-shot test object.
    from types import SimpleNamespace

    result = SimpleNamespace(
        answer_text="AAPL P/E is 37.73x [query_fundamentals row 0].",
        latency_s=5.0,
        ttft_s=1.0,
        phase_timings_ms={},
        output_tokens=12,
        tool_calls=[],
        tool_results=[],
        citations=[],
        contradictions=[],
        error=None,
        status_code=200,
        tools_called=lambda: ["query_fundamentals"],
    )

    q = {
        "id": "x",
        "rubric": {"expected_tools": ["query_fundamentals", "get_fundamentals_history"]},
        "budgets": {"max_latency_s": 30},
    }
    heur = script_mod.compute_heuristics(q, result)
    # expected_tools comes from rubric, not top-level.
    assert "query_fundamentals" in heur["expected_tools"]
    assert "get_fundamentals_history" in heur["expected_tools"]
    # tool_overlap correctly intersects rubric tools with called tools.
    assert heur["tool_overlap_with_expected"] == ["query_fundamentals"]
    # Latency budget honoured (5 < 30).
    assert heur["latency_within_budget"] is True
    # Removed legacy keys are no longer in the heuristic dict.
    for legacy_key in ("entities_mentioned", "entities_missing", "must_not_say_hits", "answer_meets_min_words"):
        assert legacy_key not in heur, f"Legacy heuristic key {legacy_key!r} should be removed"


def test_safe_slot_single_run(script_mod) -> None:
    assert script_mod._safe_slot("foo/bar", 0, 1) == "q_foo_bar"


def test_safe_slot_multi_run_appends_index(script_mod) -> None:
    assert script_mod._safe_slot("foo", 2, 3) == "q_foo_run3"
