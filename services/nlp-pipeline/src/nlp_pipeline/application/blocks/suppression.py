"""Block 6 — Suppression and audit gate (PRD §6.7 Block 6).

Determines processing path based on routing tier.
Always writes an audit log entry to routing_decisions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# PLAN-0057 A-1: ProcessingPath now lives in the domain layer so it can be
# a typed field on the RoutingDecision dataclass. We re-export it from this
# module so existing call sites (`from ...suppression import ProcessingPath`)
# don't break.
from nlp_pipeline.domain.enums import ProcessingPath, RoutingTier

if TYPE_CHECKING:
    from nlp_pipeline.domain.models import RoutingDecision

__all__ = [
    "ProcessingPath",
    "apply_deep_extraction_value_gate",
    "apply_suppression_gate",
    "should_generate_chunk_embeddings",
    "should_generate_section_embeddings",
    "should_run_deep_extraction",
    "should_run_entity_resolution",
]


def apply_suppression_gate(routing_decision: RoutingDecision) -> ProcessingPath:
    """Apply the suppression gate based on routing tier.

    PRD §6.7 Block 6:
    - SUPPRESS → HALT (retain MinIO silver 7 days, commit offset, stop)
    - LIGHT    → SECTION_EMBEDDINGS_ONLY (no NER reprocessing, no extraction)
    - MEDIUM   → FULL_PIPELINE
    - DEEP     → FULL_PIPELINE

    The routing_decision row already exists as the audit log — callers are
    responsible for persisting it via RoutingDecisionRepository.

    Returns the ProcessingPath that downstream blocks should follow.
    """
    # Use final_routing_tier if set by Stage 2 novelty; else use initial tier
    effective_tier = routing_decision.final_routing_tier or routing_decision.routing_tier

    if effective_tier == RoutingTier.SUPPRESS:
        return ProcessingPath.HALT

    if effective_tier == RoutingTier.LIGHT:
        return ProcessingPath.SECTION_EMBEDDINGS_ONLY

    # MEDIUM and DEEP proceed through the full pipeline
    return ProcessingPath.FULL_PIPELINE


def apply_deep_extraction_value_gate(
    path: ProcessingPath,
    routing_decision: RoutingDecision,
    source_type: str | None,
    *,
    enabled: bool,
    score_floor: float,
    filing_sources: frozenset[str],
) -> ProcessingPath:
    """Backlog-drain lever (2026-07-17): skip the expensive deep-extraction chain for
    genuinely LOW-VALUE documents, routing them to the same cheap path as LIGHT.

    Ref: docs/audits/2026-07-17-article-backlog-lever.md.

    The tier router maps BOTH MEDIUM and DEEP tiers to ``FULL_PIPELINE``, so ~69% of
    intake runs the full DeepInfra chain (entity resolution + LLM relation/event/claim
    extraction + entailment guards) — the dominant per-article cost and the reason the
    ~192k backlog never drains. This gate reclassifies the low-value tail as
    ``SECTION_EMBEDDINGS_ONLY`` (the LIGHT path): chunk embeddings are STILL written
    (see ``should_generate_chunk_embeddings``) so the doc stays fully searchable, and
    only the costly KG extraction is skipped (and remains backfillable from the
    persisted chunks/mentions).

    Conservative by construction — the path is downgraded ONLY when ALL hold:
      * ``enabled`` is True;
      * the doc is currently on ``FULL_PIPELINE`` (a MEDIUM/DEEP-tier doc). LIGHT /
        SUPPRESS already skip extraction, so they are returned unchanged;
      * ``source_type`` is NOT an authoritative regulatory filing — filings are ALWAYS
        deep-extracted regardless of score (their low entity-density score is a
        structural artefact of raw HTML, not low informational value);
      * the composite routing score is BELOW ``score_floor`` — every doc scoring at or
        above the floor (all genuinely high-value news + all DEEP-tier docs above it)
        is always fully extracted.

    Keying on the raw composite score (not the tier label) keeps the gate independent
    of the DEEP/MEDIUM tier cutoffs (which prod tunes at runtime): the floor IS the
    value line. Returns the (possibly downgraded) ``ProcessingPath``.
    """
    if not enabled:
        return path
    # Only MEDIUM/DEEP docs reach the expensive chain; leave every other path as-is.
    if path != ProcessingPath.FULL_PIPELINE:
        return path
    # Authoritative regulatory filings are always fully extracted (high-value
    # disclosures whose worth the entity_density-driven score under-measures).
    if source_type is not None and source_type in filing_sources:
        return path
    # High-value docs (score at/above the floor) are always fully extracted.
    if routing_decision.composite_score >= score_floor:
        return path
    # Genuinely low-value doc: drop to the LIGHT path — chunk embeddings only,
    # no entity resolution, no deep LLM extraction.
    return ProcessingPath.SECTION_EMBEDDINGS_ONLY


def should_generate_chunk_embeddings(path: ProcessingPath) -> bool:
    """Chunk embeddings are generated for every non-SUPPRESS tier (PLAN-0111 B-1).

    WHY this changed: chat retrieval queries CHUNK-granularity vectors. Previously
    LIGHT (SECTION_EMBEDDINGS_ONLY) produced no chunk embeddings, so ~21% of the
    corpus (the LIGHT tier) was invisible to semantic ANN retrieval — reachable only
    via the BM25/tsvector leg. We now embed LIGHT chunks too, making every ingested
    article semantically searchable. The expensive work (entity resolution, deep LLM
    extraction) remains gated to FULL_PIPELINE only — see the two functions below.

    SUPPRESS (HALT) still produces nothing: those docs are discarded as noise.
    """
    return path in {ProcessingPath.FULL_PIPELINE, ProcessingPath.SECTION_EMBEDDINGS_ONLY}


def should_generate_section_embeddings(path: ProcessingPath) -> bool:
    """Section embeddings are generated only on MEDIUM/DEEP (PLAN-0111 B-2).

    WHY: chat retrieval uses CHUNK granularity exclusively (confirmed by grepping
    rag-chat for granularity usage). For LIGHT, now that chunk embeddings exist
    (see should_generate_chunk_embeddings), the section embedding is pure dead
    weight — it costs an embed call and a vector row but is never queried. We keep
    section embeddings for MEDIUM/DEEP to avoid widening the diff / changing
    behavior for tiers where they were already produced, but stop emitting them
    for LIGHT. SUPPRESS (HALT) produces nothing.
    """
    return path == ProcessingPath.FULL_PIPELINE


def should_run_entity_resolution(path: ProcessingPath) -> bool:
    """Entity resolution runs only on MEDIUM/DEEP."""
    return path == ProcessingPath.FULL_PIPELINE


def should_run_deep_extraction(path: ProcessingPath) -> bool:
    """Deep LLM extraction runs only on MEDIUM/DEEP (Block 10)."""
    return path == ProcessingPath.FULL_PIPELINE
