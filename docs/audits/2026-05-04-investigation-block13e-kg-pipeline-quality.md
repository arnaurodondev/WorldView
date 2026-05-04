# Investigation Report: Block 13E Processing + KG Pipeline Quality Audit

**Date**: 2026-05-04
**Investigator**: Claude (investigation skill)
**Severity**: CRITICAL (BP-349 blocks all NLP-based temporal events) + MEDIUM (quality gaps)
**Status**: Root causes identified — P1 fix ready, P2–P7 are enhancements

---

## 1. Issue Summary

Two-part investigation: (1) verify whether Block 13E has produced any `intelligence.temporal_event.v1`
events since its deployment at `e4e03e06`; (2) audit the KG pipeline filtering chain and identify
quality enhancement opportunities.

**Conclusion**: Block 13E has produced **zero** temporal events despite 3 MACRO events (confidence 0.95)
being extracted AFTER deployment. Root cause: field name mismatch between raw LLM output and what
`_emit_temporal_events` expects. Additionally, the KG pipeline has 5 quality gaps ranging from
MEDIUM to LOW severity.

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| `outbox_events WHERE topic='intelligence.temporal_event.v1'` = 0 | nlp_db | Block 13E never published |
| 3 MACRO events in `events` table created at 00:08:30 UTC (after Block 13E deploy at 00:02) | intelligence_db | Qualifying events existed but were skipped |
| `extraction_result.get("events", [])` passed to `_emit_temporal_events` at line 620 | article_consumer.py:620 | Raw LLM dicts, NOT processed dicts |
| `_emit_temporal_events` reads `"extraction_confidence"` (line 1438) | article_consumer.py:1438 | Raw LLM uses `"confidence"` → default 0.0 → Filter 2 fails |
| `_build_raw_events` maps `"confidence"` → `"extraction_confidence"` at line 1286 | article_consumer.py:1286 | Normalization only happens AFTER Block 13E call site |
| `deep_extraction.complete` logs show events=3 for article `019dee97-*` | docker logs | Events were extracted but not emitted |
| `temporal_events` table: 12751 `corporate`, 0 `macro`/`geopolitical`/`regulatory_action` | intelligence_db | Confirms Block 13E never fired |
| `entity_event_exposures` = 8 (all corporate earnings) | intelligence_db | EODHD BP-348 fix working |
| DLQ: 186 `content.article.stored.v1` timeout (45s) | nlp_db dead_letter_queue | Article throughput issue |
| routing_decisions: 2771 with routing_tier set but processing_path=NULL | nlp_db | Large processing backlog |
| events table: 24 unique event_types including malformed values | intelligence_db | LLM enum normalization gap |

---

## 3. Execution Path Analysis

### 3.1 Block 13E path

```
content.article.stored.v1
  ↓ ArticleProcessingConsumer._run_pipeline()
  ↓ Block 10: deep_extraction.run() → extraction_result
     {"events": [{"event_type": "MACRO", "description": "...", "confidence": 0.95, "entity_refs": [...]}]}
  ↓ Line 600: if should_run_deep_extraction(final_path) and extraction_result.get("events"):
  ↓ Line 619: _emit_temporal_events(raw_events=extraction_result.get("events", []))
                                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                     RAW LLM output — "confidence" not "extraction_confidence"
  ↓ _emit_temporal_events() line 1438: confidence = float(evt_d.get("extraction_confidence", 0.0))
                                                                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                                                     key doesn't exist → 0.0
  ↓ line 1439: if confidence < 0.5: continue  ← ALL events skipped here
  → outbox_repo.add() never called
  → intelligence.temporal_event.v1 never published
```

### 3.2 KG pipeline funnel (full picture)

```
Article ingestion → document_source_metadata (4187 docs)
  ↓ Routing scorer → routing_decisions (3877 scored)
    deep:   1054 scored → 441 processed as full_pipeline (42%)
    medium: 2399 scored → 614 processed as full_pipeline (26%)
    light:   424 scored →  51 processed as section_embeddings_only (12%)
  ↓ NLP full_pipeline articles (1055):
    entity_mentions:     29039 (27.5 per article avg)
    mention_resolutions: 33888
    events extracted:     1613 (1.5 per article avg)
    relations:            1105 (1.05 per article avg)
  ↓ KG EnrichedArticleConsumer:
    canonical_entities: 1531 (KG-deduplicated entities)
    events with entity: 1613 → event_entities: 1424 (88% have a linked entity)
    relations:          1105 → with evidence: 209 (19%)
    entity_event_exposures: 8 (all corporate earnings, from BP-348 fix)
    NLP temporal events: 0 (BP-349 blocks this entire path)
```

---

## 4. Hypotheses Tested

| # | Hypothesis | Result | Method |
|---|-----------|--------|--------|
| H-1 | Block 13E never produced events due to field name mismatch (`extraction_confidence` vs `confidence`) | **CONFIRMED** | Code trace: line 620 passes raw LLM dicts; line 1438 reads `extraction_confidence` which is never present |
| H-2 | No qualifying MACRO/GEOPOLITICAL events extracted since deployment | **REFUTED** | 3 MACRO events (confidence 0.95) in events table at 00:08:30 UTC, after deployment at 00:02 |
| H-3 | Block 13E is guarded by `should_run_deep_extraction` and no deep articles processed | **REFUTED** | Logs show 3 DEEP-tier articles processed after deployment; one had events=3 |
| H-4 | Avro serialization failure silently drops events | **REFUTED** | `outbox_repo.add()` is never reached — filter rejects events first |
| H-5 | entity_event_exposures = 0 was a data gap, not a bug | **PARTIALLY CONFIRMED** — 8 corporate exposures appeared after BP-348 fix; earnings window coverage still sparse | EODHD fix working, but window limitations remain |

---

## 5. Root Cause: BP-349

### Statement
`_emit_temporal_events()` at `article_consumer.py:619` receives `extraction_result.get("events", [])` —
the raw LLM output dicts. These use field name `"confidence"` for the extraction confidence.
`_emit_temporal_events()` reads `"extraction_confidence"` (the normalized name created by
`_build_raw_events()`). Since `"extraction_confidence"` doesn't exist in the raw dicts, it defaults
to `0.0`, causing all events to fail Filter 2 (`confidence < 0.5`).

### Location
- **Call site bug**: `article_consumer.py:620` — `raw_events=extraction_result.get("events", [])`
- **Consumer reads wrong field**: `article_consumer.py:1438` — `evt_d.get("extraction_confidence", 0.0)`
- **Correct field mapping done by**: `article_consumer.py:1286` — `_build_raw_events()`, called AFTER Block 13E

### Secondary bug (same root cause)
`evt_d.get("event_text", "")` at `article_consumer.py:1478` also uses the normalized name.
Raw LLM uses `"description"`. All temporal event titles would be empty even if events weren't filtered.

### Trigger condition
Every article — since Block 13E deployed, this bug prevents ANY NLP-based temporal events.

---

## 6. Impact Analysis

- **Immediate**: Zero NLP-based temporal events ever published to `intelligence.temporal_event.v1`.
  The 55 MACRO + 62 REGULATORY_ACTION events in the `events` table have never been propagated
  to `temporal_events`. KG queries for macro/geopolitical temporal context return empty.
- **Blast radius**: RAG briefing temporal context queries ("what macro events affected X this week?")
  return only corporate earnings events (not NLP-extracted macro context). Intelligence brief
  temporal section is empty.
- **Data integrity**: No corruption — events table is correct, temporal_events has earnings calendar
  data (corporate scope only), no orphaned data.

---

## 7. KG Pipeline Quality Gaps (Beyond BP-349)

### QG-1: Large Routing Backlog (MEDIUM)
2771 articles have `routing_tier` set but `processing_path=NULL` — they have been scored but not
yet processed by the NLP article consumer. With ~1 deep article per minute, the backlog is ~46 hours
of processing. This delays the KG reaching its full potential.

### QG-2: LLM Event Type Hallucinations (MEDIUM)
24 unique event_types detected, including malformed values: `"PARTNER_OF"`, `"INVESTMENT_IN"`,
`"EVENT_TYPE NOT MAPPED"`, `"EVENT OTHER"`, `"EVENT_CHG"`. These should either be normalised to
the canonical enum set or rejected at extraction time. The extraction prompt constrains the enum
but 8B-class models still produce out-of-enum values.

### QG-3: Temporal Events Skip Macro Events Without Entity Refs (MEDIUM)
`_build_raw_events()` skips any event where no entity_refs resolve to a canonical entity. For
macro/geopolitical events (e.g., "Federal Reserve raised rates 25bp"), the referenced entities
(central banks, governments) are not in the KG. These events never appear in `temporal_events` even
after BP-349 is fixed. This eliminates the most valuable macro context signal.

### QG-4: Evidence Text Coverage — Only 19% of Relations (LOW)
209 of 1105 relations (19%) have `evidence_text`. The 925 NULL-evidence relations are from articles
processed before BP-345 was fixed (evidence_text was never forwarded through the pipeline then).
These relations have lower utility for KG explanation and RAG grounding.

### QG-5: DLQ Timeout Backlog (LOW)
186 articles timed out at 45s. These are likely long/complex articles. The timeout is hard-coded
at 45s; a 120s timeout would capture most of these. Alternatively, intelligent chunk-level
extraction for large articles would reduce timeouts.

### QG-6: `final_routing_tier` Always NULL (LOW)
The suppression gate sets `processing_path` but never sets `final_routing_tier`. This makes it
impossible to distinguish "deep tier → processed" from "deep tier → suppressed" in SQL queries.

---

## 8. Recommended Fix for BP-349

**Minimal fix** (article_consumer.py lines 600–627):

Replace:
```python
await _emit_temporal_events(
    raw_events=extraction_result.get("events", []),
    entity_id_by_ref=_te_entity_id_by_ref,
    ...
)
```

With:
```python
# BP-349: normalize raw LLM events through _build_raw_events() so that
# _emit_temporal_events receives the expected "extraction_confidence" /
# "event_text" / "participant_entity_ids" field names.
_te_provisional_refs: set[str] = {
    v for v, eid in _te_entity_id_by_ref.items() if eid in _te_provisional_ids
}
_te_processed_events = _build_raw_events(
    extraction_result.get("events", []),
    _te_entity_id_by_ref,
    _te_provisional_refs,
)
if _te_processed_events:
    await _emit_temporal_events(
        raw_events=_te_processed_events,
        entity_id_by_ref=_te_entity_id_by_ref,
        ...
    )
```

**Enhancement for QG-3** (separate PR): Add a fallback in `_emit_temporal_events` that processes
events with empty `entity_refs` (scope them to GLOBAL and set `exposed_entities=[]`) so macro
context events are never lost from temporal_events even when entities aren't in the KG.

---

## 9. Prevention Recommendations

- **BP-349 pattern**: When a helper function is designed to receive pre-processed data, validate this
  with a docstring assertion or type alias. Add a `TypedDict` for processed event dicts.
- **Regression test needed**: Add a unit test for `_emit_temporal_events` that feeds it a raw LLM
  dict (without `extraction_confidence`) and asserts that it raises/warns rather than silently skipping.
- **QG-2 prevention**: Add `event_type` to the `_build_raw_events` filtering step — reject values
  not in the canonical enum set rather than storing them as-is.
- **QG-3 prevention**: Add a separate `_build_raw_events_for_temporal()` that does NOT skip events
  with unresolved entities (just sets `exposed_entities=[]`).
- **Observability**: Add a structured log `"temporal_event_skipped"` with `reason` field in
  `_emit_temporal_events` to make future filter misses visible in the logs.
- **New bug pattern**: BP-349 — Raw-vs-Processed Event Dict Field Name Mismatch should be added
  to `docs/bug-patterns/kafka-messaging.md`.

---

## 10. Pipeline State at Time of Investigation

```
NLP pipeline:
  total_docs:               4187
  routing_decisions_scored: 3877
  deep_tier processed:       441  (42% of scored)
  medium_tier processed:     614  (26% of scored)
  full_pipeline total:      1055
  DLQ timeouts (45s):        186

intelligence_db:
  canonical_entities:       1531
  events:                   1613  (24 event_types, some malformed)
  relations:                1110  (19% with evidence_text)
  temporal_events:         12751  (all corporate earnings, 0 NLP-derived)
  entity_event_exposures:      8  (AAPL/MSFT/GOOGL/AMZN/META/TSLA/APLE/BRK-B)
  NLP temporal events:         0  (BP-349 blocks entire path)
```

---

## 11. Open Questions

1. Should temporal macro events be emitted even when entity_refs are empty/unresolvable?
   (Current: skipped; Proposed QG-3 enhancement: emit with `exposed_entities=[]`)
2. Should the 45s DLQ timeout be raised, or should we implement chunk-level extraction for
   long articles?
3. Should `final_routing_tier` be backfilled from `routing_tier` for historical rows where
   the suppression gate wasn't applied?
4. The `evidence_text` backfill for 925 pre-fix relations — is re-processing the original
   articles feasible, or should we leave them as-is?
