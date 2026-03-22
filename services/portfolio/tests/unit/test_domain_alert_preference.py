"""Unit tests for alert preference domain entities."""

from __future__ import annotations

from uuid import uuid4

import pytest
from portfolio.domain.entities.alert_preference import AlertPreference, EntitySuppression
from portfolio.domain.enums import AlertType
from portfolio.domain.errors import AlertPreferenceNotFoundError, DomainError

from common.time import utc_now  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


def test_alert_preference_creation() -> None:
    ap = AlertPreference(
        id=uuid4(),
        tenant_id=uuid4(),
        user_id=uuid4(),
        alert_type=AlertType.SIGNAL,
        enabled=True,
        updated_at=utc_now(),
    )
    assert ap.alert_type == AlertType.SIGNAL
    assert ap.enabled is True


def test_entity_suppression_creation() -> None:
    entity_id = uuid4()
    es = EntitySuppression(
        id=uuid4(),
        tenant_id=uuid4(),
        user_id=uuid4(),
        entity_id=entity_id,
        suppressed_at=utc_now(),
    )
    assert es.entity_id == entity_id


def test_alert_type_enum_values() -> None:
    assert AlertType.SIGNAL == "signal"
    assert AlertType.CONTRADICTION == "contradiction"
    assert AlertType.CONFIDENCE_DROP == "confidence_drop"
    assert AlertType.NEW_EVENT == "new_event"


def test_alert_preference_error_hierarchy() -> None:
    assert issubclass(AlertPreferenceNotFoundError, DomainError)
