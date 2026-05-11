"""Metrics port for the Alert fan-out use case.

Application layer declares the interface; infrastructure provides the implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alert.domain.enums import AlertSeverity, AlertType


class IAlertMetrics(ABC):
    """Port for recording alert fan-out metrics."""

    @abstractmethod
    def record_alert_fanned_out(
        self,
        severity: AlertSeverity,
        alert_type: AlertType,
        count: int,
    ) -> None:
        """Increment the alerts-by-severity counter."""

    @abstractmethod
    def record_flash_overlay(self) -> None:
        """Increment the flash-overlay triggered counter."""


class NoOpAlertMetrics(IAlertMetrics):
    """No-op implementation used in tests and when prometheus is unavailable."""

    def record_alert_fanned_out(
        self,
        severity: AlertSeverity,
        alert_type: AlertType,
        count: int,
    ) -> None:
        pass

    def record_flash_overlay(self) -> None:
        pass
