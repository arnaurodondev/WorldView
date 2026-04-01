"""Prometheus metrics for the Knowledge Graph service (S7).

Custom counters track the volume of each background worker's main operation.
"""

from __future__ import annotations

from prometheus_client import Counter

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
