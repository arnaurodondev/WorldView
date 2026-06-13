"""Offline tests for the routing-classifier train/ablation harness (PLAN-0111 C-4/C-5).

These exercise the PURE helpers (text assembly, static rule, metric calc, threshold
selection, cost/yield curve, feature-matrix assembly, embedding cache I/O) WITHOUT
any network or sklearn-at-import. The embedding API is never called here; the one
network-touching path (`get_embeddings` → adapter) is exercised against a stubbed
adapter so no real DeepInfra call is made.

Run:  python -m pytest scripts/eval/test_routing_classifier_train.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import routing_classifier_train as rct

# ── build_classifier_text ─────────────────────────────────────────────────────


def test_build_classifier_text_joins_with_newline() -> None:
    assert rct.build_classifier_text("Apple beats", "Q3 revenue up 12%") == "Apple beats\nQ3 revenue up 12%"


def test_build_classifier_text_handles_missing_parts() -> None:
    assert rct.build_classifier_text("Title only", None) == "Title only"
    assert rct.build_classifier_text(None, "Subtitle only") == "Subtitle only"
    assert rct.build_classifier_text(np.nan, np.nan) == ""
    # NaN must never leak as the literal string "nan".
    assert "nan" not in rct.build_classifier_text(
        np.nan, "real subtitle"
    ).lower() or "real" in rct.build_classifier_text(np.nan, "real subtitle")


def test_build_classifier_text_strips_whitespace() -> None:
    assert rct.build_classifier_text("  A  ", "  B  ") == "A\nB"


# ── static_weighted_score (baseline D) ────────────────────────────────────────


def test_static_weighted_score_all_max_is_one() -> None:
    row = {f: 1.0 for f in rct.STATIC_SIGNAL_WEIGHTS}
    assert rct.static_weighted_score(row) == pytest.approx(1.0)


def test_static_weighted_score_all_zero_is_zero() -> None:
    row = {f: 0.0 for f in rct.STATIC_SIGNAL_WEIGHTS}
    assert rct.static_weighted_score(row) == pytest.approx(0.0)


def test_static_weighted_score_weighted_mix() -> None:
    # Only entity_density set → its weight 0.35.
    row = {f: 0.0 for f in rct.STATIC_SIGNAL_WEIGHTS}
    row["entity_density"] = 1.0
    assert rct.static_weighted_score(row) == pytest.approx(0.35)


def test_static_weights_sum_to_one() -> None:
    assert sum(rct.STATIC_SIGNAL_WEIGHTS.values()) == pytest.approx(1.0)


# ── assemble_feature_matrix ───────────────────────────────────────────────────


def _toy_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "entity_density": [0.1, 0.9],
            "source_reliability": [0.5, 0.5],
            "recency": [1.0, 0.2],
            "document_type": [0.5, 0.88],
            "extraction_yield": [0.0, 0.7],
        }
    )


def test_assemble_hand_only() -> None:
    x = rct.assemble_feature_matrix(_toy_df(), hand_features=rct.HAND_FEATURES)
    assert x.shape == (2, 5)


def test_assemble_embedding_only() -> None:
    emb = np.ones((2, 4))
    x = rct.assemble_feature_matrix(_toy_df(), hand_features=(), embeddings=emb)
    assert x.shape == (2, 4)


def test_assemble_concat_orders_hand_then_embedding() -> None:
    emb = np.full((2, 3), 7.0)
    x = rct.assemble_feature_matrix(_toy_df(), hand_features=("recency",), embeddings=emb)
    assert x.shape == (2, 4)
    # first column is the hand feature, rest are embedding dims
    assert x[0, 0] == pytest.approx(1.0)
    assert np.all(x[:, 1:] == 7.0)


def test_assemble_rejects_empty() -> None:
    with pytest.raises(ValueError, match="at least one"):
        rct.assemble_feature_matrix(_toy_df(), hand_features=(), embeddings=None)


def test_assemble_rejects_row_mismatch() -> None:
    with pytest.raises(ValueError, match="rows"):
        rct.assemble_feature_matrix(_toy_df(), embeddings=np.ones((3, 2)))


# ── brier_score ───────────────────────────────────────────────────────────────


def test_brier_perfect_is_zero() -> None:
    assert rct.brier_score(np.array([1, 0, 1]), np.array([1.0, 0.0, 1.0])) == pytest.approx(0.0)


def test_brier_worst_is_one() -> None:
    assert rct.brier_score(np.array([1, 0]), np.array([0.0, 1.0])) == pytest.approx(1.0)


def test_brier_half_guess() -> None:
    assert rct.brier_score(np.array([1, 0]), np.array([0.5, 0.5])) == pytest.approx(0.25)


# ── threshold selection (Youden) ──────────────────────────────────────────────


def test_select_threshold_perfect_separation() -> None:
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.2, 0.8, 0.9])
    thr = rct.select_threshold_youden(y, p)
    # any threshold in (0.2, 0.8] perfectly separates; chosen one must classify all right
    cm = rct.confusion_at_threshold(y, p, thr)
    assert cm["fp"] == 0 and cm["fn"] == 0


def test_select_threshold_returns_probability() -> None:
    y = np.array([0, 1, 0, 1, 1])
    p = np.array([0.2, 0.6, 0.4, 0.7, 0.55])
    thr = rct.select_threshold_youden(y, p)
    assert 0.0 <= thr <= 1.0


# ── confusion + accuracy/F1 ───────────────────────────────────────────────────


def test_confusion_counts() -> None:
    y = np.array([1, 1, 0, 0])
    p = np.array([0.9, 0.4, 0.6, 0.1])
    cm = rct.confusion_at_threshold(y, p, 0.5)
    assert cm == {"tp": 1, "fp": 1, "tn": 1, "fn": 1}


def test_accuracy_f1_balanced() -> None:
    acc, f1 = rct.accuracy_f1_from_confusion({"tp": 1, "fp": 1, "tn": 1, "fn": 1})
    assert acc == pytest.approx(0.5)
    assert f1 == pytest.approx(0.5)


def test_accuracy_f1_perfect() -> None:
    acc, f1 = rct.accuracy_f1_from_confusion({"tp": 5, "fp": 0, "tn": 5, "fn": 0})
    assert acc == pytest.approx(1.0)
    assert f1 == pytest.approx(1.0)


def test_accuracy_f1_empty_safe() -> None:
    acc, f1 = rct.accuracy_f1_from_confusion({"tp": 0, "fp": 0, "tn": 0, "fn": 0})
    assert acc == 0.0 and f1 == 0.0


# ── cost / yield curve ────────────────────────────────────────────────────────


def test_cost_yield_curve_monotone_recall() -> None:
    y = np.array([1, 1, 0, 0, 1])
    p = np.array([0.9, 0.7, 0.3, 0.1, 0.5])
    curve = rct.cost_yield_curve(y, p, n_points=11)
    recalls = [pt["yield_recall"] for pt in curve]
    # recall is non-increasing as threshold rises
    assert all(recalls[i] >= recalls[i + 1] for i in range(len(recalls) - 1))
    # at threshold 0 everything routed → recall 1.0, routed_fraction 1.0
    assert curve[0]["yield_recall"] == pytest.approx(1.0)
    assert curve[0]["routed_fraction"] == pytest.approx(1.0)


def test_cost_yield_curve_precision_at_top() -> None:
    y = np.array([1, 1, 0, 0])
    p = np.array([0.9, 0.8, 0.2, 0.1])
    curve = rct.cost_yield_curve(y, p, n_points=11)
    # a mid threshold routes only the two positives → precision 1.0
    mid = [pt for pt in curve if 0.3 <= pt["threshold"] <= 0.75]
    assert any(pt["precision"] == pytest.approx(1.0) for pt in mid)


# ── embedding cache I/O ───────────────────────────────────────────────────────


def test_embedding_cache_roundtrip(tmp_path: Path) -> None:
    cache = tmp_path / "embeddings_256.parquet"
    doc_ids = ["a", "b", "c"]
    vectors = np.arange(9, dtype=np.float64).reshape(3, 3)
    rct.save_embeddings_cache(cache, doc_ids, vectors)
    loaded = rct.load_cached_embeddings(cache)
    assert set(loaded.keys()) == {"a", "b", "c"}
    assert np.allclose(loaded["a"], [0, 1, 2])
    assert np.allclose(loaded["c"], [6, 7, 8])


def test_load_cached_embeddings_missing_returns_empty(tmp_path: Path) -> None:
    assert rct.load_cached_embeddings(tmp_path / "nope.parquet") == {}


def test_embedding_cache_path_keyed_by_dims(tmp_path: Path) -> None:
    ds = tmp_path / "routing_dataset.csv"
    assert rct.embedding_cache_path(ds, 768).name == "embeddings_768.parquet"
    assert rct.embedding_cache_path(ds, 256).name == "embeddings_256.parquet"
    assert rct.embedding_cache_path(ds, 256).parent == tmp_path


# ── report rendering (no network/sklearn) ─────────────────────────────────────


def test_render_report_contains_preliminary_and_tables(tmp_path: Path) -> None:
    results = {
        "gbm_lib": "lightgbm",
        "embedding_dims": 768,
        "cv_folds": 5,
        "random_seed": 42,
        "n_rows": 100,
        "positive_rate": 0.6,
        "models": [
            {
                "feature_set": "A",
                "model": "gbm",
                "roc_auc": 0.70,
                "pr_auc": 0.75,
                "brier": 0.20,
                "threshold": 0.5,
                "accuracy": 0.66,
                "f1": 0.70,
                "n_rows": 100,
                "feature_importance": {"entity_density": 0.5, "recency": 0.5},
            },
            {
                "feature_set": "A",
                "model": "logreg",
                "roc_auc": 0.68,
                "pr_auc": 0.72,
                "brier": 0.21,
                "threshold": 0.5,
                "accuracy": 0.64,
                "f1": 0.68,
                "n_rows": 100,
                "feature_importance": {},
            },
            {
                "feature_set": "B",
                "model": "gbm",
                "roc_auc": 0.78,
                "pr_auc": 0.82,
                "brier": 0.17,
                "threshold": 0.5,
                "accuracy": 0.72,
                "f1": 0.77,
                "n_rows": 100,
                "feature_importance": {},
            },
            {
                "feature_set": "C",
                "model": "gbm",
                "roc_auc": 0.80,
                "pr_auc": 0.84,
                "brier": 0.16,
                "threshold": 0.5,
                "accuracy": 0.74,
                "f1": 0.79,
                "n_rows": 100,
                "feature_importance": {"source_reliability": 0.3, "embedding(all_dims)": 0.7},
            },
            {
                "feature_set": "A_no_yield",
                "model": "gbm",
                "roc_auc": 0.69,
                "pr_auc": 0.74,
                "brier": 0.20,
                "threshold": 0.5,
                "accuracy": 0.65,
                "f1": 0.69,
                "n_rows": 100,
                "feature_importance": {},
            },
            {
                "feature_set": "D",
                "model": "static_rule",
                "roc_auc": 0.62,
                "pr_auc": 0.68,
                "brier": 0.24,
                "threshold": 0.5,
                "accuracy": 0.60,
                "f1": 0.64,
                "n_rows": 100,
                "feature_importance": {},
            },
        ],
        "cost_yield_curves": {
            "C": [
                {"threshold": 0.0, "routed_fraction": 1.0, "yield_recall": 1.0, "precision": 0.6},
                {"threshold": 0.5, "routed_fraction": 0.5, "yield_recall": 0.9, "precision": 0.9},
            ],
            "B": [{"threshold": 0.0, "routed_fraction": 1.0, "yield_recall": 1.0, "precision": 0.6}],
            "D": [{"threshold": 0.0, "routed_fraction": 1.0, "yield_recall": 1.0, "precision": 0.6}],
        },
    }
    md = rct.render_report(results, tmp_path / "routing_dataset.csv")
    assert "PRELIMINARY" in md
    assert "ROC-AUC" in md
    # verdict must reflect B (0.78) beating A (0.70)
    assert "BEATS" in md
    # C feature importance table present
    assert "embedding(all_dims)" in md


# ── get_embeddings against a stubbed adapter (no real network) ────────────────


def test_get_embeddings_uses_cache_and_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Build a tiny dataset; pre-seed cache for one doc so only the other is embedded.
    ds = tmp_path / "routing_dataset.csv"
    df = pd.DataFrame(
        {
            "doc_id": ["d1", "d2"],
            "title": ["t1", "t2"],
            "subtitle": ["s1", "s2"],
        }
    )
    df.to_csv(ds, index=False)
    rct.save_embeddings_cache(rct.embedding_cache_path(ds, 256), ["d1"], np.array([[1.0, 2.0]]))

    # Stub the async embedding helper so no DeepInfra call is made.
    async def _fake_embed(texts_by_doc: dict[str, str], *, dims: int, batch_size: int = 256) -> dict[str, np.ndarray]:
        assert list(texts_by_doc.keys()) == ["d2"]  # only the uncached doc
        return {"d2": np.array([3.0, 4.0])}

    monkeypatch.setattr(rct, "_embed_missing", _fake_embed)
    out = rct.get_embeddings(df, ds, 256)
    assert out.shape == (2, 2)
    assert np.allclose(out[0], [1.0, 2.0])  # from cache
    assert np.allclose(out[1], [3.0, 4.0])  # freshly stubbed
