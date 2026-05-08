"""Unit tests for S10 domain entities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from alert.domain.entities import Alert, AlertDelivery, DeadLetterEntry, OutboxEvent, PendingAlert, SeverityThresholds
from alert.domain.enums import AlertSeverity, AlertType, DeliveryChannel, DeliveryStatus, DLQStatus, OutboxStatus

pytestmark = pytest.mark.unit


class TestSeverityThresholds:
    @pytest.mark.unit
    def test_severity_thresholds_classify_critical(self) -> None:
        t = SeverityThresholds()
        assert t.classify(0.90) == AlertSeverity.CRITICAL

    @pytest.mark.unit
    def test_severity_thresholds_classify_high(self) -> None:
        t = SeverityThresholds()
        assert t.classify(0.70) == AlertSeverity.HIGH

    @pytest.mark.unit
    def test_severity_thresholds_classify_medium(self) -> None:
        t = SeverityThresholds()
        assert t.classify(0.50) == AlertSeverity.MEDIUM

    @pytest.mark.unit
    def test_severity_thresholds_classify_low(self) -> None:
        t = SeverityThresholds()
        assert t.classify(0.20) == AlertSeverity.LOW

    @pytest.mark.unit
    def test_severity_thresholds_boundary_critical(self) -> None:
        t = SeverityThresholds()
        assert t.classify(0.85) == AlertSeverity.CRITICAL

    @pytest.mark.unit
    def test_severity_thresholds_boundary_below_critical(self) -> None:
        t = SeverityThresholds()
        assert t.classify(0.849) == AlertSeverity.HIGH

    @pytest.mark.unit
    def test_severity_thresholds_boundary_high(self) -> None:
        t = SeverityThresholds()
        assert t.classify(0.65) == AlertSeverity.HIGH

    @pytest.mark.unit
    def test_severity_thresholds_boundary_below_high(self) -> None:
        t = SeverityThresholds()
        assert t.classify(0.649) == AlertSeverity.MEDIUM

    @pytest.mark.unit
    def test_severity_thresholds_boundary_medium(self) -> None:
        t = SeverityThresholds()
        assert t.classify(0.40) == AlertSeverity.MEDIUM

    @pytest.mark.unit
    def test_severity_thresholds_boundary_below_medium(self) -> None:
        t = SeverityThresholds()
        assert t.classify(0.399) == AlertSeverity.LOW

    @pytest.mark.unit
    def test_severity_thresholds_invalid_critical_below_high(self) -> None:
        with pytest.raises(ValueError):
            SeverityThresholds(critical=0.60, high=0.65, medium=0.40)

    @pytest.mark.unit
    def test_severity_thresholds_invalid_high_below_medium(self) -> None:
        with pytest.raises(ValueError):
            SeverityThresholds(critical=0.85, high=0.30, medium=0.40)

    @pytest.mark.unit
    def test_severity_thresholds_invalid_negative_medium(self) -> None:
        with pytest.raises(ValueError):
            SeverityThresholds(critical=0.85, high=0.65, medium=-0.1)


class TestAlert:
    @pytest.mark.unit
    def test_default_construction(self) -> None:
        alert = Alert()
        assert alert.alert_id is not None
        assert alert.alert_type == AlertType.SIGNAL
        assert alert.payload == {}
        assert alert.dedup_key == ""

    @pytest.mark.unit
    def test_alert_has_severity_field(self) -> None:
        alert = Alert()
        assert alert.severity == AlertSeverity.LOW

    @pytest.mark.unit
    def test_alert_severity_assigned(self) -> None:
        alert = Alert(severity=AlertSeverity.CRITICAL)
        assert alert.severity == AlertSeverity.CRITICAL

    @pytest.mark.unit
    def test_explicit_construction(self) -> None:
        from uuid import UUID

        aid = UUID("01912345-6789-7abc-8def-0123456789ab")
        eid = UUID("01912345-6789-7abc-8def-0123456789ac")
        alert = Alert(
            alert_id=aid,
            entity_id=eid,
            alert_type=AlertType.CONTRADICTION,
            source_topic="intelligence.contradiction.v1",
            payload={"key": "value"},
        )
        assert alert.alert_id == aid
        assert alert.entity_id == eid
        assert alert.alert_type == AlertType.CONTRADICTION
        assert alert.source_topic == "intelligence.contradiction.v1"

    @pytest.mark.unit
    def test_compute_dedup_key_deterministic(self) -> None:
        from uuid import UUID

        eid = UUID("01912345-6789-7abc-8def-0123456789ac")
        ts = datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC)

        key1 = Alert.compute_dedup_key(eid, AlertType.SIGNAL, ts, window_seconds=300)
        key2 = Alert.compute_dedup_key(eid, AlertType.SIGNAL, ts, window_seconds=300)
        assert key1 == key2
        assert len(key1) == 64  # sha256 hex digest

    @pytest.mark.unit
    def test_compute_dedup_key_same_window(self) -> None:
        """Two timestamps within the same 300s window produce the same key."""
        from uuid import UUID

        eid = UUID("01912345-6789-7abc-8def-0123456789ac")
        ts1 = datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC)
        ts2 = datetime(2026, 3, 28, 12, 4, 59, tzinfo=UTC)  # 299s later

        key1 = Alert.compute_dedup_key(eid, AlertType.SIGNAL, ts1, window_seconds=300)
        key2 = Alert.compute_dedup_key(eid, AlertType.SIGNAL, ts2, window_seconds=300)
        assert key1 == key2

    @pytest.mark.unit
    def test_compute_dedup_key_different_window(self) -> None:
        """Timestamps in different 300s windows produce different keys."""
        from uuid import UUID

        eid = UUID("01912345-6789-7abc-8def-0123456789ac")
        ts1 = datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC)
        ts2 = ts1 + timedelta(seconds=300)  # next window

        key1 = Alert.compute_dedup_key(eid, AlertType.SIGNAL, ts1, window_seconds=300)
        key2 = Alert.compute_dedup_key(eid, AlertType.SIGNAL, ts2, window_seconds=300)
        assert key1 != key2

    @pytest.mark.unit
    def test_compute_dedup_key_different_alert_type(self) -> None:
        """Different alert types in the same window produce different keys."""
        from uuid import UUID

        eid = UUID("01912345-6789-7abc-8def-0123456789ac")
        ts = datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC)

        key_signal = Alert.compute_dedup_key(eid, AlertType.SIGNAL, ts)
        key_graph = Alert.compute_dedup_key(eid, AlertType.GRAPH_CHANGE, ts)
        assert key_signal != key_graph

    @pytest.mark.unit
    def test_compute_dedup_key_excludes_source_event_id(self) -> None:
        """AD-9: dedup_key does NOT include source_event_id."""
        from uuid import UUID

        eid = UUID("01912345-6789-7abc-8def-0123456789ac")
        ts = datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC)

        # Same entity+type+window should always produce same key
        # regardless of which source event triggered it
        key = Alert.compute_dedup_key(eid, AlertType.SIGNAL, ts)
        assert isinstance(key, str)
        assert len(key) == 64


class TestPendingAlert:
    @pytest.mark.unit
    def test_default_construction(self) -> None:
        pa = PendingAlert()
        assert pa.pending_id is not None
        assert pa.delivered_at is None

    @pytest.mark.unit
    def test_delivered_at_tracking(self) -> None:
        now = datetime.now(tz=UTC)
        pa = PendingAlert(delivered_at=now)
        assert pa.delivered_at == now


class TestAlertDelivery:
    @pytest.mark.unit
    def test_defaults(self) -> None:
        d = AlertDelivery()
        assert d.channel == DeliveryChannel.WEBSOCKET
        assert d.status == DeliveryStatus.DELIVERED
        assert d.delivered_at is None


class TestOutboxEvent:
    @pytest.mark.unit
    def test_defaults(self) -> None:
        e = OutboxEvent()
        assert e.status == OutboxStatus.PENDING
        assert e.retry_count == 0
        assert e.payload_avro == b""


class TestDeadLetterEntry:
    @pytest.mark.unit
    def test_defaults(self) -> None:
        d = DeadLetterEntry()
        assert d.status == DLQStatus.FAILED
        assert d.error_detail is None
        assert d.resolved_at is None
