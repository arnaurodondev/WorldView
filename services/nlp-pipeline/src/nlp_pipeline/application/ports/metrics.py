"""Metrics port -- application layer boundary for recording NLP pipeline metrics.

The infrastructure layer provides the concrete Prometheus implementation
(``PrometheusNlpMetrics``).  Application-layer blocks depend only on this
protocol, preserving hexagonal layer isolation (LAYER-APP-ISOLATION).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class NlpMetricsPort(Protocol):
    """Port for recording NLP pipeline metrics.

    Wraps metric operations used by the application layer so that
    application code never imports from infrastructure.metrics directly.
    """

    def record_sectioning_fallback(self) -> None:
        """Increment the sectioning-fallback counter.

        Called when the synthetic (fallback) sectioner is used because
        source_type is unknown or a source-specific sectioner returns no sections.
        """
        ...

    def record_deep_extraction_window_timeout(self) -> None:
        """Increment the deep-extraction window-timeout counter.

        Task #22 (BP-677): called when a single extraction window hits a
        transient/timeout failure so the per-window failure rate is observable
        in Prometheus, not just logs.
        """
        ...


class _NoOpNlpMetrics:
    """No-op implementation used as a default when no metrics adapter is injected.

    This allows pure-function callers (e.g. tests) to call application-layer
    blocks without wiring up a Prometheus adapter.
    """

    def record_sectioning_fallback(self) -> None:
        """No-op."""

    def record_deep_extraction_window_timeout(self) -> None:
        """No-op."""


NOOP_METRICS: NlpMetricsPort = _NoOpNlpMetrics()
