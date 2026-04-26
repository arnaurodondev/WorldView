"""Concrete Prometheus adapter implementing RagMetricsPort.

Wraps the module-level Prometheus singletons from ``prometheus.py`` so that
the application layer never imports from infrastructure directly.
"""

from __future__ import annotations


class PrometheusRagMetrics:
    """Adapter that delegates to Prometheus metric singletons."""

    def record_query(self, intent: str, provider: str, tenant_id: str) -> None:
        from rag_chat.infrastructure.metrics.prometheus import rag_queries_total

        rag_queries_total.labels(intent=intent, provider=provider, tenant_id=tenant_id).inc()

    def observe_latency(self, intent: str, step: str, duration: float) -> None:
        from rag_chat.infrastructure.metrics.prometheus import rag_latency

        rag_latency.labels(intent=intent, step=step).observe(duration)

    def observe_retrieval_items(self, source_type: str, count: int) -> None:
        from rag_chat.infrastructure.metrics.prometheus import rag_retrieval_items

        rag_retrieval_items.labels(source_type=source_type).observe(count)

    def record_cache_hit(self, cache_type: str) -> None:
        from rag_chat.infrastructure.metrics.prometheus import rag_cache_hits

        rag_cache_hits.labels(cache_type=cache_type).inc()

    def record_contradiction_surfaced(self, claim_type: str) -> None:
        from rag_chat.infrastructure.metrics.prometheus import rag_contradiction_surfaced

        rag_contradiction_surfaced.labels(claim_type=claim_type).inc()

    def record_injection_blocked(self) -> None:
        from rag_chat.infrastructure.metrics.prometheus import rag_injection_blocked

        rag_injection_blocked.inc()

    def set_thread_count(self, tenant_id: str, delta: int) -> None:
        from rag_chat.infrastructure.metrics.prometheus import rag_thread_count

        if delta > 0:
            rag_thread_count.labels(tenant_id=tenant_id).inc(delta)
        elif delta < 0:
            rag_thread_count.labels(tenant_id=tenant_id).dec(abs(delta))

    def record_chunk_cache_hit(self, intent: str) -> None:
        from rag_chat.infrastructure.metrics.prometheus import rag_chunk_cache_hits

        rag_chunk_cache_hits.labels(intent=intent).inc()

    def record_chunk_cache_miss(self, reason: str) -> None:
        from rag_chat.infrastructure.metrics.prometheus import rag_chunk_cache_misses

        rag_chunk_cache_misses.labels(reason=reason).inc()

    def observe_turn_summary_duration(self, duration: float) -> None:
        from rag_chat.infrastructure.metrics.prometheus import rag_turn_summary_duration

        rag_turn_summary_duration.observe(duration)

    def observe_context_token_estimate(self, intent: str, tokens: int) -> None:
        from rag_chat.infrastructure.metrics.prometheus import rag_context_token_estimate

        rag_context_token_estimate.labels(intent=intent).observe(tokens)
