"""Unit tests for Block 6 — Suppression gate (T-C-2-05)."""

from __future__ import annotations

import uuid

import pytest
from nlp_pipeline.application.blocks.routing import _AUTHORITATIVE_FILING_SOURCES
from nlp_pipeline.application.blocks.suppression import (
    ProcessingPath,
    apply_deep_extraction_value_gate,
    apply_suppression_gate,
    should_generate_chunk_embeddings,
    should_generate_section_embeddings,
    should_run_deep_extraction,
    should_run_entity_resolution,
)
from nlp_pipeline.domain.enums import RoutingTier
from nlp_pipeline.domain.models import RoutingDecision

pytestmark = pytest.mark.unit


def _decision(
    tier: RoutingTier, final_tier: RoutingTier | None = None, *, composite_score: float = 0.5
) -> RoutingDecision:
    return RoutingDecision(
        decision_id=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        routing_tier=tier,
        composite_score=composite_score,
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
class TestApplyDeepExtractionValueGate:
    """Backlog-drain lever (docs/audits/2026-07-17-article-backlog-lever.md).

    Skips the expensive deep-extraction chain for genuinely low-value docs by
    downgrading FULL_PIPELINE → SECTION_EMBEDDINGS_ONLY (chunk embeddings only).
    """

    _FLOOR = 0.45  # the safe default: == the live-prod DEEP tier boundary

    def _gate(
        self,
        path: ProcessingPath,
        *,
        score: float,
        source_type: str | None = "eodhd",
        enabled: bool = True,
        floor: float = _FLOOR,
    ) -> ProcessingPath:
        return apply_deep_extraction_value_gate(
            path,
            _decision(RoutingTier.MEDIUM, composite_score=score),
            source_type,
            enabled=enabled,
            score_floor=floor,
            filing_sources=_AUTHORITATIVE_FILING_SOURCES,
        )

    def test_below_floor_full_pipeline_is_downgraded(self) -> None:
        # A low-value MEDIUM news doc (score < floor, in the [0.35, 0.45) band) is
        # routed to the cheap LIGHT path — chunk embeddings only, no deep extraction.
        assert self._gate(ProcessingPath.FULL_PIPELINE, score=0.40) == ProcessingPath.SECTION_EMBEDDINGS_ONLY

    def test_at_or_above_floor_full_pipeline_is_kept(self) -> None:
        # Docs scoring >= floor are ALWAYS fully extracted. At the default floor 0.45
        # (== the live DEEP boundary), this includes EVERY DEEP-tier doc (score >= 0.45),
        # so no DEEP-tier doc is gated — the exact boundary (0.45) and above stay.
        assert self._gate(ProcessingPath.FULL_PIPELINE, score=0.45) == ProcessingPath.FULL_PIPELINE
        assert self._gate(ProcessingPath.FULL_PIPELINE, score=0.497) == ProcessingPath.FULL_PIPELINE
        assert self._gate(ProcessingPath.FULL_PIPELINE, score=0.85) == ProcessingPath.FULL_PIPELINE

    def test_filing_source_below_floor_is_kept(self) -> None:
        # Authoritative regulatory filings are always extracted regardless of score
        # (their low entity-density score is a raw-HTML artefact, not low value).
        for src in ("sec_10q", "sec_8k", "sec_edgar", "tenant_upload"):
            assert self._gate(ProcessingPath.FULL_PIPELINE, score=0.10, source_type=src) == ProcessingPath.FULL_PIPELINE

    def test_disabled_is_noop(self) -> None:
        # enabled=False restores the pre-gate behaviour (nothing downgraded).
        assert self._gate(ProcessingPath.FULL_PIPELINE, score=0.10, enabled=False) == ProcessingPath.FULL_PIPELINE

    def test_non_full_pipeline_paths_are_untouched(self) -> None:
        # LIGHT (already cheap), HALT (discarded) are never modified.
        assert self._gate(ProcessingPath.SECTION_EMBEDDINGS_ONLY, score=0.10) == ProcessingPath.SECTION_EMBEDDINGS_ONLY
        assert self._gate(ProcessingPath.HALT, score=0.10) == ProcessingPath.HALT

    def test_floor_is_configurable(self) -> None:
        # A doc at 0.47 is gated at floor 0.50 but kept at a lower floor 0.45.
        assert self._gate(ProcessingPath.FULL_PIPELINE, score=0.47, floor=0.50) == (
            ProcessingPath.SECTION_EMBEDDINGS_ONLY
        )
        assert self._gate(ProcessingPath.FULL_PIPELINE, score=0.47, floor=0.45) == ProcessingPath.FULL_PIPELINE

    def test_none_source_type_below_floor_is_downgraded(self) -> None:
        # A missing source_type is not a filing → low-value doc is still gated.
        assert self._gate(ProcessingPath.FULL_PIPELINE, score=0.30, source_type=None) == (
            ProcessingPath.SECTION_EMBEDDINGS_ONLY
        )


@pytest.mark.unit
class TestValueGateConfigDefaults:
    """Lock the safe-by-default invariant: the floor must never gate DEEP-tier docs.

    That holds iff ``deep_extraction_score_floor <= routing_tier_deep`` (a DEEP doc
    scores >= the DEEP boundary, so a floor at/below the boundary keeps it). The
    default floor 0.45 is chosen to equal the live-prod DEEP boundary.
    """

    def test_default_floor_is_045(self) -> None:
        from nlp_pipeline.config import Settings

        s = Settings()  # type: ignore[call-arg]
        assert s.deep_extraction_score_floor == 0.45
        assert s.deep_extraction_value_gate_enabled is True

    def test_default_floor_does_not_gate_deep_tier(self) -> None:
        # Invariant: floor <= the DEEP tier boundary → no DEEP-tier doc is ever gated.
        from nlp_pipeline.config import Settings

        s = Settings()  # type: ignore[call-arg]
        assert s.deep_extraction_score_floor <= s.routing_tier_deep


@pytest.mark.unit
class TestDownstreamFlags:
    def test_halt_produces_nothing(self) -> None:
        # SUPPRESS → HALT: noise docs are discarded entirely.
        assert should_generate_chunk_embeddings(ProcessingPath.HALT) is False
        assert should_generate_section_embeddings(ProcessingPath.HALT) is False
        assert should_run_entity_resolution(ProcessingPath.HALT) is False
        assert should_run_deep_extraction(ProcessingPath.HALT) is False

    def test_light_gets_chunk_embeddings_but_no_extraction(self) -> None:
        # PLAN-0111 B-1/B-2: LIGHT now gets CHUNK embeddings (semantically
        # retrievable) but NO section embeddings (dead weight), and still NO
        # entity resolution / deep extraction (those stay FULL_PIPELINE-only).
        assert should_generate_chunk_embeddings(ProcessingPath.SECTION_EMBEDDINGS_ONLY) is True
        assert should_generate_section_embeddings(ProcessingPath.SECTION_EMBEDDINGS_ONLY) is False
        assert should_run_entity_resolution(ProcessingPath.SECTION_EMBEDDINGS_ONLY) is False
        assert should_run_deep_extraction(ProcessingPath.SECTION_EMBEDDINGS_ONLY) is False

    def test_full_pipeline_all_enabled(self) -> None:
        assert should_generate_chunk_embeddings(ProcessingPath.FULL_PIPELINE) is True
        assert should_generate_section_embeddings(ProcessingPath.FULL_PIPELINE) is True
        assert should_run_entity_resolution(ProcessingPath.FULL_PIPELINE) is True
        assert should_run_deep_extraction(ProcessingPath.FULL_PIPELINE) is True
