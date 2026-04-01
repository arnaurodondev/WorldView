"""Unit tests for domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from knowledge_graph.domain.enums import SemanticMode
from knowledge_graph.domain.errors import ConfidenceBoundsViolation
from knowledge_graph.domain.models import (
    ConfidenceComponents,
    Contradiction,
    ContradictionLink,
    Relation,
    RelationEvidence,
    RelationSummary,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 3, 27, 12, 0, 0, tzinfo=UTC)


class TestRelation:
    def test_construction(self) -> None:
        r = Relation(
            relation_id=uuid4(),
            subject_entity_id=uuid4(),
            object_entity_id=uuid4(),
            canonical_type="employs",
            semantic_mode=SemanticMode.RELATION_STATE,
            decay_class="DURABLE",
            decay_alpha=0.000950,
            base_confidence=0.70,
            confidence=None,
            confidence_stale=True,
            summary_stale=True,
            evidence_count=0,
            first_evidence_at=_NOW,
            latest_evidence_at=_NOW,
        )
        assert r.canonical_type == "employs"
        assert r.confidence is None
        assert r.confidence_stale is True

    def test_is_frozen(self) -> None:
        r = Relation(
            relation_id=uuid4(),
            subject_entity_id=uuid4(),
            object_entity_id=uuid4(),
            canonical_type="employs",
            semantic_mode=SemanticMode.RELATION_STATE,
            decay_class="DURABLE",
            decay_alpha=0.000950,
            base_confidence=0.70,
            confidence=0.5,
            confidence_stale=False,
            summary_stale=True,
            evidence_count=3,
            first_evidence_at=_NOW,
            latest_evidence_at=_NOW,
        )
        from dataclasses import FrozenInstanceError

        with pytest.raises(FrozenInstanceError):
            r.confidence = 0.9  # type: ignore[misc]


class TestRelationEvidence:
    def test_construction_with_is_backfill(self) -> None:
        e = RelationEvidence(
            evidence_id=uuid4(),
            relation_id=uuid4(),
            doc_id=uuid4(),
            extraction_confidence=0.85,
            source_weight=0.90,
            evidence_date=_NOW,
            is_backfill=True,
        )
        assert e.is_backfill is True
        assert e.chunk_id is None
        assert e.claim_id is None

    def test_optional_fields_default_none(self) -> None:
        e = RelationEvidence(
            evidence_id=uuid4(),
            relation_id=uuid4(),
            doc_id=uuid4(),
            extraction_confidence=0.7,
            source_weight=0.6,
            evidence_date=_NOW,
            is_backfill=False,
        )
        assert e.evidence_text is None
        assert e.canonicalized_evidence_text is None


class TestRelationSummary:
    def test_construction(self) -> None:
        s = RelationSummary(
            summary_id=uuid4(),
            relation_id=uuid4(),
            summary_text="Apple employs Tim Cook as CEO.",
            evidence_count=5,
            evidence_hash="abc123",
            model_id="llama3.2",
            prompt_template_id=uuid4(),
            is_current=True,
            generation_trigger="stale",
            generated_at=_NOW,
        )
        assert s.is_current is True
        assert s.summary_embedding is None


class TestContradictionLink:
    def test_construction(self) -> None:
        link = ContradictionLink(
            link_id=uuid4(),
            relation_evidence_id=uuid4(),
            claim_id=uuid4(),
            contradiction_type="polarity_flip",
            strength=0.8,
            detected_at=_NOW,
        )
        assert link.invalidated_at is None

    def test_with_invalidated_at(self) -> None:
        link = ContradictionLink(
            link_id=uuid4(),
            relation_evidence_id=uuid4(),
            claim_id=uuid4(),
            contradiction_type="polarity_flip",
            strength=0.8,
            detected_at=_NOW,
            invalidated_at=_NOW,
        )
        assert link.invalidated_at == _NOW


class TestContradiction:
    def test_construction(self) -> None:
        c = Contradiction(
            subject_entity_id=uuid4(),
            claim_type="analyst_rating",
            claim_a_id=uuid4(),
            claim_b_id=uuid4(),
            polarity_a="positive",
            polarity_b="negative",
            strength=0.75,
            detected_at=_NOW,
        )
        assert c.polarity_a == "positive"
        assert c.polarity_b == "negative"


class TestConfidenceComponents:
    def test_validate_passes_valid(self) -> None:
        c = ConfidenceComponents(
            support=0.7,
            corroboration=0.15,
            contradiction=0.3,
            final=0.55,
        )
        c.validate()  # no exception

    def test_validate_final_below_zero_raises(self) -> None:
        c = ConfidenceComponents(support=0.0, corroboration=0.0, contradiction=0.0, final=-0.1)
        with pytest.raises(ConfidenceBoundsViolation, match="outside"):
            c.validate()

    def test_validate_final_above_one_raises(self) -> None:
        c = ConfidenceComponents(support=0.0, corroboration=0.0, contradiction=0.0, final=1.1)
        with pytest.raises(ConfidenceBoundsViolation, match="outside"):
            c.validate()

    def test_validate_corroboration_exceeds_cap_raises(self) -> None:
        c = ConfidenceComponents(
            support=0.5,
            corroboration=0.25,  # > 0.20
            contradiction=0.0,
            final=0.75,
        )
        with pytest.raises(ConfidenceBoundsViolation, match="corroboration"):
            c.validate()

    def test_validate_contradiction_exceeds_cap_raises(self) -> None:
        c = ConfidenceComponents(
            support=0.5,
            corroboration=0.10,
            contradiction=0.65,  # > 0.60
            final=0.0,
        )
        with pytest.raises(ConfidenceBoundsViolation, match="contradiction"):
            c.validate()

    def test_corroboration_cap_constant(self) -> None:
        assert ConfidenceComponents.CORROBORATION_CAP == 0.20

    def test_contradiction_cap_constant(self) -> None:
        assert ConfidenceComponents.CONTRADICTION_CAP == 0.60
