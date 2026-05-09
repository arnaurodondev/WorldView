"""Unit tests for S10 domain enumerations."""

from __future__ import annotations

import pytest
from alert.domain.enums import AlertSeverity, AlertType, DeliveryChannel, DeliveryStatus, DLQStatus, OutboxStatus

pytestmark = pytest.mark.unit


class TestAlertSeverity:
    @pytest.mark.unit
    def test_alert_severity_values(self) -> None:
        assert AlertSeverity.LOW == "low"
        assert AlertSeverity.MEDIUM == "medium"
        assert AlertSeverity.HIGH == "high"
        assert AlertSeverity.CRITICAL == "critical"

    @pytest.mark.unit
    def test_alert_severity_is_strenum(self) -> None:
        assert AlertSeverity.LOW == "low"
        assert isinstance(AlertSeverity.LOW, str)

    @pytest.mark.unit
    def test_alert_severity_has_exactly_four_members(self) -> None:
        assert len(AlertSeverity) == 4


class TestAlertType:
    @pytest.mark.unit
    def test_alert_type_values(self) -> None:
        assert AlertType.SIGNAL == "SIGNAL"
        assert AlertType.GRAPH_CHANGE == "GRAPH_CHANGE"
        assert AlertType.CONTRADICTION == "CONTRADICTION"
        # PLAN-0082 Wave B: USER_RULE added for user-created write-action alerts.
        # WHY lowercase "user_rule" (unlike other UPPERCASE values): the existing
        # system-generated alert types use UPPERCASE because they originated as
        # PG enum values that have since been migrated to VARCHAR.  USER_RULE is
        # a new user-facing concept and uses lowercase for readability in API
        # responses (alert_type: "user_rule" vs. "SIGNAL").
        assert AlertType.USER_RULE == "user_rule"

    @pytest.mark.unit
    def test_alert_type_has_exactly_four_members(self) -> None:
        # PLAN-0082 Wave B: updated from 3 → 4 when USER_RULE was added.
        assert len(AlertType) == 4

    @pytest.mark.unit
    def test_alert_type_from_string(self) -> None:
        assert AlertType("SIGNAL") is AlertType.SIGNAL
        assert AlertType("GRAPH_CHANGE") is AlertType.GRAPH_CHANGE
        assert AlertType("CONTRADICTION") is AlertType.CONTRADICTION
        assert AlertType("user_rule") is AlertType.USER_RULE


class TestOutboxStatus:
    @pytest.mark.unit
    def test_outbox_status_values(self) -> None:
        assert OutboxStatus.PENDING == "pending"
        assert OutboxStatus.DISPATCHED == "dispatched"
        assert OutboxStatus.FAILED == "failed"


class TestDeliveryEnums:
    @pytest.mark.unit
    def test_delivery_channel(self) -> None:
        assert DeliveryChannel.WEBSOCKET == "websocket"

    @pytest.mark.unit
    def test_delivery_status(self) -> None:
        assert DeliveryStatus.PENDING == "pending"
        assert DeliveryStatus.DELIVERED == "delivered"

    @pytest.mark.unit
    def test_dlq_status(self) -> None:
        assert DLQStatus.FAILED == "failed"
        assert DLQStatus.RESOLVED == "resolved"
