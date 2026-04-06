"""Prometheus metrics for the RAG-Chat service (T-F-4-04).

All 10 metrics from PRD §13.1. Metrics are module-level singletons
registered with the default Prometheus registry on import.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── Query lifecycle ──────────────────────────────────────────────────────────

rag_queries_total = Counter(
    "rag_chat_queries_total",
    "Total chat queries processed",
    ["intent", "provider", "tenant_id"],
)

rag_latency = Histogram(
    "rag_chat_latency_seconds",
    "Per-request latency broken down by pipeline step",
    ["intent", "step"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

rag_first_token = Histogram(
    "rag_chat_first_token_seconds",
    "Time to first token from LLM provider",
    ["provider"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

rag_retrieval_items = Histogram(
    "rag_retrieval_items_total",
    "Number of items retrieved per query by source type",
    ["source_type"],
    buckets=[0, 1, 5, 10, 15, 20, 30, 50],
)

# ── Cache ────────────────────────────────────────────────────────────────────

rag_cache_hits = Counter(
    "rag_cache_hit_total",
    "Number of cache hits",
    ["cache_type"],  # completion, hyde
)

# ── Provider ─────────────────────────────────────────────────────────────────

rag_provider_fallback = Counter(
    "rag_provider_fallback_total",
    "Number of provider fallback activations",
    ["from_provider", "to_provider"],
)

rag_provider_unavail = Counter(
    "rag_provider_unavailable_total",
    "Number of negative cache activations per provider",
    ["provider"],
)

# ── Threads ──────────────────────────────────────────────────────────────────

rag_thread_count = Gauge(
    "rag_thread_count",
    "Number of active (non-archived) conversation threads",
    ["tenant_id"],
)

# ── Safety ───────────────────────────────────────────────────────────────────

rag_contradiction_surfaced = Counter(
    "rag_contradiction_surfaced_total",
    "Number of contradictions surfaced to users",
    ["claim_type"],
)

rag_injection_blocked = Counter(
    "rag_injection_blocked_total",
    "Number of prompt injection attempts blocked",
)
