#!/usr/bin/env python3
"""Train + ablation harness for the news-routing classifier (PLAN-0111 C-4/C-5).

PURPOSE
-------
PLAN-0111 Sub-Plan C is replacing the 5-hand-feature *static weighted-sum* router
(``services/nlp-pipeline/.../blocks/routing.py``) with a small calibrated
classifier whose input is an EmbeddingGemma-300m embedding of the article's
``title + subtitle``. This script is the **offline modelling harness** that:

  1. EMBEDS each labelled row's ``title + "\\n" + subtitle`` with the EmbeddingGemma
     *classification* prompt (cached to parquet so re-runs are free).
  2. TRAINS + CALIBRATES candidate routers with stratified 5-fold cross-validation,
     reporting *out-of-fold* metrics (nothing is scored on its own training data).
  3. Runs the ABLATION — the thesis result — comparing feature sets A/B/C/D on the
     SAME folds with the SAME metrics, plus a routing-economics (cost vs recall)
     view at the calibrated operating point.
  4. Writes a results JSON + a markdown report.

IMPORTANT — this is OFFLINE modelling only. Nothing here touches the production
routing path (that wiring is C-6). We never import nlp_pipeline; we only read the
CSV dataset and call the embedding adapter.

LEAKAGE NOTE
------------
``extraction_yield`` is a *pre-extraction* prior (``0.6*min(1,mentions/20) +
0.4*min(1,sections/8)``) — it does NOT observe the label, but its name is
misleading and it is correlated with structural richness, so the ablation runs the
hand-feature baseline (A) BOTH with and without it (``A`` and ``A_no_yield``).

FEATURE SETS (the ablation)
---------------------------
  A           : the 5 hand features (the baseline-to-beat).
  A_no_yield  : A minus ``extraction_yield`` (the cautious 4-feature baseline).
  B           : EmbeddingGemma(title+subtitle) ONLY.
  C           : Embedding + cheap structured features
                (source_reliability, recency, document_type).
  D           : the CURRENT static weighted-sum tier rule, scored as a classifier
                (a fixed-score baseline — shows lift over what is deployed).

For A/A_no_yield/B/C we train BOTH a logistic regression and a gradient-boosted
tree (LightGBM if importable, else sklearn HistGradientBoostingClassifier), each
wrapped in ``CalibratedClassifierCV`` (isotonic) so the reported probabilities are
calibrated and the threshold is meaningful. D is a non-learned fixed score, so it
is only evaluated (its "probability" is the normalised weighted sum).

METRICS (per model, out-of-fold)
--------------------------------
  ROC-AUC, PR-AUC (average precision), Brier score (calibration), and
  accuracy/F1 at the cost-aware decision threshold. Plus the routing-economics
  curve: across thresholds, the fraction of docs SENT to expensive extraction
  vs the fraction of realised yield (true positives) CAPTURED. This cost/recall
  tradeoff is what economically justifies (or kills) the router.

OUTPUT
------
  <out>/ablation_results.json
  docs/audits/2026-06-12-routing-classifier-ablation.md   (PRELIMINARY)

USAGE
-----
  # default: 768d embedding, full ablation on the base C-3 dataset
  NLP_PIPELINE_EXTRACTION_API_KEY=... \\
    python scripts/eval/routing_classifier_train.py \\
      --dataset results/routing_dataset/routing_dataset.csv

  # MRL 256d head; or re-run on the C-3b augmented CSV by swapping --dataset
  ... --dims 256 --dataset results/routing_dataset/routing_dataset_augmented.csv

The ``--dataset`` arg is the single knob to re-run on the augmented + de-biased
C-3b set once it lands; everything downstream (embedding cache key, CV, ablation)
is dataset-agnostic.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Sequence

# ── Repo paths ────────────────────────────────────────────────────────────────
# The harness lives in scripts/eval; libs/ml-clients holds the embedding adapter.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MLCLIENTS_SRC = _REPO_ROOT / "libs" / "ml-clients" / "src"
if str(_MLCLIENTS_SRC) not in sys.path:
    sys.path.insert(0, str(_MLCLIENTS_SRC))

# ── The 5 hand features (numeric signal scores, as persisted in the CSV) ──────
# NOTE: in the C-3 CSV ``document_type`` is ALREADY the numeric signal score
# (0.50 / 0.55 / 0.88, etc.), not a string — so every hand feature is float and
# usable directly as a model column with no encoding step.
HAND_FEATURES: tuple[str, ...] = (
    "entity_density",
    "source_reliability",
    "recency",
    "document_type",
    "extraction_yield",
)

# The "cheap structured" subset used in feature set C alongside the embedding.
# entity_density is excluded here because it is the most extraction-adjacent of
# the structured signals; source_reliability/recency/document_type are pure
# metadata available at ingest with zero extraction coupling.
CHEAP_STRUCTURED_FEATURES: tuple[str, ...] = (
    "source_reliability",
    "recency",
    "document_type",
)

# ── Static weighted-sum rule (baseline D), copied from the live routing block ──
# services/nlp-pipeline/src/nlp_pipeline/application/blocks/routing.py (v2).
# Kept as a literal here (NOT imported) so the offline harness never depends on a
# production module. If the production weights change, update this dict and note
# it in the report — it is the "what is deployed today" baseline.
STATIC_SIGNAL_WEIGHTS: dict[str, float] = {
    "entity_density": 0.35,
    "source_reliability": 0.30,
    "recency": 0.15,
    "document_type": 0.10,
    "extraction_yield": 0.10,
}

LABEL_COLUMN = "yielded"
DOC_ID_COLUMN = "doc_id"

# Cross-validation configuration (stratified k-fold, fixed seed for determinism).
CV_FOLDS = 5
RANDOM_SEED = 42

# Cost model for the routing-economics view. These are *relative* unit costs used
# to pick a single "cost-aware" operating threshold; the absolute $ figure is
# reported separately from the per-doc light/deep estimates in the C-3 manifest.
# A false-positive (route to expensive extraction, get nothing) wastes one deep
# extraction; a false-negative (route cheap, miss real yield) loses signal. We
# weight recall of realised yield as the primary objective (the platform exists to
# capture structured intelligence) and report the cost it implies.


# ════════════════════════════════════════════════════════════════════════════
# PURE HELPERS  (unit-tested; no DB, no network, no sklearn-at-import)
# ════════════════════════════════════════════════════════════════════════════


def build_classifier_text(title: str | float | None, subtitle: str | float | None) -> str:
    """Compose the classifier input string ``title + "\\n" + subtitle``.

    Missing title or subtitle (NaN / None / empty) are coerced to empty strings so
    the embedding call never receives a literal ``"nan"``. A row with neither
    yields the empty string (the adapter still returns a valid vector for "").
    """
    title_str = "" if title is None or (isinstance(title, float) and np.isnan(title)) else str(title).strip()
    subtitle_str = (
        "" if subtitle is None or (isinstance(subtitle, float) and np.isnan(subtitle)) else str(subtitle).strip()
    )
    if title_str and subtitle_str:
        return f"{title_str}\n{subtitle_str}"
    return title_str or subtitle_str


def static_weighted_score(row: dict[str, float], weights: dict[str, float] = STATIC_SIGNAL_WEIGHTS) -> float:
    """Score a row with the deployed static weighted-sum rule (baseline D).

    Returns the composite in [0, 1] (weights sum to 1.0 and every feature is a
    [0,1] signal score). This is the exact number the production router thresholds
    into DEEP/MEDIUM/LIGHT; here we use it directly as a classifier "probability".
    """
    return float(sum(weights[name] * float(row.get(name, 0.0)) for name in weights))


def assemble_feature_matrix(
    df: pd.DataFrame,
    *,
    hand_features: Sequence[str] = (),
    embeddings: np.ndarray | None = None,
) -> np.ndarray:
    """Assemble a 2-D float matrix from selected hand features and/or embeddings.

    Columns are ordered ``[hand_features..., embedding_dims...]``. Either part may
    be empty (e.g. embedding-only set B passes ``hand_features=()``; hand-only set
    A passes ``embeddings=None``). Raises if BOTH are empty (degenerate request).
    """
    blocks: list[np.ndarray] = []
    if hand_features:
        blocks.append(df.loc[:, list(hand_features)].to_numpy(dtype=np.float64))
    if embeddings is not None:
        if embeddings.shape[0] != len(df):
            raise ValueError(f"embedding rows {embeddings.shape[0]} != dataframe rows {len(df)}")
        blocks.append(np.asarray(embeddings, dtype=np.float64))
    if not blocks:
        raise ValueError("assemble_feature_matrix needs at least one of hand_features or embeddings")
    return np.hstack(blocks)


def brier_score(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    """Mean squared error between predicted probability and the 0/1 label.

    Lower is better; 0.0 is perfect. This is the standard calibration-quality
    metric — a model can have great AUC yet poor Brier if its probabilities are
    miscalibrated (which is why we calibrate before reporting it).
    """
    yt = np.asarray(y_true, dtype=np.float64)
    yp = np.asarray(y_prob, dtype=np.float64)
    return float(np.mean((yp - yt) ** 2))


def select_threshold_youden(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    """Pick the decision threshold maximising Youden's J (= TPR - FPR).

    Youden's J is threshold selection that balances sensitivity and specificity
    without needing an explicit cost ratio — a defensible default operating point
    for a binary router. Returns a probability in (0, 1). Ties resolve to the
    lowest qualifying threshold (more recall-favouring, matching the router's goal
    of capturing yield).
    """
    yt = np.asarray(y_true, dtype=np.int64)
    yp = np.asarray(y_prob, dtype=np.float64)
    positives = max(int(yt.sum()), 1)
    negatives = max(int((1 - yt).sum()), 1)
    # Evaluate J at each unique predicted probability as a candidate threshold.
    candidates = np.unique(yp)
    best_threshold = 0.5
    best_j = -np.inf
    for thr in candidates:
        predicted = yp >= thr
        tpr = float(np.sum(predicted & (yt == 1))) / positives
        fpr = float(np.sum(predicted & (yt == 0))) / negatives
        j = tpr - fpr
        if j > best_j:
            best_j = j
            best_threshold = float(thr)
    return best_threshold


def confusion_at_threshold(y_true: np.ndarray, y_prob: np.ndarray, threshold: float) -> dict[str, int]:
    """Return tp/fp/tn/fn counts for ``y_prob >= threshold``."""
    yt = np.asarray(y_true, dtype=np.int64)
    predicted = (np.asarray(y_prob, dtype=np.float64) >= threshold).astype(np.int64)
    tp = int(np.sum((predicted == 1) & (yt == 1)))
    fp = int(np.sum((predicted == 1) & (yt == 0)))
    tn = int(np.sum((predicted == 0) & (yt == 0)))
    fn = int(np.sum((predicted == 0) & (yt == 1)))
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def accuracy_f1_from_confusion(cm: dict[str, int]) -> tuple[float, float]:
    """Compute (accuracy, F1) from a tp/fp/tn/fn confusion dict."""
    tp, fp, tn, fn = cm["tp"], cm["fp"], cm["tn"], cm["fn"]
    total = tp + fp + tn + fn
    accuracy = (tp + tn) / total if total else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return float(accuracy), float(f1)


def cost_yield_curve(y_true: np.ndarray, y_prob: np.ndarray, n_points: int = 21) -> list[dict[str, float]]:
    """Routing-economics curve: at each threshold, fraction routed vs yield captured.

    For ``n_points`` thresholds spanning [0, 1]:
      * ``routed_fraction``  = fraction of docs whose score >= threshold (these are
        sent to EXPENSIVE deep extraction — this is the cost axis).
      * ``yield_recall``     = fraction of TRULY-yielding docs that are routed
        (true-positive rate — the value captured).
      * ``precision``        = of routed docs, fraction that actually yield (how
        much of the deep-extraction spend is "wasted" on zero-yield docs).

    The router is justified when, at a given ``yield_recall``, its ``routed_fraction``
    is well below 1.0 (i.e. it captures most of the value while skipping a large
    share of the expensive calls).
    """
    yt = np.asarray(y_true, dtype=np.int64)
    yp = np.asarray(y_prob, dtype=np.float64)
    n = len(yt)
    positives = max(int(yt.sum()), 1)
    curve: list[dict[str, float]] = []
    for thr in np.linspace(0.0, 1.0, n_points):
        routed = yp >= thr
        n_routed = int(np.sum(routed))
        tp = int(np.sum(routed & (yt == 1)))
        curve.append(
            {
                "threshold": float(thr),
                "routed_fraction": n_routed / n if n else 0.0,
                "yield_recall": tp / positives,
                "precision": (tp / n_routed) if n_routed else 0.0,
            }
        )
    return curve


def embedding_cache_path(dataset_path: Path, dims: int) -> Path:
    """Cache parquet path for the given dims, co-located with the dataset.

    Keyed by dims so 768d and 256d caches coexist. The cache stores doc_id + the
    vector columns so a re-run with a superset/subset dataset reuses overlapping
    rows by doc_id (see ``load_cached_embeddings``).
    """
    return dataset_path.parent / f"embeddings_{dims}.parquet"


def load_cached_embeddings(cache_path: Path) -> dict[str, np.ndarray]:
    """Load a doc_id → vector dict from the parquet cache (empty if absent)."""
    if not cache_path.exists():
        return {}
    cached = pd.read_parquet(cache_path)
    vec_cols = [c for c in cached.columns if c.startswith("e")]
    out: dict[str, np.ndarray] = {}
    for _, row in cached.iterrows():
        out[str(row[DOC_ID_COLUMN])] = row[vec_cols].to_numpy(dtype=np.float64)
    return out


def save_embeddings_cache(cache_path: Path, doc_ids: Sequence[str], vectors: np.ndarray) -> None:
    """Persist doc_id → vector rows to parquet (gitignored alongside the dataset)."""
    dims = vectors.shape[1]
    frame = pd.DataFrame(vectors, columns=[f"e{i}" for i in range(dims)])
    frame.insert(0, DOC_ID_COLUMN, list(doc_ids))
    frame.to_parquet(cache_path, index=False)


# ════════════════════════════════════════════════════════════════════════════
# EMBEDDING STAGE  (network; cached aggressively)
# ════════════════════════════════════════════════════════════════════════════


def _resolve_api_key() -> str:
    """Read the DeepInfra/EmbeddingGemma API key from env (never print it).

    The harness expects ``NLP_PIPELINE_EXTRACTION_API_KEY`` (the shared DeepInfra
    key) exported by the caller. We deliberately do not read the docker.env file
    here — the caller exports it — so the key never appears in this source or logs.
    """
    key = os.environ.get("NLP_PIPELINE_EXTRACTION_API_KEY") or os.environ.get("DEEPINFRA_API_KEY")
    if not key:
        raise SystemExit(
            "Set NLP_PIPELINE_EXTRACTION_API_KEY (DeepInfra key) in the environment. "
            "It is in services/nlp-pipeline/configs/docker.env — export it, do NOT hardcode."
        )
    return key


async def _embed_missing(
    texts_by_doc: dict[str, str],
    *,
    dims: int,
    batch_size: int = 256,
) -> dict[str, np.ndarray]:
    """Embed the given doc_id → text map with EmbeddingGemma, in batches.

    Returns doc_id → vector. Network/timeout errors propagate (the adapter already
    wraps an explicit httpx.Timeout per BP-235). Each batch is one DeepInfra call.
    """
    from ml_clients.adapters.embeddinggemma_router import EmbeddingGemmaRouterAdapter

    adapter = EmbeddingGemmaRouterAdapter(api_key=_resolve_api_key(), default_dimensions=dims, timeout=60.0)
    doc_ids = list(texts_by_doc.keys())
    out: dict[str, np.ndarray] = {}
    for start in range(0, len(doc_ids), batch_size):
        batch_ids = doc_ids[start : start + batch_size]
        batch_texts = [texts_by_doc[d] for d in batch_ids]
        vectors = await adapter.embed_for_classification(batch_texts, dimensions=dims)
        for doc_id, vec in zip(batch_ids, vectors, strict=True):
            out[doc_id] = np.asarray(vec, dtype=np.float64)
        print(f"  embedded {min(start + batch_size, len(doc_ids))}/{len(doc_ids)}", flush=True)
    return out


def get_embeddings(df: pd.DataFrame, dataset_path: Path, dims: int) -> np.ndarray:
    """Return the embedding matrix for ``df`` (cached by doc_id, dims-keyed).

    Loads any cached vectors, embeds only the missing doc_ids, updates the cache,
    then returns vectors in dataframe row order. Re-runs on an overlapping dataset
    are free for the shared rows.
    """
    cache_path = embedding_cache_path(dataset_path, dims)
    cached = load_cached_embeddings(cache_path)
    print(f"  embedding cache: {len(cached)} vectors at {cache_path}", flush=True)

    texts_by_doc: dict[str, str] = {}
    for _, row in df.iterrows():
        doc_id = str(row[DOC_ID_COLUMN])
        if doc_id not in cached:
            texts_by_doc[doc_id] = build_classifier_text(row.get("title"), row.get("subtitle"))

    if texts_by_doc:
        print(f"  embedding {len(texts_by_doc)} missing rows (dims={dims})...", flush=True)
        fresh = asyncio.run(_embed_missing(texts_by_doc, dims=dims))
        cached.update(fresh)
        # Persist the union so the next run (any dims-matching dataset) is free.
        all_ids = list(cached.keys())
        all_vecs = np.vstack([cached[d] for d in all_ids])
        save_embeddings_cache(cache_path, all_ids, all_vecs)

    return np.vstack([cached[str(row[DOC_ID_COLUMN])] for _, row in df.iterrows()])


# ════════════════════════════════════════════════════════════════════════════
# CV + EVALUATION  (sklearn imported lazily so pure-helper tests need no sklearn)
# ════════════════════════════════════════════════════════════════════════════


@dataclass
class ModelResult:
    """Out-of-fold metrics for one (feature_set, model) combination."""

    feature_set: str
    model: str
    roc_auc: float
    pr_auc: float
    brier: float
    threshold: float
    accuracy: float
    f1: float
    n_rows: int
    feature_importance: dict[str, float] = field(default_factory=dict)


def _build_estimator(kind: str, gbm_lib: str) -> Any:
    """Construct a calibrated estimator for ``kind`` in {logreg, gbm}.

    Wrapped in CalibratedClassifierCV(isotonic) so reported probabilities are
    calibrated (isotonic chosen over Platt: non-parametric, handles the tree
    models' non-sigmoid score shape; dataset is large enough to avoid overfit).
    """
    from sklearn.calibration import CalibratedClassifierCV  # type: ignore[import-untyped]
    from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
    from sklearn.pipeline import make_pipeline  # type: ignore[import-untyped]
    from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

    if kind == "logreg":
        base = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, random_state=RANDOM_SEED))
    elif kind == "gbm":
        if gbm_lib == "lightgbm":
            from lightgbm import LGBMClassifier  # type: ignore[import-untyped]

            base = LGBMClassifier(n_estimators=300, learning_rate=0.05, random_state=RANDOM_SEED, verbose=-1)
        else:
            from sklearn.ensemble import HistGradientBoostingClassifier  # type: ignore[import-untyped]

            base = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=RANDOM_SEED)
    else:
        raise ValueError(f"unknown estimator kind: {kind}")
    # cv=3 inner calibration folds; the outer 5-fold CV provides the honest OOF
    # estimate, the inner folds only calibrate within each training split.
    return CalibratedClassifierCV(base, method="isotonic", cv=3)


def cross_val_oof_probabilities(estimator_factory: Any, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Return out-of-fold predicted probabilities via stratified 5-fold CV.

    Each fold trains on 4/5 and predicts the held-out 1/5; concatenated, every
    row has a probability from a model that never saw it. A fresh estimator is
    built per fold (no leakage across folds).
    """
    from sklearn.model_selection import StratifiedKFold  # type: ignore[import-untyped]

    skf = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_SEED)
    oof = np.zeros(len(y), dtype=np.float64)
    for train_idx, test_idx in skf.split(x, y):
        est = estimator_factory()
        # LightGBM, refitted by CalibratedClassifierCV on a bare ndarray, emits a
        # cosmetic "X does not have valid feature names" UserWarning. We pass numpy
        # arrays deliberately (no column names), so suppress just that warning.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="X does not have valid feature names")
            est.fit(x[train_idx], y[train_idx])
            oof[test_idx] = est.predict_proba(x[test_idx])[:, 1]
    return oof


def evaluate_probabilities(feature_set: str, model: str, y: np.ndarray, y_prob: np.ndarray) -> ModelResult:
    """Compute the full metric bundle for a set of OOF probabilities."""
    from sklearn.metrics import average_precision_score, roc_auc_score  # type: ignore[import-untyped]

    threshold = select_threshold_youden(y, y_prob)
    cm = confusion_at_threshold(y, y_prob, threshold)
    accuracy, f1 = accuracy_f1_from_confusion(cm)
    return ModelResult(
        feature_set=feature_set,
        model=model,
        roc_auc=float(roc_auc_score(y, y_prob)),
        pr_auc=float(average_precision_score(y, y_prob)),
        brier=brier_score(y, y_prob),
        threshold=threshold,
        accuracy=accuracy,
        f1=f1,
        n_rows=len(y),
    )


def _gbm_feature_importance(x: np.ndarray, y: np.ndarray, names: Sequence[str], gbm_lib: str) -> dict[str, float]:
    """Fit a single GBM on all data to report (normalised) feature importances.

    This is for interpretability only (the report's feature-importance table); the
    scored metrics always come from the OOF CV above, never from this full fit.
    """
    if gbm_lib == "lightgbm":
        from lightgbm import LGBMClassifier  # type: ignore[import-untyped]

        model = LGBMClassifier(n_estimators=300, learning_rate=0.05, random_state=RANDOM_SEED, verbose=-1)
    else:
        from sklearn.ensemble import HistGradientBoostingClassifier  # type: ignore[import-untyped]
        from sklearn.inspection import permutation_importance  # type: ignore[import-untyped]

        model = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=RANDOM_SEED)
        model.fit(x, y)
        result = permutation_importance(model, x, y, n_repeats=5, random_state=RANDOM_SEED)
        raw = result.importances_mean
        total = float(np.sum(np.abs(raw))) or 1.0
        return {names[i]: float(raw[i] / total) for i in range(len(names))}

    model.fit(x, y)
    raw = model.feature_importances_.astype(np.float64)
    total = float(np.sum(raw)) or 1.0
    return {names[i]: float(raw[i] / total) for i in range(len(names))}


# ════════════════════════════════════════════════════════════════════════════
# ABLATION DRIVER
# ════════════════════════════════════════════════════════════════════════════


def run_ablation(df: pd.DataFrame, embeddings: np.ndarray, gbm_lib: str, dims: int) -> dict[str, Any]:
    """Run the full A/A_no_yield/B/C/D ablation and return a results dict."""
    y = df[LABEL_COLUMN].to_numpy(dtype=np.int64)
    results: list[ModelResult] = []
    cost_curves: dict[str, list[dict[str, float]]] = {}

    # Learned feature sets: (name, hand_features, use_embeddings).
    learned_sets: list[tuple[str, tuple[str, ...], bool]] = [
        ("A", HAND_FEATURES, False),
        ("A_no_yield", tuple(f for f in HAND_FEATURES if f != "extraction_yield"), False),
        ("B", (), True),
        ("C", CHEAP_STRUCTURED_FEATURES, True),
    ]

    for set_name, hand_feats, use_emb in learned_sets:
        x = assemble_feature_matrix(df, hand_features=hand_feats, embeddings=embeddings if use_emb else None)
        col_names = list(hand_feats) + ([f"emb_{i}" for i in range(dims)] if use_emb else [])
        print(
            f"[ablation] {set_name}: {x.shape[1]} cols ({len(hand_feats)} hand + {dims if use_emb else 0} emb)",
            flush=True,
        )

        for model_kind in ("logreg", "gbm"):
            oof = cross_val_oof_probabilities(lambda mk=model_kind: _build_estimator(mk, gbm_lib), x, y)
            res = evaluate_probabilities(set_name, model_kind, y, oof)
            if model_kind == "gbm":
                # Feature importance only meaningful when columns are nameable; for
                # embedding-heavy sets we aggregate the embedding dims into one entry.
                imp = _gbm_feature_importance(x, y, col_names, gbm_lib)
                if use_emb:
                    emb_total = sum(v for k, v in imp.items() if k.startswith("emb_"))
                    imp = {k: v for k, v in imp.items() if not k.startswith("emb_")}
                    imp["embedding(all_dims)"] = float(emb_total)
                res.feature_importance = imp
            results.append(res)
            # Cost/yield curve from the best (gbm) OOF probabilities per set.
            if model_kind == "gbm":
                cost_curves[set_name] = cost_yield_curve(y, oof)
            print(
                f"    {model_kind}: AUC={res.roc_auc:.4f} PR-AUC={res.pr_auc:.4f} Brier={res.brier:.4f} F1={res.f1:.4f}",
                flush=True,
            )

    # Baseline D: the static weighted-sum rule scored directly (no training).
    d_scores = np.array(
        [static_weighted_score(row._asdict() if hasattr(row, "_asdict") else dict(row)) for _, row in df.iterrows()]
    )
    d_res = evaluate_probabilities("D", "static_rule", y, d_scores)
    results.append(d_res)
    cost_curves["D"] = cost_yield_curve(y, d_scores)
    print(
        f"[ablation] D static_rule: AUC={d_res.roc_auc:.4f} PR-AUC={d_res.pr_auc:.4f} Brier={d_res.brier:.4f} F1={d_res.f1:.4f}",
        flush=True,
    )

    return {
        "gbm_lib": gbm_lib,
        "embedding_dims": dims,
        "cv_folds": CV_FOLDS,
        "random_seed": RANDOM_SEED,
        "n_rows": int(len(df)),
        "positive_rate": float(y.mean()),
        "models": [vars(r) for r in results],
        "cost_yield_curves": cost_curves,
    }


# ════════════════════════════════════════════════════════════════════════════
# REPORT
# ════════════════════════════════════════════════════════════════════════════


def _best_per_set(models: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Best (by ROC-AUC) model row per feature set, for the headline table."""
    best: dict[str, dict[str, Any]] = {}
    for m in models:
        fs = m["feature_set"]
        if fs not in best or m["roc_auc"] > best[fs]["roc_auc"]:
            best[fs] = m
    return best


def render_report(results: dict[str, Any], dataset_path: Path) -> str:
    """Render the PRELIMINARY markdown ablation report."""
    models = results["models"]
    best = _best_per_set(models)
    set_labels = {
        "A": "A — 5 hand features (baseline)",
        "A_no_yield": "A_no_yield — 4 hand features (drop extraction_yield)",
        "B": "B — EmbeddingGemma(title+subtitle) only",
        "C": "C — Embedding + cheap structured",
        "D": "D — Static weighted-sum rule (deployed)",
    }

    lines: list[str] = []
    lines.append("# Routing Classifier Ablation — PRELIMINARY (PLAN-0111 C-4/C-5)")
    lines.append("")
    lines.append("> **PRELIMINARY.** Trained on the CURRENT C-3 dataset, whose labels are")
    lines.append("> selection-biased (LIGHT/SUPPRESS tiers are unlabeled) and noisy (silent")
    lines.append("> deep-extraction timeouts may appear as zero-yield). To be RE-RUN on the")
    lines.append("> C-3b augmented + de-biased set by swapping `--dataset`. Do not quote these")
    lines.append("> numbers as final.")
    lines.append("")
    lines.append(
        f"- **Dataset**: `{dataset_path}` — {results['n_rows']} rows, " f"positive rate {results['positive_rate']:.4f}"
    )
    lines.append(f"- **GBM library**: `{results['gbm_lib']}`")
    lines.append(f"- **Embedding**: `google/embeddinggemma-300m`, {results['embedding_dims']}d, classification prompt")
    lines.append(f"- **CV**: stratified {results['cv_folds']}-fold, out-of-fold metrics, seed={results['random_seed']}")
    lines.append("- **Calibration**: `CalibratedClassifierCV(isotonic)`; threshold = Youden's J")
    lines.append("")

    # Headline table: best model per feature set.
    lines.append("## Ablation — best model per feature set")
    lines.append("")
    lines.append("| Feature set | Model | ROC-AUC | PR-AUC | Brier | Acc | F1 | Thr |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for fs in ("A", "A_no_yield", "B", "C", "D"):
        if fs not in best:
            continue
        m = best[fs]
        lines.append(
            f"| {set_labels[fs]} | {m['model']} | {m['roc_auc']:.4f} | {m['pr_auc']:.4f} | "
            f"{m['brier']:.4f} | {m['accuracy']:.4f} | {m['f1']:.4f} | {m['threshold']:.3f} |"
        )
    lines.append("")

    # Full per-model table.
    lines.append("## All models (logreg + gbm per set)")
    lines.append("")
    lines.append("| Feature set | Model | ROC-AUC | PR-AUC | Brier | Acc | F1 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    for m in models:
        lines.append(
            f"| {m['feature_set']} | {m['model']} | {m['roc_auc']:.4f} | {m['pr_auc']:.4f} | "
            f"{m['brier']:.4f} | {m['accuracy']:.4f} | {m['f1']:.4f} |"
        )
    lines.append("")

    # Verdict: does embedding (B) beat the hand baseline (A)?
    a_auc = best["A"]["roc_auc"]
    b_auc = best["B"]["roc_auc"]
    c_auc = best.get("C", best["B"])["roc_auc"]
    d_auc = best["D"]["roc_auc"]
    delta_ba = b_auc - a_auc
    delta_ca = c_auc - a_auc
    verdict = "BEATS" if delta_ba > 0 else "does NOT beat"
    lines.append("## Verdict")
    lines.append("")
    lines.append(
        f"- Embedding-only (B) {verdict} the 5-feature baseline (A) on ROC-AUC: "
        f"**{b_auc:.4f} vs {a_auc:.4f}** (Δ = {delta_ba:+.4f})."
    )
    lines.append(f"- Embedding + cheap structured (C): **{c_auc:.4f}** (Δ vs A = {delta_ca:+.4f}).")
    lines.append(
        f"- Lift of best learned model over the deployed static rule (D, AUC {d_auc:.4f}): "
        f"**Δ = {max(a_auc, b_auc, c_auc) - d_auc:+.4f}**."
    )
    lines.append("")

    # Cost / yield operating point — pick a representative ~0.90 recall row from C.
    lines.append("## Routing economics — cost vs realised-yield (best learned set)")
    lines.append("")
    lines.append("At the operating point, `routed_fraction` is the share of docs sent to expensive")
    lines.append("deep extraction; `yield_recall` is the share of truly-yielding docs captured;")
    lines.append("`precision` is the share of routed docs that actually yield.")
    lines.append("")
    best_set = "C" if c_auc >= b_auc else "B"
    curve = results["cost_yield_curves"].get(best_set, [])
    lines.append(f"Curve for set **{best_set}** (GBM OOF):")
    lines.append("")
    lines.append("| Threshold | Routed frac | Yield recall | Precision |")
    lines.append("|---:|---:|---:|---:|")
    for pt in curve:
        lines.append(
            f"| {pt['threshold']:.2f} | {pt['routed_fraction']:.3f} | "
            f"{pt['yield_recall']:.3f} | {pt['precision']:.3f} |"
        )
    lines.append("")
    # Highlight the threshold that captures ~95% recall and its cost.
    target = next((p for p in curve if p["yield_recall"] <= 0.95 and p["yield_recall"] > 0), None)
    if target:
        lines.append(
            f"At ~{target['yield_recall']*100:.0f}% yield-recall the router sends only "
            f"**{target['routed_fraction']*100:.0f}%** of docs to deep extraction — the "
            f"cost saving that justifies the router (vs routing 100% blindly)."
        )
        lines.append("")

    # Feature importance for the GBM (set A, the interpretable hand-feature model).
    a_gbm = next((m for m in models if m["feature_set"] == "A" and m["model"] == "gbm"), None)
    if a_gbm and a_gbm.get("feature_importance"):
        lines.append("## GBM feature importance — set A (hand features)")
        lines.append("")
        lines.append("| Feature | Normalised importance |")
        lines.append("|---|---:|")
        for k, v in sorted(a_gbm["feature_importance"].items(), key=lambda kv: -kv[1]):
            lines.append(f"| {k} | {v:.4f} |")
        lines.append("")
    c_gbm = next((m for m in models if m["feature_set"] == "C" and m["model"] == "gbm"), None)
    if c_gbm and c_gbm.get("feature_importance"):
        lines.append("## GBM feature importance — set C (embedding + cheap structured)")
        lines.append("")
        lines.append("| Feature | Normalised importance |")
        lines.append("|---|---:|")
        for k, v in sorted(c_gbm["feature_importance"].items(), key=lambda kv: -kv[1]):
            lines.append(f"| {k} | {v:.4f} |")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_Generated by `scripts/eval/routing_classifier_train.py` (PLAN-0111 C-4/C-5)._")
    lines.append("")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════


def _detect_gbm_lib() -> str:
    """Return 'lightgbm' if importable, else 'hist_gbm' (sklearn fallback)."""
    import importlib.util

    return "lightgbm" if importlib.util.find_spec("lightgbm") is not None else "hist_gbm"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Routing classifier train + ablation harness (PLAN-0111 C-4/C-5)")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=_REPO_ROOT / "results" / "routing_dataset" / "routing_dataset.csv",
        help="Path to the C-3 (or C-3b augmented) routing_dataset.csv",
    )
    parser.add_argument("--dims", type=int, default=768, choices=[768, 512, 256, 128], help="MRL embedding dims")
    parser.add_argument(
        "--results-json",
        type=Path,
        default=_REPO_ROOT / "results" / "routing_dataset" / "ablation_results.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=_REPO_ROOT / "docs" / "audits" / "2026-06-12-routing-classifier-ablation.md",
    )
    args = parser.parse_args(argv)

    dataset_path: Path = args.dataset
    if not dataset_path.exists():
        raise SystemExit(f"dataset not found: {dataset_path}")

    print(f"[load] {dataset_path}", flush=True)
    df = pd.read_csv(dataset_path)
    df = df.reset_index(drop=True)
    print(f"[load] {len(df)} rows, positive rate {df[LABEL_COLUMN].mean():.4f}", flush=True)

    print(f"[embed] dims={args.dims}", flush=True)
    embeddings = get_embeddings(df, dataset_path, args.dims)
    print(f"[embed] matrix {embeddings.shape}", flush=True)

    gbm_lib = _detect_gbm_lib()
    print(f"[ablation] gbm_lib={gbm_lib}", flush=True)
    results = run_ablation(df, embeddings, gbm_lib, args.dims)

    args.results_json.parent.mkdir(parents=True, exist_ok=True)
    args.results_json.write_text(json.dumps(results, indent=2))
    print(f"[write] {args.results_json}", flush=True)

    report = render_report(results, dataset_path)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report)
    print(f"[write] {args.report}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
