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
- TEMPORAL_CLAIM evidence: decay_alpha from decay_class_config row

Domain layer — no DB imports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from knowledge_graph.domain.models import ConfidenceComponents

if TYPE_CHECKING:
    from knowledge_graph.domain.calibration import BetaCalibrator
    from knowledge_graph.domain.enums import SemanticMode

# Default formula constants (overridden by Settings in application layer)
_CORROBORATION_CAP: float = 0.20
_CONTRADICTION_CAP: float = 0.60
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
    # PLAN-0109 W1: the LLM's own confidence in this extraction. Folded into the
    # evidence mass in the Beta/subjective-logic backbone. Defaults to 1.0 so the
    # legacy v1 formula (which ignores it) is unaffected.
    extraction_confidence: float = 1.0
    # PLAN-0109 W4: syndication-cluster key (e.g. a hash of the normalised evidence
    # text). Evidence pieces sharing a key are reprints of the same story and count
    # ONCE in the support mass. ``None`` → the piece is treated as independent.
    dedup_key: str | None = None


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
    temporal_claim_alpha: float | None = None,
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
        Used for both RELATION_STATE and TEMPORAL_CLAIM.
    semantic_mode:
        Whether this is a RELATION_STATE or TEMPORAL_CLAIM relation.
    now:
        Reference timestamp for decay calculations (defaults to UTC now).
    corroboration_cap:
        Maximum corroboration gain (default 0.20).
    contradiction_cap:
        Maximum contradiction penalty (default 0.60).
    temporal_claim_alpha:
        Backward-compatible parameter retained for callers. Ignored.
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

    # Use registry-provided decay_alpha for all semantic modes.
    eff_alpha = decay_alpha
    _ = temporal_claim_alpha

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


# ---------------------------------------------------------------------------
# PLAN-0109 W1 — Beta / subjective-logic confidence backbone (v2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BetaConfidence:
    """Result of the Beta / subjective-logic confidence backbone.

    ``final``       — projected probability (posterior mean), in [0, 1].
    ``uncertainty`` — subjective-logic uncertainty mass ``u`` in [0, 1]; shrinks
                      as more (fresher, more-trusted) evidence accumulates. This
                      is the thin-node signal the old additive formula lacked.
    ``support_mass`` / ``contradiction_mass`` — accumulated R / S (diagnostics).
    """

    final: float
    uncertainty: float
    support_mass: float
    contradiction_mass: float


def _is_signal(semantic_mode: SemanticMode) -> bool:
    """True for TEMPORAL_CLAIM (signal) facts; False for RELATION_STATE (stateful)."""
    return str(getattr(semantic_mode, "value", semantic_mode)).upper() == "TEMPORAL_CLAIM"


def compute_confidence_beta(
    evidence: list[EvidenceInput],
    contradictions: list[ContradictionInput],
    decay_alpha: float,
    semantic_mode: SemanticMode,
    base_confidence: float,
    *,
    now: datetime | None = None,
    prior_strength: float = 2.0,
    signal_decay_floor: float = 0.1,
    valid_to: datetime | None = None,
    calibrator: BetaCalibrator | None = None,
) -> BetaConfidence:
    """Compute relation confidence as a Beta / subjective-logic posterior (PLAN-0109).

    Accumulate a decay-weighted, source-trust-weighted *evidence mass*::

        m_g = d_g * source_trust_g * extraction_conf_g          (per evidence g)
        R   = sum(m_g)  (support)      S = sum(decayed contradiction strengths)
        a0, b0 = kappa * prior , kappa * (1 - prior)            (prior pseudo-counts)
        final = (a0 + R) / (a0 + b0 + R + S)                    (posterior mean)
        u     = (a0 + b0) / (a0 + b0 + R + S)                   (uncertainty)

    Per-semantic-mode decay floor (PLAN-0109):
    - RELATION_STATE (stateful): prior = ``base_confidence``; evidence does NOT
      decay (``d_g = 1``) — the fact holds at full strength while valid. Once its
      validity window closes (``valid_to`` is set and ``now > valid_to``) it has
      expired: evidence mass steps to zero and it drops to ``signal_decay_floor``
      (PLAN-0109 W3 bitemporal step decay).
    - TEMPORAL_CLAIM (signal): prior = ``signal_decay_floor`` (low); evidence
      decays absolutely (``d_g = exp(-alpha*age)``) so confidence relaxes to the floor.

    Unlike the v1 additive formula, decay multiplies each mass (it does not cancel
    in a normalised average), independent corroboration has natural diminishing
    returns (no 0.20 cap), and the predicate prior + per-evidence extraction
    confidence + graded source trust all enter the score.
    """
    if now is None:
        now = datetime.now(tz=UTC)

    is_signal = _is_signal(semantic_mode)
    # PLAN-0109 W3: a stateful fact whose validity window has closed
    # (now > valid_to) is no longer true — step its evidence mass to zero so it
    # drops to the low floor (a former CEO is not "still the CEO").
    expired = (not is_signal) and valid_to is not None and now > valid_to

    prior_belief = signal_decay_floor if (is_signal or expired) else base_confidence
    prior_belief = min(0.999, max(0.001, prior_belief))
    a0 = prior_strength * prior_belief
    b0 = prior_strength * (1.0 - prior_belief)

    # PLAN-0109 W4: cluster syndicated reprints. Evidence sharing a ``dedup_key``
    # (identical normalised text — the same wire story republished by many outlets)
    # contributes ONCE, at the cluster's best (highest-mass) member, so corroboration
    # reflects INDEPENDENT sources rather than copy count. Keyless pieces are
    # independent and summed individually.
    support_mass = 0.0
    cluster_best: dict[str, float] = {}
    for e in evidence:
        if expired:
            d = 0.0  # validity window closed — no surviving evidence mass (step)
        elif is_signal:
            d = _temporal_weight(_days_since(e.evidence_date, now), decay_alpha)
        else:
            d = 1.0  # stateful holds at full strength while valid
        st = min(1.0, max(0.0, e.source_weight))
        ec = min(1.0, max(0.0, e.extraction_confidence))
        mass = d * st * ec
        if e.dedup_key is None:
            support_mass += mass
        else:
            cluster_best[e.dedup_key] = max(cluster_best.get(e.dedup_key, 0.0), mass)
    support_mass += sum(cluster_best.values())

    contradiction_mass = 0.0
    for c in contradictions:
        d = _temporal_weight(_days_since(c.detected_at, now), decay_alpha)
        contradiction_mass += min(1.0, max(0.0, c.strength)) * d

    total = a0 + b0 + support_mass + contradiction_mass
    if total < 1e-12:
        return BetaConfidence(prior_belief, 1.0, 0.0, 0.0)

    final = min(1.0, max(0.0, (a0 + support_mass) / total))
    uncertainty = (a0 + b0) / total
    # PLAN-0109 W6: map the raw posterior to a calibrated P(true). No-op (identity)
    # until an operator supplies fitted Beta-calibration parameters.
    if calibrator is not None:
        final = calibrator.apply(final)
    return BetaConfidence(
        final=final,
        uncertainty=uncertainty,
        support_mass=support_mass,
        contradiction_mass=contradiction_mass,
    )
