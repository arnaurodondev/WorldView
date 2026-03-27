"""Unit tests for Block 6 — Suppression gate (T-C-2-05)."""

from __future__ import annotations

import uuid

import pytest
from nlp_pipeline.application.blocks.suppression import (
    ProcessingPath,
    apply_suppression_gate,
    should_generate_chunk_embeddings,
    should_run_deep_extraction,
    should_run_entity_resolution,
)
from nlp_pipeline.domain.enums import RoutingTier
from nlp_pipeline.domain.models import RoutingDecision


def _decision(tier: RoutingTier, final_tier: RoutingTier | None = None) -> RoutingDecision:
    return RoutingDecision(
        decision_id=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        routing_tier=tier,
        composite_score=0.5,
        feature_scores={},
        final_routing_tier=final_tier,
    )


@pytest.mark.unit
class TestApplySuppressionGate:
    def test_suppress_tier_returns_halt(self) -> None:
        path = apply_suppression_gate(_decision(RoutingTier.SUPPRESS))
        assert path == ProcessingPath.HALT

    def test_light_tier_returns_section_embeddings_only(self) -> None:
        path = apply_suppression_gate(_decision(RoutingTier.LIGHT))
        assert path == ProcessingPath.SECTION_EMBEDDINGS_ONLY

    def test_medium_tier_returns_full_pipeline(self) -> None:
        path = apply_suppression_gate(_decision(RoutingTier.MEDIUM))
        assert path == ProcessingPath.FULL_PIPELINE

    def test_deep_tier_returns_full_pipeline(self) -> None:
        path = apply_suppression_gate(_decision(RoutingTier.DEEP))
        assert path == ProcessingPath.FULL_PIPELINE

    def test_final_tier_overrides_initial_when_set(self) -> None:
        """final_routing_tier (novelty correction) must take precedence."""
        # Initial: DEEP, Final (downgraded by novelty): LIGHT
        path = apply_suppression_gate(_decision(RoutingTier.DEEP, final_tier=RoutingTier.LIGHT))
        assert path == ProcessingPath.SECTION_EMBEDDINGS_ONLY

    def test_final_tier_suppress_overrides_initial_deep(self) -> None:
        path = apply_suppression_gate(_decision(RoutingTier.DEEP, final_tier=RoutingTier.SUPPRESS))
        assert path == ProcessingPath.HALT

    def test_final_tier_upgrade_from_suppress_to_light(self) -> None:
        """Stage 2 novelty can upgrade suppress → light."""
        path = apply_suppression_gate(_decision(RoutingTier.SUPPRESS, final_tier=RoutingTier.LIGHT))
        assert path == ProcessingPath.SECTION_EMBEDDINGS_ONLY

    def test_audit_log_written_for_every_tier(self) -> None:
        """apply_suppression_gate must not raise — audit log is caller's responsibility."""
        for tier in RoutingTier:
            path = apply_suppression_gate(_decision(tier))
            assert path in ProcessingPath  # just verify it returns a valid path


@pytest.mark.unit
class TestDownstreamFlags:
    def test_halt_no_chunks_no_resolution_no_extraction(self) -> None:
        assert should_generate_chunk_embeddings(ProcessingPath.HALT) is False
        assert should_run_entity_resolution(ProcessingPath.HALT) is False
        assert should_run_deep_extraction(ProcessingPath.HALT) is False

    def test_section_embeddings_only_no_chunks_no_resolution_no_extraction(self) -> None:
        assert should_generate_chunk_embeddings(ProcessingPath.SECTION_EMBEDDINGS_ONLY) is False
        assert should_run_entity_resolution(ProcessingPath.SECTION_EMBEDDINGS_ONLY) is False
        assert should_run_deep_extraction(ProcessingPath.SECTION_EMBEDDINGS_ONLY) is False

    def test_full_pipeline_all_enabled(self) -> None:
        assert should_generate_chunk_embeddings(ProcessingPath.FULL_PIPELINE) is True
        assert should_run_entity_resolution(ProcessingPath.FULL_PIPELINE) is True
        assert should_run_deep_extraction(ProcessingPath.FULL_PIPELINE) is True
