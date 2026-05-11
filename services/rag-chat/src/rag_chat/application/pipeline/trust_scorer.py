"""Multi-factor trust scorer replacing flat DEFAULT_TRUST_WEIGHTS (PLAN-0079 Wave A)."""

from __future__ import annotations

import math

import structlog

from contracts.trust import SOURCE_AUTHORITY  # type: ignore[import-untyped]

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Default corroboration factor when evidence_count not available (MVP decision — PLAN-0079 §0).
_DEFAULT_CORROBORATION = 0.5


class TrustScorer:
    """Stateless value object computing per-item trust weight.

    Formula (PLAN-0079 §1):
        trust = w_source * source_authority(source_type)
              + w_corroboration * corroboration_factor
              + w_extraction * extraction_confidence_factor

    The formula is ADDITIVE (not multiplicative across all factors) to avoid
    numerical collapse. With default weights (w_source=0.4, w_corroboration=0.1,
    w_extraction=0.1), a sec_10k item yields:
        0.4*1.0 + 0.1*0.5 + 0.1*0.5 = 0.50 — numerically stable and compatible
    with the existing fusion_score = score * recency_score * trust_weight invariant.

    Recency is NOT included here — it is handled by the existing ``recency_score``
    field on ``RetrievedItem`` (computed by compute_recency_score, PLAN-0063 W5-4).
    The existing fusion_score invariant score*recency_score*trust_weight is preserved.

    Args:
        w_source: Weight for source authority factor (default 0.4).
        w_corroboration: Weight for corroboration factor (default 0.1).
        w_extraction: Weight for extraction confidence factor (default 0.1).
    """

    def __init__(
        self,
        w_source: float = 0.4,
        w_corroboration: float = 0.1,
        w_extraction: float = 0.1,
    ) -> None:
        self._w_source = w_source
        self._w_corroboration = w_corroboration
        self._w_extraction = w_extraction

    def score(
        self,
        source_type: str | None,
        extraction_confidence: float | None = None,
        evidence_count: int = 0,
    ) -> float:
        """Compute composite trust weight for a retrieved item.

        Args:
            source_type: Source type string (e.g. 'sec_10k', 'eodhd_news').
            extraction_confidence: Extraction confidence [0,1] when known.
                Falls back to 0.5 when None (neutral proxy).
            evidence_count: Number of independent sources corroborating this item.
                MVP: defaults to 0 → uses _DEFAULT_CORROBORATION = 0.5.

        Returns:
            Trust weight in [0, 1].
        """
        source_auth: float = SOURCE_AUTHORITY.get(source_type or "default", SOURCE_AUTHORITY["default"])
        corr_factor = self._corroboration_factor(evidence_count)
        extr_factor = extraction_confidence if extraction_confidence is not None else 0.5

        trust: float = (
            self._w_source * source_auth + self._w_corroboration * corr_factor + self._w_extraction * extr_factor
        )

        log.debug(
            "trust_scorer.score",
            source_type=source_type,
            source_auth=source_auth,
            corr_factor=corr_factor,
            extr_factor=extr_factor,
            trust=trust,
        )
        return min(1.0, max(0.0, trust))

    @staticmethod
    def _corroboration_factor(evidence_count: int) -> float:
        """1 - exp(-evidence_count/3); saturates ~0.95 at 10+; default 0.5 when count=0."""
        if evidence_count == 0:
            return _DEFAULT_CORROBORATION
        return 1.0 - math.exp(-evidence_count / 3.0)
