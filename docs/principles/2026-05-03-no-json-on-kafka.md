---
title: No JSON on Kafka — All Wire Contracts Use Avro
date: 2026-05-03
owner: Platform
status: ratified
ratified: 2026-05-03
---

# Platform Principle — No JSON on Kafka

## Why

Pure-JSON Kafka payloads make schema drift invisible. Producers can rename
a field, drop a default, or change a value's type and every downstream
JSON consumer keeps decoding into a Python `dict` without complaint —
the missing key surfaces as a `KeyError` weeks later, in production,
inside a single consumer that happened to read it. There is no compile-
time check, no registry-time check, no test-time check. JSON-on-Kafka
turns every topic into an implicit-and-unenforced contract whose only
authoritative description lives in whichever code path was edited last.

The architecture sweep performed for PLAN-0061 / PLAN-0062 found three
JSON-only consumers on topics that already had registered `.avsc`
schemas — meaning the producers and consumers had silently diverged
from the declared contract for months. See BP-313.

## The decision

**Every Kafka topic in worldview uses Avro on the wire.**

Concretely:

- One `.avsc` file per topic in `infra/kafka/schemas/`, registered with
  Confluent Schema Registry by `infra/kafka/init/register-schemas.py`
  at startup.
- One frozen-dataclass canonical model in `libs/contracts/src/contracts/`
  mirroring the schema field-for-field.
- Producers use `messaging.kafka.serialization_utils.serialize_confluent_avro`.
- Consumers use `messaging.kafka.serialization_utils.deserialize_confluent_avro`.
- A JSON-fallback path is permitted **only** as a transition aid during
  the migration of an existing topic, must log every fallback hit at
  `warning` level, and must be removed once traffic decays to zero.

Enforcement is mechanical, not policy:

- **Hard Rule R28** in `RULES.md` codifies the rule.
- **Architecture test** `tests/architecture/test_kafka_avro_enforcement.py`
  is unconditional after PLAN-0062 Wave D — any consumer whose
  `deserialize_value` body uses `json.loads` without `deserialize_confluent_avro`
  fails the build.

## Cross-references

- [PLAN-0062](../plans/0062-kafka-avro-enforcement-migration-plan.md) — the migration plan that codified this rule
- [Hard Rule R28](../../RULES.md) — the hard rule itself
- [BP-313](../BUG_PATTERNS.md#bp-313--json-only-kafka-consumer-hides-schema-evolution-bugs-plan-0062) — the bug pattern this principle prevents
- [STANDARDS.md §3.7](../STANDARDS.md) — the producer/consumer contract documentation, including §3.7.2 for the `_json` heterogeneous-array escape hatch
