"""Prometheus implementation of the IAlertMetrics port."""

from __future__ import annotations

from typing import TYPE_CHECKING

from alert.application.ports.metrics import IAlertMetrics
from alert.infrastructure.metrics.prometheus import (
    s10_alerts_by_severity_total,
    s10_flash_overlays_triggered_total,
)

if TYPE_CHECKING:
    from alert.domain.enums import AlertSeverity, AlertType


class PrometheusAlertMetrics(IAlertMetrics):
    """Records alert fan-out metrics to Prometheus counters."""

    def record_alert_fanned_out(
        self,
        severity: AlertSeverity,
        alert_type: AlertType,
        count: int,
    ) -> None:
        s10_alerts_by_severity_total.labels(severity=str(severity), alert_type=str(alert_type)).inc(count)

    def record_flash_overlay(self) -> None:
        s10_flash_overlays_triggered_total.inc()
