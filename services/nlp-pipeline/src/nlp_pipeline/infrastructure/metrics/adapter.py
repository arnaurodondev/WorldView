"""Concrete Prometheus adapter implementing NlpMetricsPort.

Wraps the module-level Prometheus singletons from ``prometheus.py`` so that
the application layer never imports from infrastructure directly.
"""

from __future__ import annotations


class PrometheusNlpMetrics:
    """Adapter that delegates to Prometheus metric singletons."""

    def record_sectioning_fallback(self) -> None:
        from nlp_pipeline.infrastructure.metrics.prometheus import nlp_sectioning_fallback_total

        nlp_sectioning_fallback_total.inc()
