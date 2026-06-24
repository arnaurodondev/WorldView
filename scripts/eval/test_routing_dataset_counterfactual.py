"""Offline tests for the counterfactual LIGHT + negative-verification labeler (C-3b).

These exercise the pure logic (Wilson CI, degraded exclusion, FN-rate analysis,
GoldenArticle adaptation) WITHOUT any DB or network. The DB-bound selectors and the
API-bound extractor are integration-run manually against the live DBs + DeepInfra.

Run:  python -m pytest scripts/eval/test_routing_dataset_counterfactual.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import routing_dataset_counterfactual as cf

# ── Wilson CI ─────────────────────────────────────────────────────────────────


def test_wilson_ci_zero_n() -> None:
    assert cf._wilson_ci(0, 0) == (0.0, 0.0)


def test_wilson_ci_brackets_point_estimate() -> None:
    lo, hi = cf._wilson_ci(10, 100)
    assert lo < 0.10 < hi
    assert 0.0 <= lo <= hi <= 1.0


def test_wilson_ci_extreme_zero_successes() -> None:
    # 0/50: lower bound pinned at 0, upper bound strictly positive and < 1.
    lo, hi = cf._wilson_ci(0, 50)
    assert lo == 0.0
    assert 0.0 < hi < 1.0


# ── LIGHT positive-rate analysis (degraded excluded) ──────────────────────────


def _run(doc_id: str, *, yielded: bool, degraded: bool = False, ev: int = 0, cl: int = 0, rel: int = 0) -> cf.DocRun:
    return cf.DocRun(
        doc_id=doc_id,
        status="degraded" if degraded else "ok",
        n_events=ev,
        n_claims=cl,
        n_relations=rel,
        yielded=yielded,
        degraded=degraded,
        attempts=1,
        tokens_in=10,
        tokens_out=5,
        usd=0.0001,
    )


def test_analyze_light_excludes_degraded() -> None:
    runs = [
        _run("a", yielded=True, ev=1),
        _run("b", yielded=False),
        _run("c", yielded=True, rel=2),
        _run("d", yielded=False, degraded=True),  # excluded from denominator
    ]
    res = cf.analyze_light(runs)
    assert res["n_extracted"] == 4
    assert res["n_degraded_excluded"] == 1
    assert res["n_labelable"] == 3  # d excluded
    assert res["n_positive"] == 2
    assert res["positive_rate"] == round(2 / 3, 4)


# ── Negative false-negative analysis ──────────────────────────────────────────


def _neg_sample(doc_id: str, title: str = "t") -> cf.NegativeSample:
    return cf.NegativeSample(
        doc_id=doc_id,
        title=title,
        old_yielded=False,
        old_n_relations=0,
        old_n_claims=0,
        old_n_events=0,
        entities="none identified",
        text="body",
    )


def test_analyze_negatives_fn_rate_and_recommendation_low() -> None:
    # 1 of 10 labelable flips → 10% FN → below threshold → USE AS-IS.
    runs = [_run(str(i), yielded=False) for i in range(9)] + [_run("9", yielded=True, ev=1)]
    samples = [_neg_sample(str(i)) for i in range(10)]
    res = cf.analyze_negatives(runs, samples)
    assert res["n_labelable"] == 10
    assert res["n_flipped_to_positive"] == 1
    assert res["false_negative_rate"] == 0.1
    assert "USE AS-IS" in res["recommendation"]


def test_analyze_negatives_fn_rate_high_recommends_reextract() -> None:
    # 3 of 10 flip → 30% FN → above 15% threshold → RE-EXTRACT.
    runs = [_run(str(i), yielded=False) for i in range(7)] + [_run(str(i), yielded=True, cl=1) for i in range(7, 10)]
    samples = [_neg_sample(str(i)) for i in range(10)]
    res = cf.analyze_negatives(runs, samples)
    assert res["false_negative_rate"] == 0.3
    assert "RE-EXTRACT" in res["recommendation"]
    assert len(res["flipped_examples"]) == 3


def test_analyze_negatives_excludes_degraded_from_denominator() -> None:
    runs = [_run("a", yielded=False), _run("b", yielded=False, degraded=True)]
    samples = [_neg_sample("a"), _neg_sample("b")]
    res = cf.analyze_negatives(runs, samples)
    assert res["n_labelable"] == 1
    assert res["n_degraded_excluded"] == 1


# ── GoldenArticle adaptation (faithful reuse of the C-3 harness input model) ───


def test_to_golden_carries_entities_and_text() -> None:
    art = cf._to_golden("doc1", "Title", "Apple Inc., Tim Cook", "Apple reported earnings.")
    assert art.doc_id == "doc1"
    assert art.entities == "Apple Inc., Tim Cook"
    assert art.text == "Apple reported earnings."
    assert art.word_count == 3  # "Apple reported earnings."


# ── USD fallback uses API cost when present, else published rate ──────────────


def test_usd_for_prefers_api_cost() -> None:
    assert cf._usd_for(1000, 1000, 0.05) == 0.05


def test_usd_for_falls_back_to_rate() -> None:
    # 1M in @ 0.071 + 1M out @ 0.10 = 0.171
    assert abs(cf._usd_for(1_000_000, 1_000_000, None) - 0.171) < 1e-9
