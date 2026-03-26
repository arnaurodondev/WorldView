# intelligence-migrations

DDL owner for `intelligence_db`. This is a one-shot init container — no application logic, no API, no Kafka consumers. It runs Alembic migrations, seeds reference data, and populates embeddings, then exits.

## What this container does

1. **Alembic migrations** — Creates all 21 tables, 100+ indexes, 108 pre-seeded partitions via `alembic upgrade head`
2. **Seed scripts** — Runs idempotent SQL scripts in `seeds/` for `model_registry` and `prompt_templates`
3. **Embedding population** — Embeds `relation_type_registry` canonical types via Ollama (non-blocking on failure)
4. Exits with code 0 on success

### Tables created

| Table | Partitioning | Seed Data |
|-------|-------------|-----------|
| `decay_class_config` | — | 6 rows (inline) |
| `source_trust_weights` | — | 11 rows (inline) |
| `model_registry` | — | via `seeds/001_model_registry.sql` |
| `prompt_templates` | — | via `seeds/002_prompt_templates.sql` |
| `canonical_entities` | — | — |
| `entity_aliases` | — | — |
| `entity_embedding_state` | ��� | �� |
| `llm_usage_log` | — | — |
| `relation_type_registry` | — | 20 rows (inline) |
| `relations` | HASH x8 | — |
| `relation_evidence_raw` | — | — |
| `relation_evidence` | RANGE monthly (36) | — |
| `relation_contradiction_links` | — | — |
| `relation_summaries` | — | — |
| `claims` | RANGE monthly (36) | — |
| `events` | RANGE monthly (36) | — |
| `event_entities` | — | — |
| `provisional_entity_queue` | — | — |
| `embedding_migration_state` | — | — |
| `outbox_events` | — | — |
| `dead_letter_queue` | — | — |

## Boot order requirement

This container **must complete before S6 (nlp-pipeline) and S7 (knowledge-graph) start.** See PRD §12.1 step 5. Docker Compose `depends_on: condition: service_completed_successfully` enforces this.

S6 and S7 connect to `intelligence_db` with **`ALEMBIC_ENABLED=false`** ��� they perform read/write operations only and must never run Alembic against `intelligence_db`.

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `INTELLIGENCE_DB_URL` | Yes | — | Postgres connection string |
| `EMBEDDING_BASE_URL` | No | `http://ollama:11434` | Ollama API endpoint |
| `EMBEDDING_MODEL` | No | `bge-large-en-v1.5` | Embedding model name |

## How to run locally

```bash
# Build the image
docker build -t intel-migrations .

# Run against a local Postgres with pgvector installed
docker run \
  -e INTELLIGENCE_DB_URL=postgresql://postgres:postgres@localhost:5432/intelligence_db \
  -e EMBEDDING_BASE_URL=http://host.docker.internal:11434 \
  --network host \
  intel-migrations
```

The `INTELLIGENCE_DB_URL` environment variable is required. asyncpg-style URLs (`postgresql+asyncpg://`) are accepted and automatically rewritten to `postgresql://` for the sync Alembic runner.

## Warning: never add intelligence_db Alembic to S6 or S7

`intelligence_db` DDL is exclusively owned by this container. If you add `intelligence_db` Alembic configuration to `services/nlp-pipeline/` or `services/knowledge-graph/`, the migration chain will conflict with this container on the next boot.

Both services must have `ALEMBIC_ENABLED=false` (or equivalent guard) in their startup code.

## How to add a new partition (for S7 monthly_partition_job)

`relation_evidence`, `claims`, and `events` are RANGE-partitioned by month. The 2024-01 through 2026-12 partitions are pre-seeded in `0001_create_intelligence_db.py`. For future months, create a new migration file:

```bash
# From services/intelligence-migrations/
alembic revision -m "add_partitions_2027"
```

Then in the new `upgrade()`:

```python
op.execute("""
CREATE TABLE relation_evidence_2027_01 PARTITION OF relation_evidence
    FOR VALUES FROM ('2027-01-01') TO ('2027-02-01')
""")
# ... repeat for claims_2027_01, events_2027_01
```

The S7 `monthly_partition_job` should create next-month partitions automatically; this manual step is only needed if S7's job has not yet run and a new month's data arrives.

## Running tests

```bash
# Integration tests (requires running Postgres with pgvector)
INTELLIGENCE_DB_URL=postgresql://postgres:postgres@localhost:5432/intelligence_test_db \
  python -m pytest tests/ -v
```
