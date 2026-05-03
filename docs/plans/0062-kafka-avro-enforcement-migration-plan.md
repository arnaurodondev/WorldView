---
id: PLAN-0062
title: Kafka Avro Enforcement — Migrate Remaining JSON Consumers to Avro Wire Format
prd: platform-principle/2026-05-03-no-json-on-kafka
status: completed
created: 2026-05-03
updated: 2026-05-03
---

# PLAN-0062 — Kafka Avro Enforcement Migration

## Background

PLAN-0061 Wave E introduced `entity.provisional.queued.v1`, the first new
Kafka topic added under the platform principle that **all Kafka contracts use
Avro on the wire**. As part of completing that work we:

1. Moved the `EntityProvisionalQueuedV1` canonical model into
   `libs/contracts/src/contracts/events/kg/provisional_queued.py`.
2. Converted the producer (`UnresolvedResolutionWorker` in nlp-pipeline) to
   use `serialize_confluent_avro`.
3. Converted the consumer (`ProvisionalQueuedConsumer` in knowledge-graph)
   to use `deserialize_confluent_avro`.
4. Added `tests/architecture/test_kafka_avro_enforcement.py` which scans every
   `deserialize_value` implementation across `services/*/src/**/consumers/`
   and fails the build if a NEW consumer uses pure `json.loads` without
   appearing in the explicit `JSON_CONSUMER_BASELINE`.

The architecture sweep performed for PLAN-0061 found **18 of 21 consumers
already use Avro** (mostly with a JSON-fallback safety net for legacy
payloads — the AVRO_FIRST pattern). Only **3 consumers remain pure JSON**.
This plan tracks the migration of those three.

## Principle (codified)

| Layer | Rule |
|-------|------|
| **Schema source of truth** | One `.avsc` file per topic, in `infra/kafka/schemas/`, registered with the schema registry by `infra/kafka/init/register-schemas.py` at startup. |
| **Canonical model location** | `libs/contracts/src/contracts/canonical/<event>.py` (entity-shaped) **OR** `libs/contracts/src/contracts/events/<domain>/<event>.py` (pure-event-shaped). Mirrors the Avro fields field-for-field. |
| **Producer side** | `serialize_confluent_avro(schema_path, record)` produces the Confluent wire format (5-byte header + Avro body). |
| **Consumer side** | `deserialize_confluent_avro(schema_path, raw)` decodes it. JSON fallback is permitted only as a transition aid for replaying legacy messages — log every fallback hit so the migration window is measurable. |
| **Architecture test** | `tests/architecture/test_kafka_avro_enforcement.py` — fails on any new pure-JSON consumer. Existing exceptions baselined in `JSON_CONSUMER_BASELINE` with a migration-plan reason. |

## In-scope topics

| Topic | Producer | Consumer file (current JSON_ONLY) | Existing schema? |
|-------|----------|-----------------------------------|------------------|
| `intelligence.contradiction.v1` | knowledge-graph (outbox) | `services/alert/src/alert/infrastructure/messaging/consumers/intelligence_consumer.py` | ✅ `infra/kafka/schemas/intelligence.contradiction.v1.avsc` |
| `nlp.article.enriched.v1` | nlp-pipeline (outbox) | `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/enriched_consumer.py` | ✅ `infra/kafka/schemas/nlp.article.enriched.v1.avsc` |
| `entity.canonical.created.v1` | knowledge-graph (outbox) | `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/entity_consumer.py` | ✅ `infra/kafka/schemas/entity.canonical.created.v1.avsc` |

All three target topics already have Avro schemas registered. The work is to
align the **runtime serialization** with the existing schemas.

## Wave A — Migrate `entity.canonical.created.v1` (knowledge-graph entity_consumer) ✅
**Status**: **DONE** — 2026-05-03 · 6 contracts + 2 entity-consumer + 747 KG unit tests pass · ruff + mypy clean

**Why first:** Lowest blast radius. Producer is the same service
(knowledge-graph outbox writes the event after `persist_enrichment`), consumer
is `EntityCreatedConsumer` in the same service. Same-service migration means
no cross-team coordination.

| Task | File | Action |
|------|------|--------|
| T-A-1 | `libs/contracts/src/contracts/events/kg/entity_canonical_created.py` (new) | Add `CanonicalEntityCanonicalCreated` frozen dataclass mirroring the existing `entity.canonical.created.v1.avsc` fields. Provide `from_dict`/`to_dict`. |
| T-A-2 | `libs/contracts/tests/test_events_kg_entity_canonical_created.py` (new) | Field-alignment + round-trip + fastavro-roundtrip tests, mirroring `test_events_kg_provisional_queued.py`. |
| T-A-3 | `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment_core.py` (`persist_enrichment`) | The outbox `payload_avro` is currently a `json.dumps().encode()` blob. Switch to `serialize_avro` against `entity.canonical.created.v1.avsc` (this row is consumed by the outbox dispatcher, which is responsible for prefixing the Confluent header — verify the dispatcher behaviour first, then pick the right helper). |
| T-A-4 | `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/entity_consumer.py` | Replace `json.loads(raw)` in `deserialize_value` with the AVRO_FIRST pattern (Avro on magic-byte 0x00, JSON fallback with warning log). Wire `get_schema_path()` to return the schema path for `entity.canonical.created.v1`. |
| T-A-5 | `services/knowledge-graph/tests/unit/.../test_entity_consumer.py` | Add Avro round-trip test mirroring the one in `test_provisional_queued_consumer.py`. |
| T-A-6 | `tests/architecture/test_kafka_avro_enforcement.py` | Remove the `entity_consumer.py` line from `JSON_CONSUMER_BASELINE`. |

**Validation gate:** knowledge-graph + libs/contracts unit tests + architecture tests all green.

## Wave B — Migrate `nlp.article.enriched.v1` (knowledge-graph enriched_consumer) ✅
**Status**: **DONE** — 2026-05-03 · 7 contracts + 15 enriched-consumer + 677 nlp-pipeline unit tests pass · schema additively extended with `raw_relations_json`/`raw_events_json`/`raw_claims_json` (forward-compat per HR-011) · ruff + mypy clean

**Why second:** The producer is nlp-pipeline (cross-service), so the migration
must coordinate the producer cutover with the consumer cutover. The
AVRO_FIRST pattern (Avro with JSON fallback) handles this naturally — deploy
the consumer first, then the producer.

| Task | File | Action |
|------|------|--------|
| T-B-1 | `libs/contracts/src/contracts/events/nlp/article_enriched.py` (new) | Add canonical model. |
| T-B-2 | `libs/contracts/tests/test_events_nlp_article_enriched.py` (new) | Alignment + round-trip tests. |
| T-B-3 | `services/knowledge-graph/.../consumers/enriched_consumer.py` | AVRO_FIRST `deserialize_value`. |
| T-B-4 | `services/knowledge-graph/tests/unit/.../test_enriched_consumer.py` | Avro round-trip test. |
| T-B-5 | nlp-pipeline outbox dispatcher / event factory | Switch `payload_avro` construction to use the schema. (Verify whether the outbox dispatcher already wraps the Confluent header — most do; if so this task is just the body.) |
| T-B-6 | nlp-pipeline integration tests | Cover the new wire format end-to-end. |
| T-B-7 | `tests/architecture/test_kafka_avro_enforcement.py` | Remove the `enriched_consumer.py` line from `JSON_CONSUMER_BASELINE`. |

**Deployment order:** ship Wave B in two PRs — consumer first (safe because of
the JSON fallback), producer second.

## Wave C — Migrate `intelligence.contradiction.v1` (alert intelligence_consumer) ✅
**Status**: **DONE** — 2026-05-03 · 4 contracts + 3 intelligence-consumer + 435 alert unit tests pass · `JSON_CONSUMER_BASELINE` is now `{}` · ruff + mypy clean

**Why last:** This consumer is the single most complex JSON parser in the
JSON_ONLY set — it dispatches on `event_type` to multiple `AlertType` codes.
We migrate it last so the pattern is settled by the time we touch alert.

| Task | File | Action |
|------|------|--------|
| T-C-1 | `libs/contracts/src/contracts/events/intelligence/contradiction.py` (new) | Canonical model. |
| T-C-2 | `libs/contracts/tests/test_events_intelligence_contradiction.py` (new) | Alignment + round-trip tests. |
| T-C-3 | `services/alert/.../consumers/intelligence_consumer.py` | AVRO_FIRST `deserialize_value`. The `_resolve_topic` dispatch logic is unaffected — it only reads `event_type` from the decoded dict. |
| T-C-4 | `services/alert/tests/unit/.../test_intelligence_consumer.py` | Avro round-trip. |
| T-C-5 | knowledge-graph producer (outbox row construction for contradictions) | Switch `payload_avro` to Avro encoding. |
| T-C-6 | `tests/architecture/test_kafka_avro_enforcement.py` | Remove the `intelligence_consumer.py` line from `JSON_CONSUMER_BASELINE`. The dict should now be empty `{}`. |

**Validation gate:** alert + knowledge-graph + libs/contracts + architecture tests all green; `JSON_CONSUMER_BASELINE` is empty.

## Wave D — Lock the door ✅
**Status**: **DONE** — 2026-05-03 · architecture test unconditional (no baseline lookup), R28 added to RULES.md, STANDARDS.md §3.7.1 documents the producer/consumer contract, BP-313 added to BUG_PATTERNS.md · 2 architecture tests pass

Once the baseline is empty, harden the architecture test:

| Task | File | Action |
|------|------|--------|
| T-D-1 | `tests/architecture/test_kafka_avro_enforcement.py` | After `JSON_CONSUMER_BASELINE = {}` is in main, **remove the baseline-lookup code path** so the test is unconditional: any pure-JSON `deserialize_value` is a build failure. |
| T-D-2 | `RULES.md` | Add **Hard Rule R28 — All Kafka contracts use Avro**: every topic has a registered `.avsc`; producer uses `serialize_confluent_avro`; consumer uses `deserialize_confluent_avro` (or `deserialize_avro` for non-Confluent envelopes). Pure JSON serialization on Kafka is forbidden. |
| T-D-3 | `docs/STANDARDS.md` | Add a §3.x section documenting the canonical-model layout (`canonical/` for entity payloads vs `events/<domain>/` for trigger events) and the producer/consumer helper functions. |
| T-D-4 | `docs/BUG_PATTERNS.md` | Add BP-307 — *"JSON-only Kafka consumer hides schema-evolution bugs"* — with reference to PLAN-0062. |

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| In-flight messages during cutover are JSON, but the new consumer expects Avro | Use the AVRO_FIRST pattern (Avro on magic-byte 0x00, JSON fallback with structured log). The fallback log lets us watch the JSON traffic decay to zero before removing it. |
| Schema registry not mounted in some environment | The serialization helpers do NOT consult the registry — they read the local `.avsc` file. Schema registry registration is a separate concern handled by `register-schemas.py` at startup. |
| Outbox `payload_avro` already contains JSON in some places | This is the actual blocker — outbox-dispatched events are stored in PostgreSQL as the bytes that will be produced. We must change the producer-side write at the outbox-row construction site, not just the dispatcher. Audit each topic's outbox writers (T-A-3, T-B-5, T-C-5). |
| Breaking change to event_type unions | Out of scope — Wave A/B/C just change the encoding. Field changes are deferred. |

## Estimated effort

| Wave | Effort | Notes |
|------|--------|-------|
| A | 1 day | Same-service migration, no cross-team coordination |
| B | 2 days | Cross-service; deploy in two PRs |
| C | 2 days | Largest event-type dispatch; careful test coverage |
| D | 0.5 day | Documentation + rule codification |

Total: ~5–6 days of focused work.

## Validation gate (each wave)

- [ ] `ruff check libs/contracts/src services/<svc>/src tests/architecture`
- [ ] `mypy libs/contracts/src services/<svc>/src --config-file mypy.ini`
- [ ] `pytest libs/contracts/tests services/<svc>/tests -m unit`
- [ ] `pytest tests/architecture/test_kafka_avro_enforcement.py`
- [ ] After Wave D: `JSON_CONSUMER_BASELINE` is empty AND the baseline-lookup code is deleted

## Out of scope

- Schema field changes (additive evolution, deprecations) — handled by normal schema-version bumps
- Outbox dispatcher refactors beyond the Confluent header concern
- Producer-side authentication/authorization — covered by PRD-0025 + ongoing security work
- Schema Registry compatibility-mode tightening — separate platform decision

## Acceptance

This plan is complete when:
1. `JSON_CONSUMER_BASELINE` in `tests/architecture/test_kafka_avro_enforcement.py` is empty.
2. The baseline-lookup code path is removed (Wave D-1) so the test is unconditional.
3. RULES.md Hard Rule R28 is in main.
4. Every topic in the platform has a registered `.avsc` AND a corresponding canonical model in `libs/contracts`.
