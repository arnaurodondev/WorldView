# Investigation Report: All Discovered Issues — Root Cause & Long-Term Solutions

**Date**: 2026-05-04
**Investigator**: Claude (investigation skill)
**Severity**: CRITICAL (BP-349), MEDIUM (QG-2, QG-3), LOW (QG-1, QG-4, QG-5, QG-6)
**Status**: Root cause identified for all issues

---

## 1. Issue Summary

Seven issues were identified across two investigation sessions on 2026-05-03/04:
- **BP-349**: Block 13E never emits temporal events (field name mismatch)
- **QG-1**: 2771/3890 routing_decisions have NULL processing_path
- **QG-2**: LLM event_type has no enum constraint — hallucinated values silently dropped
- **QG-3**: Macro/geopolitical events with no entity refs silently dropped by Block 13E
- **QG-4**: 927 relation_evidence_raw rows missing evidence_text (pre-BP-345 backlog)
- **QG-5**: 186 DLQ entries from 45s timeout (pre-BP-324 data)
- **QG-6**: final_routing_tier always NULL in routing_decisions

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| Block 13E temporal events = 0 from NLP | `intelligence_db.temporal_events` query | Confirms BP-349 — no NLP-sourced events |
| `_emit_temporal_events` reads `extraction_confidence` | `article_consumer.py:1438` | Expects normalized field name |
| Block 13E call site passes raw extraction result | `article_consumer.py:620` | Raw dict has `confidence`, not `extraction_confidence` |
| `_build_raw_events` normalizes `confidence→extraction_confidence` at line 1286 | `article_consumer.py:1286` | Normalization happens here — Block 13E bypasses it |
| `_EXTRACTION_SCHEMA event_type` has `{"type": "string"}` only | `deep_extraction.py:65` | No enum validation — LLM can return any string |
| `_build_raw_events` skips events with no resolvable entity | `article_consumer.py:1278` | `if subject_id is None: continue` |
| 2771 rows have `processing_path=NULL` from Apr 26-29 | `nlp_db.routing_decisions` | All pre-migration 0015 (added 2026-04-30) |
| Migration 0015 `Create Date: 2026-04-30` | `alembic/versions/0015_*` | Confirms dates: old rows couldn't have had the column |
| Kafka lag for `nlp-pipeline-group` = 82 messages | `kafka-consumer-groups` output | Active small backlog, not 2771 stuck articles |
| 927/1178 relation_evidence_raw rows have NULL evidence_text | `intelligence_db.relation_evidence_raw` | Pre-BP-345 data |
| `article_consumer_main.py:183` sets `message_processing_timeout_s=300` | Source code | BP-324 already fixed the 45s issue |
| 186 DLQ entries dated May 1-3 | `intelligence_db.dead_letter_queue` | All pre-300s fix deployment |
| `novelty.py:149,166` sets `final_routing_tier = RoutingTier.LIGHT` | Source code | Only set on downgrade — NULL means no downgrade occurred |
| 0/3890 routing_decisions have `final_routing_tier` set | DB query | No novelty downgrades yet (expected for fresh pipeline) |

---

## 3. Issue-by-Issue Root Cause Analysis

---

### BP-349: Block 13E Field Name Mismatch (CRITICAL)

**Root cause**: Block 13E (lines 619–627) passes the raw LLM extraction output dict directly to `_emit_temporal_events`, but `_emit_temporal_events` expects the POST-`_build_raw_events` normalized format.

**Exact divergence**:
| Field in raw LLM dict | Expected by `_emit_temporal_events` | Result |
|---|---|---|
| `confidence` | `extraction_confidence` | Reads 0.0 → all events fail 0.5 threshold |
| `description` | `event_text` | Reads "" → title always blank |
| `entity_refs: [str]` | `participant_entity_ids: [UUID]` | No entity UUIDs → empty exposed_entities |

**Location**: `article_consumer.py:620`
```python
# BAD: raw LLM output
raw_events=extraction_result.get("events", [])

# The full processing chain calls _build_raw_events at line 1000,
# but Block 13E bypasses it and passes the unprocessed dict.
```

**Trigger condition**: Every deep-tier article that Block 10 extracts events from.

**Impact**: Zero NLP-sourced temporal events ever emitted. The `intelligence.temporal_event.v1` topic is never published from the NLP pipeline despite articles containing macro/geopolitical content.

**Long-term fix**: Add `_normalize_temporal_events_for_emit()` — a variant of `_build_raw_events` that normalizes field names and resolves entity refs BUT does not skip events with zero entity refs. Call it at the Block 13E call site (lines 619–627).

---

### QG-1: 2771 NULL processing_path Rows (NOT A BUG)

**Root cause**: Historical schema gap — migration `0015` (created 2026-04-30) added the `processing_path` column with `nullable=True`. All 2771 articles processed on Apr 26-29 predate this migration and legitimately have NULL.

**Evidence**: 100% of rows with `processing_path IS NOT NULL` have `decided_at >= 2026-05-01`. 0% of rows from Apr 26-29 have it set. The Kafka consumer has only 82-message backlog — not 2771 stuck messages.

**Impact**: None. The column was designed nullable for this exact backward-compat reason. The consumer's `_final_tier` logging at line 658 uses `routing_decision.final_routing_tier or routing_decision.routing_tier` which is not affected.

**Long-term**: No fix needed. These rows are correctly historical. If analytics require processing_path for old rows, a data migration could set it to `full_pipeline` for rows where `events` / `relation_evidence_raw` exist (evidence of full pipeline completion), but this is low value.

---

### QG-2: No Enum Constraint on event_type (MEDIUM)

**Root cause**: `_EXTRACTION_SCHEMA["properties"]["events"]["items"]["properties"]["event_type"]` is defined as `{"type": "string"}` with no `"enum"` field. 8B-class LLMs (Meta-Llama-3.1-8B) frequently return non-canonical event type strings: `"earnings release"` instead of `"EARNINGS_RELEASE"`, `"ipo"` instead of `"CAPITAL_RAISE"`, `"acquisition"` instead of `"M_AND_A"`.

**Impact**: Events with non-canonical types pass JSON schema validation, pass `_build_raw_events` (which stores them as-is), but fail the KG consumer's `_SUPPORTED_EVENT_TYPES` filter. Events are silently dropped at the KG layer. Magnitude unknown but likely significant for non-EARNINGS event types.

**Trigger condition**: Every deep-tier article where the LLM uses a non-canonical event type string.

**Long-term fix**: Add `"enum"` with the full list of canonical event types to `_EXTRACTION_SCHEMA`. This triggers JSON schema validation failure at the LLM response parse step, which causes the extraction to retry or default to `"OTHER"`, rather than silently propagating garbage through the pipeline.

The full canonical enum (from S7's `_SUPPORTED_EVENT_TYPES`):
```
EARNINGS_RELEASE, M_AND_A, REGULATORY_ACTION, MACRO, MANAGEMENT_CHANGE,
PRODUCT_LAUNCH, CAPITAL_RAISE, LEGAL, ANALYST_RATING, GUIDANCE_RAISE,
NATURAL_DISASTER, GEOPOLITICAL, SANCTIONS, OTHER
```

---

### QG-3: Macro Events Without Entity Refs Silently Dropped (MEDIUM)

**Root cause**: Both `_build_raw_events` (line 1278: `if subject_id is None: continue`) and `_emit_temporal_events` (which expects pre-resolved `participant_entity_ids`) are designed around entity-centric events. Macro/geopolitical events like "Fed raises interest rates" or "EU sanctions Russia" have no specific company entity refs — they are global scope events.

**Impact**: Macro-scope temporal events from NLP extraction are always dropped (once BP-349 is fixed), because they have no company entity refs. The KG consumer DOES support empty `exposed_entities` (it just doesn't create `entity_event_exposures` rows). This is a significant gap: macro events are the most market-relevant temporal signals.

**Trigger condition**: Any `MACRO`, `GEOPOLITICAL`, `SANCTIONS`, `NATURAL_DISASTER`, `REGULATORY_ACTION` event where the LLM includes no `entity_refs` (common for global macro events).

**Long-term fix**: The normalization helper added for BP-349 (`_normalize_temporal_events_for_emit`) should NOT skip events with zero resolved entities. Instead it should pass `participant_entity_ids: []` and let `_emit_temporal_events` emit a temporal event with an empty `exposed_entities` list. The temporal event record itself is still valuable for the KG's temporal context queries.

---

### QG-4: 927 relation_evidence_raw Rows Missing evidence_text (LOW)

**Root cause**: Pre-BP-345 rows (before the fix that wired evidence_text through the NLP→S7 chain). These rows were written when `article_consumer.py` did not propagate the `evidence_text` field from the LLM extraction output to the Kafka event payload.

**Evidence**: 1178 total rows in `relation_evidence_raw`; 251 have evidence_text (21%); 927 do not (79%). The 961 unprocessed rows are the pre-fix backlog.

**Impact**: LOW. The knowledge graph `RelationScheduler` worker processes `relation_evidence_raw → relation_evidence` and can function without `evidence_text` (it uses `extraction_confidence` for scoring). The `evidence_text` is only used for relation context explanations in RAG responses.

**Long-term fix**: Accept as historical data quality gap. Options:
1. **Backfill via re-ingestion** (HIGH COST): Re-fetch the 927 source articles from MinIO, re-run Block 10 extraction, update `relation_evidence_raw.evidence_text`. Requires a one-time worker script. Not recommended for 927 rows.
2. **Accept gap** (RECOMMENDED): New rows will all have evidence_text. The 927 old rows will have `evidence_text=NULL` which the RAG pipeline can handle gracefully. Document as known historical gap.
3. **Mark as processed** (PRAGMATIC): If the `evidence_text` is not required for scheduler correctness, mark the 927 rows as processed and let the RelationScheduler build relations from them — they'll just lack evidence text in the relation summaries.

---

### QG-5: 186 DLQ Timeout Entries (ALREADY FIXED)

**Root cause**: `BaseKafkaConsumer.message_processing_timeout_s` defaults to 45 seconds (see `libs/messaging/src/messaging/kafka/consumer/base.py:86`). DeepInfra extraction can take 60–180s. Articles hitting this watchdog went to DLQ.

**Status**: ALREADY FIXED by BP-324. `article_consumer_main.py:183` sets `message_processing_timeout_s=300`. The 186 DLQ entries are from before this fix was deployed (dated May 1-3, 2026). No new DLQ entries are expected under normal load.

**Impact**: 186 articles were dead-lettered and not processed. These may need to be re-ingested if their content is valuable.

**Long-term**: Monitor DLQ count going forward. If new entries appear with 45s timeouts, the fix wasn't deployed to the running container (UV cache issue similar to BP-346).

---

### QG-6: final_routing_tier Always NULL (NOT A BUG)

**Root cause (apparent)**: 0/3890 routing_decisions have `final_routing_tier` set.

**Actual behavior**: `final_routing_tier` is set ONLY when the novelty gate (Block 8) detects a near-duplicate and DOWNGRADES the routing tier (e.g., DEEP → LIGHT). Per `novelty.py:149,166`, this only fires when `minhash_similarity > minhash_threshold` or `embedding_similarity > embedding_threshold`.

**Why all NULL is expected**: This is a fresh pipeline with mostly unique articles. No near-duplicates have been detected yet. The code handles this correctly: `(routing_decision.final_routing_tier or routing_decision.routing_tier)` at line 658 falls back to `routing_tier` when `final_routing_tier` is NULL.

**Impact**: None. The NULL fallback is correct and designed.

**Long-term**: No fix needed. As the pipeline matures and articles accumulate, near-duplicate events will trigger non-NULL `final_routing_tier` values. Monitor the `novelty_gate_downgrade` Prometheus metric to confirm the gate fires as expected.

---

## 4. Priority Matrix

| Issue | Severity | Action | Complexity |
|-------|----------|--------|------------|
| BP-349 | CRITICAL | Fix immediately — add normalization helper | LOW (1 function + 5-line call site change) |
| QG-2 | MEDIUM | Fix — add enum to `_EXTRACTION_SCHEMA` | TRIVIAL (10-line schema change) |
| QG-3 | MEDIUM | Fix alongside BP-349 — allow empty entities | LOW (handled in the same normalization helper) |
| QG-4 | LOW | Accept as historical gap; no backfill | NONE |
| QG-5 | LOW | Already fixed (BP-324) | NONE |
| QG-1 | INFO | Pre-migration data; document and move on | NONE |
| QG-6 | INFO | Correct behavior; no fix needed | NONE |

---

## 5. Recommended Fixes (Implementation Plan)

### Fix 1 (BP-349 + QG-3 combined): New `_normalize_temporal_events_for_emit`

Add helper function between `_build_raw_events` and `_emit_temporal_events`:

```python
def _normalize_temporal_events_for_emit(
    raw_events: list[Any],
    entity_id_by_ref: dict[str, str],
    provisional_ids: frozenset[str],
) -> list[dict[str, Any]]:
    """Normalize raw LLM event dicts for _emit_temporal_events.

    Like _build_raw_events but does NOT skip events with no resolvable entity
    refs — macro/geopolitical events are globally scoped and may have no
    company-specific participants. Passes participant_entity_ids=[] in that case.
    """
    result: list[dict[str, Any]] = []
    for evt in raw_events:
        evt_d = dict(evt) if not isinstance(evt, dict) else evt
        participant_ids: list[str] = []
        for ref in evt_d.get("entity_refs", []) or []:
            eid, _ = _resolve_ref(str(ref), entity_id_by_ref)
            if eid is not None and eid not in provisional_ids:
                participant_ids.append(eid)
        result.append({
            "event_type": str(evt_d.get("event_type", "")).upper(),
            "event_text": str(evt_d.get("description", "")),
            "extraction_confidence": float(evt_d.get("confidence", 0.5)),
            "participant_entity_ids": participant_ids,
        })
    return result
```

At line 619–627, change call site to:
```python
_te_normalized = _normalize_temporal_events_for_emit(
    extraction_result.get("events", []),
    _te_entity_id_by_ref,
    _te_provisional_ids,
)
if _te_normalized:
    await _emit_temporal_events(
        raw_events=_te_normalized,
        entity_id_by_ref=_te_entity_id_by_ref,
        provisional_entity_ids=_te_provisional_ids,
        ...
    )
```

### Fix 2 (QG-2): Add enum to `_EXTRACTION_SCHEMA`

In `deep_extraction.py:65`, change:
```python
"event_type": {"type": "string"},
```
to:
```python
"event_type": {
    "type": "string",
    "enum": [
        "EARNINGS_RELEASE", "M_AND_A", "REGULATORY_ACTION", "MACRO",
        "MANAGEMENT_CHANGE", "PRODUCT_LAUNCH", "CAPITAL_RAISE", "LEGAL",
        "ANALYST_RATING", "GUIDANCE_RAISE", "NATURAL_DISASTER",
        "GEOPOLITICAL", "SANCTIONS", "OTHER",
    ],
},
```

This causes json-schema validation to reject non-canonical event types at extraction time, preventing silent pipeline drops at the KG layer.

---

## 6. Prevention Recommendations

1. **Contract testing between producers and consumers**: `_emit_temporal_events` and `_build_raw_events` share an implicit field name contract. A unit test asserting field names match would have caught BP-349.
2. **Enum constraints on all LLM output schemas**: Any field used as a filter/enum downstream should have an enum in `_EXTRACTION_SCHEMA`. Apply the same pattern to `claim_type`, `predicate`, and `polarity`.
3. **Temporal event count Prometheus metric**: Add `temporal_events_emitted_total` counter to `_emit_temporal_events` (similar to `record_article_processed`). Zero count after 1000 articles should alert.
4. **DLQ age metric**: Alert if DLQ grows by >5 entries/hour — catches timeout regressions before they accumulate.
