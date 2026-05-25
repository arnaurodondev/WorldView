"""Prometheus metrics for the Knowledge Graph service (S7).

Custom counters track the volume of each background worker's main operation.

PLAN-0073 F-A07 / F-P2-02 — Worker 13J (StructuredEnrichment) counters defined
below and wired at these sites:
  - ``application/use_cases/structured_enrichment.py`` increments
    ``entities_total``, ``source``, ``market_data_miss``, ``llm_latency_seconds``,
    ``data_completeness``, ``relations_seeded_total``.
  - ``infrastructure/workers/structured_enrichment_worker.py`` increments
    ``sweep_entities_processed_total`` and ``entities_total{outcome="retryable"|"fatal"}``
    on the sweep error paths.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# Worker 13J metrics: defined in application/metrics.py and re-exported here so
# infrastructure/workers/structured_enrichment_worker.py can import without a
# cross-layer jump.  Listed in __all__ to prevent ruff F401 removal.
from knowledge_graph.application.metrics import (
    s7_enrichment_data_completeness as s7_enrichment_data_completeness,
)
from knowledge_graph.application.metrics import (
    s7_enrichment_entities_total as s7_enrichment_entities_total,
)
from knowledge_graph.application.metrics import (
    s7_enrichment_llm_latency_seconds as s7_enrichment_llm_latency_seconds,
)
from knowledge_graph.application.metrics import (
    s7_enrichment_market_data_miss_total as s7_enrichment_market_data_miss_total,
)
from knowledge_graph.application.metrics import (
    s7_enrichment_relations_seeded_total as s7_enrichment_relations_seeded_total,
)
from knowledge_graph.application.metrics import (
    s7_enrichment_source_total as s7_enrichment_source_total,
)
from knowledge_graph.application.metrics import (
    s7_enrichment_sweep_entities_processed_total as s7_enrichment_sweep_entities_processed_total,
)

# ── Counters ─────────────────────────────────────────────────────────────────

s7_relations_upserted_total = Counter(
    "s7_relations_upserted_total",
    "Total relation upserts performed by the hot-path write block (Block 12a).",
)

s7_evidence_appended_total = Counter(
    "s7_evidence_appended_total",
    "Total evidence rows appended to relation_evidence_raw.",
)

s7_contradictions_detected_total = Counter(
    "s7_contradictions_detected_total",
    "Total contradictions detected (Blocks 12b + 13B).",
)

s7_confidence_recomputed_total = Counter(
    "s7_confidence_recomputed_total",
    "Total relation confidence recomputations (Worker 13A).",
)

s7_summaries_generated_total = Counter(
    "s7_summaries_generated_total",
    "Total LLM relation summaries generated (Worker 13C).",
)

s7_embeddings_refreshed_total = Counter(
    "s7_embeddings_refreshed_total",
    "Total entity/relation embeddings refreshed, by worker.",
    ["worker"],
)

s7_worker_crash_total = Counter(
    "s7_worker_crash_total",
    "Total unhandled exceptions from background worker jobs, by worker.",
    ["worker"],
)

s7_economic_events_ingested_total = Counter(
    "s7_economic_events_ingested_total",
    "Total economic events upserted by Worker 13D-6, by country.",
    ["country"],
)

s7_macro_indicator_updates_total = Counter(
    "s7_macro_indicator_updates_total",
    "Total country entities re-enriched with macro indicators by Worker 13D-7, by country.",
    ["country"],
)

s7_age_sync_entities_total = Counter(
    "s7_age_sync_entities_total",
    "Total canonical_entities vertices synced to AGE by Worker 13F per run.",
)

s7_age_sync_relations_total = Counter(
    "s7_age_sync_relations_total",
    "Total relation edges synced to AGE by Worker 13F per run.",
)

s7_age_sync_duration_seconds = Histogram(
    "s7_age_sync_duration_seconds",
    "Duration of a single Worker 13F AGE shadow sync run in seconds.",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600),
)

# PLAN-0093 B-1 (T-B-1-03): per-phase stall detector.  Incremented when a sync
# phase reports synced_count == 0 even though the source table has rows newer
# than the watermark — indicates a silent sync failure (e.g. AGE label missing,
# Cypher MERGE silently no-op'ing).
s7_age_sync_phase_stalled_total = Counter(
    "s7_age_sync_phase_stalled_total",
    "Times an AGE sync phase reported 0 rows synced despite the source table having newer rows.",
    ["phase"],
)

s7_insider_transactions_relations_total = Counter(
    "s7_insider_transactions_relations_total",
    "Total has_executive relations upserted by Worker 13D-8, by ticker.",
    ["ticker"],
)

s7_insider_transactions_skipped_total = Counter(
    "s7_insider_transactions_skipped_total",
    "Total insider transactions skipped by Worker 13D-8 (non-executive title, no name), by reason.",
    ["reason"],
)

s7_provisional_enrichment_failed_total = Counter(
    "s7_provisional_enrichment_failed_total",
    "Total provisional entity queue rows transitioned to terminal 'failed' status (max retries exceeded).",
)

s7_provisional_enrichment_success_total = Counter(
    "s7_provisional_enrichment_success_total",
    "Total provisional entity queue rows successfully enriched and transitioned to 'resolved' status.",
)

s7_provisional_queue_stuck_total = Counter(
    "s7_provisional_queue_stuck_total",
    "Total provisional entity queue rows stuck in 'processing' due to retry transition failure.",
)

s7_provisional_stuck_recovered_total = Counter(
    "s7_provisional_stuck_recovered_total",
    "Provisional queue rows recovered by stale-processing sweep (reset 'processing'->'pending').",
)

# ── PLAN-0068 Wave A-1: Earnings Calendar consumer (13D-9) ───────────────────

s7_earnings_calendar_events_ingested_total = Counter(
    "s7_earnings_calendar_events_ingested_total",
    "Total earnings calendar events upserted by consumer 13D-9, by ticker.",
    ["ticker"],
)

# ── PLAN-0072 Wave 1: Noise filtering counters ────────────────────────────────

s7_provisional_noise_filtered_total = Counter(
    "s7_provisional_noise_filtered_total",
    "Provisional queue rows rejected by the Layer 1 static blocklist (no LLM call).",
)

s7_provisional_noise_llm_filtered_total = Counter(
    "s7_provisional_noise_llm_filtered_total",
    "Provisional queue rows rejected by the Layer 2 cheap LLM classifier.",
)

# ── E-3 Evidence Quality Gate (Worker 13B) ────────────────────────────────────

kg_evidence_quality_gated_total = Counter(
    "kg_evidence_quality_gated_total",
    "Relation evidence rows blocked by quality gate (low confidence + low density).",
)


# ── PLAN-0093 Sub-Plan D — KG refresh workers (path-insight + summary) ────────

# T-D-1-02 — gauge for path_insights rows still awaiting an LLM explanation.
# A row is "pending" when llm_explanation IS NULL AND computed_at is older than
# 1 hour (so we are not counting freshly-seeded rows that are about to be
# explained on the next sweep).  Updated once per PathExplanationBatchWorker
# cycle.  Alert rule: > 100 for 30 min.
path_insight_explanation_pending_total = Gauge(
    "path_insight_explanation_pending_total",
    "Count of path_insights rows with llm_explanation IS NULL older than 1 hour.",
)

# T-D-3-01 — gauge for relations missing a fresh summary.  A relation is in
# the backlog when summary_stale=true OR no current row in relation_summaries.
# Updated once per SummaryWorker cycle.  Alert rule: > 1000 for 1 h.
relation_summary_backlog = Gauge(
    "relation_summary_backlog",
    "Count of relations whose summary is stale or missing entirely.",
)

# T-D-3-03 — counter for relations that have failed summary generation
# repeatedly (>= 3 attempts) without success.  Lets us identify pathological
# rows (e.g. zero evidence) for tombstoning.
summary_worker_stuck_relations_total = Counter(
    "summary_worker_stuck_relations_total",
    "Relations whose summary generation has failed >= 3 consecutive times.",
)
