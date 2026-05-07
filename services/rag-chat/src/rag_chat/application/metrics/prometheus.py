"""Prometheus metrics for the RAG-Chat service (T-F-4-04).

All 10 metrics from PRD §13.1. Metrics are module-level singletons
registered with the default Prometheus registry on import.
"""

from __future__ import annotations

from collections import deque

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

# ── Context management (PRD-0016 §13) ────────────────────────────────────────

rag_chunk_cache_hits = Counter(
    "s8_chunk_cache_hits_total",
    "Chunk cache hits — previous turn's chunks reused (all 3 conditions met)",
    ["intent"],
)

rag_chunk_cache_misses = Counter(
    "s8_chunk_cache_misses_total",
    "Chunk cache misses broken down by reason",
    ["reason"],  # no_cache | intent_mismatch | entity_mismatch | low_similarity
)

rag_turn_summary_duration = Histogram(
    "s8_turn_summary_duration_seconds",
    "Async LLM turn-summary generation latency",
    buckets=[0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
)

rag_context_token_estimate = Histogram(
    "s8_context_token_estimate",
    "Assembled ConversationContext token estimate per intent",
    ["intent"],
    buckets=[500, 1000, 1500, 2000, 3000, 4000, 5000, 6000],
)

# ── Retrieval quality (PLAN-0063 W5-5 T-W5-5-01) ─────────────────────────────

rag_retrieval_score_distribution = Histogram(
    "rag_retrieval_score_distribution",
    "Score distribution of chunks that survive fusion, by source_type",
    ["source"],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.0],
)

rag_source_contribution_total = Counter(
    "rag_source_contribution_total",
    "Number of queries where each source_type contributed at least one chunk to fusion",
    ["source"],
)

rag_reranker_position_change = Gauge(
    "rag_reranker_position_change",
    "Rolling fraction of queries where reranker's top-1 differed from fusion's top-1 (window=100)",
)

# Rolling window backing the gauge above. deque(maxlen=100) keeps the last 100 booleans.
_reranker_position_deque: deque[bool] = deque(maxlen=100)


def record_reranker_position_change(top_changed: bool) -> None:
    """Update the rolling reranker-position-change gauge."""
    _reranker_position_deque.append(top_changed)
    n = len(_reranker_position_deque)
    fraction = sum(_reranker_position_deque) / n if n > 0 else 0.0
    rag_reranker_position_change.set(fraction)


# ── Citation accuracy (PLAN-0063 W5-5 T-W5-5-02) ─────────────────────────────

rag_citation_accuracy = Gauge(
    "rag_citation_accuracy",
    "Mean citation accuracy score from weekly LLM-as-judge (0=irrelevant … 1=direct)",
)
