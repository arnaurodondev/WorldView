"""Block 5 — Document Routing Score (PRD §6.7 Block 5, PLAN-0093 C-1 v2).

Routing signal v2 (PLAN-0093 Sub-Plan C, Wave C-1, 2026-05-23)
==============================================================

Originally a weighted formula over 8 signals. Audit 2026-05-23 (F-NPL-003/004/006,
F-NPL-ROUTING-001) confirmed that 3 of those 8 signals are permanently zero in the
current single-pass routing architecture:

  1. ``watchlist`` — checks ``m.resolved_entity_id``, but ``compute_routing_score``
     runs BEFORE entity resolution. ``resolved_entity_id`` is always ``None``.
  2. ``novelty`` — hardcoded to ``1.0`` at the call site (article_consumer.py:575)
     because MinHash novelty runs AFTER routing, not before it.
  3. ``price_impact`` — derived from ``article_impact_windows`` which is empty
     (F-NPL-FUNDAMENTALS-001 — market-data symbol resolver broken; PLAN-0093 C-3
     re-enables this signal once data starts flowing).

To restore these signals we would need to implement two-pass routing (route →
resolve → re-route) which is a substantial architecture change. PLAN-0093 defers
that to a follow-up plan. For now we **drop** the three dead signals and
re-weight the remaining 5 so they sum to exactly 1.0.

If/when two-pass routing lands, the dropped signals can be reintroduced by
restoring the keys here and rebalancing weights — keep the assertion intact.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import UUID

from nlp_pipeline.domain.enums import MentionClass, RoutingTier
from nlp_pipeline.domain.models import EntityMention, RoutingDecision

# ── Signal weights (PLAN-0093 Sub-Plan C Wave C-1 — v2) ─────────────────────
#
# v1 weights (deprecated 2026-05-23, kept here for traceability):
#   entity_density=0.25, source_reliability=0.20, novelty=0.15, recency=0.10,
#   watchlist=0.10, document_type=0.05, extraction_yield=0.05, price_impact=0.10
#   → composite ceiling ~0.65 because watchlist/novelty/price_impact never fired
#
# v2 weights (active): the 3 dead signals are removed and their 0.35 of weight
# is redistributed to the 5 live signals, prioritising the strongest ones
# (entity_density and source_reliability are the most informative live signals).
SIGNAL_WEIGHTS: dict[str, float] = {
    "entity_density": 0.35,
    "source_reliability": 0.30,
    "recency": 0.15,
    "document_type": 0.10,
    "extraction_yield": 0.10,
}

# Module-level assertion: weights must sum to exactly 1.0
assert (
    abs(sum(SIGNAL_WEIGHTS.values()) - 1.0) < 1e-9
), f"Signal weights must sum to 1.0, got {sum(SIGNAL_WEIGHTS.values())}"

# ── Tier thresholds (PLAN-0093 C-1 — recalibrated for v2 ceiling) ───────────
#
# With v1 (8 signals, 3 dead) the practical max composite was ~0.65 because the
# 3 dead signals contributed 0.0 even on perfect docs. With v2 (5 live signals)
# the practical max is ~0.90+, so tier thresholds shift upward to maintain the
# same DEEP/MEDIUM/LIGHT proportions.
TIER_DEEP: float = 0.75
TIER_MEDIUM: float = 0.45
TIER_LIGHT: float = 0.20

# ── Document-type signal map (PRD §6.7 Block 5) ──────────────────────────────

DOCUMENT_TYPE_SIGNAL: dict[str, float] = {
    "sec_8k": 0.95,
    "sec_10k": 0.90,
    "sec_10q": 0.90,
    "sec_edgar": 0.88,  # generic SEC filing — all form types (10-K/10-Q/8-K/DEF14A)
    "sec_def14a": 0.88,
    "earnings_call": 0.80,
    "analyst_report": 0.80,
    "press_release": 0.70,
    "eodhd": 0.55,  # actual source_type emitted by content-ingestion EODHD adapter
    "eodhd_news": 0.55,  # legacy alias (seed data)
    "finnhub": 0.55,  # actual source_type emitted by content-ingestion Finnhub adapter
    "finnhub_news": 0.55,  # legacy alias (seed data)
    "newsapi": 0.55,  # actual source_type emitted by content-ingestion NewsAPI adapter
    "newsapi_news": 0.55,  # legacy alias
    "manual": 0.50,
}
_DEFAULT_DOCUMENT_TYPE_SIGNAL: float = 0.50

# Authoritative regulatory filings are guaranteed at least MEDIUM routing even when
# entity density is low — structural SEC filings contain high-value factual disclosures
# whose value is not captured by the entity_density signal (low ORGANIZATION/FI mention
# counts in raw HTML do not indicate low informational value).
_AUTHORITATIVE_FILING_SOURCES: frozenset[str] = frozenset(
    {
        "sec_edgar",
        "sec_8k",
        "sec_10k",
        "sec_10q",
        "sec_def14a",
        "tenant_upload",
    }
)

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

    DEPRECATED (PLAN-0093 C-1, 2026-05-23): no longer wired into
    ``compute_routing_score`` because resolution runs AFTER routing in the
    current single-pass architecture, so ``resolved_entity_id`` is always
    ``None`` at the time this would be called. The helper is kept ONLY so the
    existing unit tests in ``test_routing.py`` can continue to exercise the
    signal-math invariants (overlap counting, cap-at-1 behaviour) until
    two-pass routing is implemented in a follow-up plan.

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


def _assign_tier(
    score: float,
    tier_deep: float = TIER_DEEP,
    tier_medium: float = TIER_MEDIUM,
    tier_light: float = TIER_LIGHT,
) -> RoutingTier:
    """Assign routing tier from composite score (PRD §6.7 Block 5)."""
    if score >= tier_deep:
        return RoutingTier.DEEP
    if score >= tier_medium:
        return RoutingTier.MEDIUM
    if score >= tier_light:
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
    tier_deep: float = TIER_DEEP,
    tier_medium: float = TIER_MEDIUM,
    tier_light: float = TIER_LIGHT,
) -> RoutingDecision:
    """Compute the 5-signal routing score and assign a RoutingTier.

    PLAN-0093 C-1 (2026-05-23): dropped ``novelty_score``, ``watched_entity_ids``,
    and ``price_impact_score`` arguments — the corresponding signals were
    permanently zero in single-pass routing. See module docstring for the
    full rationale. Re-introducing them requires implementing two-pass routing.

    Args:
        doc_id: Document being routed.
        decision_id: Pre-generated UUID for the routing decision row.
        source_type: Content source type string.
        published_at: Original publication datetime (UTC).
        extracted_at: Extraction datetime (UTC).
        mentions: Entity mentions from Block 4.
        section_count: Number of sections from Block 3.
        source_trust_weight: From intelligence_db.source_trust_weights.

    Returns:
        RoutingDecision with composite_score, feature_scores, and routing_tier.
    """
    feature_scores: dict[str, float] = {
        "entity_density": _entity_density_signal(mentions),
        "source_reliability": source_trust_weight,
        "recency": _recency_signal(published_at, extracted_at),
        "document_type": DOCUMENT_TYPE_SIGNAL.get(source_type, _DEFAULT_DOCUMENT_TYPE_SIGNAL),
        "extraction_yield": _extraction_yield_signal(len(mentions), section_count),
    }

    composite = sum(SIGNAL_WEIGHTS[signal] * value for signal, value in feature_scores.items())
    # Clamp to [0, 1] for safety
    composite = max(0.0, min(1.0, composite))

    tier = _assign_tier(composite, tier_deep=tier_deep, tier_medium=tier_medium, tier_light=tier_light)

    # Authoritative filings are upgraded from LIGHT to MEDIUM — their low entity_density
    # scores do not reflect low informational value; it's a structural artifact of raw HTML.
    if tier == RoutingTier.LIGHT and source_type in _AUTHORITATIVE_FILING_SOURCES:
        tier = RoutingTier.MEDIUM

    return RoutingDecision(
        decision_id=decision_id,
        doc_id=doc_id,
        routing_tier=tier,
        composite_score=composite,
        feature_scores=feature_scores,
    )
