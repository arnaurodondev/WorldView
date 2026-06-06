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
    assert ns.max_runs_per_q == 1


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
    heur = {
        "status_code": 200,
        "error": None,
        "is_empty": False,
        "is_refusal": False,
        "must_not_say_hits": [],
        "entities_missing": [],
        "answer_meets_min_words": True,
        "latency_within_budget": True,
        "missing_expected_tools": [],
        "distinct_tools_called": ["get_entity_news"],
        "word_count": 200,
        "latency_s": 10.0,
    }
    bucket, reasons = script_mod.derive_pass_fail(heur)
    assert bucket == "PASS"
    assert reasons == []


def test_derive_pass_fail_forbidden_phrase_is_fail(script_mod) -> None:
    heur = {
        "status_code": 200,
        "error": None,
        "is_empty": False,
        "is_refusal": False,
        "must_not_say_hits": ["No data was found"],
        "entities_missing": [],
        "answer_meets_min_words": True,
        "latency_within_budget": True,
        "missing_expected_tools": [],
        "distinct_tools_called": [],
        "word_count": 100,
        "latency_s": 5.0,
    }
    bucket, reasons = script_mod.derive_pass_fail(heur)
    assert bucket == "FAIL"
    assert any("forbidden" in r for r in reasons)


def test_safe_slot_single_run(script_mod) -> None:
    assert script_mod._safe_slot("foo/bar", 0, 1) == "q_foo_bar"


def test_safe_slot_multi_run_appends_index(script_mod) -> None:
    assert script_mod._safe_slot("foo", 2, 3) == "q_foo_run3"
