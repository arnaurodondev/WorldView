"""Unit tests for scripts/eval_retrieval.py — PLAN-0063 W5-1-02."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

# Import the script as a module.
_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "eval_retrieval.py"
_SPEC = importlib.util.spec_from_file_location("eval_retrieval", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
eval_retrieval = importlib.util.module_from_spec(_SPEC)
sys.modules["eval_retrieval"] = eval_retrieval
_SPEC.loader.exec_module(eval_retrieval)


# ─── Metric primitive tests ───────────────────────────────────────────────────


def test_ndcg_perfect_ranking_returns_1() -> None:
    """When retrieved order matches ideal order, NDCG = 1.0."""
    relevant = {"a": 3, "b": 2, "c": 1}
    retrieved = ["a", "b", "c"]
    assert eval_retrieval.ndcg_at_k(retrieved, relevant, k=10) == pytest.approx(1.0)


def test_ndcg_inverted_ranking_drops_below_1() -> None:
    """Reversed ideal → NDCG < 1.0 with deterministic value."""
    relevant = {"a": 3, "b": 2, "c": 1}
    retrieved = ["c", "b", "a"]  # reversed
    score = eval_retrieval.ndcg_at_k(retrieved, relevant, k=10)
    assert 0 < score < 1.0
    # Hand-computed: DCG = 1/1 + 3/log2(3) + 7/log2(4) = 1 + 1.893 + 3.5 = 6.393
    # IDCG = 7/1 + 3/log2(3) + 1/log2(4) = 7 + 1.893 + 0.5 = 9.393
    # NDCG ≈ 6.393 / 9.393 ≈ 0.681
    assert score == pytest.approx(0.681, abs=0.01)


def test_ndcg_no_relevant_docs_returns_0() -> None:
    """Empty relevant dict → NDCG = 0.0 (no possible gain)."""
    assert eval_retrieval.ndcg_at_k(["a", "b"], {}, k=10) == 0.0


def test_mrr_first_hit_at_rank_3() -> None:
    """First relevant at rank 3 → MRR = 1/3."""
    relevant = {"x": 1}
    retrieved = ["a", "b", "x", "c"]
    assert eval_retrieval.mean_reciprocal_rank(retrieved, relevant) == pytest.approx(1 / 3)


def test_mrr_no_relevant_returns_0() -> None:
    """No retrieved doc has relevance >= 1 → MRR = 0.0."""
    assert eval_retrieval.mean_reciprocal_rank(["a", "b"], {"x": 1}) == 0.0


def test_precision_at_5_three_hits() -> None:
    """3 of top-5 are relevant → P@5 = 0.6."""
    relevant = {"a": 1, "c": 2, "e": 1}
    retrieved = ["a", "b", "c", "d", "e"]
    assert eval_retrieval.precision_at_k(retrieved, relevant, k=5) == pytest.approx(0.6)


def test_recall_at_20_with_2_of_5_relevant_in_top_20() -> None:
    """2 of 5 relevant docs found in top-20 → Recall@20 = 0.4."""
    relevant = {f"r{i}": 1 for i in range(5)}
    retrieved = ["r0", "x", "r3"] + [f"y{i}" for i in range(17)]
    assert eval_retrieval.recall_at_k(retrieved, relevant, k=20) == pytest.approx(0.4)


# ─── Loader tests ─────────────────────────────────────────────────────────────


def test_load_golden_set_rejects_duplicate_ids(tmp_path: Path) -> None:
    """Duplicate query_id should raise."""
    f = tmp_path / "dup.jsonl"
    f.write_text(
        json.dumps({"query_id": "q001", "query_text": "x"})
        + "\n"
        + json.dumps({"query_id": "q001", "query_text": "y"})
        + "\n"
    )
    with pytest.raises(ValueError, match="duplicate query_id"):
        eval_retrieval.load_golden_set(f)


def test_load_golden_set_skips_blank_lines(tmp_path: Path) -> None:
    """Blank lines in JSONL are tolerated."""
    f = tmp_path / "ok.jsonl"
    f.write_text(
        json.dumps({"query_id": "q001", "query_text": "x"})
        + "\n\n"
        + json.dumps({"query_id": "q002", "query_text": "y"})
        + "\n"
    )
    rows = eval_retrieval.load_golden_set(f)
    assert len(rows) == 2


# ─── Per-query evaluation ─────────────────────────────────────────────────────


def test_evaluate_query_uses_doc_id_lowercase_compare() -> None:
    """doc_id comparison is case-insensitive (UUIDs may differ in case)."""
    row = {
        "query_id": "q001",
        "query_class": "factual_lookup",
        "intent": "FACTUAL_LOOKUP",
        "relevant_doc_ids": [{"doc_id": "ABC123", "relevance": 3}],
    }
    candidates = [{"doc_id": "abc123", "chunk_id": "c1"}]
    out = eval_retrieval.evaluate_query(row, candidates, top_k=10)
    assert out["ndcg_at_10"] == pytest.approx(1.0)
    assert out["mrr"] == pytest.approx(1.0)


def test_evaluate_query_n_relevant_labelled_counts_only_labelled() -> None:
    """n_relevant_labelled counts entries in relevant_doc_ids."""
    row = {
        "query_id": "q001",
        "query_class": "comparison",
        "intent": "COMPARISON",
        "relevant_doc_ids": [
            {"doc_id": "a", "relevance": 3},
            {"doc_id": "b", "relevance": 2},
        ],
    }
    candidates: list[dict[str, str]] = []
    out = eval_retrieval.evaluate_query(row, candidates, top_k=10)
    assert out["n_relevant_labelled"] == 2
    assert out["n_retrieved"] == 0


# ─── Aggregation ──────────────────────────────────────────────────────────────


def test_aggregate_breaks_down_by_class() -> None:
    """by_class groups per-query results by query_class."""
    per_query = [
        {
            "query_id": "q001",
            "query_class": "factual_lookup",
            "intent": "FACTUAL_LOOKUP",
            "ndcg_at_10": 0.8,
            "mrr": 1.0,
            "p_at_5": 0.6,
            "recall_at_20": 0.7,
            "n_retrieved": 20,
            "n_relevant_labelled": 5,
            "retrieved_top_5": [],
        },
        {
            "query_id": "q002",
            "query_class": "factual_lookup",
            "intent": "FACTUAL_LOOKUP",
            "ndcg_at_10": 0.4,
            "mrr": 0.5,
            "p_at_5": 0.4,
            "recall_at_20": 0.5,
            "n_retrieved": 20,
            "n_relevant_labelled": 5,
            "retrieved_top_5": [],
        },
        {
            "query_id": "q003",
            "query_class": "comparison",
            "intent": "COMPARISON",
            "ndcg_at_10": 0.6,
            "mrr": 0.5,
            "p_at_5": 0.4,
            "recall_at_20": 0.6,
            "n_retrieved": 20,
            "n_relevant_labelled": 5,
            "retrieved_top_5": [],
        },
    ]
    agg = eval_retrieval.aggregate(per_query)
    assert agg["summary"]["ndcg_at_10"]["mean"] == pytest.approx((0.8 + 0.4 + 0.6) / 3)
    assert agg["by_class"]["factual_lookup"]["n"] == 2
    assert agg["by_class"]["factual_lookup"]["ndcg_at_10"] == pytest.approx(0.6)
    assert agg["by_class"]["comparison"]["n"] == 1


# ─── Baseline regression ──────────────────────────────────────────────────────


def test_compare_to_baseline_passes_when_unchanged() -> None:
    """Same-score current vs baseline → passes."""
    baseline = {
        "summary": {"ndcg_at_10": {"mean": 0.5}},
        "by_class": {"factual_lookup": {"ndcg_at_10": 0.6}},
    }
    current = {
        "summary": {"ndcg_at_10": {"mean": 0.5}},
        "by_class": {"factual_lookup": {"ndcg_at_10": 0.6}},
    }
    passed, _msgs = eval_retrieval.compare_to_baseline(current, baseline, fail_on_regression=0.03)
    assert passed is True


def test_compare_to_baseline_fails_on_global_regression() -> None:
    """Global NDCG@10 dropping below threshold → fail."""
    baseline = {
        "summary": {"ndcg_at_10": {"mean": 0.5}},
        "by_class": {},
    }
    current = {
        "summary": {"ndcg_at_10": {"mean": 0.45}},  # 0.05 drop
        "by_class": {},
    }
    passed, msgs = eval_retrieval.compare_to_baseline(current, baseline, fail_on_regression=0.03)
    assert passed is False
    assert any("REGRESSION" in m for m in msgs)


def test_compare_to_baseline_required_improvement_mode() -> None:
    """Negative threshold → required improvement floor."""
    baseline = {
        "summary": {"ndcg_at_10": {"mean": 0.5}},
        "by_class": {},
    }
    # Current lifts by 0.03 only; required is 0.05.
    current = {
        "summary": {"ndcg_at_10": {"mean": 0.53}},
        "by_class": {},
    }
    passed, msgs = eval_retrieval.compare_to_baseline(current, baseline, fail_on_regression=-0.05)
    assert passed is False
    assert any("INSUFFICIENT_LIFT" in m for m in msgs)


def test_compare_to_baseline_per_class_regression_fails() -> None:
    """Per-class regression ≥0.05 fails even when global is fine."""
    baseline = {
        "summary": {"ndcg_at_10": {"mean": 0.5}},
        "by_class": {"identifier_lookup": {"ndcg_at_10": 0.8}},
    }
    current = {
        "summary": {"ndcg_at_10": {"mean": 0.5}},
        "by_class": {"identifier_lookup": {"ndcg_at_10": 0.7}},  # 0.10 drop
    }
    passed, msgs = eval_retrieval.compare_to_baseline(current, baseline, fail_on_regression=0.03)
    assert passed is False
    assert any("PER_CLASS_REGRESSION" in m for m in msgs)


# ─── Sanity checks ────────────────────────────────────────────────────────────


def test_dcg_monotonic_in_relevance() -> None:
    """DCG increases as gains increase at any fixed rank."""
    a = eval_retrieval.dcg([1.0, 1.0, 1.0], 3)
    b = eval_retrieval.dcg([3.0, 3.0, 3.0], 3)
    assert b > a


def test_dcg_decreases_with_lower_rank_for_same_total_gain() -> None:
    """Same gain at later rank produces less DCG (rank-discounting)."""
    a = eval_retrieval.dcg([3.0, 0.0, 0.0], 3)
    b = eval_retrieval.dcg([0.0, 0.0, 3.0], 3)
    assert a > b
    assert b > 0
    # Sanity: log2-discounted gain at rank 3 is gain / log2(4) = (2^3 - 1) / 2 = 3.5
    assert b == pytest.approx(7.0 / math.log2(4))
