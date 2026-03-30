"""Metrics port — application layer boundary for recording fetch metrics.

The infrastructure layer provides the concrete Prometheus implementation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MetricsPort(Protocol):
    """Port for recording fetch-cycle metrics."""

    def record_fetch(
        self,
        source: str,
        *,
        fetched: int,
        skipped: int,
        failed: int,
        duration: float,
    ) -> None:
        """Record metrics for a completed fetch cycle."""
        ...
