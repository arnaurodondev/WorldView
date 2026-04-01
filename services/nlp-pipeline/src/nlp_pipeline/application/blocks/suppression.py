"""Block 6 — Suppression and audit gate (PRD §6.7 Block 6).

Determines processing path based on routing tier.
Always writes an audit log entry to routing_decisions.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from nlp_pipeline.domain.enums import RoutingTier

if TYPE_CHECKING:
    from nlp_pipeline.domain.models import RoutingDecision


class ProcessingPath(StrEnum):
    """Processing path assigned by the suppression gate."""

    HALT = "halt"  # SUPPRESS tier — stop all downstream
    SECTION_EMBEDDINGS_ONLY = "section_embeddings_only"  # LIGHT tier — no NER reprocessing
    FULL_PIPELINE = "full_pipeline"  # MEDIUM or DEEP — continue full processing


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


def should_generate_chunk_embeddings(path: ProcessingPath) -> bool:
    """Chunk embeddings are only generated on MEDIUM/DEEP (not LIGHT, not SUPPRESS)."""
    return path == ProcessingPath.FULL_PIPELINE


def should_run_entity_resolution(path: ProcessingPath) -> bool:
    """Entity resolution runs only on MEDIUM/DEEP."""
    return path == ProcessingPath.FULL_PIPELINE


def should_run_deep_extraction(path: ProcessingPath) -> bool:
    """Deep LLM extraction runs only on MEDIUM/DEEP (Block 10)."""
    return path == ProcessingPath.FULL_PIPELINE
