"""Learned routing classifier — SHADOW-mode inference (PLAN-0111 C-2 / C-6).

WHAT THIS IS
------------
The deployed router (``blocks/routing.py``) is a static *weighted sum* over 5
hand-engineered signals. PLAN-0111 Sub-Plan C trained a small calibrated
classifier that predicts ``P(yield)`` — the probability that deep extraction of
an article produces at least one relation / claim / event — directly from an
**EmbeddingGemma-300m embedding of the headline** plus 3 cheap structured
features. The ablation (``scripts/eval/routing_classifier_train.py``) showed this
"set C" model meaningfully out-performs the deployed static rule.

This module is the *runtime inference* component for that model. In this wave it
runs ONLY in SHADOW mode: it computes a *proposed* tier for every article that
is logged, counted, and persisted, but it **never** changes which processing path
the article actually takes (the static router still controls that). Flipping it
to LIVE and adding the LLM cascade tie-breaker are the NEXT wave — deliberately
out of scope here.

ARTIFACT
--------
``LearnedRouter`` loads, once at construction:
  * ``models/routing_classifier.joblib`` — a fitted ``CalibratedClassifierCV``
    (isotonic-calibrated LightGBM) producing a calibrated ``P(yield)``.
  * ``models/routing_classifier_meta.json`` — the feature-order contract,
    embedding model id + dims, and the P(yield)→tier thresholds.

Both are produced by ``scripts/eval/routing_classifier_export.py`` and committed
into the package so the container loads them at startup with no network/download.

FEATURE VECTOR CONTRACT
-----------------------
The exporter fit on ``[structured_features..., embedding_dims...]`` in the EXACT
order recorded in the meta JSON. ``propose`` rebuilds that same order:
``[source_reliability, recency, document_type] + embed(title + "\\n" + subtitle)``.
Any drift here silently corrupts predictions, so the order is read from the meta
(not hard-coded) and asserted against the model's expected feature count.

FAILURE POLICY (shadow must never break the pipeline)
-----------------------------------------------------
The embedding call is a network round-trip to DeepInfra; it can fail or time out.
Because this is a SHADOW observer, a failure must NEVER fail the article. Every
public path is best-effort: ``propose`` catches embedding/inference errors, logs a
warning, and returns ``None``. The caller treats ``None`` as "no shadow proposal
this time" and proceeds with the static router unchanged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from nlp_pipeline.domain.enums import RoutingTier

if TYPE_CHECKING:
    from ml_clients.adapters.embeddinggemma_router import EmbeddingGemmaRouterAdapter

logger = structlog.get_logger()

# Artifact location — co-located with this module inside the package so it ships
# in the container image (see Dockerfile COPY of src/ + pyproject artifacts glob).
_MODELS_DIR = Path(__file__).resolve().parent / "models"
_MODEL_PATH = _MODELS_DIR / "routing_classifier.joblib"
_META_PATH = _MODELS_DIR / "routing_classifier_meta.json"


@dataclass(frozen=True)
class LearnedRoutingResult:
    """Pure-domain result of one shadow routing proposal.

    Deliberately framework-free (no sklearn / numpy types leak out): the caller
    only needs the calibrated probability, the mapped tier, and whether the
    article sits in the ambiguous band the future LLM cascade will adjudicate.
    """

    p_yield: float
    proposed_tier: RoutingTier
    in_ambiguous_band: bool


def map_p_yield_to_tier(p_yield: float, thr_extract: float, thr_deep: float) -> RoutingTier:
    """Map a calibrated P(yield) to a routing tier (PLAN-0111 C-2 mapping).

    See ``routing_classifier_export.py`` for the full rationale. In short:
      * ``p >= thr_deep``                → DEEP   (high-confidence yield)
      * ``thr_extract <= p < thr_deep``  → MEDIUM (worth extracting)
      * ``p < thr_extract``              → LIGHT  (likely no relational yield)

    SUPPRESS is intentionally never produced here — it is an upstream
    document-type / stub-filter concern handled by the suppression gate, not a
    yield-probability decision. The binary classifier was trained on a
    yield/no-yield label, so only the ``thr_extract`` boundary is statistically
    grounded; the DEEP cut is a documented policy value. This is fine in shadow
    mode (nothing acts on the tier) and gives us live agreement data to refine.
    """
    if p_yield >= thr_deep:
        return RoutingTier.DEEP
    if p_yield >= thr_extract:
        return RoutingTier.MEDIUM
    return RoutingTier.LIGHT


class LearnedRouter:
    """Loads the calibrated classifier once and proposes tiers in shadow mode.

    Args:
        embedder: the EmbeddingGemma adapter (injected — it already holds the
                  DeepInfra key + httpx pool). The router never constructs it so
                  the network client lifecycle stays owned by the consumer wiring.
        model_path / meta_path: overridable for tests; default to the committed
                  artifact next to this module.

    Raises at construction if the artifact is missing or the meta is malformed —
    we want a LOUD startup failure (visible in container logs) rather than a
    silently-degraded router. The construction itself does no network I/O.
    """

    def __init__(
        self,
        embedder: EmbeddingGemmaRouterAdapter,
        *,
        model_path: Path = _MODEL_PATH,
        meta_path: Path = _META_PATH,
    ) -> None:
        import joblib  # type: ignore[import-untyped]  # local import: heavy, only on this path

        self._embedder = embedder
        # Load the calibrated classifier + the feature/threshold contract.
        self._model: Any = joblib.load(model_path)
        meta: dict[str, Any] = json.loads(meta_path.read_text())

        # The structured-feature ORDER is contractual (must match training).
        self._structured_features: list[str] = list(meta["structured_features"])
        self._embedding_dims: int = int(meta["embedding_dims"])
        self._thr_extract: float = float(meta["thr_extract"])
        self._thr_deep: float = float(meta["thr_deep"])
        band = meta["ambiguous_band"]
        self._band_low: float = float(band["low"])
        self._band_high: float = float(band["high"])
        self._total_features: int = int(meta["total_features"])

        logger.info(  # type: ignore[no-any-return]
            "learned_router_loaded",
            model_path=str(model_path),
            embedding_model_id=meta.get("embedding_model_id"),
            embedding_dims=self._embedding_dims,
            structured_features=self._structured_features,
            thr_extract=self._thr_extract,
            thr_deep=self._thr_deep,
            total_features=self._total_features,
            training_rows=meta.get("training_rows"),
            created_at=meta.get("created_at"),
        )

    async def propose(
        self,
        *,
        title: str | None,
        subtitle: str | None,
        structured_features: dict[str, float],
    ) -> LearnedRoutingResult | None:
        """Propose a routing tier for one article (best-effort, never raises).

        Builds the classifier text (``title + "\\n" + subtitle``), embeds it,
        concatenates the structured features in the trained order, runs
        ``predict_proba``, and maps the probability to a tier.

        Returns ``None`` (and logs a warning) on ANY failure — embedding network
        error, missing feature, dimension mismatch — so the shadow path can never
        break the pipeline.
        """
        try:
            text = self._build_text(title, subtitle)

            # One embedding call (a batch of size 1). Network round-trip — the
            # adapter wraps an explicit httpx.Timeout (BP-235) so it cannot hang.
            vectors = await self._embedder.embed_for_classification([text], dimensions=self._embedding_dims)
            if not vectors:
                logger.warning("learned_router_empty_embedding", title_len=len(text))  # type: ignore[no-any-return]
                return None
            embedding = vectors[0]
            if len(embedding) != self._embedding_dims:
                logger.warning(  # type: ignore[no-any-return]
                    "learned_router_dim_mismatch",
                    got=len(embedding),
                    expected=self._embedding_dims,
                )
                return None

            # Feature vector: structured features (in trained order) + embedding.
            # Missing structured features default to 0.0 — defensive, but every
            # caller supplies all three. We import numpy lazily (heavy module).
            import numpy as np

            structured = [float(structured_features.get(name, 0.0)) for name in self._structured_features]
            row = np.asarray([structured + list(embedding)], dtype=np.float64)
            if row.shape[1] != self._total_features:
                logger.warning(  # type: ignore[no-any-return]
                    "learned_router_feature_count_mismatch",
                    got=int(row.shape[1]),
                    expected=self._total_features,
                )
                return None

            # predict_proba returns [[p_no_yield, p_yield]]; we want the positive
            # (yield) class probability.
            p_yield = float(self._model.predict_proba(row)[0, 1])
            tier = map_p_yield_to_tier(p_yield, self._thr_extract, self._thr_deep)
            in_band = self._band_low <= p_yield <= self._band_high
            return LearnedRoutingResult(p_yield=p_yield, proposed_tier=tier, in_ambiguous_band=in_band)
        except Exception as exc:  # — shadow must never break the pipeline
            # Any failure (network, sklearn, malformed input) is swallowed: this
            # is a passive observer. Log once at warning so it is visible without
            # being alarming, then signal "no proposal" to the caller.
            logger.warning("learned_router_propose_failed", error=str(exc))  # type: ignore[no-any-return]
            return None

    @staticmethod
    def _build_text(title: str | None, subtitle: str | None) -> str:
        """Compose ``title + "\\n" + subtitle`` exactly as the exporter did.

        Mirrors ``routing_classifier_train.build_classifier_text``: None/empty
        parts are dropped so the embedder never receives a literal ``"None"``.
        """
        title_str = (title or "").strip()
        subtitle_str = (subtitle or "").strip()
        if title_str and subtitle_str:
            return f"{title_str}\n{subtitle_str}"
        return title_str or subtitle_str
