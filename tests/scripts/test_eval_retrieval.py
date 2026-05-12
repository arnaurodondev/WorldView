"""Unit tests for scripts/eval_retrieval.py — PLAN-0063 W5-1-02."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import httpx
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
    candidates = [{"doc_id": "abc123"}]
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


# ─── Boost-sweep mode tests (PLAN-0063 W5-3 §0-bis.7 / L9) ────────────────────


def _agg(*, identifier: float, comparison: float = 0.5, factual: float = 0.5) -> dict:
    """Minimal aggregate dict shaped like aggregate()'s return."""
    return {
        "summary": {"ndcg_at_10": {"mean": (identifier + comparison + factual) / 3}},
        "by_class": {
            "identifier_lookup": {"ndcg_at_10": identifier},
            "comparison": {"ndcg_at_10": comparison},
            "factual_lookup": {"ndcg_at_10": factual},
        },
    }


def test_boost_sweep_picks_max_identifier_lookup_without_regression() -> None:
    """When 1.5 lifts target without regressing others → picked."""
    per_boost = {
        1.0: _agg(identifier=0.40, comparison=0.50, factual=0.50),  # baseline
        1.2: _agg(identifier=0.45, comparison=0.50, factual=0.50),
        1.5: _agg(identifier=0.55, comparison=0.495, factual=0.498),  # tiny drop ok
        1.8: _agg(identifier=0.52, comparison=0.49, factual=0.49),
    }
    picked, decision = eval_retrieval.select_optimal_boost(per_boost)
    assert picked == 1.5
    assert decision["target_class"] == "identifier_lookup"


def test_boost_sweep_rejects_boost_that_regresses_other_class() -> None:
    """boost=2.0 has best target but tanks comparison → rejected."""
    per_boost = {
        1.0: _agg(identifier=0.40, comparison=0.60, factual=0.50),  # baseline
        1.5: _agg(identifier=0.50, comparison=0.59, factual=0.49),
        2.0: _agg(identifier=0.65, comparison=0.55, factual=0.50),  # 0.05 drop on comparison
    }
    picked, decision = eval_retrieval.select_optimal_boost(per_boost)
    assert picked != 2.0
    assert any(r["boost"] == 2.0 for r in decision["rejected"])
    assert any("comparison" in r["reason"] for r in decision["rejected"] if r["boost"] == 2.0)


def test_boost_sweep_writes_output(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """run_boost_sweep with --boost-sweep-inputs writes the expected JSON shape.

    S-011 (Wave 1): --boost-sweep-inputs paths are now validated to be under cwd.
    monkeypatch.chdir(tmp_path) makes tmp_path the cwd so the paths are valid.
    """
    import asyncio

    monkeypatch.chdir(tmp_path)  # S-011: path guard checks relative to cwd
    base_path = tmp_path / "agg_1_0.json"
    boost15_path = tmp_path / "agg_1_5.json"
    base_path.write_text(json.dumps(_agg(identifier=0.40, comparison=0.50, factual=0.50)))
    boost15_path.write_text(json.dumps(_agg(identifier=0.55, comparison=0.50, factual=0.50)))

    args = eval_retrieval.parse_args(
        [
            "--mode",
            "hybrid_boost_sweep",
            "--output-dir",
            str(tmp_path),
            "--boost-sweep-inputs",
            f"1.0:{base_path}",
            "--boost-sweep-inputs",
            f"1.5:{boost15_path}",
        ]
    )
    rc = asyncio.run(eval_retrieval.run_boost_sweep(args))
    assert rc == 0

    # Expect a boost_sweep_*.json file with the right top-level keys.
    sweep_files = list(tmp_path.glob("boost_sweep_*.json"))
    assert len(sweep_files) == 1
    payload = json.loads(sweep_files[0].read_text())
    assert "candidates" in payload
    assert "per_boost" in payload
    assert "decision" in payload
    assert payload["decision"]["picked_boost"] == 1.5


def test_boost_sweep_baseline_required() -> None:
    """select_optimal_boost without baseline_boost in inputs → ValueError."""
    per_boost = {1.5: _agg(identifier=0.55)}
    with pytest.raises(ValueError):
        eval_retrieval.select_optimal_boost(per_boost)


# ─── PLAN-0084 E-2: per-class regression check tests ─────────────────────────


def _make_golden_jsonl(tmp_path: Path, *, n_labelled: int = 10, n_unlabelled: int = 0) -> Path:
    """Write a minimal JSONL golden set to tmp_path/queries.jsonl."""
    golden = tmp_path / "queries.jsonl"
    lines = []
    # Labelled rows: one class with n_labelled entries (>=6 for the gate to apply)
    for i in range(n_labelled):
        lines.append(
            json.dumps(
                {
                    "query_id": f"q{i:04d}",
                    "query_text": f"test query {i}",
                    "query_class": "factual_lookup",
                    "intent": "FACTUAL_LOOKUP",
                    "relevant_doc_ids": [{"doc_id": f"doc{i}", "relevance": 1}],
                }
            )
        )
    # Unlabelled rows: no relevant_doc_ids
    for i in range(n_unlabelled):
        lines.append(
            json.dumps(
                {
                    "query_id": f"u{i:04d}",
                    "query_text": f"unlabelled {i}",
                    "query_class": "factual_lookup",
                    "intent": "FACTUAL_LOOKUP",
                    "relevant_doc_ids": [],
                }
            )
        )
    golden.write_text("\n".join(lines) + "\n")
    return golden


def _make_baseline_json(
    tmp_path: Path,
    *,
    factual_lookup_ndcg: float = 0.6,
    factual_lookup_n: int = 10,
) -> Path:
    """Write a minimal baseline JSON to tmp_path/baseline.json."""
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "summary": {"ndcg_at_10": {"mean": factual_lookup_ndcg}},
                "by_class": {
                    "factual_lookup": {
                        "n": factual_lookup_n,
                        "ndcg_at_10": factual_lookup_ndcg,
                        "mrr": 0.6,
                        "p_at_5": 0.4,
                        "recall_at_20": 0.5,
                    }
                },
            }
        )
    )
    return baseline


def test_per_class_regression_check_passes_when_within_threshold(tmp_path: Path) -> None:
    """Global pass + per-class within threshold → exit 0.

    NDCG@10 ≈ 1.0 (perfect retrieval) vs baseline 0.60 — well within 0.05 → exit 0.
    Uses call_retrieve patch so no HTTP is needed.
    """
    import asyncio
    import unittest.mock

    golden = _make_golden_jsonl(tmp_path, n_labelled=10)
    # Baseline: factual_lookup NDCG@10 = 0.60
    baseline = _make_baseline_json(tmp_path, factual_lookup_ndcg=0.60)
    args = eval_retrieval.parse_args(
        [
            "--golden",
            str(golden),
            "--baseline",
            str(baseline),
            "--output-dir",
            str(tmp_path / "out"),
            "--fail-on-regression",
            "0.03",
            "--fail-on-regression-per-class",
            "0.05",
        ]
    )

    # Patch call_retrieve to return the matching doc for each query (NDCG≈1.0).
    async def _good_retrieve(
        client: object,
        rag_url: str,
        query_text: str,
        *,
        query_embedding: object = None,
        top_k: int = 20,
        internal_jwt: object = None,
    ) -> list[dict[str, object]]:
        try:
            idx = int(query_text.split()[-1])
        except (ValueError, IndexError):
            idx = 0
        return [{"doc_id": f"doc{idx}"}]

    with unittest.mock.patch.object(eval_retrieval, "call_retrieve", side_effect=_good_retrieve):
        rc = asyncio.run(eval_retrieval.run_eval(args))

    assert rc == 0


def test_per_class_regression_check_fails_when_one_class_regresses(tmp_path: Path) -> None:
    """When a class drops > threshold → exit 1 and message names the class.

    Baseline NDCG = 0.95; current returns empty candidates (NDCG=0.0).
    Drop of 0.95 >> 0.05 threshold → exit 1.
    Global gate is disabled (fail_on_regression=1.0) so only per-class fires.
    """
    import asyncio
    import unittest.mock

    golden = _make_golden_jsonl(tmp_path, n_labelled=10)
    baseline = _make_baseline_json(tmp_path, factual_lookup_ndcg=0.95)
    args = eval_retrieval.parse_args(
        [
            "--golden",
            str(golden),
            "--baseline",
            str(baseline),
            "--output-dir",
            str(tmp_path / "out"),
            "--fail-on-regression",
            "1.0",  # disable global gate — only per-class should fire
            "--fail-on-regression-per-class",
            "0.05",
        ]
    )

    async def _zero_retrieve(
        client: object,
        rag_url: str,
        query_text: str,
        *,
        query_embedding: object = None,
        top_k: int = 20,
        internal_jwt: object = None,
    ) -> list[dict[str, object]]:
        return []  # empty candidates → NDCG=0 for all queries

    with unittest.mock.patch.object(eval_retrieval, "call_retrieve", side_effect=_zero_retrieve):
        rc = asyncio.run(eval_retrieval.run_eval(args))

    assert rc == 1


def test_per_class_regression_check_absent_means_no_per_class_check(tmp_path: Path) -> None:
    """Flag not set (0.0) → new per-class gate code path never fires; exits 0.

    Without --fail-on-regression-per-class AND without --baseline, there is
    nothing to compare against — the run produces its own output and exits 0.
    This verifies that omitting the flag doesn't introduce unexpected failures
    from the new gate code path (the new code path is guarded by
    ``per_class_threshold > 0.0``).
    """
    import asyncio
    import unittest.mock

    golden = _make_golden_jsonl(tmp_path, n_labelled=10)
    args = eval_retrieval.parse_args(
        [
            "--golden",
            str(golden),
            "--output-dir",
            str(tmp_path / "out"),
            # No --baseline → compare_to_baseline never runs.
            # No --fail-on-regression-per-class → defaults to 0.0 (disabled).
        ]
    )

    async def _zero_retrieve(
        client: object,
        rag_url: str,
        query_text: str,
        *,
        query_embedding: object = None,
        top_k: int = 20,
        internal_jwt: object = None,
    ) -> list[dict[str, object]]:
        return []  # NDCG=0 for all queries

    with unittest.mock.patch.object(eval_retrieval, "call_retrieve", side_effect=_zero_retrieve):
        rc = asyncio.run(eval_retrieval.run_eval(args))

    # Without a baseline and with the flag disabled, we always exit 0.
    assert rc == 0


def test_empty_per_query_with_many_labelled_exits_1(tmp_path: Path) -> None:
    """n_labelled >= 50 and per_query empty → exit 1 (eval should have run).

    When >=50 rows are labelled but every retrieve call raises RequestError
    (all go to ``failed`` list), ``per_query`` stays empty.  The tightened
    exit code (PLAN-0084 E-2) must return 1 because the labelling coverage is
    sufficient — the failure signals a broken service, not a labelling gap.
    """
    import asyncio
    import unittest.mock

    golden = _make_golden_jsonl(tmp_path, n_labelled=50)
    args = eval_retrieval.parse_args(
        [
            "--golden",
            str(golden),
            "--output-dir",
            str(tmp_path / "out"),
            "--max-failures",
            "100",  # don't exit on max-failures — let per_query stay empty
        ]
    )

    async def _always_fails(
        client: object,
        rag_url: str,
        query_text: str,
        *,
        query_embedding: object = None,
        top_k: int = 20,
        internal_jwt: object = None,
    ) -> list[dict[str, object]]:
        raise httpx.RequestError("connection refused", request=unittest.mock.MagicMock())

    with unittest.mock.patch.object(eval_retrieval, "call_retrieve", side_effect=_always_fails):
        rc = asyncio.run(eval_retrieval.run_eval(args))

    assert rc == 1


def test_empty_per_query_with_few_labelled_exits_0(tmp_path: Path) -> None:
    """n_labelled < 50 and per_query empty → exit 0 (labelling still in flight).

    When <50 rows are labelled and per_query is empty, the gate is informational:
    the labelling gap explains the empty result, so exit 0 is correct.
    """
    import asyncio
    import unittest.mock

    golden = _make_golden_jsonl(tmp_path, n_labelled=10)
    args = eval_retrieval.parse_args(
        [
            "--golden",
            str(golden),
            "--output-dir",
            str(tmp_path / "out"),
            "--max-failures",
            "100",
        ]
    )

    async def _always_fails(
        client: object,
        rag_url: str,
        query_text: str,
        *,
        query_embedding: object = None,
        top_k: int = 20,
        internal_jwt: object = None,
    ) -> list[dict[str, object]]:
        raise httpx.RequestError("connection refused", request=unittest.mock.MagicMock())

    with unittest.mock.patch.object(eval_retrieval, "call_retrieve", side_effect=_always_fails):
        rc = asyncio.run(eval_retrieval.run_eval(args))

    assert rc == 0


def test_per_class_gate_skips_class_with_fewer_than_6_queries(tmp_path: Path) -> None:
    """Classes with n < 6 must emit a WARN and be excluded from the n<6-guarded gate.

    F-013: The n<6 guard lives in the SEPARATE per-class check in run_eval
    (lines 699-738), which is distinct from compare_to_baseline's built-in check.
    Setup: baseline ndcg=0.04 so a drop to 0.0 is -0.04, which is within
    compare_to_baseline's 0.05 threshold (passes) but exceeds the
    --fail-on-regression-per-class=0.03 threshold.  The n<6 guard must then
    skip the class and return exit 0.
    """
    import asyncio
    import unittest.mock

    # 5 labelled rows → n_graded=5 < 6 after eval
    golden = _make_golden_jsonl(tmp_path, n_labelled=5)
    # Baseline ndcg=0.04: a drop to 0.0 is -0.04, within compare_to_baseline's 0.05 gate
    baseline = _make_baseline_json(tmp_path, factual_lookup_ndcg=0.04, factual_lookup_n=5)
    args = eval_retrieval.parse_args(
        [
            "--golden",
            str(golden),
            "--baseline",
            str(baseline),
            "--output-dir",
            str(tmp_path / "out"),
            "--fail-on-regression",
            "1.0",  # disable global gate
            "--fail-on-regression-per-class",
            "0.03",  # -0.04 drop exceeds this, but n<6 guard must skip
        ]
    )

    async def _zero_retrieve(
        client: object,
        rag_url: str,
        query_text: str,
        *,
        query_embedding: object = None,
        top_k: int = 20,
        internal_jwt: object = None,
    ) -> list[dict[str, object]]:
        return []  # NDCG=0 → delta=-0.04 (within compare_to_baseline's 0.05 gate)

    with unittest.mock.patch.object(eval_retrieval, "call_retrieve", side_effect=_zero_retrieve):
        rc = asyncio.run(eval_retrieval.run_eval(args))

    # n=5 < 6 → per-class gate skips class → exit 0 despite -0.04 regression
    assert rc == 0, "Class with n < 6 must be skipped by the n<6 guard — should not trigger exit 1"
