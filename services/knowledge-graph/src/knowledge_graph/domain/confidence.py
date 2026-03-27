"""4-step bounded confidence formula for knowledge-graph relations (PRD §10.1).

Formula overview
----------------
Given a list of evidence pieces (each with source_weight, source_type, source_name,
evidence_date) and a list of contradiction links (each with strength, detected_at),
compute:

    1. Support        = temporal-weighted average of source_weights
    2. Corroboration  = diversity bonus, capped at CORROBORATION_CAP (0.20)
    3. Contradiction  = top-K decayed link strengths, capped at CONTRADICTION_CAP (0.60)
    4. Final          = clamp(support + corroboration - contradiction, 0.0, 1.0)

Decay
-----
- RELATION_STATE evidence: decay_alpha from decay_class_config row
- TEMPORAL_CLAIM evidence: fixed alpha = 0.02310 (30-day half-life)

Domain layer — no DB imports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from knowledge_graph.domain.enums import SemanticMode
from knowledge_graph.domain.models import ConfidenceComponents

# Default formula constants (overridden by Settings in application layer)
_CORROBORATION_CAP: float = 0.20
_CONTRADICTION_CAP: float = 0.60
_TEMPORAL_CLAIM_ALPHA: float = 0.02310  # 30-day half-life
_CORROBORATION_GAIN_PER_SOURCE: float = 0.05
_CORROBORATION_MIN_TEMPORAL_WEIGHT: float = 0.1
_CONTRADICTION_TOP_K: int = 3


# ---------------------------------------------------------------------------
# Input value objects (pure, no DB dependency)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceInput:
    """Single evidence piece fed into the confidence formula."""

    source_weight: float  # from source_trust_weights
    source_type: str  # e.g. "sec_10k"
    source_name: str  # e.g. "Apple Inc."
    evidence_date: datetime


@dataclass(frozen=True)
class ContradictionInput:
    """Single contradiction link fed into the confidence formula."""

    strength: float
    detected_at: datetime


# ---------------------------------------------------------------------------
# Temporal decay helpers
# ---------------------------------------------------------------------------


def _days_since(ts: datetime, now: datetime) -> float:
    """Return elapsed days between *ts* and *now* (non-negative)."""
    delta = now - ts
    return max(0.0, delta.total_seconds() / 86400.0)


def _temporal_weight(days: float, alpha: float) -> float:
    """Exponential temporal decay: exp(-alpha * days)."""
    return math.exp(-alpha * days)


# ---------------------------------------------------------------------------
# Main formula
# ---------------------------------------------------------------------------


def compute_confidence(
    evidence: list[EvidenceInput],
    contradictions: list[ContradictionInput],
    decay_alpha: float,
    semantic_mode: SemanticMode,
    *,
    now: datetime | None = None,
    corroboration_cap: float = _CORROBORATION_CAP,
    contradiction_cap: float = _CONTRADICTION_CAP,
    temporal_claim_alpha: float = _TEMPORAL_CLAIM_ALPHA,
    corroboration_gain_per_source: float = _CORROBORATION_GAIN_PER_SOURCE,
    corroboration_min_temporal_weight: float = _CORROBORATION_MIN_TEMPORAL_WEIGHT,
    contradiction_top_k: int = _CONTRADICTION_TOP_K,
) -> ConfidenceComponents:
    """Compute the 4-step confidence formula for a relation.

    Parameters
    ----------
    evidence:
        All evidence pieces for the relation.
    contradictions:
        All active contradiction links for the relation.
    decay_alpha:
        The per-class decay_alpha from ``decay_class_config``.
        Used for RELATION_STATE; overridden by ``temporal_claim_alpha`` for
        TEMPORAL_CLAIM.
    semantic_mode:
        Whether this is a RELATION_STATE or TEMPORAL_CLAIM relation.
    now:
        Reference timestamp for decay calculations (defaults to UTC now).
    corroboration_cap:
        Maximum corroboration gain (default 0.20).
    contradiction_cap:
        Maximum contradiction penalty (default 0.60).
    temporal_claim_alpha:
        Fixed alpha for TEMPORAL_CLAIM evidence (default 0.02310).
    corroboration_gain_per_source:
        Gain added per distinct qualifying corroboration source (default 0.05).
    corroboration_min_temporal_weight:
        Minimum temporal weight for a source to count toward corroboration
        (default 0.1).
    contradiction_top_k:
        How many top-decayed contradiction links to sum (default 3).

    Returns
    -------
    :class:`ConfidenceComponents`
        Intermediate + final values.  Call ``.validate()`` to assert bounds.
    """
    if now is None:
        now = datetime.now(tz=UTC)

    # Pick the alpha used for evidence decay
    eff_alpha = temporal_claim_alpha if semantic_mode == SemanticMode.TEMPORAL_CLAIM else decay_alpha

    # ------------------------------------------------------------------
    # Step 1 — Support: temporal-weighted average of source_weights
    # Normalize by sum(temporal_weight), NOT count.
    # ------------------------------------------------------------------
    support = _compute_support(evidence, eff_alpha, now)

    # ------------------------------------------------------------------
    # Step 2 — Corroboration gain
    # Count distinct (source_type, source_name) pairs whose temporal
    # weight >= corroboration_min_temporal_weight.
    # ------------------------------------------------------------------
    corroboration = _compute_corroboration(
        evidence,
        eff_alpha,
        now,
        corroboration_min_temporal_weight,
        corroboration_gain_per_source,
        corroboration_cap,
    )

    # ------------------------------------------------------------------
    # Step 3 — Contradiction penalty
    # Decay each link's strength; sum top-K; cap at contradiction_cap.
    # Contradiction links use the relation's decay_alpha (not eff_alpha).
    # ------------------------------------------------------------------
    contradiction = _compute_contradiction(
        contradictions,
        decay_alpha,
        now,
        contradiction_top_k,
        contradiction_cap,
    )

    # ------------------------------------------------------------------
    # Step 4 - Final = clamp(support + corroboration - contradiction, 0, 1)
    # ------------------------------------------------------------------
    final = max(0.0, min(1.0, support + corroboration - contradiction))

    return ConfidenceComponents(
        support=support,
        corroboration=corroboration,
        contradiction=contradiction,
        final=final,
    )


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------


def _compute_support(
    evidence: list[EvidenceInput],
    alpha: float,
    now: datetime,
) -> float:
    """Step 1: temporal-weighted average of source weights.

    sum(w_i * source_weight_i) / sum(w_i)
    where w_i = exp(-alpha * days_since(evidence_date))
    """
    if not evidence:
        return 0.0

    weighted_sum = 0.0
    weight_total = 0.0
    for e in evidence:
        days = _days_since(e.evidence_date, now)
        w = _temporal_weight(days, alpha)
        weighted_sum += w * e.source_weight
        weight_total += w

    if weight_total < 1e-12:
        return 0.0

    # Clamp to [0, 1] — source weights are trust values in (0, 1]
    return min(1.0, max(0.0, weighted_sum / weight_total))


def _compute_corroboration(
    evidence: list[EvidenceInput],
    alpha: float,
    now: datetime,
    min_temporal_weight: float,
    gain_per_source: float,
    cap: float,
) -> float:
    """Step 2: diversity bonus from distinct qualifying sources."""
    qualifying_sources: set[tuple[str, str]] = set()
    for e in evidence:
        days = _days_since(e.evidence_date, now)
        w = _temporal_weight(days, alpha)
        if w >= min_temporal_weight:
            qualifying_sources.add((e.source_type, e.source_name))

    return min(cap, len(qualifying_sources) * gain_per_source)


def _compute_contradiction(
    contradictions: list[ContradictionInput],
    decay_alpha: float,
    now: datetime,
    top_k: int,
    cap: float,
) -> float:
    """Step 3: top-K temporally-decayed contradiction link strengths, capped."""
    if not contradictions:
        return 0.0

    decayed_strengths = []
    for c in contradictions:
        days = _days_since(c.detected_at, now)
        decayed = c.strength * _temporal_weight(days, decay_alpha)
        decayed_strengths.append(decayed)

    top_k_sum = sum(sorted(decayed_strengths, reverse=True)[:top_k])
    return min(cap, top_k_sum)
