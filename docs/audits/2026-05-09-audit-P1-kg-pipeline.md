# Audit P1 — KG Generation Pipeline (VA-3)

**Agent**: P1 (KG + NLP)
**Scope**: VA-3 — full KG generation pipeline (header → body → model → entities → enrichment → edges)
**Started**: 2026-05-09T17:00Z
**Completed**: 2026-05-09T17:25Z
**Method**: Live-stack inspection only (read-only). No code modified, no containers restarted.

---

## 1. Executive Summary

The KG generation pipeline is **catastrophically broken**. The seed populated `nlp_db.document_source_metadata` with **513 articles** that were never wired through the Kafka chain — they have **0 entity_mentions, 0 routing_decisions, 0 LLM scores**. The fresh ingestion path that *is* running (content-ingestion → content-store → nlp-pipeline → kg) is now slowly trickling data — but at the rate observed (3 articles in 20 min), and with multiple consumer crashes, the demo path will be empty.

Worse, **3 KG consumers are crash-looping** because they reference table/topic names that don't exist:
- `temporal_events` table (renamed to `events` in a migration nobody updated callers for)
- `entity_event_exposures` table (renamed to `event_entities`)
- `intelligence.temporal_event.v1` topic (schema registered, topic not created)
- `entity.provisional.queued.v1` topic (schema registered, topic not created)
- KG `enriched-consumer` queries `document_source_metadata` against `intelligence_db` (table lives in `nlp_db` — R9 violation)
- KG service queries `temporal_events` and `confidence_components` column (both wrong)

**Net result**: zero new relations, zero narrative versions, zero claims, zero impact windows, zero AGE projection. The 18 relations and 277 canonicals shown in the baseline are stale seed from 2026-05-07.

---

## 2. Per-Article Trace Table — 5 Sample Documents

5 most-recently-`created_at` from `nlp_db.document_source_metadata`:

| doc_id (short) | source_name | source_type | sections | chunks | chunk_emb | section_emb | mentions | chunk_mentions | resolutions | routing | llm_scores | impact_windows | entity_stats |
|----------------|-------------|-------------|----------|--------|-----------|-------------|----------|----------------|-------------|---------|------------|-----------------|--------------|
| 96dc4cd1… | sec_edgar | press_release | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 1c6c0b81… | sec_edgar | relation | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ef30337b… | yahoo_finance | financial | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 97c4de10… | sec_edgar | sec_10k | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 8e132413… | sec_edgar | sec_10k | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

**Reading the table**: every sampled doc reaches stage "chunk_embedded" then **falls off a cliff** — no mentions, no routing, no scoring, nothing. This is the "all-green / zero-output" pattern flagged in memory (`feedback_audit_returned_value_persistence`).

The 6 docs that *did* get routed are 2026-05-09 14:18 `tenant_upload` test fixtures from FTS work, not real articles. They produced 6 routing decisions, 12 LLM scores (relevance + sentiment), but never reached enrichment because KG `enriched-consumer` errors on every event.

### Live-pipeline trace (3 articles processed in last 20 min)

For comparison, the **fresh** path is partially working:

| doc_id | routing_tier | sections | chunks | mentions | resolved_winners | LLM extraction |
|--------|--------------|----------|--------|----------|------------------|----------------|
| 019e0dbb-a98c… | deep | 1 | 1 | 14 | ~6 | DeepSeek OK |
| 019e0dbb-a9b6… | medium | 1 | 1 | 3 | ~1 | DeepSeek OK |
| 019e0dbb-a9e3… | medium | 1 | 1 | 4 | ~2 | DeepSeek OK |

`mention_class` resolution rates (live, 70 mentions across 9 docs at time of capture):

| mention_class | mentions | resolved | rate |
|---------------|----------|----------|------|
| organization | 53 | 5 | **9 %** |
| person | 8 | 0 | **0 %** |
| financial_instrument | 4 | 2 | 50 % |
| financial_institution | 3 | 1 | 33 % |
| commodity | 2 | 1 | 50 % |

Net: **9/70 ≈ 13 % overall mention-resolution rate**. Examples that fail:
- `Intel` (5 mentions) → 20 stage rows, all score=0, no candidate_entity_id — **no canonical exists** for Intel/INTC
- `Qualcomm` (1 mention) → no candidate
- `Apple Inc.` → 1 row, score=1.0, resolved (alias match)
- `Apple` (4 mentions) → 12 candidate rows, 1 winner score 0.54 (low)

---

## 3. Stage-by-Stage Drop-off Chart

End-to-end count (intelligence + nlp DBs combined, captured 2026-05-09T17:20Z):

```
content.article.raw.v1 topic        ≈ 436 messages (cumulative across 12 partitions)
        │ (content-store-consumer)
        ▼
content.article.stored.v1 topic     ≈ 32 messages          ← drops 92 % (raw → stored)
        │ (nlp article-consumer)
        ▼
NLP Stage 1: doc metadata wrote     517 rows in document_source_metadata
        │  (BUT: 511 of these are SEED — bypass Kafka entirely; only 6 are tenant_upload + 3 fresh = 9 actually flowed)
        ▼
NLP Stage 2: sections + chunks       sections=517  chunks=517  chunk_emb=517  section_emb=0
        │
        ▼
NLP Stage 3: GLiNER mentions         entity_mentions=33   chunk_entity_mentions=33   ← 484 docs (94 %) have ZERO mentions
        │
        ▼
NLP Stage 4: routing decisions       routing_decisions=10                            ← 507 docs (98 %) never routed
        │
        ▼
NLP Stage 5: LLM relevance/sentiment llm_scores=18 (=9 docs × 2 score_types)         ← 504 docs (98 %) never scored
        │
        ▼
NLP Stage 6: mention resolutions     70 candidate rows, 17 winners with entity_id    ← 13 % resolution rate
        │
        ▼
NLP Stage 7: outbox → nlp.article.enriched.v1 topic   ≈ 9 messages
        │  (KG enriched-consumer)
        ▼
KG Stage 1: relation_evidence_raw    0 rows                                          ← 100 % drop (consumer crashes)
        │
        ▼
KG Stage 2: relations                18 (all from seed 2026-05-07; 0 new)
        │
        ▼
KG Stage 3: provisional_entity_queue 6 rows pending, 0 resolved
        │
        ▼
KG Stage 4: enrichment               0 enriched canonicals (out of 306)              ← never runs
        │
        ▼
KG Stage 5: entity_narrative_versions  0 rows                                        ← Intelligence layer empty
        │
        ▼
KG Stage 6: AGE projection           graph 'worldview_graph' has 0 nodes / 0 edges  ← never projected
        │
        ▼
A4 Intelligence tab + A7 entity-graph chat = empty
```

**Single biggest gate**: between `nlp.article.enriched.v1` (9 messages) and `relation_evidence_raw` (0 rows). The KG enriched-consumer fails with `relation "document_source_metadata" does not exist` on every single message — see D-P1-001 below.

---

## 4. Routing Model Audit

| Worker | Capability | model_id (actual) | Provider | Calls observed | Status |
|--------|------------|-------------------|----------|----------------|--------|
| article-consumer (NLP) | embedding | (DeepInfra OpenAI-compatible API) | deepinfra | 30+ (last 1h) | OK |
| article-consumer (NLP) | extraction | qwen2.5:7b-instruct | unknown / Ollama | 6 | also DeepSeek-style calls observed (`deepseek_extraction_completed`) — possibly via DeepInfra |
| article-relevance-scoring-worker | classification | meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo | deepinfra | 12 (relevance + sentiment) | OK |
| unresolved-resolution-worker | resolution | (no calls in 1h) | — | 0 | **silent — backlog?** |
| ProvisionalEnrichmentWorker (KG scheduler) | embedding | ollama (bge-large) | unknown | 6 calls | **fallback to Ollama instead of DeepInfra** — see D-P1-008 |
| KG instrument-consumer | extraction + embedding | — | — | 36 `fallback_chain_exhausted` events | **all chains failing** — see D-P1-009 |
| KG provisional-queued-consumer | extraction | (would call DeepInfra) | deepinfra | 0 (consumer crashes on poll) | broken |

**Key observations**:
- DeepInfra IS reachable (article-consumer + relevance-scoring use it successfully).
- KG-side `ProvisionalEnrichmentWorker` logs only `ollama` for embedding capability — DeepInfra is *not* being used on the KG side. Per memory `project_platform_status_2026_04_27`, all 4 ML capabilities should be on DeepInfra.
- KG instrument-consumer fires `fallback_chain_exhausted` for both `extraction` and `embedding` 36 times — **its** ML chain is misconfigured.

---

## 5. Per-Consumer Error Summary (last 30 min)

| Consumer | err count | warn count | top error / warning |
|----------|-----------|------------|---------------------|
| knowledge-graph (S7 main) | **22** | 0 | `unhandled_error` — 88 occurrences of `relation "temporal_events" does not exist`; 12 of `column "confidence_components" does not exist` |
| knowledge-graph-enriched-consumer | 0 | 7 | `evidence_source_metadata_lookup_failed` — `relation "document_source_metadata" does not exist` (in intelligence_db) — fires on every message |
| knowledge-graph-instrument-consumer | 0 | 37 | `fallback_chain_exhausted` (capability=extraction & embedding) ×36 |
| knowledge-graph-temporal-event-consumer | 1 | 1 | `kafka_poll_error` — `Subscribed topic not available: intelligence.temporal_event.v1` |
| knowledge-graph-economic-events-dataset-consumer | 4 | 3 | `economic_events_consumer_failure` — `relation "temporal_events" does not exist` on INSERT |
| knowledge-graph-insider-transactions-dataset-consumer | 2 | 2 | `insider_transactions_consumer_failure` — `there is no unique or exclusion constraint matching the ON CONFLICT specification` (uses `ON CONFLICT (entity_type, canonical_name)` but unique idx is on `LOWER(canonical_name)` for non-financial_instrument types) |
| knowledge-graph-provisional-queued-consumer | 1 | 1 | `kafka_poll_error` — `Subscribed topic not available: entity.provisional.queued.v1` |
| nlp-pipeline (S6 main) | 0 | 50 | `s5_missing_doc` — content-store has 35 docs but nlp-pipeline asked for 50 doc_ids that don't exist there (orphan seed rows) |
| All other KG/NLP consumers | 0–1 | 0–1 | mostly `kg_read_replica_not_configured` (warn) — DATABASE_URL_READ unset, R23 partial (per memory) |

**Files touched (read-only inspection)**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/enriched_consumer.py:250` — calls `evidence_repo.lookup_source_metadata(doc_id)`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_evidence.py:103-124` — `lookup_source_metadata` queries `document_source_metadata` against the intelligence_db session

---

## 6. AGE Graph Status

```
LOAD 'age'; SET search_path = ag_catalog, "$user", public;
SELECT * FROM cypher('worldview_graph', $$ MATCH (n) RETURN COUNT(n) $$) AS (count agtype);
  count
  -----
  0          ← intelligence_db.worldview_graph

SELECT * FROM cypher('market_kg', $$ MATCH (n) RETURN COUNT(n) $$) AS (count agtype);
  count
  -----
  0          ← kg_db.market_kg
```

**Both AGE graphs are empty** despite 18 relations existing in the relational `relations` table. AGE projection (PLAN-0072 KG quality) has never run successfully against this stack, OR the projection job exists only in the relational tables and there is no graph-projection worker at all. Confirms HF-7 from PRD-0087 §3.1 (KG tab will show isolated nodes for Apple/Microsoft/OpenAI/NVIDIA/Meta).

---

## 7. Defect Register Rows (Ready to Append)

```yaml
- id: D-P1-001
  va: VA-3
  surface: A4-intelligence-tab, A7
  severity: HF-3
  status: open
  agent: P1
  found_at: 2026-05-09T17:05Z
  reproduce: |
    1. tail KG enriched-consumer logs:
       docker logs worldview-knowledge-graph-enriched-consumer-1 --since 30m | grep evidence_source_metadata_lookup_failed
    2. observe Traceback for every nlp.article.enriched.v1 message:
       sqlalchemy.exc.ProgrammingError: relation "document_source_metadata" does not exist
       SQL: SELECT source_name, source_type FROM document_source_metadata WHERE document_id = $1 LIMIT 1
       — executed against intelligence_db session (table lives in nlp_db)
  evidence:
    - file: services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_evidence.py:103-124
    - log: 6 of 7 enriched messages errored; relation_evidence_raw stays at 0 rows
    - schema: nlp_db.document_source_metadata exists with column `doc_id` (NOT `document_id`)
  root_cause: |
    PLAN-0078 T-B-03 added `lookup_source_metadata` that queries the wrong DB and the wrong column name (`document_id` vs `doc_id`). Violates R9 (no cross-service DB access). The lookup must call S5 via REST or denormalise into intelligence_db.
  fix_decision: TBD
  spawned_plan: null
  fix_commit: null

- id: D-P1-002
  va: VA-3
  surface: A2 (dashboard alerts/news), A4-intelligence
  severity: HF-1
  status: open
  agent: P1
  found_at: 2026-05-09T16:43Z
  reproduce: |
    1. tail S7 main service logs:
       docker logs worldview-knowledge-graph-1 --since 30m | grep unhandled_error
    2. observe 88 occurrences of:
       relation "temporal_events" does not exist
       SQL: SELECT te.event_id ... FROM temporal_events te WHERE te.event_type=$1 ...
  evidence:
    - intelligence_db has table `events` (renamed); `temporal_events` does NOT exist
    - intelligence_db has table `event_entities` (renamed); `entity_event_exposures` does NOT exist
    - 22 unhandled_error events in 30 min on S7 alone
  root_cause: |
    Migration renamed `temporal_events`→`events` and `entity_event_exposures`→`event_entities` (likely PLAN-0072/0078) but multiple call-sites in S7 still reference the old names: `services/knowledge-graph/...` query layer + economic-events-dataset-consumer INSERT statements.
  fix_decision: TBD

- id: D-P1-003
  va: VA-3
  surface: A4-instrument header (calendar widget)
  severity: HF-1
  status: open
  agent: P1
  found_at: 2026-05-09T17:08Z
  reproduce: |
    docker logs worldview-knowledge-graph-economic-events-dataset-consumer-1 --since 30m | grep economic_events_consumer_failure
  evidence:
    - INSERT INTO temporal_events (...) — table doesn't exist
    - 4 errors in 30 min
    - Kafka lag: kg-economic-events-dataset-group has lag=37+35 on partitions 2/0
  root_cause: same as D-P1-002 — temporal_events rename not propagated to economic-events consumer INSERTs
  fix_decision: TBD

- id: D-P1-004
  va: VA-3
  surface: A4-instrument insider activity
  severity: HF-1
  status: open
  agent: P1
  found_at: 2026-05-09T17:08Z
  reproduce: |
    docker logs worldview-knowledge-graph-insider-transactions-dataset-consumer-1 --since 30m | grep insider_transactions_consumer_failure
  evidence: |
    SQL: INSERT INTO canonical_entities (entity_id, entity_type, canonical_name, metadata)
         VALUES ($1, 'person', $2, cast($3 AS jsonb))
         ON CONFLICT (entity_type, canonical_name) DO NOTHING
    Error: there is no unique or exclusion constraint matching the ON CONFLICT specification
  root_cause: |
    The unique index on canonical_entities is `idx_canonical_entities_lower_name` on `LOWER(canonical_name)` WHERE entity_type<>'financial_instrument'. There is no plain `(entity_type, canonical_name)` unique constraint, so ON CONFLICT fails. Insider consumer must use `ON CONFLICT (LOWER(canonical_name)) WHERE entity_type<>'financial_instrument'` OR change to upsert via the canonical_entities use case.
  fix_decision: TBD

- id: D-P1-005
  va: VA-3
  surface: A2 (events stream), A4-instrument
  severity: HF-1
  status: open
  agent: P1
  found_at: 2026-05-09T17:09Z
  reproduce: |
    docker logs worldview-knowledge-graph-temporal-event-consumer-1 --since 30m | grep kafka_poll_error
    docker exec worldview-kafka-1 kafka-topics --bootstrap-server localhost:9092 --list | grep -i temporal
  evidence: |
    Error: KafkaError{code=UNKNOWN_TOPIC_OR_PART}: "Subscribed topic not available: intelligence.temporal_event.v1"
    Schema Registry HAS the schema: intelligence.temporal_event.v1-value
    Kafka topics list does NOT contain `intelligence.temporal_event.v1`
  root_cause: |
    Topic `intelligence.temporal_event.v1` was never created — auto-create disabled and infra/kafka topic-creation script (`infra/kafka/topics/`) likely missing this topic. Schema is registered but no producer ever emitted, so no auto-topic-creation either. Same root cause as D-P1-006.
  fix_decision: TBD

- id: D-P1-006
  va: VA-3
  surface: A4-intelligence (provisional resolution)
  severity: HF-1
  status: open
  agent: P1
  found_at: 2026-05-09T17:09Z
  reproduce: |
    docker logs worldview-knowledge-graph-provisional-queued-consumer-1 --since 30m | grep kafka_poll_error
  evidence: |
    Error: "Subscribed topic not available: entity.provisional.queued.v1"
    Schema Registry HAS the schema: entity.provisional.queued.v1-value
    Kafka topics list does NOT contain `entity.provisional.queued.v1`
    BUT: provisional_entity_queue DB table HAS 6 rows pending — they will never be consumed via Kafka path
  root_cause: same as D-P1-005 — topic not created
  fix_decision: TBD

- id: D-P1-007
  va: VA-3
  surface: A4-instrument intelligence tab, A7 chat
  severity: HF-3
  status: open
  agent: P1
  found_at: 2026-05-09T17:00Z
  reproduce: |
    psql intelligence_db -c "SELECT COUNT(*) FROM canonical_entities WHERE enriched_at IS NOT NULL;" → 0
    psql intelligence_db -c "SELECT COUNT(*) FROM entity_narrative_versions;" → 0
    psql intelligence_db -c "SELECT COUNT(*) FROM relation_evidence_raw;" → 0
    psql intelligence_db -c "SELECT COUNT(*) FROM events;" → 0
    psql intelligence_db -c "SELECT COUNT(*) FROM relations WHERE created_at > '2026-05-08';" → 0
  evidence: |
    306 canonical_entities, 0 enriched, 0 narratives, 0 events, 0 raw evidence, 0 relations newer than 2026-05-07
    KG scheduler IS running every 5 min (provisional_enrichment_worker_complete logs) — but produces no rows because:
      (a) provisional_entity_queue is fed by entity.provisional.queued.v1 which is broken (D-P1-006)
      (b) enriched-consumer crashes (D-P1-001)
      (c) any S7 query path through "temporal_events" crashes (D-P1-002)
    The 18 relations + 2 narratives are all dated 2026-05-07 — pre-baseline seed only
  root_cause: |
    Cascade of D-P1-001..006 — every gate from "enriched event" forward in the KG side is blocked. Even if all 6 root causes are fixed, the demo-day data refresh cycle (~30 min per scheduler tick) means relations/narratives won't materialise within the demo prep window without backfill.
  fix_decision: TBD

- id: D-P1-008
  va: VA-3
  surface: A4-intelligence (KG-side ML fallback)
  severity: SF-2
  status: open
  agent: P1
  found_at: 2026-05-09T17:11Z
  reproduce: |
    psql intelligence_db -c "SELECT model_id, provider, capability, COUNT(*) FROM llm_usage_log GROUP BY 1,2,3;"
      → ollama | unknown | embedding | 6     (only entry)
    Memory project_platform_status_2026_04_27 says all 4 KG capabilities should run on DeepInfra
  evidence: |
    KG-side llm_usage_log has 0 deepinfra entries. NLP-side has DeepInfra entries (relevance, embedding) — so the API key works, just not on KG.
    instrument-consumer logs `fallback_chain_exhausted` (extraction + embedding) ×36 in 30 min — chain is exhausted but Ollama still attempted as fallback.
  root_cause: |
    KG service likely still wired to `ollama` provider (or DeepInfra base_url not exposed to KG containers) — needs config audit on knowledge-graph compose envs.
  fix_decision: TBD

- id: D-P1-009
  va: VA-3
  surface: A4-instrument header (entity health)
  severity: SF-2
  status: open
  agent: P1
  found_at: 2026-05-09T17:14Z
  reproduce: |
    docker logs worldview-knowledge-graph-1 --since 30m | grep "confidence_components"
  evidence: |
    SQL: SELECT AVG((confidence_components->>'support')::float) ...
    Error: column "confidence_components" does not exist
    12 errors in 30 min
  root_cause: |
    A `confidence_components` JSONB column was likely planned (PLAN-0079 TrustScorer) but the migration wasn't applied OR the column was renamed. S7 read code references it directly.
  fix_decision: TBD

- id: D-P1-010
  va: VA-3
  surface: A4 instrument page, B5 (director picks any ticker)
  severity: HF-4
  status: open
  agent: P1
  found_at: 2026-05-09T17:00Z
  reproduce: |
    psql nlp_db -c "SELECT mention_text, COUNT(*) FROM entity_mentions WHERE mention_class='organization' GROUP BY 1 ORDER BY 2 DESC;"
      → Intel ×5, Apple ×4, Apple Inc. ×1, Qualcomm ×1, INTC ×1, ...
    psql intelligence_db -c "SELECT * FROM canonical_entities WHERE ticker='INTC' OR canonical_name ILIKE '%intel%' AND entity_type='financial_instrument';" → 0 rows
    psql intelligence_db -c "SELECT entity_type, COUNT(*) FROM canonical_entities WHERE entity_type='financial_instrument';" → 35
  evidence: |
    Only 35 canonical financial_instrument entities total. INTC, QCOM, AMD, GOOG, BRK, JNJ, ORCL, CSCO, ADBE, CRM, IBM all absent. Live news mentions Intel/Qualcomm — both fail resolution.
    Resolution rate: 13 % overall (9 winners / 70 mentions across 9 fully-processed live docs).
    Person resolution rate: 0/8.
  root_cause: |
    Seed coverage is far below the demo bar of "≥top-25 instruments". instrument-discovered consumer can backfill, but only when EODHD universe is queried — which appears blocked or incomplete (only 26 of 35 instruments are from today's discovery).
  fix_decision: TBD

- id: D-P1-011
  va: VA-3
  surface: cross-cutting (graph projection)
  severity: HF-7
  status: open
  agent: P1
  found_at: 2026-05-09T17:18Z
  reproduce: |
    psql intelligence_db -c "LOAD 'age'; SET search_path=ag_catalog,public; SELECT * FROM cypher('worldview_graph', \$\$ MATCH (n) RETURN COUNT(n) \$\$) AS (count agtype);"
      → 0
    psql kg_db -c "LOAD 'age'; ... cypher('market_kg', ...) " → 0
    psql intelligence_db -c "SELECT COUNT(*) FROM relations;" → 18
  evidence: |
    18 relational rows, 0 AGE nodes, 0 AGE edges. PRD §3.1 HF-7 ("KG tab shows isolated nodes for any well-known entity") fires unconditionally.
  root_cause: |
    Either (a) AGE projection worker doesn't exist and was meant to be added in PLAN-0072/0073, or (b) it does exist but only runs when relations change — 18 relations are 2 days old, projection ran and was cleared, never re-ran. Investigation needed in services/knowledge-graph/src for any cypher INSERT or `CREATE (n:Entity ...)` calls.
  fix_decision: TBD

- id: D-P1-012
  va: VA-3
  surface: cross-cutting (data freshness, every Phase A surface)
  severity: HF-4
  status: open
  agent: P1
  found_at: 2026-05-09T17:00Z
  reproduce: |
    psql nlp_db -c "SELECT COUNT(*) FROM document_source_metadata;" → 517
    psql nlp_db -c "SELECT COUNT(*) FROM entity_mentions;" → 33
    psql nlp_db -c "SELECT COUNT(*) FROM routing_decisions;" → 10
    docker exec worldview-kafka-1 kafka-run-class kafka.tools.GetOffsetShell --topic content.article.stored.v1 → ~32 across all partitions
  evidence: |
    nlp_db.document_source_metadata = 517 rows, but content-store has only 35 docs and Kafka stored.v1 has only ~32 messages. The 511 surplus rows have no chunks/mentions/routing — they were INSERT-loaded by the seed script bypassing the entire pipeline.
    Causes 50 `s5_missing_doc` warnings in 30 min as nlp-pipeline-1 looks up doc body via S5 and fails.
  root_cause: |
    The seed script (likely scripts/seed.py or PLAN-0084 baseline data loader) writes directly to nlp_db.document_source_metadata without producing matching content-store rows or stored.v1 messages. Pipeline thinks docs exist but cannot fetch the body for any downstream stage. Net effect: every "old" demo article has metadata but no extractable content, resulting in zero KG output for them. The "fresh" path that DOES work produces ~3 docs / 20 min — far too slow to catch up before demo.
  fix_decision: TBD

- id: D-P1-013
  va: VA-3
  surface: cross-cutting (entity resolution quality)
  severity: SF-4
  status: open
  agent: P1
  found_at: 2026-05-09T17:13Z
  reproduce: |
    psql nlp_db -c "SELECT mr.score, mr.is_winner, mr.stage, mr.candidate_entity_id FROM mention_resolutions mr JOIN entity_mentions em ON em.mention_id=mr.mention_id WHERE em.mention_text='Intel' ORDER BY mr.score DESC;"
      → all rows score=0, candidate_entity_id=NULL across stages 1-4
  evidence: |
    Intel/Qualcomm/etc. mentions hit all 4 resolution stages with score=0 because no canonical exists. This is a *failure logging* row, not a real candidate, but it inflates `mention_resolutions` count and makes "candidates=20" misleading. Should produce 0 rows or a single is_failure flag instead.
  root_cause: |
    PLAN-0078 mention storage writes failure stages as score=0 rows. Should be marked `is_resolution_failure=true` in metadata or skipped to avoid skewing observability metrics.
  fix_decision: TBD

- id: D-P1-014
  va: VA-3
  surface: ops / observability
  severity: INFO
  status: open
  agent: P1
  found_at: 2026-05-09T17:05Z
  reproduce: |
    docker logs <any KG consumer> --since 30m | grep kg_read_replica_not_configured
      → fires once on every consumer startup
  evidence: |
    "DATABASE_URL_READ is empty or matches DATABASE_URL — read traffic falls through to the write pool (Wave B-5 / R23 partially active)."
  root_cause: |
    PLAN-0076 Wave B-5 (R23) read/write split is wired but DATABASE_URL_READ is unset in compose envs. Functionally fine for a demo, but represents the deferred half of B-5.
  fix_decision: defer (per memory: PLAN-0076 fully complete; this is a known partial)
```

---

## 8. Summary for Triage Wave D

**Hard fails (block demo)**: D-P1-001, D-P1-002, D-P1-003, D-P1-004, D-P1-005, D-P1-006, D-P1-007, D-P1-010, D-P1-011, D-P1-012 — **10 HF defects**.

**Soft fails**: D-P1-008, D-P1-009, D-P1-013 — 3 SF.

**Info**: D-P1-014 — 1 INFO.

**Net assessment of VA-3**: the KG generation pipeline is **non-functional end-to-end** for demo-day data. Six independent regressions (table renames, missing topics, wrong DB target, broken ON CONFLICT, missing canonicals, wrong ML provider) compound into total output blockage. Even fixing all of them, the live throughput of ~3 articles/20 min means a backfill strategy is mandatory: either re-trigger Kafka ingestion of the 511 orphan articles, OR rebuild the seed to write content-store + Kafka events instead of inserting directly into nlp_db.

**Recommended fix grouping (suggestion for triage)**:
- Subagent **PLAN-0087-G — KG table-rename remediation**: D-P1-002, D-P1-003 — single sweep of S7 codebase replacing `temporal_events`→`events` and `entity_event_exposures`→`event_entities`, plus column `confidence_components` migration check (D-P1-009).
- Subagent **PLAN-0087-H — Kafka topic creation + cross-DB R9 fix**: D-P1-001 (move `lookup_source_metadata` to a REST call to S5 *or* denormalise via stored.v1 envelope), D-P1-005, D-P1-006 (add topic creation to infra/kafka/topics/).
- Fix-now batch: D-P1-004 (1-line ON CONFLICT change), D-P1-008 (KG compose env), D-P1-013 (skip failure-log rows).
- **Risk**: D-P1-007 + D-P1-010 + D-P1-012 — these are data backfill issues. May require a one-off seed rerun + 60-90 min scheduler crank time. If audit Wave D triage is at hour 12 and live throughput hasn't cleared the orphan rows, the demo-path B5 ("director types any ticker") must be trimmed per §9.6 of the PRD.
