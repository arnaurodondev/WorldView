"""Prometheus metrics definitions for the NLP Pipeline service (S6).

Custom metrics — STANDARDS.md §5 requires using create_metrics() from observability
for the generic service metrics (request counts, latency). The domain-specific
counters and gauges defined here are supplementary.
"""

from __future__ import annotations

import prometheus_client

# ── Article processing ────────────────────────────────────────────────────────

s6_articles_processed_total = prometheus_client.Counter(
    "s6_articles_processed_total",
    "Total articles processed by routing tier",
    ["routing_tier"],
)

s6_ner_mentions_total = prometheus_client.Counter(
    "s6_ner_mentions_total",
    "Total GLiNER entity mentions extracted across all processed articles",
)

s6_embeddings_created_total = prometheus_client.Counter(
    "s6_embeddings_created_total",
    "Total chunk and section embeddings successfully created",
)

s6_entity_resolved_total = prometheus_client.Counter(
    "s6_entity_resolved_total",
    "Total entity mentions resolved, by resolution method",
    ["method"],  # exact | ticker | fuzzy | ann
)

s6_claims_extracted_total = prometheus_client.Counter(
    "s6_claims_extracted_total",
    "Total claims extracted by deep LLM extraction (Block 10)",
)

s6_extraction_entity_ref_hallucinated_total = prometheus_client.Counter(
    "s6_extraction_entity_ref_hallucinated_total",
    "Entity refs produced by the extraction LLM that were not in the entities list "
    "(hallucination signal — refs invented by the model rather than copied from input)",
)

# Task #22 (BP-677): deep-extraction window-level transient failures (timeouts,
# 429s, 5xx, connection errors — anything the extraction adapter raises as a
# RetryableError). Previously these were silently swallowed and substituted with
# an empty {events:[], claims:[], relations:[]} result, making a timed-out
# extraction indistinguishable from a genuinely empty article (the ~16% timeout
# rate was hidden as fake "0 events/0 claims/0 relations" completions). This
# counter makes the per-window timeout rate observable in Prometheus.
deep_extraction_window_timeout_total = prometheus_client.Counter(
    "deep_extraction_window_timeout_total",
    "Deep-extraction (Block 10) windows that failed with a transient/timeout error "
    "(RetryableError) instead of returning a parsed result. A non-zero rate here "
    "explains all-zero extraction completions that are degraded, not truly empty.",
)

nlp_sectioning_fallback_total = prometheus_client.Counter(
    "nlp_sectioning_fallback_total",
    "Times the synthetic (fallback) sectioner was used because source_type was unknown",
)

# ── Backpressure gauge (polled from BackpressureController) ──────────────────

s6_intel_commit_failures_total = prometheus_client.Counter(
    "s6_intel_commit_failures_total",
    "Total times the intel_session.commit() failed after nlp_session.commit() succeeded "
    "(D-004 dual-commit path). Non-zero values indicate intelligence-db write failures "
    "that require message re-delivery for provisional-entity-queue recovery.",
)

# ── Pre-persist tenant_id substitution (PLAN-0099 W2 T-W2-04) ─────────────────
# Defence-in-depth instrumentation for the pre-persist safety net at
# article_consumer._run_pipeline. Bounded-cardinality counter attributing
# null-tenant_id substitutions (BP-575/586) to the upstream block source.
nlp_pipeline_pre_persist_tenant_id_substituted_total = prometheus_client.Counter(
    "nlp_pipeline_pre_persist_tenant_id_substituted_total",
    "Times the pre-persist safety net substituted tenant_id on an EntityMention "
    "that arrived at the persist boundary with tenant_id=None (BP-575/BP-586). "
    "Labelled by the inferred upstream block source.",
    ["block_source"],
)

# Fixed enum of allowed block_source label values — referenced from the
# consumer's classifier helper. Keep in sync with the docstring above.
PRE_PERSIST_BLOCK_SOURCES: tuple[str, ...] = (
    "ner",
    "entity_resolution",
    "novelty_backfill",
    "deep_extraction",
    "unknown",
)


def record_pre_persist_tenant_substituted(block_source: str) -> None:
    """Increment the pre-persist tenant_id substitution counter.

    ``block_source`` MUST be one of ``PRE_PERSIST_BLOCK_SOURCES``. Anything
    else is silently coerced to ``"unknown"`` to enforce bounded cardinality.
    """
    label = block_source if block_source in PRE_PERSIST_BLOCK_SOURCES else "unknown"
    nlp_pipeline_pre_persist_tenant_id_substituted_total.labels(block_source=label).inc()


s6_ollama_queue_depth_current = prometheus_client.Gauge(
    "s6_ollama_queue_depth_current",
    "Current number of in-flight Ollama inference requests (backpressure depth)",
)


def record_article_processed(routing_tier: str) -> None:
    """Increment per-tier article counter."""
    s6_articles_processed_total.labels(routing_tier=routing_tier).inc()


def record_entity_resolved(method: str) -> None:
    """Increment per-method entity resolution counter."""
    s6_entity_resolved_total.labels(method=method).inc()


# ── Display relevance score path tracking (PLAN-0063 W5-5 T-W5-5-01) ─────────

news_display_score_path_total = prometheus_client.Counter(
    "news_display_score_path_total",
    "Tracks which display_relevance_score formula path was used per article row",
    ["path"],  # full_formula | no_price_impact | no_llm_score | routing_only
)


def record_display_score_path(
    market_impact_score: float | None,
    llm_relevance_score: float | None,
) -> None:
    """Classify and increment the display-score path counter."""
    if market_impact_score is not None and market_impact_score > 0 and llm_relevance_score is not None:
        path = "full_formula"
    elif market_impact_score is not None and market_impact_score > 0:
        path = "no_llm_score"
    elif llm_relevance_score is not None:
        path = "no_price_impact"
    else:
        path = "routing_only"
    news_display_score_path_total.labels(path=path).inc()


# ── Full-text document search (PLAN-0064 W6) ─────────────────────────────────

s6_search_documents_total = prometheus_client.Counter(
    "s6_search_documents_total",
    "Total document search requests by source_type and status",
    ["source_type", "status"],  # status: ok | error | empty
)

s6_search_documents_duration_seconds = prometheus_client.Histogram(
    "s6_search_documents_duration_seconds",
    "Document search end-to-end duration in seconds",
    ["source_type"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

s6_search_documents_results_count = prometheus_client.Histogram(
    "s6_search_documents_results_count",
    "Distribution of result counts per search request",
    ["source_type"],
    buckets=[0, 1, 5, 10, 25, 50, 100, 500, 1000],
)
