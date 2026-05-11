# QA Beta Audit — Data Platform Engineer

**Date**: 2026-05-09
**Specialist**: Data Platform Engineer (Avro / Kafka / outbox / DDL / pgvector / MinIO / DLQ)
**Branch**: `feat/content-ingestion-wave-a1`
**Scope**: 17 most recent session commits + full data-plane state at audit time
**Bar**: beta deployment

---

## Executive summary

Platform topology is largely correct (outbox + Avro + claim-check + partitioning + HNSW are all implemented somewhere), but the **runtime state shows the news → NLP → KG pipeline is silently dark in this environment**, several topics are orphaned, several backbone tables are empty, and the outbox table schema is inconsistent across services. Only **18 relations** exist (all from the demo seed) and **0 relation_evidence / 0 events / 0 claims / 0 temporal_events / 0 entity_event_exposures** — the KG is effectively empty for everything that is supposed to be derived from the live news pipeline. Also: **no consumer group exists for `content.article.stored.v1`**, **`alert.email.sent.v1`, `content.document.deleted.v1`, `watchlist.item_added`, `watchlist.item_deleted` are registered subjects without a topic**, and **5 dead-letter topics have no schema registered**.

| Finding bucket | Severity | Count |
|---|---|---|
| BLOCKING (data-plane unsafe for beta) | P0 | 5 |
| MAJOR (data leak / drift / silent failures) | P1 | 7 |
| MEDIUM (consistency / hygiene) | P2 | 6 |
| LOW (nits) | P3 | 3 |

Recommendation: **DO NOT ship to beta** until F-001..F-005 are resolved. The dark NLP pipeline (F-001) alone makes the entire knowledge-graph and brief feature non-functional for any document that landed after the article-consumer container was last running.

---

## 1. Per-question summary (12 mandate items)

| # | Question | Status |
|---|---|---|
| 1 | Avro envelope on every schema | **PASS** (envelope on 26/26 schemas — see §3) |
| 2 | Schema evolution: defaults, no removed/renamed | **PASS w/ caveats** (R5 honored on recent diffs; one schema uses `string` schema_version, see F-013) |
| 3 | Topic naming, partitions, retention, cleanup | **MIXED** — naming ok; retention only on 7/22 topics; replication=1 everywhere (F-014, F-015) |
| 4 | Outbox pattern for DB+Kafka | **PASS w/ MAJOR drift** — every service uses outbox, but **5 different table schemas** (F-006, BLOCKING for ops/replay tooling) |
| 5 | Claim-check for >1MB | **PASS** (S4 puts raw payload in MinIO bronze, event carries `minio_bronze_key`; bronze bucket has 43 979 objects, silver 1 095) |
| 6 | DDL ↔ Avro alignment | **PASS w/ caveats** — types align; `entity_embedding_state` has `vector(1024)` matching BGE-large; F-016 on missing `tenant_id` index pattern |
| 7 | Seed data matches PRD | **PARTIAL** — `decay_class_config` has 6 rows (matches ADR), `source_trust_weights` 11 rows (matches PRD-0017), `relation_type_registry` 27 rows; **but** demo entities = 330, only 8 are intentionally seeded (the other 322 came from runtime — fine), and `path_templates` only has 3 of the documented templates |
| 8 | Relations partitioned hash by subject_entity_id (8 parts) | **PASS** (`HASH (subject_entity_id)`, `relations_p0..p7` exist) |
| 9 | pgvector HNSW + 1024 dims | **PASS** — 3 partial HNSW indexes on `entity_embedding_state` (definition, narrative, fundamentals_ohlcv); `vector(1024)` matches BGE-large |
| 10 | MinIO key format + bronze/silver | **PASS** — `<service>/raw/<provider>/<artifact>/<ULID>` + `worldview-bronze` / `worldview-silver` buckets |
| 11 | Consumer idempotency (dedup or upsert) | **MIXED** — R9 architecture test enforces `ValkeyDedupMixin`; runtime cannot prove every consumer is mixed-in (visual audit acceptable, but see F-008 for a hot suspect: `kg-economic-events-dataset-group` has persistent lag=2 on partition 4 with no progress). |
| 12 | DLQ routing | **PASS w/ caveat** — 5 DLQ topics exist (`alert/content/kg/market/nlp.dead-letter.v1`), all DLQ DB tables are empty (good — no failures, OR failures bypass DLQ — F-017) |

---

## 2. BLOCKING findings (5)

### F-001 [P0] NLP article-consumer is not running — `content.article.stored.v1` has zero consumers

**Evidence**:
- Container `worldview-nlp-pipeline-article-consumer-1` is **defined** in `infra/compose/docker-compose.yml:1211` (entry point `python -m nlp_pipeline.infrastructure.messaging.consumers.article_consumer_main`) but **does not exist in `docker ps`**.
- `kafka-consumer-groups --list` shows no group consuming `content.article.stored.v1`.
- `content_store_db.outbox_events`: 1 095 rows of `content.article.stored.v1` all `dispatched`.
- `nlp_db.document_source_metadata`: 579 rows (so something processed ~half — likely an earlier session before the container was stopped).
- `nlp_db.routing_decisions`: only 72 rows — **507 articles have NO routing decision = pipeline gap of 87.5 %**.
- `nlp_db.article_impact_windows`: 0 rows (PriceImpactLabellingWorker output table — completely empty).

**Impact**: Any article published since the article-consumer was last running stays "stored, never analysed" — they don't appear in entity-news endpoints, never produce `nlp.article.enriched.v1`, never reach KG, never feed user briefs (`rag_db.user_briefs = 0`). The brief feature is structurally dead until this is fixed.

**Fix**: Bring the container up; rerun the gap (replay 507 missing docs from `content_store.documents`). Add a `docker compose ps` health gate to `make dev` that fails if any of the named consumer/worker containers from `docker-compose.yml` is missing from `docker ps`.

---

### F-002 [P0] KG is dark — only 18 relations (all demo-seeded), 0 evidence, 0 events, 0 claims, 0 temporal_events, 0 exposures

**Evidence** (intelligence_db real counts):

| Table | Count | Expected (running pipeline) |
|---|---:|---|
| canonical_entities | 330 | OK (8 seed + ~320 from earlier runs) |
| relations | **18** | hundreds-thousands |
| relation_evidence | **0** | one row per article-relation observation |
| relation_evidence_raw | **0** | every extracted relation, pre-write |
| events | **0** | should have rows from corp-action / earnings articles |
| claims | **0** | LLM-extracted claims |
| temporal_events | **0** | should have rows from `intelligence.temporal_event.v1` (S6 Block 13E) |
| entity_event_exposures | **0** | should explode from `temporal_events` × related entities |
| event_entities | **0** | join table for events↔entities |

The 18 relations are split: `EXPOSED_TO_THEME=13`, `COMPETES_WITH=4`, `SUPPLIER_OF=1` — confidences are round numbers (0.93, 0.80, 0.95, 0.70, 0.95) — these are **demo seed rows**, not extraction output.

**Root cause**: cascades from F-001 (no enriched events flowing) plus probably a related issue in `kg-service-group-enriched` (sees 12 messages but lag is 7 on most partitions — see §4).

**Impact**: For-beta-demo, this is the entire backend value-prop empty. RAG chat answers fall back to vector-only context with zero relations.

**Fix**: Resolve F-001 first; verify `kg-service-group-enriched` consumer is committing offsets after writing `relation_evidence_raw` (tail logs while replaying one article).

---

### F-003 [P0] Outbox schema drift across 5 different shapes — operational tooling impossible

Outbox is implemented per-service but the table is incompatible across services. Replay/inspection tooling that works on `content_ingestion_db` will fail on `portfolio_db`, on `alert_db`, etc.

| DB | PK col | Topic col | Status col / values | Pending col | Lock col |
|---|---|---|---|---|---|
| `intelligence_db`, `nlp_db`, `market_data_db` | `id varchar(26)` | `topic varchar(200)` | `status varchar(30)` (pending/processing/published/failed) | `published_at` | `locked_by`, `locked_until` |
| `content_ingestion_db` | `id uuid` | `topic text` (default `content.article.raw.v1`!) | `status text` (delivered) | `dispatched_at` | `lease_owner`, `leased_until` |
| `content_store_db` | (different again) | — | — | — | — |
| `alert_db` | `event_id uuid` | `topic varchar(200)` | `status varchar(20)` (pending/...) | `dispatched_at` | none — relies on `idx_outbox_s10_pending` |
| `portfolio_db` | `id uuid` | `event_type` (no `topic`!) | `status varchar` (pending) | `published_at` | `lease_owner`, `lease_expires` |
| `ingestion_db` | `id uuid` | `event_type text` | `status text` (published) | none (no `dispatched_at`!) | `lease_owner`, `leased_until` |

**Two outright bugs**:
1. `portfolio_db.outbox_events` has **no `topic` column** — the dispatcher must hard-code or look up the topic from `event_type` (silent coupling violates R8).
2. `ingestion_db.outbox_events` has **no `dispatched_at`** — only a `status='published'` flag — replay window is zero (lost on truncate).

**Fix**: PLAN to consolidate on the shape used by `intelligence_db / nlp_db / market_data_db` (which is the libs/messaging canonical one). Files in `libs/messaging/src/messaging/outbox/` should be the single source of truth; an Alembic migration can rename columns and back-fill on each laggard service.

---

### F-004 [P0] 4 schema-registry subjects without a Kafka topic — wasted/zombie contracts

```
ORPHAN_SUBJECT: alert.email.sent.v1-value  (no topic 'alert.email.sent.v1')
ORPHAN_SUBJECT: content.document.deleted.v1-value
ORPHAN_SUBJECT: watchlist.item_added-value  (legacy unversioned)
ORPHAN_SUBJECT: watchlist.item_deleted-value  (legacy unversioned)
```

`alert.email.sent.v1` and `content.document.deleted.v1` have `.avsc` files in the repo and are referenced by code, but the topic was never created in this environment. If a producer publishes, broker auto-creation will fire with default partition count = 1 — silently undersized.

`watchlist.item_added` / `watchlist.item_deleted` are **older unversioned shapes superseded by `portfolio.watchlist.updated.v1`** but never deleted from Schema Registry. R5 implication: keeping them around invites a new producer to publish on the wrong contract.

**Fix**:
1. Create the two real topics explicitly with intended partition count and retention (don't rely on auto-create).
2. Soft-delete the two legacy `watchlist.item_*` subjects (or at minimum mark as `deprecated_at` in subject metadata).

---

### F-005 [P0] 5 dead-letter topics have no schema registered (R5 / R28 gap)

```
TOPIC_NO_SCHEMA: alert.dead-letter.v1
TOPIC_NO_SCHEMA: content.dead-letter.v1
TOPIC_NO_SCHEMA: kg.dead-letter.v1
TOPIC_NO_SCHEMA: market.dead-letter.v1
TOPIC_NO_SCHEMA: nlp.dead-letter.v1
```

R28 says **every topic must have an `.avsc`** — the architecture test `tests/architecture/test_kafka_avro_enforcement.py` enforces this for any consumer that does NOT use a JSON-fallback path. DLQ topics are typically written by the consumer's error handler, so they may today be JSON — that bypass is exactly the kind of contract drift that means **operational replay tooling cannot deserialise the DLQ payload reliably** during incident response.

**Fix**: Add `infra/kafka/schemas/<domain>.dead-letter.v1.avsc` with envelope + `original_topic` + `original_payload_b64` + `error_class` + `error_message` + `retry_count` + `first_failed_at`; register at startup; have all DLQ writers go through `serialize_confluent_avro`.

---

## 3. MAJOR findings (7)

### F-006 [P1] `entity.narrative.generated.v1` schema declares `schema_version` as **string** (`"1.0.0"`) — every other schema uses `int`

`infra/kafka/schemas/entity.narrative.generated.v1.avsc:17` —
```
{"name": "schema_version", "type": "string", "default": "1.0.0", ...}
```

Everywhere else (25 of 26 schemas) the field is `"type": "int", "default": 1`. Mixing types makes downstream tooling that reads `schema_version` from the envelope (registry watchers, observability dashboards) need a per-topic case statement. R5 forward-compat is unaffected at the wire level (Avro keeps the field shape), but the **canonical envelope contract is broken**.

**Fix**: bump to V2 schema with `int schema_version` defaulting to 2; publish a one-time consumer migration before retiring the V1 string variant.

---

### F-007 [P1] 4 topics have an `.avsc` and are produced by `outbox_events`, but **no consumer group exists**

Cross-checking schema registry vs `kafka-consumer-groups --list`:

| Topic | Producers | Subscribers (consumer group) | Result |
|---|---|---|---|
| `entity.dirtied.v1` | KG dispatcher (1 dispatched) | **none** | Any consumer that should refresh embeddings on dirtied entities is dead/disabled |
| `entity.narrative.generated.v1` | KG narrative worker (330 dispatched in 40 min!) | **none** | Massive write throughput, zero readers — wasted broker cost; or someone is meant to consume and rebuild narrative embeddings (entity_embedding_state.narrative has 8 due, 322 not yet refreshed) |
| `relation.type.proposed.v1` | KG | **none** | Relation-type-discovery loop dead |
| `content.article.stored.v1` | S5 (1 095 dispatched) | **none** (because F-001) | Same root as F-001 |
| `alert.delivered.v1` | S10 | **none** | Delivery telemetry orphaned |
| `portfolio.events.v1` | S1 | **none** | Other services that should react to user signup / portfolio create are silent |
| `intelligence.temporal_event.v1` | NLP | KG temporal-event consumer **exists** | OK, but topic has 0 messages — see F-002 |

**Fix**: For each, decide: deprecate the producer, or wire the consumer. Three of these (`entity.narrative.generated.v1`, `entity.dirtied.v1`, `relation.type.proposed.v1`) are already documented features (PLAN-0064 KG W6, PLAN-0079 entity dirtying) — the producers shipped, the consumers are missing.

---

### F-008 [P1] `kg-economic-events-dataset-group` has persistent lag with no consumer progress

```
kg-economic-events-dataset-group market.dataset.fetched 4  CURRENT=22  LOG-END=24  LAG=2
kg-economic-events-dataset-group market.dataset.fetched 1  CURRENT=66  LOG-END=67  LAG=1
```
Other dataset groups on the same topic are caught up (lag=0). This consumer is processing all but 1–2 messages per partition — likely a **fatal-but-unhandled exception in two specific dataset payloads**. Without DLQ + structured error classification (R20), these poison-pills will block forever on rebalance.

**Fix**: Tail container logs (`worldview-knowledge-graph-economic-events-dataset-consumer-1`); identify the failing offsets; route to DLQ.

---

### F-009 [P1] `market-data-prediction-markets` consumer has 16 500-message lag

```
market-data-prediction-markets market.prediction.v1 0..7 LAG = 1860 .. 2289   (total ~16 500)
```
`market_data_db.prediction_market_snapshots` has only **723 rows** but the producer (`content_ingestion_db.outbox_events.market.prediction.v1`) has shipped **16 500** messages. So **~96 % of prediction-market data is sitting on Kafka un-ingested**.

Likely cause: the `market.prediction.v1` consumer is throttled or has a slow per-message DB write (no batching). With Polymarket fetch frequency the broker will bloat fast.

**Fix**: Profile the consumer; add batched upsert (`INSERT ... ON CONFLICT` with `executemany`) instead of per-message commit.

---

### F-010 [P1] `entity_embedding_state.fundamentals_ohlcv` has 61 rows, **0 with embeddings**

```
view_type           | total | with_emb
fundamentals_ohlcv  |    61 |        0   ← every row has NULL embedding
narrative           |   330 |      322   ← OK
definition          |   330 |      267   ← 63 missing (~19 %)
```

61 financial-instrument entities have an `entity_embedding_state` row for fundamentals_ohlcv, but **zero have actually been embedded**. `next_refresh_at` is set equal to `last_refreshed_at` and `refresh_count = 0` — the rows exist as "scheduled placeholders" but no worker has picked them up. The fundamentals embedding pipeline is silently disabled.

**Fix**: Identify the worker that owns the fundamentals_ohlcv view (likely `embedding-retry-worker` or a separate `fundamentals-embedding-worker`); confirm container is running; check the SELECT pattern that picks `next_refresh_at <= now()` and confirm `last_refreshed_at != next_refresh_at` (otherwise rows look not-due to the worker).

---

### F-011 [P1] `provisional_entity_queue` shows 50 rows in `processing` state — likely stuck

```
status      | count
processing  |    50
pending     |    10
noise       |    11
resolved    |     1
```

50 rows in `processing` and only 1 ever reached `resolved` is a strong signal of a **claim-and-stall** pattern (BP-112 family). If the worker crashed mid-processing without releasing leases, those rows are blocked until the lease expires — and with only 1 ever resolved, it's plausible the worker has a bug where it claims but never advances the status field.

**Fix**: Inspect `worldview-knowledge-graph-provisional-queued-consumer-1` logs; add a reaper that resets stale `processing` rows back to `pending` after a TTL.

---

### F-012 [P1] `canonical_entities` has 116 rows with `entity_type='other'` — ML extraction is leaking

Sample: `World Bank Group`, `International Monetary Fund`, `FOMC`, `SEC`, `Bank of Japan`, `BIS`, `Knesset`, `Bank of England` — these are all **organizations** but were classified as `'other'`. The CHECK constraint allows `'organization'` — so this is an extraction-side mapping bug (GLiNER label → canonical entity_type). Affects 35 % of canonicals.

**Impact**: Frontend filters that look up "organization" entities will miss every regulator and central bank. This is a quality bug, not a structural one, but it materially hurts demo quality.

**Fix**: Add a re-classification migration / one-shot script that updates rows with `entity_type='other'` whose `canonical_name` matches an organization heuristic. Long term: fix the extraction → canonical mapping in S6.

---

## 4. MEDIUM findings (6)

### F-013 [P2] Topic configuration is irregular — partition counts and retention are inconsistent

| Topic | Partitions | Retention | Compaction |
|---|---:|---|---|
| `alert.created.v1` | 1 | default (forever?) | – |
| `alert.delivered.v1` | 12 | default | – |
| `content.article.raw.v1` | 12 | 30 d | – |
| `content.article.stored.v1` | 12 | 30 d | – |
| `entity.canonical.created.v1` | 12 | default | – |
| `entity.dirtied.v1` | 24 | – | **compact**, dirty-ratio=0.01 |
| `entity.narrative.generated.v1` | **1** | default | – |
| `entity.provisional.queued.v1` | 1 | default | – |
| `graph.state.changed.v1` | 12 | 14 d | – |
| `intelligence.contradiction.v1` | 12 | 30 d | – |
| `intelligence.temporal_event.v1` | 1 | default | – |
| `market.dataset.fetched` | 6 | 30 d | – |
| `market.instrument.created` | 3 | default | – |
| `market.instrument.updated` | 3 | default | – |
| `market.instrument.discovered.v1` | 3 | default | – |
| `market.prediction.v1` | 8 | 30 d | – |
| `nlp.article.enriched.v1` | 12 | 30 d | – |
| `nlp.document.ready.v1` | **1** | default | – |
| `nlp.signal.detected.v1` | 24 | 14 d | – |
| `portfolio.events.v1` | 3 | default | – |
| `portfolio.watchlist.updated.v1` | 12 | default | – |
| `relation.type.proposed.v1` | 4 | 30 d | – |

Issues:
- `alert.created.v1`, `entity.narrative.generated.v1`, `intelligence.temporal_event.v1`, `nlp.document.ready.v1`, `entity.provisional.queued.v1` all have **partition count = 1** — fanout-impossible (one consumer max per group). For `entity.narrative.generated.v1` already producing 330 msg/40 min this is a near-term scaling cliff.
- 11/22 topics have **no retention set** → broker default (`log.retention.hours=168`, 7 days). For idempotent compacted topics this is fine; for `alert.created.v1` (audit trail!) this is wrong — alerts should be retained at least 90 d for compliance/debug.
- Replication factor is **1 everywhere** (single-broker dev). For beta this is acceptable if it's a single AZ deployment, but call it out in the runbook.

**Fix**: Define `infra/kafka/topic-configs.yaml` with per-topic `partitions/retention/cleanup_policy/replication`; have `register-schemas.py` (or a sibling `apply-topic-configs.py`) reconcile.

---

### F-014 [P2] `relation_evidence_raw` table exists but is empty even when `relations` has rows

`relation_evidence_raw` is the PLAN-0062 staging table for raw extraction output; the seed migration that created the 18 relations bypassed it (direct insert into `relations`). The **invariant "every row in `relations` has at least one row in `relation_evidence_raw`" is violated** for 18 rows. This is fine while no live extraction is happening, but as soon as F-001/F-002 get fixed and the extraction pipeline writes evidence rows, queries that join `relations` ↔ `relation_evidence_raw` will silently miss demo entities.

**Fix**: Either back-fill `relation_evidence_raw` from the seed migration, or adjust queries to LEFT JOIN.

---

### F-015 [P2] No `tenant_id` index on `nlp_db.sections` (only a partial index `WHERE tenant_id IS NOT NULL`)

The pattern is correct (partial index) but **`document_source_metadata` has no tenant_id column at all** — yet `sections.tenant_id` is populated from it via the consumer. This means tenant-isolated reads of news articles must JOIN three tables — and there's no composite index on `(tenant_id, published_at DESC)` on `document_source_metadata`. Top-news per-tenant queries will scan the whole table.

**Fix**: Add `tenant_id uuid NULL` to `document_source_metadata` and a partial index `WHERE tenant_id IS NOT NULL ORDER BY published_at DESC`.

---

### F-016 [P2] `kg-service-group-enriched` has 7-12 message lag on most partitions

Not catastrophic, but combined with F-002 it suggests the enriched-consumer is **slowly draining and writing nothing useful** — every consume is non-erroring but produces 0 relation_evidence_raw rows. A consumer that always commits-with-no-write will make BP-415-style "false-OK" silent failures.

**Fix**: Add a Prometheus counter that increments only after `relation_evidence_raw` insert; alert if `messages_consumed - rows_inserted > 100` over 5 min.

---

### F-017 [P2] All 5 DLQ tables are empty — could mean "no errors" OR "errors silenced"

`dead_letter_queue` count is 0 in alert_db, content_ingestion_db, content_store_db, intelligence_db, nlp_db. Given F-008 (consumer lag with no progress) and F-009 (96 % data un-ingested), it's **statistically impossible that there have been zero failures**. The DLQ writer is probably swallowing errors silently (SA-006).

**Fix**: Audit `BaseKafkaConsumer._handle_message` error path; ensure FatalError → DLQ insert + structured log line; add an architecture test that fakes a fatal exception and asserts the DLQ row was written.

---

### F-018 [P2] `claims` and `events` are partitioned BY RANGE on `created_at` — wrong dimension

```
claims:           RANGE (created_at)
events:           RANGE (created_at)
relation_evidence: RANGE (evidence_date)
relations:        HASH (subject_entity_id)   ← correct
```

Range-partitioning by `created_at` is fine for retention/drop-old, but the dominant query pattern for these tables is **"WHERE entity_id = ?"** (entity detail page). With time-range partitions the planner must scan every monthly partition. `relation_evidence` correctly partitions on `evidence_date` (the natural time dim of the fact); `claims` and `events` should match.

The audit cannot tell whether queries use the partition key as a predicate without seeing the application; flagging for investigation. Note: `claims` has 36 partitions (2024-01..2026-12) — 36 × 8-fold-hash on relations means a 7-table join path could touch 200+ partitions in the worst case.

**Fix**: Re-evaluate; if entity-id is the dominant filter, switch to HASH(entity_id) like `relations`, or add a sub-partitioning level.

---

## 5. LOW findings (3)

### F-019 [P3] `path_templates` has only 3 templates seeded (PRD-0017 implies more)

```
template_name
supply_chain_3hop
financial_holding_chain
sector_supply_chain
```

The PathInsight feature has wired 3 templates; PRD-0017 mentions ~6 patterns. Not a blocker but should be tracked.

### F-020 [P3] MinIO has 9 buckets but only 3 are used (`market-bronze`, `market-canonical`, `worldview`, `worldview-bronze`, `worldview-silver`)

Empty buckets `content-data`, `intelligence-data`, `market-data`, `rag-data` — leftover from earlier infra. Either delete or document the migration story.

### F-021 [P3] `nlp_db.alembic_version` has 0 rows — same in `intelligence_db`, `portfolio_db`, `market_data_db`, `rag_db`

```
nlp_db.alembic_version=0
intelligence_db.alembic_version=0
market_data_db.alembic_version=0
portfolio_db.alembic_version=0
rag_db.alembic_version=0
content_ingestion_db.alembic_version=1
content_store_db.alembic_version=1
alert_db.alembic_version=1
ingestion_db.alembic_version=1
```

5 of 9 DBs have NO row in `alembic_version` — Alembic's `current` will report no version, and `alembic upgrade head` will run **everything from scratch**. Likely the latest migration deleted the row instead of UPDATEing it (or a manual ops command truncated). For beta this is silent until the next migration is applied, then chaos.

**Fix**: Re-stamp each affected DB: `alembic stamp head`.

---

## 6. Backups + durability story for the 3 named tables

### `rag_db.user_briefs` (rows: 0)

- **Schema**: `\d` confirms `user_briefs` exists with `idempotency_key UNIQUE` — feed-forward safe.
- **Persistence**: only Postgres; no MinIO claim-check; no Kafka topic for "brief generated" (so brief loss = data loss).
- **Backup**: not configured at the platform layer in this audit (no `pg_dump` cron job seen in `infra/`).
- **Durability gap**: failed-brief retention is undocumented. If a brief generation hits a 50 % LLM and rolls back, user sees no error message and there's no archived attempt.
- **Recommendation for beta**: nightly `pg_dump rag_db | gzip > /backups/rag_db_<date>.sql.gz`, retained 14 d.

### `intelligence_db.canonical_entities` (rows: 330)

- **Schema**: PK + 5 indexes (lower(canonical_name) UNIQUE for non-instrument).
- **Persistence**: Postgres only; entity creations are NOT shipped to MinIO; producer of `entity.canonical.created.v1` has 0 backed-up consumers (F-007).
- **Backup**: Same gap as above. Critically, `entity_embedding_state.embedding vector(1024)` adds ~330 × 3 × 4 KB = 4 MB of HNSW data per entity-view; rebuilding from scratch requires re-running BGE-large on every narrative + definition + fundamentals_ohlcv text (DeepInfra cost: ~$15 to re-embed 990 vectors at current pricing — non-trivial).
- **Recommendation for beta**: tag canonical_entities and entity_embedding_state into a daily logical dump, retain 30 d.

### `market_data_db.ohlcv_bars` (rows: 4 364)

- **Schema**: not inspected in detail; column `symbol` does NOT exist on this table (probable `instrument_id` foreign key) — note this for documentation.
- **Persistence**: Postgres only — but **bronze is fully replayable from MinIO `market-bronze/` (280 raw payloads, 350 MB)**. So OHLCV is the most-recoverable critical table.
- **Backup**: bronze MinIO IS the durable source-of-truth; recovery = re-run market-data ingestion consumer over `market.dataset.fetched`.
- **Gap**: silver/canonical layer in `market-canonical/` (280 objects) is the same shape — make sure the recovery script knows which is authoritative (PRD-0018 silver should be).

---

## 7. Topic matrix (full)

| Topic | Partitions | Retention | Producers | Consumer groups | Lag (max) | Last seen | Status |
|---|---:|---|---|---|---:|---|---|
| alert.created.v1 | **1** | default | alert | – | – | 16:17 | **F-013 partition=1** |
| alert.delivered.v1 | 12 | default | alert-dispatcher | **none** | – | – | **F-007** |
| alert.email.sent.v1 | – | – | – | – | – | – | **F-004 no topic** |
| content.article.raw.v1 | 12 | 30 d | content-ingestion | content-store-consumer | 0 | active | OK |
| content.article.stored.v1 | 12 | 30 d | content-store | **none** | – | 18:58 | **F-001 / F-007** |
| content.document.deleted.v1 | – | – | – | – | – | – | **F-004 no topic** |
| entity.canonical.created.v1 | 12 | default | KG-entity-worker | kg-service-group-entity | 0 | – | OK |
| entity.dirtied.v1 | 24 | compact | KG | **none** | – | 17:36 | **F-007** |
| entity.narrative.generated.v1 | **1** | default | KG-narrative-worker | **none** | – | 18:36 | **F-007 + F-013** |
| entity.provisional.queued.v1 | **1** | default | NLP | kg-provisional-queued-group | 16 | – | F-013 |
| graph.state.changed.v1 | 12 | 14 d | KG | alert-service-group | 0 | – | OK |
| intelligence.contradiction.v1 | 12 | 30 d | KG | alert-service-group | 0 | – | OK |
| intelligence.temporal_event.v1 | **1** | default | NLP | kg-service-group-temporal-event | 0 | 17:28 | F-013 |
| market.dataset.fetched | 6 | 30 d | market-ingestion | 5 KG groups + 3 market-data | up to 67 | active | F-008 |
| market.instrument.created | 3 | default | market-data | kg-service-group-instrument, portfolio-instrument-sync | up to 16 | – | OK |
| market.instrument.updated | 3 | default | market-data | – | – | – | watch |
| market.instrument.discovered.v1 | 3 | default | market-data | kg-service-group-instrument-discovered | 0 | – | OK |
| market.prediction.v1 | 8 | 30 d | content-ingestion | market-data-prediction-markets | **2 289** | active | **F-009** |
| nlp.article.enriched.v1 | 12 | 30 d | NLP-dispatcher | kg-service-group-enriched | 12 | 17:41 | F-016 |
| nlp.document.ready.v1 | **1** | default | NLP | – (or unverified) | – | 14:19 | F-013 |
| nlp.signal.detected.v1 | 24 | 14 d | NLP | alert-service-group | 0 | 17:37 | OK |
| portfolio.events.v1 | 3 | default | portfolio | **none** | – | – | F-007 |
| portfolio.watchlist.updated.v1 | 12 | default | portfolio | alert-service-watchlist-group, nlp-watchlist-group | 0 | – | OK |
| relation.type.proposed.v1 | 4 | 30 d | KG | **none** | – | – | F-007 |
| watchlist.item_added | – | – | – | – | – | – | **F-004 legacy** |
| watchlist.item_deleted | – | – | – | – | – | – | **F-004 legacy** |
| alert.dead-letter.v1 | ? | ? | (consumers on err) | – | – | – | **F-005 no schema** |
| content.dead-letter.v1 | ? | ? | (consumers on err) | – | – | – | **F-005** |
| kg.dead-letter.v1 | ? | ? | (consumers on err) | – | – | – | **F-005** |
| market.dead-letter.v1 | ? | ? | (consumers on err) | – | – | – | **F-005** |
| nlp.dead-letter.v1 | ? | ? | (consumers on err) | – | – | – | **F-005** |

---

## 8. Table population matrix (full)

### intelligence_db (the KG)
| Table | Rows | Expected for live system | Verdict |
|---|---:|---|---|
| canonical_entities | 330 | hundreds (live) | OK (8 demo + 322 runtime) |
| entity_aliases | 785 | thousands (live) | OK starter |
| entity_narrative_versions | 330 | one per entity ✓ | OK |
| entity_embedding_state | 721 | 990 (3 views × 330 entities) | **partial** (61 fundamentals_ohlcv with 0 embeddings — F-010) |
| relations | **18** | hundreds-thousands | **F-002 BLOCKING** |
| relation_evidence | **0** | one per article-relation | **F-002** |
| relation_evidence_raw | **0** | every extraction event | **F-002** |
| events | **0** | hundreds | **F-002** |
| claims | **0** | thousands | **F-002** |
| temporal_events | **0** | hundreds | **F-002** |
| event_entities | **0** | join | **F-002** |
| entity_event_exposures | **0** | thousands | **F-002** |
| llm_usage_log | 1 316 | grows with extraction | OK |
| outbox_events | 331 | dispatched | OK (all dispatched) |
| provisional_entity_queue | 72 | small backlog | F-011 (50 stuck in `processing`) |
| relation_summaries | 0 | derived from relations+evidence | empty consequence of F-002 |
| relation_contradiction_links | 0 | derived | empty consequence of F-002 |
| path_insight_jobs | 9 | jobs | OK starter |
| path_insights | 0 | populated by jobs | jobs not finishing or no surface |
| path_templates | 3 | 6 | F-019 |
| prompt_templates | 0 | seeded | **EMPTY — should be populated by migration** |
| model_registry | 0 | seeded | **EMPTY** |
| source_trust_weights | 11 | seeded ✓ | OK |
| decay_class_config | 6 | seeded ✓ | OK |
| relation_type_registry | 27 | seeded ✓ | OK |
| embedding_migration_state | 0 | tracks migrations | OK if no migration in flight |
| dead_letter_queue | 0 | – | F-017 (suspicious) |

### nlp_db
| Table | Rows | Verdict |
|---|---:|---|
| document_source_metadata | 579 | OK historical |
| sections | 579 | OK |
| chunks | 602 | OK |
| chunk_embeddings | 598 | OK (4 missing — investigate gap) |
| section_embeddings | 66 | low — 11 % section-level embedding coverage |
| entity_mentions | 415 | OK |
| chunk_entity_mentions | 415 | OK |
| mention_resolutions | 1 347 | OK |
| document_entity_stats | 72 | matches routing_decisions count — **also a 90 % gap** |
| document_source_llm_scores | 136 | matches `document_source_llm_latest=136` — note the schema says S6 wrote latest separately |
| routing_decisions | **72** of 579 docs | **F-001 87.5 % gap** |
| article_impact_windows | **0** | **PriceImpactLabellingWorker dead** |
| llm_replay_jobs | 0 | OK no replay backlog |
| llm_usage_log | 236 | OK |
| embedding_pending | 0 | OK |
| outbox_events | 90 | all dispatched |
| dead_letter_queue | 0 | F-017 |

### market_data_db
| Table | Rows | Verdict |
|---|---:|---|
| ohlcv_bars | 4 364 | OK (matches `instruments=57` × ~76 bars) |
| quotes | **0** | quote consumer dead OR no quote events arriving |
| prediction_market_snapshots | 723 (vs 16 500 published) | **F-009 96 % lag** |
| earnings_calendar | **0** | F-008 root cause |
| economic_events | **0** | F-008 root cause |
| macro_indicators | **0** | F-008 root cause |
| insider_transactions | **0** | F-008 root cause |
| outstanding_shares | **0** | not pulled |
| market_cap_history | **0** | not pulled |
| yield_curve | **0** | not pulled |
| daily_sentiments | **0** | not pulled |
| fundamental_metrics | 209 526 | OK populated |
| balance_sheets | 5 594 | OK |
| income_statements | 5 597 | OK |
| cash_flow_statements | 5 111 | OK |
| earnings_history | 3 532 | OK |
| earnings_trends | 1 228 | OK |
| earnings_annual_trends | 908 | OK |
| dividend_history | 1 058 | OK |
| company_profiles | 40 (vs 57 instruments) | **17 instruments without profile** |
| highlights | 31 | OK |
| valuation_ratios | 31 | OK |
| share_statistics | 31 | OK |
| splits_dividends | 31 | OK |
| insider_transactions_snapshot | 31 | OK |
| analyst_consensus | 31 | OK |
| institutional_holders | 30 | OK |
| fund_holders | 30 | OK |
| instrument_fundamentals_snapshot | 47 | partial (47 of 57) |
| technicals_snapshots | 47 | partial |
| screen_field_metadata | **0** | **EMPTY — required by screener** |
| failed_tasks | 0 | OK |
| ingestion_events | 987 | OK |
| outbox_events | 47 | all dispatched |

### portfolio_db
| Table | Rows | Verdict |
|---|---:|---|
| tenants | 1 | OK demo |
| users | 1 | OK demo |
| portfolios | 1 | OK |
| holdings | 5 | OK |
| watchlists | 3 | OK |
| watchlist_members | (?) | check |
| transactions | **0** | OK if no live trade sync |
| brokerage_connections | 0 | OK |
| invitations | 0 | OK |
| beta_enrollments | 0 | OK |
| micro_survey_responses | 0 | OK |
| nps_scores | 0 | OK |
| feedback_submissions | 0 | OK |
| feature_requests | 0 | OK |
| feature_votes | 0 | OK |
| portfolio_value_snapshots | 30 | OK |
| auth_audit_log | **0** | **suspicious — every login should log here** |
| outbox_events | 0 | OK no events to ship |
| idempotency | 47 | OK |

### rag_db
| Table | Rows | Verdict |
|---|---:|---|
| user_briefs | **0** | **CRITICAL — brief feature dead, follows from F-001/F-002** |
| brief_feedback | 0 | OK |
| messages | 42 | OK |
| threads | 21 | OK |
| llm_usage_log | 1 121 | OK |

### alert_db
| Table | Rows | Verdict |
|---|---:|---|
| alerts | 2 | minimal — not flowing from KG/NLP |
| alert_subscriptions | 0 | likely fine for demo |
| alert_deliveries | 0 | empty consequence |
| pending_alerts | 0 | OK |
| email_log | 0 | OK |
| email_preferences | 1 | OK |
| outbox_events | 2 (delivered) | OK |

### content_ingestion_db
| Table | Rows | Verdict |
|---|---:|---|
| sources | 11 | OK |
| article_fetch_log | 1 529 | OK |
| prediction_market_fetch_log | 16 306 | OK |
| content_ingestion_tasks | 983 | OK |
| tenant_document_uploads | 6 | OK |
| outbox_events | 17 993 (all delivered) | OK |
| source_adapter_state | 0 | suspicious — should track per-source last-fetch |
| dead_letter_queue | 0 | F-017 |

### content_store_db
| Table | Rows | Verdict |
|---|---:|---|
| documents | 1 096 | OK matches outbox |
| dedup_hashes | 2 192 | OK (2× docs is reasonable for hash variants) |
| minhash_signatures | 1 096 | OK |
| duplicate_clusters | 0 | OK no duplicates surfaced |
| minhash_entity_mentions | 0 | check — is this populated by another worker? |
| processed_events | 0 | suspicious — should track every consumed event |
| outbox_events | 1 066 (all delivered) | OK |

### ingestion_db (legacy `market-ingestion`)
| Table | Rows | Verdict |
|---|---:|---|
| ingestion_tasks | 283 | OK |
| ingestion_watermarks | 399 | OK |
| polling_policies | 424 | OK |
| provider_budgets | 2 | OK |
| symbol_tiers | 0 | suspicious |
| outbox_events | 280 (published) | OK |

---

## 9. Recommended fix sequence (for beta-readiness)

1. **F-001 + F-002** — bring the article-consumer container up; replay 507 missed articles; verify `relation_evidence_raw` rows appear; verify `temporal_events` rows appear.
2. **F-005** — register 5 DLQ schemas, mandate Avro for DLQ writes.
3. **F-007** — wire (or formally retire) the 4 orphan-topic consumers; in particular `entity.narrative.generated.v1` is producing 330+ msg/40 min and nobody is listening.
4. **F-008 + F-009** — dig into the two stuck consumers; either fix the bug (poison-pill / batch perf) or DLQ + alert.
5. **F-006** — converge outbox to a single shape (libs/messaging is canonical).
6. **F-021** — `alembic stamp head` on the 5 DBs missing alembic_version rows.
7. **F-013** — add `infra/kafka/topic-configs.yaml`; reconcile partitions / retention / cleanup_policy on every topic.
8. **F-004** — delete legacy unversioned watchlist subjects; create the 2 missing topics.
9. **F-010 + F-011 + F-012** — quality follow-ups, can ship after beta.

---

## Appendix A — Methodology

- Read RULES.md (R5, R8, R9, R12, R20, R28).
- Read KAFKA_PIPELINE_CHECKLIST.md, STORAGE_IO_CHECKLIST.md, STORAGE_ATOMICITY_PATTERNS.md.
- `git log --oneline` last 25 commits to scope session changes.
- `kafka-topics --list` + `kafka-consumer-groups --list/--describe --all-groups` for runtime topology.
- `curl http://schema-registry:8081/subjects` for schema-registry state.
- `psql -At` row counts on every table in 9 DBs.
- Cross-reference: schema-registry subjects vs Kafka topics vs schema files in `infra/kafka/schemas/`.
- `mc ls --recursive` for MinIO bucket inventory.
- Manual `\d` of suspect tables (outbox_events × 5 services, canonical_entities, relations, entity_embedding_state, document_source_metadata).
