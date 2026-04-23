"""Block 5 — Document Routing Score (PRD §6.7 Block 5).

8-signal weighted formula. Weights sum to exactly 1.0 (module-level assertion).
Watchlist signal sourced from Valkey SET maintained by the watchlist consumer.
price_impact signal sourced from article_price_impacts table (PRD-0020 §6.5).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import UUID

from nlp_pipeline.domain.enums import MentionClass, RoutingTier
from nlp_pipeline.domain.models import EntityMention, RoutingDecision

# ── Signal weights (PRD §6.7 Block 5 / PRD-0020 §6.5 rebalance) ─────────────

SIGNAL_WEIGHTS: dict[str, float] = {
    "entity_density": 0.25,
    "source_reliability": 0.20,
    "novelty": 0.15,
    "recency": 0.10,
    "watchlist": 0.10,
    "document_type": 0.05,
    "extraction_yield": 0.05,
    "price_impact": 0.10,
}

# Module-level assertion: weights must sum to exactly 1.0
assert (
    abs(sum(SIGNAL_WEIGHTS.values()) - 1.0) < 1e-9
), f"Signal weights must sum to 1.0, got {sum(SIGNAL_WEIGHTS.values())}"

# ── Tier thresholds (PRD §6.7 Block 5) ───────────────────────────────────────

TIER_DEEP: float = 0.70
TIER_MEDIUM: float = 0.45
TIER_LIGHT: float = 0.20

# ── Document-type signal map (PRD §6.7 Block 5) ──────────────────────────────

DOCUMENT_TYPE_SIGNAL: dict[str, float] = {
    "sec_8k": 0.95,
    "sec_10k": 0.90,
    "sec_10q": 0.90,
    "sec_def14a": 0.88,
    "earnings_call": 0.80,
    "analyst_report": 0.80,
    "press_release": 0.70,
    "eodhd_news": 0.55,
    "finnhub_news": 0.55,
    "newsapi_news": 0.55,
    "manual": 0.50,
}
_DEFAULT_DOCUMENT_TYPE_SIGNAL: float = 0.50

# ── Signal computation helpers ────────────────────────────────────────────────


def _entity_density_signal(mentions: list[EntityMention]) -> float:
    """min(1.0, org+financial_institution count / 15)."""
    org_fi_classes = {MentionClass.ORGANIZATION, MentionClass.FINANCIAL_INSTITUTION}
    count = sum(1 for m in mentions if m.mention_class in org_fi_classes)
    return min(1.0, count / 15.0)


def _recency_signal(published_at: datetime | None, extracted_at: datetime) -> float:
    """exp(-0.02 * hours_since_published) — half-life ~35h."""
    reference = published_at or extracted_at
    now = datetime.now(tz=UTC)
    # Ensure reference is timezone-aware
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    hours = max(0.0, (now - reference).total_seconds() / 3600.0)
    return math.exp(-0.02 * hours)


def _watchlist_signal(mentions: list[EntityMention], watched_entity_ids: frozenset[UUID]) -> float:
    """min(1.0, watchlist_overlap_count / 3).

    Checks resolved entity_ids against watched_entity_ids set.
    Best-effort: if Valkey is unavailable, caller passes an empty frozenset → 0.0.
    """
    if not watched_entity_ids:
        return 0.0
    overlap = sum(
        1 for m in mentions if m.resolved_entity_id is not None and m.resolved_entity_id in watched_entity_ids
    )
    return min(1.0, overlap / 3.0)


def _extraction_yield_signal(mention_count: int, section_count: int) -> float:
    """0.6 * min(1.0, mentions/20) + 0.4 * min(1.0, sections/8)."""
    return 0.6 * min(1.0, mention_count / 20.0) + 0.4 * min(1.0, section_count / 8.0)


def _assign_tier(score: float) -> RoutingTier:
    """Assign routing tier from composite score (PRD §6.7 Block 5)."""
    if score >= TIER_DEEP:
        return RoutingTier.DEEP
    if score >= TIER_MEDIUM:
        return RoutingTier.MEDIUM
    if score >= TIER_LIGHT:
        return RoutingTier.LIGHT
    return RoutingTier.SUPPRESS


# ── Main block entry point ────────────────────────────────────────────────────


def compute_routing_score(
    doc_id: UUID,
    decision_id: UUID,
    source_type: str,
    published_at: datetime | None,
    extracted_at: datetime,
    mentions: list[EntityMention],
    section_count: int,
    *,
    source_trust_weight: float,
    novelty_score: float,
    watched_entity_ids: frozenset[UUID],
    price_impact_score: float = 0.0,
) -> RoutingDecision:
    """Compute the 8-signal routing score and assign a RoutingTier.

    Args:
        doc_id: Document being routed.
        decision_id: Pre-generated UUID for the routing decision row.
        source_type: Content source type string.
        published_at: Original publication datetime (UTC).
        extracted_at: Extraction datetime (UTC).
        mentions: Entity mentions from Block 4.
        section_count: Number of sections from Block 3.
        source_trust_weight: From intelligence_db.source_trust_weights.
        novelty_score: Stage 1 novelty output [0, 1].
        watched_entity_ids: Resolved entity IDs currently on any watchlist.
        price_impact_score: Normalised price-impact score [0, 1] from
            article_price_impacts table. Defaults to 0.0 for articles not
            yet labelled (< 25h old) or when lookup fails (best-effort).

    Returns:
        RoutingDecision with composite_score, feature_scores, and routing_tier.
    """
    feature_scores: dict[str, float] = {
        "entity_density": _entity_density_signal(mentions),
        "source_reliability": source_trust_weight,
        "novelty": novelty_score,
        "recency": _recency_signal(published_at, extracted_at),
        "watchlist": _watchlist_signal(mentions, watched_entity_ids),
        "document_type": DOCUMENT_TYPE_SIGNAL.get(source_type, _DEFAULT_DOCUMENT_TYPE_SIGNAL),
        "extraction_yield": _extraction_yield_signal(len(mentions), section_count),
        "price_impact": max(0.0, min(1.0, price_impact_score)),
    }

    composite = sum(SIGNAL_WEIGHTS[signal] * value for signal, value in feature_scores.items())
    # Clamp to [0, 1] for safety
    composite = max(0.0, min(1.0, composite))

    tier = _assign_tier(composite)

    return RoutingDecision(
        decision_id=decision_id,
        doc_id=doc_id,
        routing_tier=tier,
        composite_score=composite,
        feature_scores=feature_scores,
    )
