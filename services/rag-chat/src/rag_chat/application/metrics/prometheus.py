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

# E-8: Layer 2 (LLM semantic) injection blocks specifically.
# Distinct from rag_injection_blocked (which covers Layer 1 regex + Layer 2).
rag_injection_blocked_layer2 = Counter(
    "rag_injection_blocked_layer2_total",
    "Number of prompt injection attempts blocked by Layer 2 LLM semantic classifier",
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


# ── Citation accuracy (PLAN-0063 W5-5 T-W5-5-02, PLAN-0084 A-1) ─────────────

rag_citation_accuracy = Gauge(
    "rag_citation_accuracy",
    "Mean citation accuracy score from weekly LLM-as-judge (0=irrelevant … 1=direct)",
)

# PLAN-0084 A-1 T-A-1-04: per-call failure counter for the citation judge cron.
# label reason: "timeout" | "provider_error" | "invalid_response"
rag_citation_accuracy_call_failures_total = Counter(
    "rag_citation_accuracy_call_failures_total",
    "Number of citation-accuracy judge call failures, broken down by reason",
    ["reason"],
)

# ── Circuit breaker (PLAN-0084 A-2 T-A-2-04) ─────────────────────────────────

rag_circuit_breaker_open = Gauge(
    "rag_circuit_breaker_open",
    "1 if circuit breaker is open for the labelled source, 0 otherwise.",
    ["source"],
)

# ── Security (F-S004) ─────────────────────────────────────────────────────────

rag_jti_check_bypass_total = Counter(
    "rag_jti_check_bypass_total",
    "Number of JTI replay checks bypassed due to Valkey unavailability (fail-open). Alert threshold: >0 in production.",
)

# ── Tool-use metrics (PLAN-0067 W11-3) ───────────────────────────────────────

rag_tool_call_total = Counter(
    "rag_tool_call_total",
    "Number of tool calls executed in the tool-use path",
    ["tool_name", "status"],  # status: "ok" | "empty" | "error"
)

rag_tool_call_latency_seconds = Histogram(
    "rag_tool_call_latency_seconds",
    "Tool call execution latency in seconds",
    ["tool_name"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

rag_tool_use_first_turn_latency_seconds = Histogram(
    "rag_tool_use_first_turn_latency_seconds",
    "Latency of the first LLM turn (blocking, non-streaming) in the tool-use path",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0],
)

# ── E-6: Multi-turn agent loop (AgentBudget) ──────────────────────────────────

rag_agent_iterations = Histogram(
    "rag_agent_iterations",
    "Number of tool-use iterations per query",
    buckets=[1, 2, 3, 4, 5, 6, 7, 8],
)

rag_budget_exceeded_total = Counter(
    "rag_budget_exceeded_total",
    "Budget exceeded events by type",
    ["budget_type"],  # "latency" | "iterations" | "consecutive_errors"
)

# ── E-7: Citation egress allowlist ────────────────────────────────────────────

rag_citations_scrubbed_total = Counter(
    "rag_citations_scrubbed_total",
    "Citation references scrubbed from answers (not grounded in tool results)",
)

# ── PLAN-0093 Wave E-2: numeric-grounding validator ──────────────────────────

rag_grounding_validation_total = Counter(
    "rag_grounding_validation_total",
    "Numeric grounding validator outcomes per chat turn",
    # passed: response numbers all matched tool results within tolerance
    # failed_one_rewrite: first pass failed → LLM re-prompted → second pass passed
    # failed_banner: both passes failed → banner appended to the response
    ["result"],
)

# ── E-12: Per-turn audit log ──────────────────────────────────────────────────

rag_audit_entries_total = Counter(
    "rag_audit_entries_total",
    "Number of chat audit log entries written",
)
