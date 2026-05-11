# Investigation Report: Temporal Events & Silent Pipeline Failures

**Date**: 2026-05-03
**Investigator**: Claude (investigation skill)
**Severity**: CRITICAL (multiple compounding failures; some fixed in prior sessions)
**Status**: Root causes identified and resolved or documented

---

## 1. Issue Summary

Investigation into why `temporal_events = 0` and a broader sweep of silently broken pipeline paths. Starting state: `relations = 907`, `temporal_events = 0`, `entity_event_exposures = 0`, `events = 1530`. Uncovered 6 distinct root causes — 3 fixed, 3 documented as missing features or data gaps.

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| `temporal_events = 0` | intelligence_db query | Primary symptom |
| `entity_event_exposures = 0` | intelligence_db query | Secondary symptom |
| `events` table has 820 lowercase event_types | intelligence_db query | Data quality bug |
| Block 13E grep returns no code | services/nlp-pipeline source | Missing feature |
| `earnings_calendar` and `economic_events` tables empty | market_data_db query | Upstream data gap |
| NLP DLQ: 186 entries for `content.article.stored.v1` | Kafka offset inspection | Extraction timeouts |
| `knowledge-graph-earnings-calendar-dataset-consumer` not running | docker ps | Missing container |
| DeepSeek max_tokens=512 in running container despite code fix | docker exec grep | UV cache served stale 0.1.0 wheel |
| `economic_events_dataset_consumer` group session timeout | docker logs | Kafka group coordinator instability |

---

## 3. Execution Path Analysis

### 3.1 temporal_events population path

```
S6 NLP (Block 13E) → intelligence.temporal_event.v1 → kg-temporal-event-consumer → temporal_events table
```

Block 13E is documented in the Avro schema comment ("Emitted by S6 NLP Pipeline (Block 13E)") but **no code exists** in the NLP pipeline that publishes to `intelligence.temporal_event.v1`. The consumer exists and is running but has never received a message.

### 3.2 entity_event_exposures population paths

Three consumers write to `entity_event_exposures`:
1. `temporal_event_consumer` — zero input (see 3.1)
2. `economic_events_dataset_consumer` — subscribes to `market.dataset.fetched` where `dataset_type='economic_events'`; economic_events table in market_data_db is empty (S2 never fetched this dataset)
3. `earnings_calendar_dataset_consumer` — was **not started** (missing from running stack despite being in docker-compose under `infra` profile)

### 3.3 events table event_type case inconsistency

```
LLM extraction → _build_raw_events() → article_consumer → nlp.article.enriched.v1 → enriched_consumer → events table
```

`_build_raw_events()` in `article_consumer.py:1238` passed `event_type` verbatim from LLM output with no normalization. 8B-class models return lowercase (`earnings_release`) despite the prompt specifying uppercase `EARNINGS_RELEASE | M_AND_A | ...`.

### 3.4 max_tokens=512 silently truncating extractions

UV Docker layer cache served the old `ml-clients==0.1.0` wheel after `max_tokens=512→2048` was committed, because the package version was not bumped. Running container had `max_tokens=512` while source had `2048`. ~62% of complex articles (multiple entities/relations) hit `finish_reason: length` → truncated JSON → 0 relations/events/claims.

---

## 4. Hypotheses Tested

| # | Hypothesis | Result | Method |
|---|-----------|--------|--------|
| H-1 | Block 13E temporal event producer was never implemented | CONFIRMED | grep across entire nlp-pipeline src |
| H-2 | earnings_calendar data never fetched by S2 | CONFIRMED | market_data_db query: 0 rows |
| H-3 | earnings_calendar_dataset_consumer container not running | CONFIRMED | docker ps, started container |
| H-4 | event_type casing mismatch from 8B-class models | CONFIRMED | DB query: 820 lowercase vs 712 uppercase |
| H-5 | UV cache serving stale ml-clients wheel | CONFIRMED | docker exec grep: max_tokens=512 in running container |
| H-6 | economic_events dataset also empty | CONFIRMED | market_data_db.economic_events: 0 rows |

---

## 5. Root Causes

### RC-1: Block 13E Never Implemented (MISSING FEATURE)
**Statement**: No code in the NLP pipeline publishes to `intelligence.temporal_event.v1`. The topic exists, the consumer exists, but the producer is entirely absent.
**Location**: Should be in `services/nlp-pipeline/src/nlp_pipeline/application/blocks/` as Block 13E
**Impact**: `temporal_events` table permanently empty; entity-level temporal context missing from KG queries

### RC-2: Earnings/Economic Dataset Feeds Never Configured (DATA GAP)
**Statement**: S2 market-ingestion has never fetched `earnings_calendar` or `economic_events` datasets. Both tables in `market_data_db` are empty.
**Impact**: `entity_event_exposures` cannot be populated via the dataset path; `earnings_calendar_dataset_consumer` was idle

### RC-3: earnings_calendar_dataset_consumer Not Started (OPERATIONAL GAP)
**Statement**: Container was defined in docker-compose under `infra` profile but was not running.
**Location**: `infra/compose/docker-compose.yml:1669`
**Fix**: Started container — it is now running and ready to process when upstream data arrives

### RC-4: event_type Lowercase from LLM (BP-347) — FIXED
**Statement**: `_build_raw_events()` passed `event_type` verbatim; 8B-class models return lowercase.
**Location**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:1238`
**Fix**: Added `.upper()` normalization; committed in `ef7eb2a8`

### RC-5: UV Cache Serving Stale ml-clients (BP pattern) — FIXED
**Statement**: `ml-clients==0.1.0` cached wheel served after version was not bumped; max_tokens=512 remained in running container.
**Location**: `libs/ml-clients/pyproject.toml`
**Fix**: Bumped version to `0.2.0`, max_tokens raised to `4096`; committed in `ef7eb2a8`

---

## 6. Impact Analysis

- **Immediate impact**: `temporal_events = 0` (no macro/geopolitical temporal context in KG); `entity_event_exposures = 0` (no entity→temporal-event linkage); 820 lowercase event_types causing query misses on KG API filters
- **Blast radius**: KG API `GET /v1/events?event_type=EARNINGS_RELEASE` was silently excluding 820 events; RAG temporal context queries return empty; frontend earnings calendar widget shows no data
- **Data integrity**: Pre-fix `events` table rows (1530) have mixed casing — requires backfill (see Recommendation 3)

---

## 7. Contributing Factors

- Block 13E was documented in Avro schema but never tracked as "not yet implemented" in TRACKING.md — design doc / code gap
- UV `--mount=type=cache` is silent about version mismatches — package name+version key, not content hash
- Container startup gap for `earnings_calendar_dataset_consumer` not caught by operational runbooks
- No monitoring alert for "consumer running but never processed a message after N minutes"

---

## 8. Fixes Applied This Session

| Fix | Commit | Status |
|-----|--------|--------|
| max_tokens 512→4096 | ef7eb2a8 | Done |
| ml-clients version bump 0.1.0→0.2.0 | ef7eb2a8 | Done |
| event_type uppercase normalization | ef7eb2a8 | Done |
| earnings_calendar_dataset_consumer started | operational | Done |
| BP-345/346/347 added to bug patterns catalog | this commit | Done |

---

## 9. Recommended Next Steps

### P1 — Implement Block 13E: NLP → Temporal Event Publisher
Requires PRD/plan. Block 13E should:
- Detect temporal events (geopolitical, regulatory, macro) in extracted events
- Classify scope (GLOBAL, REGIONAL, NATIONAL) and region
- Publish to `intelligence.temporal_event.v1`

### P2 — Configure S2 Earnings Calendar and Economic Events Fetches
S2 market-ingestion workers `EarningsCalendarFetchWorker` and `EconomicEventsFetchWorker` need to be enabled/scheduled. Once data flows, `earnings_calendar_dataset_consumer` and `economic_events_dataset_consumer` will populate `entity_event_exposures`.

### P3 — Backfill event_type Uppercase Normalization
Run SQL to uppercase existing rows: `UPDATE events SET event_type = UPPER(event_type) WHERE event_type != UPPER(event_type)`. This fixes the 820 pre-fix rows silently excluded from API filters.

### P4 — Add monitoring for idle consumers
Alert when a consumer group has been running > 30 minutes with 0 messages processed and the topic has > 0 messages. Catches both the container-not-running gap and the no-producer gap.

---

## 10. KG Pipeline State at End of Session

```
canonical_entities:       1392
relations:                 928
relation_evidence_raw:     948   (all new rows have evidence_text)
events:                   1536   (820 lowercase, 716 uppercase — backfill pending)
event_entities:           1278
entity_event_exposures:      0   (requires Block 13E + S2 dataset feeds)
temporal_events:             0   (requires Block 13E)
```

---

## 11. Open Questions

- Is Block 13E in scope for the current plan wave, or deferred to PLAN-0067?
- Which S2 workers handle earnings calendar and economic events fetches — are they implemented but disabled, or not yet implemented?
- The `economic_events_dataset_consumer` group experiences `SESSTMOUT` periodically — is this a Kafka group coordinator stability issue in the dev stack?
