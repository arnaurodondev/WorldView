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

# ── Extraction-endpoint recovery (2026-06-14 entity-ref-matching mitigation) ──
#
# When the deep-extraction LLM emits a relation/event/claim whose endpoint ref
# is NOT one of THIS document's NER mentions, the doc-local ``entity_id_by_ref``
# lookup misses it and the whole row was previously dropped silently (the
# F-CRIT-07 residual: the *opposite* endpoint of a Jackery-style relation was a
# real entity GLiNER never minted a mention for). The layered fix tries two
# precision-safe recoveries before any drop:
#
#   M1 — canonical-store fall-back (cheap, batched): resolve the missed ref
#        against ``entity_aliases``/``canonical_entities`` (exact alias +
#        ticker/ISIN, optional gated fuzzy) behind the 0.75 floor + 0.15 delta
#        gate. A hit binds to a REAL canonical (entity_provisional=False).
#   M2 — provisional minting (live first-touch): for refs still unresolved
#        after M1 and not junk/common-noun, mint a provisional_entity_queue row
#        so the relation PERSISTS with entity_provisional=True and is
#        canonicalized later by the UnresolvedResolutionWorker → KG promotion.
#
# Labelled by ``outcome`` so the recall lift is observable per stage:
#   m1_recovered    — bound to a canonical via the store fall-back
#   m2_minted       — minted a provisional queue row for an unknown endpoint
#   dropped_junk    — failed both M1 and M2 (empty/junk/common-noun ref)
s6_extraction_endpoint_recovery_total = prometheus_client.Counter(
    "s6_extraction_endpoint_recovery_total",
    "Deep-extraction endpoint refs that missed the document-local entity_id_by_ref "
    "lookup, by recovery outcome (M1 canonical-store fall-back / M2 provisional mint / "
    "still-dropped junk). Quantifies the relation-drop mitigation lift.",
    ["outcome"],  # m1_recovered | m2_minted | dropped_junk
)

# Fixed enum of allowed outcome label values — bounds cardinality.
EXTRACTION_ENDPOINT_RECOVERY_OUTCOMES: tuple[str, ...] = (
    "m1_recovered",
    "m2_minted",
    "dropped_junk",
)

# Pre-initialise every outcome child to 0 at import time.  A *labelled*
# prometheus Counter exports NO time series for a label value until that value
# is first ``.inc()``-ed — so a fresh article-consumer process that has not yet
# hit the recovery path exposes the HELP/TYPE header but ZERO
# ``s6_extraction_endpoint_recovery_total{outcome=...}`` samples.  That made the
# metric look "missing" on the /metrics endpoint (port 9100) and broke any
# Grafana panel / alert that expects all three series to exist from boot.
# Seeding each child here guarantees all three outcome series are scrape-able the
# instant the module is imported by the consumer entrypoint — without changing
# any observed value (they start at 0.0, exactly the true count).
for _outcome in EXTRACTION_ENDPOINT_RECOVERY_OUTCOMES:
    s6_extraction_endpoint_recovery_total.labels(outcome=_outcome)


def record_extraction_endpoint_recovery(outcome: str, count: int = 1) -> None:
    """Increment the endpoint-recovery counter for *count* refs.

    ``outcome`` MUST be one of ``EXTRACTION_ENDPOINT_RECOVERY_OUTCOMES``;
    anything else is coerced to ``"dropped_junk"`` to keep cardinality bounded.
    Best-effort — never let a metrics error break the article pipeline.
    """
    if count <= 0:
        return
    label = outcome if outcome in EXTRACTION_ENDPOINT_RECOVERY_OUTCOMES else "dropped_junk"
    s6_extraction_endpoint_recovery_total.labels(outcome=label).inc(count)


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


# ── Learned routing classifier shadow comparison (PLAN-0111 C-6) ─────────────
#
# Cross-tabulates the LIVE (static weighted-sum) tier against the learned
# classifier's PROPOSED tier for every article processed while the learned
# router runs in shadow mode. The {actual_tier, proposed_tier} matrix lets us
# measure agreement / disagreement structure (e.g. "learned upgrades 30% of
# LIGHT to MEDIUM") before any LIVE flip. Cardinality is bounded: both labels
# take values from the fixed 4-tier RoutingTier enum (4x4 = 16 series max).
nlp_pipeline_learned_router_shadow_total = prometheus_client.Counter(
    "nlp_pipeline_learned_router_shadow_total",
    "Learned-router SHADOW comparisons: live static tier vs proposed learned tier "
    "(PLAN-0111 C-6). Labelled by the actual (deployed) tier and the proposed tier.",
    ["actual_tier", "proposed_tier"],
)


def record_learned_router_shadow(actual_tier: str, proposed_tier: str) -> None:
    """Increment the shadow comparison counter for one article.

    Both labels come from the fixed RoutingTier enum, so cardinality is bounded.
    Best-effort: callers invoke this inside a try/except so a metrics error can
    never break the article pipeline.
    """
    nlp_pipeline_learned_router_shadow_total.labels(actual_tier=actual_tier, proposed_tier=proposed_tier).inc()


s6_ollama_queue_depth_current = prometheus_client.Gauge(
    "s6_ollama_queue_depth_current",
    "Current number of in-flight Ollama inference requests (backpressure depth)",
)


# BP-729: embedding-retry billing/auth deferrals + permanent abandons. A spend-cap /
# auth refusal (HTTP 402/401/403) is deferred without consuming the retry budget so a
# transient cap self-heals — but that made a PERSISTENT auth failure (revoked key) loop
# invisibly (structlog line only, no metric). These counters make sustained billing/auth
# deferral alertable and every permanent abandon (fatal 4xx, persistent billing/auth,
# retry exhaustion) observable with a reason label.
s6_embedding_retry_billing_deferred_total = prometheus_client.Counter(
    "s6_embedding_retry_billing_deferred_total",
    "Embedding-retry jobs deferred on a provider billing/auth refusal (HTTP 402/401/403) "
    "WITHOUT consuming the retry budget. A sustained non-zero rate means the DeepInfra "
    "spend cap is hit or the key is refused — raise the cap / fix the key.",
)

s6_embedding_retry_abandoned_total = prometheus_client.Counter(
    "s6_embedding_retry_abandoned_total",
    "Embedding-retry jobs permanently abandoned (skipped by claim_batch forever), by reason: "
    "fatal_4xx (bad input) | billing_auth_persistent (revoked key / cap down past the ceiling) "
    "| retry_exhausted (transient failures exceeded max attempts).",
    ["reason"],
)


def record_embedding_retry_billing_deferred() -> None:
    """Increment the embedding-retry billing/auth-deferral counter (BP-729)."""
    s6_embedding_retry_billing_deferred_total.inc()


def record_embedding_retry_abandoned(reason: str) -> None:
    """Increment the permanent-abandon counter for the embedding-retry worker (BP-729)."""
    s6_embedding_retry_abandoned_total.labels(reason=reason).inc()


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
