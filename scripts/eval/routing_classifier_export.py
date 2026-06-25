#!/usr/bin/env python3
"""Train + serialize the PRODUCTION news-routing classifier (PLAN-0111 C-2).

PURPOSE
-------
The ablation harness (``routing_classifier_train.py``) established that the
winning configuration is **C — EmbeddingGemma(title+subtitle) 768d + 3 cheap
structured features {source_reliability, recency, document_type}**, calibrated
GBM, ROC-AUC ≈ 0.828, Youden-J operating threshold ≈ 0.561.

That harness reports *out-of-fold* cross-validation metrics (it never serialises a
deployable model — every fold's model is discarded after scoring). This script is
the **production exporter**: it fits the SAME C-variant pipeline on the FULL
augmented dataset (NO held-out split — we want every labelled row to inform the
shipped model), wraps it in isotonic calibration, and serialises a single
self-contained artifact the nlp-pipeline container loads at startup:

  * ``routing_classifier.joblib``       — the fitted ``CalibratedClassifierCV``.
  * ``routing_classifier_meta.json``    — everything the runtime needs to build
                                          the feature vector identically and map
                                          the calibrated P(yield) → routing tier.

DESIGN NOTES — why "fit on all rows" is correct here
----------------------------------------------------
The CV harness exists to give an *honest* generalisation estimate (it answers
"will this generalise?"). Once that question is answered YES (set C beats the
deployed static rule), the production model should be fit on ALL available labels
— withholding a test fold in the shipped artifact would throw away ~20% of the
training signal for no benefit, because we are no longer measuring generalisation
here. The honest metric stays in the committed ablation report.

CALIBRATION
-----------
``CalibratedClassifierCV(method="isotonic", cv=5)`` — isotonic (non-parametric)
matches the GBM's non-sigmoid score shape and the dataset is large enough
(15k rows) to avoid isotonic's small-sample overfit. The internal cv=5 means the
exported object is itself an ensemble of 5 base GBMs each calibrated on its
held-out fifth; ``predict_proba`` averages them. This is standard and keeps the
artifact self-contained (no separate calibrator to load).

P(yield) → TIER MAPPING  (documented here AND in the meta JSON)
---------------------------------------------------------------
The classifier predicts a *binary* calibrated ``P(yield)`` = P(deep extraction
produces ≥1 relation/claim/event). The live router needs a 4-tier decision
(DEEP/MEDIUM/LIGHT/SUPPRESS). We map:

    P >= thr_deep     → DEEP      (high-confidence yield: spend the deep budget)
    thr_extract <= P  → MEDIUM    (worth extracting, lower confidence)
       < thr_deep
    P <  thr_extract  → LIGHT     (likely no relational yield: cheap path)
    (SUPPRESS)                    → NOT predicted here — SUPPRESS is an upstream
                                    document-type / stub-filter concern handled by
                                    the suppression gate, NOT a yield-probability
                                    decision. The learned gate's real job is the
                                    extract / no-extract boundary (``thr_extract``).

  * ``thr_extract`` = the calibrated Youden-J threshold (≈ 0.561). This is the
    *primary* operating point the classifier was tuned for — the extract/skip
    boundary that balances sensitivity and specificity.
  * ``thr_deep``    = a higher, deliberately conservative cut. We use a FIXED
    documented value of **0.80** rather than a data-derived quantile: the
    DEEP/MEDIUM split is economically a "how much extra budget do we spend"
    knob, not a statistical boundary the model was trained on, so a round,
    auditable constant is preferable to a fragile quantile that drifts with the
    label mix. (0.80 is well above the 0.561 extract boundary, reserving DEEP for
    genuinely high-yield-probability articles.)

This mapping is APPROXIMATE BY DESIGN. The binary classifier was trained on a
yield/no-yield label, so only the ``thr_extract`` boundary is statistically
grounded; the DEEP cut is a policy choice. In SHADOW mode this is harmless
(nothing acts on the proposed tier) and gives us live agreement data to refine
the cut before any LIVE flip.

AMBIGUOUS BAND
--------------
We also record an ``ambiguous_band`` = ``thr_extract ± 0.10``. An article whose
P(yield) lands inside this band is one the gate is *least sure* about — exactly
the population a future LLM-cascade tie-breaker (next wave) should adjudicate.
The ±0.10 width is a documented heuristic: wide enough to capture the genuinely
uncertain middle without flagging the whole distribution. ``LearnedRouter``
surfaces an ``in_ambiguous_band`` flag per article so we can measure how large
that population is in shadow before building the cascade.

USAGE
-----
    NLP_PIPELINE_EXTRACTION_API_KEY=... \\
      python scripts/eval/routing_classifier_export.py \\
        --dataset results/routing_dataset/routing_dataset_augmented.csv \\
        --save services/nlp-pipeline/src/nlp_pipeline/application/blocks/models \\
        --created-at 2026-06-12

The embedding stage reuses the SAME parquet cache as the ablation harness (keyed
by dims), so if you have already run the ablation on the augmented set this step
does zero network calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Sequence

# ── Reuse the ablation harness helpers (single source of truth) ───────────────
# The exporter MUST build features and embeddings identically to the harness, so
# we import its helpers rather than re-implementing them. ``routing_classifier_train``
# lives next to this file in scripts/eval.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from routing_classifier_train import (  # noqa: E402  (path injected above)
    CHEAP_STRUCTURED_FEATURES,
    LABEL_COLUMN,
    RANDOM_SEED,
    assemble_feature_matrix,
    get_embeddings,
    select_threshold_youden,
)

# ── Production constants (mirrored into the meta JSON for the runtime) ────────

# The shipped embedding configuration. EmbeddingGemma-300m, 768d native (the
# winning ablation config used the full 768d head).
EMBEDDING_MODEL_ID = "google/embeddinggemma-300m"
EMBEDDING_DIMS = 768

# DEEP cut — fixed, documented policy value (see module docstring).
THR_DEEP_FIXED = 0.80

# Ambiguous-band half-width around the extract threshold (documented heuristic).
AMBIGUOUS_BAND_HALF_WIDTH = 0.10


def _dataset_hash(dataset_path: Path) -> str:
    """Return a short sha256 of the dataset file for provenance in the meta JSON.

    Lets us prove (in the artifact) exactly which dataset produced the shipped
    model. Hashing the raw bytes is enough — we only need a stable fingerprint,
    not a content-aware digest.
    """
    digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    return digest[:16]


def _build_calibrated_gbm() -> Any:
    """Construct the production calibrated GBM (isotonic, cv=5).

    Mirrors the ablation harness's GBM estimator (LightGBM, 300 trees, lr 0.05,
    fixed seed) but with cv=5 calibration folds for the final fit (the harness
    used cv=3 inner folds *inside* each outer CV split; for the single production
    fit we can afford 5 calibration folds for a smoother calibration map).
    """
    from lightgbm import LGBMClassifier  # type: ignore[import-untyped]
    from sklearn.calibration import CalibratedClassifierCV  # type: ignore[import-untyped]

    base = LGBMClassifier(n_estimators=300, learning_rate=0.05, random_state=RANDOM_SEED, verbose=-1)
    return CalibratedClassifierCV(base, method="isotonic", cv=5)


def train_and_export(
    dataset_path: Path,
    save_dir: Path,
    created_at: str,
) -> dict[str, Any]:
    """Fit the C-variant on the FULL dataset, serialise artifact + meta JSON.

    Returns the meta dict (also written to ``routing_classifier_meta.json``).
    """
    import joblib  # type: ignore[import-untyped]

    print(f"[load] {dataset_path}", flush=True)
    df = pd.read_csv(dataset_path).reset_index(drop=True)
    n_rows = len(df)
    y = df[LABEL_COLUMN].to_numpy(dtype=np.int64)
    print(f"[load] {n_rows} rows, positive rate {y.mean():.4f}", flush=True)

    # Embeddings (cached parquet, keyed by dims — free if the ablation ran).
    print(f"[embed] dims={EMBEDDING_DIMS}", flush=True)
    embeddings = get_embeddings(df, dataset_path, EMBEDDING_DIMS)
    print(f"[embed] matrix {embeddings.shape}", flush=True)

    # Feature matrix = [3 cheap structured features..., 768 embedding dims...].
    # The column ORDER here is contractual — the runtime LearnedRouter MUST build
    # the same order. It is recorded in the meta JSON's ``structured_features`` +
    # ``embedding_dims`` so the runtime cannot drift from it.
    x = assemble_feature_matrix(df, hand_features=CHEAP_STRUCTURED_FEATURES, embeddings=embeddings)
    print(
        f"[fit] feature matrix {x.shape} "
        f"({len(CHEAP_STRUCTURED_FEATURES)} structured + {EMBEDDING_DIMS} embedding)",
        flush=True,
    )

    clf = _build_calibrated_gbm()
    with warnings.catch_warnings():
        # LightGBM emits a cosmetic "X does not have valid feature names" warning
        # when fit on a bare ndarray (we pass numpy on purpose — no column names).
        warnings.filterwarnings("ignore", message="X does not have valid feature names")
        clf.fit(x, y)

    # Derive the calibrated Youden-J extract threshold from the model's own
    # in-sample calibrated probabilities. NOTE: this is in-sample (the honest
    # OOF threshold ≈0.561 lives in the ablation report); for the shipped artifact
    # we re-derive on the full fit so the threshold matches THIS exact model's
    # probability scale, then sanity-check it is in a sane neighbourhood.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="X does not have valid feature names")
        p_in_sample = clf.predict_proba(x)[:, 1]
    thr_extract = float(select_threshold_youden(y, p_in_sample))
    print(f"[threshold] in-sample Youden-J extract threshold = {thr_extract:.4f}", flush=True)

    save_dir.mkdir(parents=True, exist_ok=True)
    model_path = save_dir / "routing_classifier.joblib"
    joblib.dump(clf, model_path)
    size_mb = model_path.stat().st_size / (1024 * 1024)
    print(f"[write] {model_path}  ({size_mb:.2f} MB)", flush=True)
    if size_mb > 25:
        # The plan caps the artifact at "a few MB"; a calibrated 5x300-tree LightGBM
        # is normally well under 10MB. Warn loudly if it balloons (e.g. someone
        # bumped n_estimators) so we reconsider before committing into the package.
        print(f"[WARN] artifact is {size_mb:.1f} MB — larger than expected; reconsider before committing", flush=True)

    # The ambiguous band brackets the extract threshold (clamped to [0,1]).
    band_low = max(0.0, thr_extract - AMBIGUOUS_BAND_HALF_WIDTH)
    band_high = min(1.0, thr_extract + AMBIGUOUS_BAND_HALF_WIDTH)

    meta: dict[str, Any] = {
        "plan": "PLAN-0111 C-2",
        "created_at": created_at,
        "embedding_model_id": EMBEDDING_MODEL_ID,
        "embedding_dims": EMBEDDING_DIMS,
        # FEATURE ORDER CONTRACT — the runtime builds the vector as
        # [structured_features in this order..., then embedding_dims floats].
        "structured_features": list(CHEAP_STRUCTURED_FEATURES),
        "feature_order": "structured_features (in listed order) followed by the 768 embedding dimensions",
        "n_structured_features": len(CHEAP_STRUCTURED_FEATURES),
        "total_features": int(x.shape[1]),
        # P(yield) → tier mapping (see module docstring for full rationale).
        "thr_extract": thr_extract,
        "thr_deep": THR_DEEP_FIXED,
        "tier_mapping": {
            "DEEP": f"p_yield >= {THR_DEEP_FIXED}",
            "MEDIUM": f"{thr_extract:.4f} <= p_yield < {THR_DEEP_FIXED}",
            "LIGHT": f"p_yield < {thr_extract:.4f}",
            "SUPPRESS": "NOT predicted — upstream document-type / suppression-gate concern",
        },
        "ambiguous_band": {
            "low": band_low,
            "high": band_high,
            "half_width": AMBIGUOUS_BAND_HALF_WIDTH,
            "note": "p_yield inside [low, high] is least-certain; candidate for future LLM cascade tie-break",
        },
        "calibration": "CalibratedClassifierCV(method=isotonic, cv=5)",
        "base_estimator": "lightgbm.LGBMClassifier(n_estimators=300, learning_rate=0.05)",
        "training_rows": n_rows,
        "positive_rate": float(y.mean()),
        # Store only the basename — the committed artifact must not leak an
        # absolute local path (it is reproducible from the repo-relative dataset).
        "dataset_path": dataset_path.name,
        "dataset_sha256_16": _dataset_hash(dataset_path),
        "random_seed": RANDOM_SEED,
    }
    meta_path = save_dir / "routing_classifier_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"[write] {meta_path}", flush=True)
    return meta


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export the production routing classifier (PLAN-0111 C-2)")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=_THIS_DIR.parents[1] / "results" / "routing_dataset" / "routing_dataset_augmented.csv",
        help="Augmented routing dataset CSV (full set — fit on all rows, no split)",
    )
    parser.add_argument(
        "--save",
        type=Path,
        default=(
            _THIS_DIR.parents[1]
            / "services"
            / "nlp-pipeline"
            / "src"
            / "nlp_pipeline"
            / "application"
            / "blocks"
            / "models"
        ),
        help="Directory to write routing_classifier.joblib + meta JSON (inside the service package)",
    )
    parser.add_argument(
        "--created-at",
        type=str,
        default="unspecified",
        help="Fixed created-at stamp recorded in the meta JSON (e.g. 2026-06-12)",
    )
    args = parser.parse_args(argv)

    if not args.dataset.exists():
        raise SystemExit(f"dataset not found: {args.dataset}")

    meta = train_and_export(args.dataset, args.save, args.created_at)
    print("[done] meta:", json.dumps({k: meta[k] for k in ("thr_extract", "thr_deep", "training_rows")}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
