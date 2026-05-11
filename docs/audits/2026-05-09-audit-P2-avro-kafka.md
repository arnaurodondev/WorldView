# Audit P2 — Avro/Kafka Pipeline Integrity (VA-7, T-B-P2)

**PRD**: PRD-0087 §4 VA-7
**Plan task**: PLAN-0087 T-B-P2
**Owner**: Pipeline / Data Platform agent
**Run timestamp**: 2026-05-09T17:21Z (local stack)
**Stack baseline**: 46 containers running (per defect-register pre-audit baseline)

> **Scope**: Verify PLAN-0062 Avro enforcement holds end-to-end. Read-only audit.
> Cite topic + subject + consumer-group for every defect.

---

## 1. Topic ↔ Subject coverage matrix

Source files:
- `infra/kafka/schemas/*.avsc` — 27 `.avsc` files
- `kafka-topics --list` — 24 non-internal topics + 5 dead-letter topics
- `curl :8081/subjects` — 26 subjects registered (all `*-value`)

Compatibility level (for **every** subject) is `BACKWARD` except `relation.type.proposed.v1-value` which is `FULL` (stricter — fine). Global default also `BACKWARD`.

| Topic (Kafka)                          | Subject (Schema Registry)              | Compat     | Avsc on disk | Status |
|----------------------------------------|----------------------------------------|------------|--------------|--------|
| alert.created.v1                       | alert.created.v1-value                 | BACKWARD   | yes          | OK |
| alert.delivered.v1                     | alert.delivered.v1-value               | BACKWARD   | yes          | OK |
| content.article.raw.v1                 | content.article.raw.v1-value           | BACKWARD   | yes          | OK |
| content.article.stored.v1              | content.article.stored.v1-value        | BACKWARD   | yes          | OK |
| entity.canonical.created.v1            | entity.canonical.created.v1-value      | BACKWARD   | yes          | OK |
| entity.dirtied.v1                      | entity.dirtied.v1-value                | BACKWARD   | yes          | OK |
| graph.state.changed.v1                 | graph.state.changed.v1-value           | BACKWARD   | yes          | OK |
| intelligence.contradiction.v1          | intelligence.contradiction.v1-value    | BACKWARD   | yes          | OK |
| market.dataset.fetched                 | market.dataset.fetched-value           | BACKWARD   | yes          | OK (no `.v1` legacy) |
| market.instrument.created              | market.instrument.created-value        | BACKWARD   | yes          | OK (no `.v1` legacy) |
| market.instrument.discovered.v1        | market.instrument.discovered.v1-value  | BACKWARD   | yes          | OK |
| market.instrument.updated              | market.instrument.updated-value        | BACKWARD   | yes          | OK (no `.v1` legacy) |
| market.prediction.v1                   | market.prediction.v1-value             | BACKWARD   | yes          | OK |
| nlp.article.enriched.v1                | nlp.article.enriched.v1-value          | BACKWARD   | yes          | OK |
| nlp.document.ready.v1                  | nlp.document.ready.v1-value            | BACKWARD   | yes          | OK |
| nlp.signal.detected.v1                 | nlp.signal.detected.v1-value           | BACKWARD   | yes          | OK |
| portfolio.events.v1                    | portfolio.events.v1-value              | BACKWARD   | yes          | OK |
| portfolio.watchlist.updated.v1         | portfolio.watchlist.updated.v1-value   | BACKWARD   | yes          | OK |
| relation.type.proposed.v1              | relation.type.proposed.v1-value        | **FULL**   | yes          | OK (stricter) |
| _(no topic yet)_                       | alert.email.sent.v1-value              | BACKWARD   | yes          | INFO — producer wired (`services/alert/.../email_sent_event.py`) but never fired in current session; topic will auto-create on first publish (`auto.create.topics.enable=true`). |
| _(no topic yet)_                       | content.document.deleted.v1-value      | BACKWARD   | yes          | INFO — producer wired (content-ingestion `delete_tenant_document.py`); never fired. |
| _(no topic yet)_                       | entity.narrative.generated.v1-value    | BACKWARD   | yes          | INFO — producer wired (knowledge-graph `generate_narrative.py`); never fired. Cross-references defect-register `D-INIT-2` (entity_narrative_versions=0). |
| _(no topic yet)_                       | entity.provisional.queued.v1-value     | BACKWARD   | yes          | INFO — producer wired in knowledge-graph; never fired. |
| _(no topic yet)_                       | intelligence.temporal_event.v1-value   | BACKWARD   | yes          | INFO — wired in knowledge-graph; never fired. |
| _(no topic yet)_                       | watchlist.item_added-value             | BACKWARD   | yes          | INFO — schema record name `item_added` (lowercase, no `Watchlist*` prefix). Cosmetic Avro-name drift. Subject is non-`.v1`. |
| _(no topic yet)_                       | watchlist.item_deleted-value           | BACKWARD   | yes          | INFO — schema record name `WatchlistItemDeleted`. Subject is non-`.v1`. |
| **alert.dead-letter.v1**               | _(none)_                               | n/a        | no avsc      | **By design** — DLQ payloads are opaque envelopes, written by `DLQRepository.move_to_dlq` to Postgres `dead_letter_queue` table; the Kafka DLQ topics exist but are not currently produced to (offset 0 across all partitions). See §3. |
| **content.dead-letter.v1**             | _(none)_                               | n/a        | no avsc      | By design (see above). |
| **kg.dead-letter.v1**                  | _(none)_                               | n/a        | no avsc      | By design. |
| **market.dead-letter.v1**              | _(none)_                               | n/a        | no avsc      | By design. |
| **nlp.dead-letter.v1**                 | _(none)_                               | n/a        | no avsc      | By design. |

**Coverage summary**: every active producing topic has a registered subject with sane (`BACKWARD` / `FULL`) compatibility. No subject coverage gap on a topic that is actually receiving traffic.

---

## 2. Consumer wire-format table (R28 enforcement)

Pattern audited: every consumer's `deserialize_value(raw, schema_path)` method. AVRO_FIRST = sniff `0x00` magic byte → `deserialize_confluent_avro` (or schema-id lookup via Schema Registry); JSON only as fallback for legacy/test producers.

Architecture test `tests/architecture/test_kafka_avro_enforcement.py` enforces R28 (pure-JSON consumers + producer-side `json.dumps` payloads are forbidden — class `TestProducerR28Enforcement::test_no_producer_uses_json_dumps_for_payload_avro`).

| Service | Consumer file | Topic(s) consumed | Wire format | Violation? |
|---------|---------------|-------------------|-------------|------------|
| alert | `alert/.../intelligence_consumer.py` | `intelligence.contradiction.v1`, `nlp.signal.detected.v1`, `graph.state.changed.v1` | AVRO_FIRST + 16 MiB-bounded JSON fallback | No |
| alert | `alert/.../watchlist_consumer.py` | `portfolio.watchlist.updated.v1` (per-event-type schema lookup via Schema Registry by schema_id) | AVRO_FIRST (magic-byte sniff + schema_id lookup) + JSON fallback | No |
| content-store | `content_store/.../article_consumer.py` | `content.article.raw.v1` | AVRO_FIRST + JSON fallback | No |
| content-ingestion | `content_ingestion/.../document_ready_consumer.py` | `nlp.document.ready.v1` | AVRO_FIRST + JSON fallback | No |
| knowledge-graph | `knowledge_graph/.../enriched_consumer.py` | `nlp.article.enriched.v1` | AVRO_FIRST + 16 MiB-bounded JSON fallback | No |
| knowledge-graph | `knowledge_graph/.../entity_consumer.py` | `entity.canonical.created.v1` | AVRO_FIRST + JSON fallback | No |
| knowledge-graph | `knowledge_graph/.../economic_events_dataset_consumer.py` | `market.dataset.fetched` | AVRO_FIRST + JSON fallback (dataset envelope JSON-lines from MinIO is unrelated to Kafka wire) | No |
| knowledge-graph | `knowledge_graph/.../insider_transactions_dataset_consumer.py` | `market.dataset.fetched` | AVRO_FIRST + JSON fallback | No |
| knowledge-graph | `knowledge_graph/.../macro_indicator_dataset_consumer.py` | `market.dataset.fetched` | AVRO_FIRST + JSON fallback | No |
| knowledge-graph | `knowledge_graph/.../earnings_calendar_dataset_consumer.py` | `market.dataset.fetched` | AVRO_FIRST + JSON fallback | No |
| knowledge-graph | `knowledge_graph/.../structured_enrichment_consumer.py` | `nlp.article.enriched.v1` | AVRO_FIRST + JSON fallback | No |
| knowledge-graph | `knowledge_graph/.../fundamentals_consumer.py` | `market.dataset.fetched` | AVRO_FIRST + JSON fallback | No |
| knowledge-graph | `knowledge_graph/.../instrument_consumer.py` | `market.instrument.created` | AVRO_FIRST + JSON fallback | No |
| knowledge-graph | `knowledge_graph/.../temporal_event_consumer.py` | `intelligence.temporal_event.v1` | AVRO_FIRST + JSON fallback | No |
| knowledge-graph | `knowledge_graph/.../instrument_discovered_consumer.py` | `market.instrument.discovered.v1` | AVRO_FIRST + JSON fallback | No |
| knowledge-graph | `knowledge_graph/.../provisional_queued_consumer.py` | `entity.provisional.queued.v1` | AVRO_FIRST + JSON fallback | No |
| market-data | `market_data/.../ohlcv_consumer.py` | `market.dataset.fetched` | AVRO_FIRST + JSON fallback | No |
| market-data | `market_data/.../prediction_market_consumer.py` | `market.prediction.v1` | AVRO_FIRST + JSON fallback | No |
| market-data | `market_data/.../fundamentals_consumer.py` | `market.dataset.fetched` | AVRO_FIRST + JSON fallback | No |
| market-data | `market_data/.../intraday_resampling_consumer.py` | `market.dataset.fetched` | AVRO_FIRST + JSON fallback | No |
| market-data | `market_data/.../quotes_consumer.py` | `market.dataset.fetched` | AVRO_FIRST + JSON fallback | No |
| nlp-pipeline | `nlp_pipeline/.../article_consumer.py` | `content.article.stored.v1` | AVRO_FIRST + JSON fallback | No |
| nlp-pipeline | `nlp_pipeline/.../document_deletion_consumer.py` | `content.document.deleted.v1` | AVRO_FIRST + JSON fallback | No |
| nlp-pipeline | `nlp_pipeline/.../watchlist_consumer.py` | `portfolio.watchlist.updated.v1` | AVRO_FIRST (per-event-type Schema Registry lookup) + JSON fallback | No |
| portfolio | `portfolio/.../instrument_consumer.py` | `market.instrument.created`, `market.instrument.discovered.v1` | AVRO_FIRST + JSON fallback | No |

**No JSON-only consumers found.** All consumers honour PLAN-0062's AVRO_FIRST contract; JSON fallback paths are bounded (16 MiB cap per F-018) and exist purely for legacy/test producer compatibility.

Note: `services/nlp-pipeline/.../article_consumer.py:854/871` and similar `json.loads` calls in the dataset consumers (`economic_events_dataset_consumer.py:388`, `insider_transactions_dataset_consumer.py:318`, `macro_indicator_dataset_consumer.py:334`, `earnings_calendar_dataset_consumer.py:468`, `market-data/.../ohlcv_consumer.py:42`, `intraday_resampling_consumer.py:51`, `quotes_consumer.py:40`) are reading **MinIO silver-bucket envelopes** (not Kafka wire payloads). Those are JSON-lines-on-object-storage by design and are out of scope for R28.

---

## 3. Dead-letter scan (last 24 h)

### 3.1 Postgres `dead_letter_queue` tables

DBs scanned: `portfolio_db`, `ingestion_db`, `market_data_db`, `content_ingestion_db`, `content_store_db`, `nlp_db`, `intelligence_db`, `kg_db`, `rag_db`, `gateway_db`, `alert_db`.

| DB | DLQ table present? | Row count |
|----|--------------------|-----------|
| nlp_db | yes | **0** |
| intelligence_db | yes | **0** |
| alert_db | yes | **0** |
| content_store_db | yes | **0** |
| content_ingestion_db | yes | **0** |
| portfolio_db | no | n/a |
| market_data_db | no | n/a |
| ingestion_db | no | n/a |
| kg_db | no | n/a (DLQ for knowledge-graph lives in `intelligence_db` per service convention) |
| rag_db | no | n/a |
| gateway_db | no | n/a |

**Total DLQ rows: 0.** No dead-letter buildup anywhere.

### 3.2 Kafka `*.dead-letter.v1` topics

| Topic | Total messages |
|-------|----------------|
| alert.dead-letter.v1 | 0 |
| content.dead-letter.v1 | 0 |
| kg.dead-letter.v1 | 0 |
| market.dead-letter.v1 | 0 |
| nlp.dead-letter.v1 | 0 |

All Kafka DLQ topics empty as well.

### 3.3 Producer / consumer error scan

- Tail (last 24 h) of all 8 dispatchers (content-store, content-ingestion, nlp-pipeline, market-data, knowledge-graph, portfolio, alert, market-ingestion) — **zero hits** for `Serializ*`, `IncompatibleSchema`, `avro.*error`, `schema_id` errors.
- Tail (last 24 h) of all 22 consumer containers — **zero hits** for `deserialize`, `SerializationException`, `magic byte`, `Schema not found`, `UTF-32`, `UnicodeDecodeError`.

No producer-side or consumer-side serialization failures observed in the last 24 h.

---

## 4. Consumer-group lag (sustained > 1000 = flag)

`kafka-consumer-groups --describe --all-groups` was sampled twice (≈30 s apart) to distinguish steady-state lag from rebalance-snapshot artifacts.

| Group | Topic | Lag (sample 1) | Lag (sample 2) | Trend | Flag? |
|-------|-------|----------------|----------------|-------|-------|
| **content-store-consumer** | content.article.raw.v1 | 1351 | 1351 (rising in real time as new articles published; consumer processes ~10 msg/min) | **falling-behind** | **YES — SF-2 (latency)** |
| 9 × `kg-*-dataset-group` / `market-data-*` (5 partitions × 9 groups) | market.dataset.fetched | up to 280 per group | 0 / 1-2 | catching up post-rebalance | NO (resolved within 30 s) |
| alert-service-group | nlp.signal.detected.v1, intelligence.contradiction.v1, graph.state.changed.v1 | 0 | 0 | steady | NO |
| kg-service-group-enriched | nlp.article.enriched.v1 | 0 | 0 | steady | NO |
| nlp-pipeline-group | content.article.stored.v1 | 0 | 0 | steady | NO |
| portfolio-instrument-sync | market.instrument.created, market.instrument.discovered.v1 | 0 | 0 | steady | NO |
| Others | — | 0 | 0 | steady | NO |

The `content-store-consumer` lag is the only sustained flag. Throughput observed in tail (`bronze_fetched`/`silver_object_written` events): one article every ~6 s. With ~1.4k pending and continuous publish on `content.article.raw.v1`, this group will not converge within demo-day window without remediation.

---

## 5. Summary findings

### Strengths
- **R28 / PLAN-0062 compliance is intact**: zero JSON-only consumers; all 25 audited consumers do AVRO_FIRST sniff with bounded JSON fallback.
- **No serialization errors** producer-side or consumer-side over the last 24 h.
- **No DLQ buildup** in any of 5 Postgres DLQ tables or 5 Kafka DLQ topics.
- **Schema-Registry coverage is complete** for every active topic; compat levels are sane (`BACKWARD` global, one `FULL`); architecture test enforces R28 at CI.

### Weaknesses
1. **content-store-consumer lag of ~1351 messages on `content.article.raw.v1` is growing**, throughput too low to catch up before demo. Only sustained flag of the audit. Affects every demo-path surface that depends on fresh articles (A2 morning brief, A4 News tab, A6/A7 chat citations, A8 compare, A10 alerts feed).
2. **Six subjects registered with no matching topic** (`alert.email.sent.v1`, `content.document.deleted.v1`, `entity.narrative.generated.v1`, `entity.provisional.queued.v1`, `intelligence.temporal_event.v1`, plus the legacy non-`.v1` `watchlist.item_added`/`watchlist.item_deleted`). Producers exist; topics will auto-create on first publish (`auto.create.topics.enable=true`). For `entity.narrative.generated.v1` this corroborates D-INIT-2 (NarrativeGenerationWorker has not produced any rows / events). INFO-only from Avro/Kafka angle but a symptom worth surfacing.
3. **Avro record name drift**: `watchlist.item_added-value` schema's `name` field is `item_added` (lowercase, no `Watchlist` prefix), inconsistent with `WatchlistItemDeleted`. INFO / cosmetic.

---

## 6. Defect rows

```yaml
- id: D-P2-001
  va: VA-7
  surface: A2 (morning brief), A4 News tab, A6/A7 chat citations, A8 compare, A10 alerts feed
  severity: SF-2  # p95 latency > target (consumer falling behind, not strictly a hard 5xx)
  status: open
  agent: P2
  found_at: 2026-05-09T17:21Z
  reproduce: |
    docker exec worldview-kafka-1 kafka-consumer-groups \
      --bootstrap-server localhost:9092 \
      --describe --group content-store-consumer
    Sample twice ~30 s apart. Aggregate lag is ~1351 messages across the
    12 partitions of `content.article.raw.v1` and is rising. Consumer
    processes ~10 messages/min per
    `docker logs worldview-content-store-consumer-1 --since 1h`
    (one `bronze_fetched` + `silver_object_written` cycle every ~6 s).
    At a sustained publish rate (finnhub + other ingestors continue to
    emit) the group will not converge before the 2026-05-11 demo.
  evidence:
    - cmd: kafka-consumer-groups --describe --group content-store-consumer
    - sample: 12 partitions, per-partition lag 67-134, total = 1351
    - log_throughput: ~10 msg/min sustained over the last hour
    - downstream_impact: |
        content.article.raw.v1 → content-store fetches bronze + writes silver;
        downstream pipeline (nlp-pipeline → knowledge-graph → alert/rag-chat)
        cannot process articles that have not yet been silver-stored.
        Demo-path surfaces affected: A2 morning brief, A4 News tab, A6/A7/A8
        chat answer citations, A10 alert feed.
  root_cause: |
    Unknown — investigation candidates:
    1. Single-consumer-instance bottleneck (12 partitions consumed by one
       container `worldview-content-store-consumer-1`) → CPU/IO bound on
       a single thread.
    2. Synchronous bronze-fetch HTTP latency from upstream sources
       (finnhub etc.) blocks the poll loop one article at a time.
    3. Storage write latency (MinIO bronze + silver puts) accumulates per
       message.
    Verification path: scale `content-store-consumer` replicas (rdkafka
    will rebalance the 12 partitions across replicas), or confirm whether
    `process_message` is awaited serially.
  fix_decision: TBD
  spawned_plan: null
  fix_commit: null
  validation_evidence: null
  closed_at: null

- id: D-P2-002
  va: VA-7
  surface: cross-cutting (Avro hygiene / R28 follow-up)
  severity: INFO
  status: open
  agent: P2
  found_at: 2026-05-09T17:21Z
  reproduce: |
    curl -fsS http://localhost:8081/subjects | jq .
    Compare with: docker exec worldview-kafka-1 kafka-topics \
      --bootstrap-server localhost:9092 --list
    Six subjects are registered with no matching Kafka topic:
      - alert.email.sent.v1
      - content.document.deleted.v1
      - entity.narrative.generated.v1
      - entity.provisional.queued.v1
      - intelligence.temporal_event.v1
      - (plus legacy non-.v1 watchlist.item_added / watchlist.item_deleted)
    Producers exist on disk for all of them (verified by grep).
  evidence:
    - subjects_without_topics: |
        alert.email.sent.v1
        content.document.deleted.v1
        entity.narrative.generated.v1
        entity.provisional.queued.v1
        intelligence.temporal_event.v1
        watchlist.item_added
        watchlist.item_deleted
    - producers_grep: |
        services/alert/.../email_sent_event.py emits alert.email.sent.v1
        services/content-ingestion/.../delete_tenant_document.py emits content.document.deleted.v1
        services/knowledge-graph/.../generate_narrative.py emits entity.narrative.generated.v1
        services/knowledge-graph/.../config.py declares entity.provisional.queued.v1
          + intelligence.temporal_event.v1
  root_cause: |
    These flows have not produced any events in the current session.
    `auto.create.topics.enable=true`, so the topics will materialise on
    the first publish — no immediate failure mode. However, for
    `entity.narrative.generated.v1` this is the Kafka-side mirror of
    defect-register `D-INIT-2` (`entity_narrative_versions=0` in
    intelligence_db), confirming NarrativeGenerationWorker is not
    emitting. Recommend triage with that defect.
  fix_decision: defer  # information-only from VA-7 angle; follow up
                       # under D-INIT-2 (narrative worker) and broader
                       # ingestion-freshness sweep
  spawned_plan: null
  fix_commit: null
  validation_evidence: null
  closed_at: null

- id: D-P2-003
  va: VA-7
  surface: cross-cutting (Avro hygiene)
  severity: INFO
  status: open
  agent: P2
  found_at: 2026-05-09T17:21Z
  reproduce: |
    curl -fsS http://localhost:8081/subjects/watchlist.item_added-value/versions/latest \
      | jq -r '.schema | fromjson | .name'
    → "item_added"   # lowercase, no Watchlist* prefix
    Sibling subject:
    curl -fsS http://localhost:8081/subjects/watchlist.item_deleted-value/versions/latest \
      | jq -r '.schema | fromjson | .name'
    → "WatchlistItemDeleted"   # PascalCase as expected
  evidence:
    - schema_name_drift: |
        watchlist.item_added-value   → record.name = "item_added"
        watchlist.item_deleted-value → record.name = "WatchlistItemDeleted"
    - subject_naming: both subjects also drift from the post-PLAN-0062
      `.v1` suffix convention, but those subjects are versionless legacy
      and the topics are not on the demo path.
  root_cause: |
    Producer registers the schema with a non-conformant Avro `name`. Not
    a runtime defect — Schema Registry happily accepted it under
    BACKWARD compat — but it breaks Avro IDL conventions and complicates
    schema evolution. R28 architecture test does not (and cannot) catch
    record-name drift.
  fix_decision: defer  # cosmetic, off-demo path; track for post-demo
                       # cleanup along with non-`.v1` topic naming.
  spawned_plan: null
  fix_commit: null
  validation_evidence: null
  closed_at: null
```

### Defect summary

| ID | VA | Surface | Severity | Status | Note |
|----|----|---------|----------|--------|------|
| D-P2-001 | VA-7 | A2/A4/A6-A8/A10 | SF-2 | open | content-store-consumer lag ~1351, falling behind |
| D-P2-002 | VA-7 | cross-cutting | INFO | open | 5 active subjects + 2 legacy with no matching topic; corroborates D-INIT-2 |
| D-P2-003 | VA-7 | cross-cutting | INFO | open | `watchlist.item_added-value` Avro record name drift |

No HARD_FAIL findings from this audit. Avro/Kafka substrate itself is healthy; the only demo-impacting issue is throughput on the content-store consumer, which is a backpressure/scaling concern rather than a wire-format violation.
