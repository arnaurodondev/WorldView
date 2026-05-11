"""Unit tests for TemporalEvent and EntityEventExposure domain models (PRD-0018 §6.6)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from knowledge_graph.domain.enums import EventScope, EventType, ExposureType
from knowledge_graph.domain.models import EntityEventExposure, TemporalEvent

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 8, 12, 0, 0, tzinfo=UTC)


def _make_event(**kwargs) -> TemporalEvent:
    """Build a TemporalEvent with sensible defaults; override via kwargs."""
    base: dict = {
        "event_id": uuid4(),
        "event_type": EventType.GEOPOLITICAL,
        "scope": EventScope.NATIONAL,
        "region": "US",
        "title": "US-China Technology Trade Restrictions",
        "description": "Escalating semiconductor export controls",
        "active_from": _NOW - timedelta(days=30),
        "active_until": None,
        "residual_impact_days": 90,
        "confidence": 0.85,
        "created_at": _NOW - timedelta(days=30),
    }
    base.update(kwargs)
    return TemporalEvent(**base)


# ---------------------------------------------------------------------------
# Lifecycle phase tests (PRD-0018 §6.6 — computed property)
# ---------------------------------------------------------------------------


class TestTemporalEventLifecyclePhase:
    def test_pending_active_when_not_yet_started(self, monkeypatch) -> None:
        """active_from in the future → PENDING_ACTIVE."""
        future = datetime.now(UTC) + timedelta(days=5)
        event = _make_event(active_from=future)
        assert event.lifecycle_phase == "PENDING_ACTIVE"

    def test_active_when_no_active_until(self, monkeypatch) -> None:
        """active_from in the past, active_until=None → ACTIVE (ongoing event)."""
        event = _make_event(
            active_from=datetime.now(UTC) - timedelta(days=10),
            active_until=None,
        )
        assert event.lifecycle_phase == "ACTIVE"

    def test_active_when_within_window(self) -> None:
        """active_from in the past, active_until in the future → ACTIVE."""
        event = _make_event(
            active_from=datetime.now(UTC) - timedelta(days=5),
            active_until=datetime.now(UTC) + timedelta(days=5),
        )
        assert event.lifecycle_phase == "ACTIVE"

    def test_residual_when_within_residual_window(self) -> None:
        """Event ended 20 days ago, residual_impact_days=90 → RESIDUAL."""
        ended_at = datetime.now(UTC) - timedelta(days=20)
        event = _make_event(
            active_from=ended_at - timedelta(days=10),
            active_until=ended_at,
            residual_impact_days=90,
        )
        assert event.lifecycle_phase == "RESIDUAL"

    def test_expired_when_past_residual_window(self) -> None:
        """Event ended 100 days ago, residual_impact_days=90 → EXPIRED."""
        ended_at = datetime.now(UTC) - timedelta(days=100)
        event = _make_event(
            active_from=ended_at - timedelta(days=10),
            active_until=ended_at,
            residual_impact_days=90,
        )
        assert event.lifecycle_phase == "EXPIRED"

    def test_expired_with_zero_residual_days(self) -> None:
        """Event ended 1 day ago, residual_impact_days=0 → EXPIRED immediately."""
        ended_at = datetime.now(UTC) - timedelta(days=1)
        event = _make_event(
            active_from=ended_at - timedelta(days=5),
            active_until=ended_at,
            residual_impact_days=0,
        )
        assert event.lifecycle_phase == "EXPIRED"


# ---------------------------------------------------------------------------
# Impact weight tests (PRD-0018 §6.6 — computed property)
# ---------------------------------------------------------------------------


class TestTemporalEventImpactWeight:
    def test_active_weight_is_one(self) -> None:
        """ACTIVE phase → impact weight = 1.0."""
        event = _make_event(
            active_from=datetime.now(UTC) - timedelta(days=5),
            active_until=None,
        )
        assert event.lifecycle_phase == "ACTIVE"
        assert event.current_impact_weight == pytest.approx(1.0)

    def test_residual_weight_exponential_decay(self) -> None:
        """RESIDUAL phase, 20 days since end → exp(-0.02 * 20) ≈ 0.6703."""
        days_since_end = 20
        ended_at = datetime.now(UTC) - timedelta(days=days_since_end)
        event = _make_event(
            active_from=ended_at - timedelta(days=10),
            active_until=ended_at,
            residual_impact_days=90,
        )
        assert event.lifecycle_phase == "RESIDUAL"
        expected = math.exp(-0.02 * days_since_end)
        assert event.current_impact_weight == pytest.approx(expected, rel=0.01)

    def test_expired_weight_is_zero(self) -> None:
        """EXPIRED phase → impact weight = 0.0."""
        ended_at = datetime.now(UTC) - timedelta(days=100)
        event = _make_event(
            active_from=ended_at - timedelta(days=10),
            active_until=ended_at,
            residual_impact_days=90,
        )
        assert event.lifecycle_phase == "EXPIRED"
        assert event.current_impact_weight == pytest.approx(0.0)

    def test_pending_active_weight_is_zero(self) -> None:
        """PENDING_ACTIVE phase → impact weight = 0.0 (not yet started)."""
        event = _make_event(active_from=datetime.now(UTC) + timedelta(days=5))
        assert event.lifecycle_phase == "PENDING_ACTIVE"
        assert event.current_impact_weight == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# TemporalEvent construction and invariants
# ---------------------------------------------------------------------------


class TestTemporalEventConstruction:
    def test_is_frozen(self) -> None:
        """TemporalEvent is immutable (frozen dataclass)."""
        event = _make_event()
        with pytest.raises(AttributeError):
            event.title = "mutated"  # type: ignore[misc]

    def test_default_source_article_ids_empty_tuple(self) -> None:
        """source_article_ids defaults to empty tuple when not provided."""
        event = _make_event()
        assert event.source_article_ids == ()

    def test_optional_fields_default_to_none(self) -> None:
        """region, description, source_url, active_until default to None."""
        event = TemporalEvent(
            event_id=uuid4(),
            event_type=EventType.MACRO,
            scope=EventScope.GLOBAL,
            title="Global Rate Cycle",
            confidence=1.0,
            active_from=datetime.now(UTC) - timedelta(days=1),
            residual_impact_days=30,
            created_at=datetime.now(UTC),
        )
        assert event.region is None
        assert event.description is None
        assert event.source_url is None
        assert event.active_until is None

    def test_macro_scope_global_enum_values(self) -> None:
        """EventType and EventScope use the correct case-sensitive string values."""
        assert EventType.MACRO == "macro"
        assert EventScope.GLOBAL == "GLOBAL"
        assert EventType.GEOPOLITICAL == "geopolitical"
        assert EventScope.NATIONAL == "NATIONAL"


# ---------------------------------------------------------------------------
# EntityEventExposure construction
# ---------------------------------------------------------------------------


class TestEntityEventExposureConstruction:
    def test_construction(self) -> None:
        exp = EntityEventExposure(
            exposure_id=uuid4(),
            event_id=uuid4(),
            entity_id=uuid4(),
            exposure_type=ExposureType.DIRECTLY_AFFECTED,
            confidence=0.92,
        )
        assert exp.exposure_type == ExposureType.DIRECTLY_AFFECTED
        assert exp.evidence_text is None

    def test_is_frozen(self) -> None:
        exp = EntityEventExposure(
            exposure_id=uuid4(),
            event_id=uuid4(),
            entity_id=uuid4(),
            exposure_type=ExposureType.SECTOR_EXPOSURE,
            confidence=0.75,
        )
        with pytest.raises(AttributeError):
            exp.confidence = 0.5  # type: ignore[misc]

    def test_exposure_type_values_lowercase(self) -> None:
        """ExposureType values are lowercase to match DB CHECK and Avro schema."""
        assert ExposureType.DIRECTLY_AFFECTED == "directly_affected"
        assert ExposureType.SUPPLY_CHAIN == "supply_chain"
        assert ExposureType.SECTOR_EXPOSURE == "sector_exposure"
        assert ExposureType.REVENUE_GEOGRAPHY == "revenue_geography"
        assert ExposureType.OPERATIONALLY_IMPACTED == "operationally_impacted"
