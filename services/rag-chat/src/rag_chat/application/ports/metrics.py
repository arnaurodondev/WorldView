"""Metrics port -- application layer boundary for recording RAG pipeline metrics.

The infrastructure layer provides the concrete Prometheus implementation
(``PrometheusRagMetrics``).  Application-layer use cases depend only on this
protocol, preserving hexagonal layer isolation (LAYER-APP-ISOLATION).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class RagMetricsPort(Protocol):
    """Port for recording RAG pipeline metrics.

    Wraps the 7 metric operations used by the application layer:
    query counts, latency, retrieval items, cache hits, contradiction
    surfacing, injection blocking, and thread count tracking.
    """

    def record_query(self, intent: str, provider: str, tenant_id: str) -> None:
        """Increment the total query counter with intent/provider/tenant labels."""
        ...

    def observe_latency(self, intent: str, step: str, duration: float) -> None:
        """Record a latency observation (seconds) for a pipeline step."""
        ...

    def observe_retrieval_items(self, source_type: str, count: int) -> None:
        """Record the number of items retrieved from a given source type."""
        ...

    def record_cache_hit(self, cache_type: str) -> None:
        """Increment the cache-hit counter for the given cache type."""
        ...

    def record_contradiction_surfaced(self, claim_type: str) -> None:
        """Increment the contradiction-surfaced counter for the given claim type."""
        ...

    def record_injection_blocked(self) -> None:
        """Increment the prompt-injection-blocked counter."""
        ...

    def set_thread_count(self, tenant_id: str, delta: int) -> None:
        """Adjust the thread-count gauge for a tenant by ``delta``.

        Positive ``delta`` means threads were created; negative means deleted.
        """
        ...

    def record_chunk_cache_hit(self, intent: str) -> None:
        """Increment the chunk-cache hit counter for the given intent."""
        ...

    def record_chunk_cache_miss(self, reason: str) -> None:
        """Increment the chunk-cache miss counter for the given reason."""
        ...

    def observe_turn_summary_duration(self, duration: float) -> None:
        """Record turn-summary generation latency (seconds)."""
        ...

    def observe_context_token_estimate(self, intent: str, tokens: int) -> None:
        """Record the assembled context token estimate for the given intent."""
        ...
