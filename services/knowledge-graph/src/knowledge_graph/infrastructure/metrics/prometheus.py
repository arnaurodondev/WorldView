"""Prometheus metrics for the Knowledge Graph service (S7).

Custom counters track the volume of each background worker's main operation.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

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
