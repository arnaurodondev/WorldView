"""Worker 13J structured enrichment metrics (PLAN-0073 §17.2).

Defined here (application layer) so StructuredEnrichmentUseCase can import them
without crossing into infrastructure/. prometheus.py re-exports from here.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram  # type: ignore[import-not-found]

s7_enrichment_entities_total = Counter(
    "s7_enrichment_entities_total",
    "Total entities enriched by Worker 13J, by entity_type and outcome.",
    ["entity_type", "outcome"],
)

s7_enrichment_source_total = Counter(
    "s7_enrichment_source_total",
    "Total enrichments by description source (market_data | eodhd | llm | none).",
    ["source"],
)

s7_enrichment_market_data_miss_total = Counter(
    "s7_enrichment_market_data_miss_total",
    "Cascade misses where market-data lookup returned no instrument profile.",
)

s7_enrichment_llm_latency_seconds = Histogram(
    "s7_enrichment_llm_latency_seconds",
    "Wall-clock latency of the Worker 13J LLM description call in seconds.",
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0),
)

s7_enrichment_data_completeness = Histogram(
    "s7_enrichment_data_completeness",
    "Distribution of computed data_completeness scores from Worker 13J (0.0-1.0).",
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

s7_enrichment_sweep_entities_processed_total = Counter(
    "s7_enrichment_sweep_entities_processed_total",
    "Total entities processed by the Worker 13J catch-up sweep, by outcome.",
    ["outcome"],
)

s7_enrichment_relations_seeded_total = Counter(
    "s7_enrichment_relations_seeded_total",
    "Total structural relations seeded by Worker 13J, by canonical_type.",
    ["canonical_type"],
)

# F-DB-005 (2026-05-28): per-error-class counter for FundamentalsRefreshWorker.
# Replaces the silent ``or "unknown"`` fallback at fundamentals_refresh.py:543.
# ``error_kind`` is one of the values in ``FundamentalsRefreshError`` (see the
# worker module). A non-zero ``schema_unparsable`` or ``missing_sections`` count
# means the worker is hitting a contract drift between market-data and the
# narrative builder — i.e. exactly the F-DB-005 bug class.
fundamentals_refresh_failed_total = Counter(
    "fundamentals_refresh_failed_total",
    "FundamentalsRefreshWorker failures by structured error class.",
    ["error_kind"],
)

# 2026-06-11 relations-FK-crash fix: entity-existence gate in materialize_graph.
# Before this gate, ``relation_repo.upsert`` was called unconditionally and a
# missing subject/object entity raised ForeignKeyViolationError, aborting the
# WHOLE enriched-article transaction — so ``relations`` stopped growing (stuck
# at 959 edges) while ``relation_evidence_raw`` kept writing. The gate now defers
# such relations (writes the evidence row with entity_provisional=true) instead
# of crashing. ``reason`` is one of: subject_missing | object_missing | both_missing.
s7_relation_entity_missing_total = Counter(
    "s7_relation_entity_missing_total",
    "Relations deferred because subject/object entity did not yet exist in "
    "canonical_entities (would have FK-crashed the upsert).",
    ["reason"],
)

# 2026-06-11 edge-materialization-on-unblock fix: when an entity finally lands
# (entity.canonical.created.v1), its previously-deferred provisional evidence
# rows are unblocked AND the now-resolvable graph edges are upserted into
# ``relations``. This counter tracks edges materialized via that deferred path
# (as opposed to the hot enriched path), so we can see the backlog draining.
s7_relation_edge_materialized_on_unblock_total = Counter(
    "s7_relation_edge_materialized_on_unblock_total",
    "Graph edges upserted into ``relations`` when a newly-created entity "
    "unblocked previously-deferred provisional relation evidence.",
)
