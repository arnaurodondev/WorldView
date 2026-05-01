# Kafka Avro Schemas

This directory holds the Avro schema files registered with the Confluent
Schema Registry. The Schema Registry is the source of truth for wire
compatibility; these `.avsc` files are the developer-facing source for
register-time + compile-time generation.

## Filename convention

Two patterns coexist for historical reasons:

| Pattern | Used for | Example |
|---------|----------|---------|
| `<topic>.avsc` (no version suffix) | Legacy schemas predating PLAN-0057. The "current canonical" file for a topic. Schema Registry tracks per-version IDs internally, so this filename simply represents whichever version was registered most recently. | `market.instrument.created.avsc` |
| `<topic>.v<N>.avsc` | Net-new versioned schemas added by PLAN-0057 onwards. The version number matches the Schema Registry version at registration time. | `market.instrument.discovered.v1.avsc` |

PLAN-0057 QA D-003 noted the inconsistency. We chose to **document the
convention** rather than rename existing files because:

1. The Schema Registry uses `<topic>-value` subjects regardless of filename.
2. Renaming `market.instrument.created.avsc` would break grep paths in
   ~30 service files, the dispatcher's `_AVSC_MAP`, and existing test code.
3. The version is unambiguous in code (`schema_version` envelope field) and
   in the registry (per-subject version numbers).

**Going forward**: every new schema lands as `<topic>.v<N>.avsc`. Bumping a
versioned schema (e.g., `v1` → `v2`) creates a new file rather than
overwriting the existing one — old consumers must remain able to load v1.

## Compatibility

All subjects use `BACKWARD` compatibility unless explicitly noted. The
project pins this via `infra/kafka/init/set-schema-compatibility.sh`
(`make schema-set-compat`). PLAN-0057 QA D-004 added the script + init
container so the registry never relies on Confluent's silent default.

`relation.type.proposed.v1` is the one exception (set to `FULL`) — it
needs the strictest contract because it gates ontology evolution.

## Adding a new schema

1. Create `infra/kafka/schemas/<topic>.v<N>.avsc` with full envelope
   (`event_id`, `event_type`, `schema_version`, `occurred_at`).
2. Register the topic in `infra/kafka/init/create-topics.sh`.
3. Add the dispatcher mapping in your service's outbox dispatcher
   (`_AVSC_MAP` / `EVENT_TOPIC_MAP`).
4. Re-run `make schema-set-compat` after first registration.

## Bumping a schema (forward-compat only)

R11: every change must be backward-compatible at the schema-registry level.

* New fields MUST have a `default: null` (and be nullable union types).
* Field renames are forbidden. Removals are forbidden.
* If you genuinely need a breaking change, register a new topic +
  versioned schema and run a parallel-publish migration.
