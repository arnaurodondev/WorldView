# intelligence-migrations · DDL Init Container

> **Owner**: Intelligence domain (shared) · **Database**: `intelligence_db` · **Port**: none (one-shot init container)
> **Status**: Mature — runs as `depends_on: service_completed_successfully` before S6 and S7

---

## Mission & Boundaries

**Owns**: All DDL for `intelligence_db` (the shared database used by S6 NLP Pipeline and S7 Knowledge Graph).
Runs Alembic migrations to completion, seeds reference tables, and embeds canonical relation types via Ollama.
Exits with code 0 on success.

**Never does**: Serve HTTP requests, consume Kafka, hold long-running processes.
S6 and S7 connect to `intelligence_db` with `ALEMBIC_ENABLED=false` — they must never run Alembic against `intelligence_db`.

**Boot order**: Must complete before S6 and S7 start. Docker Compose enforces this with
`depends_on: intelligence-migrations: condition: service_completed_successfully`.

---

## What it does on startup

1. **Alembic migrations** — Creates all 21 tables, 100+ indexes, and 108 pre-seeded range partitions via `alembic upgrade head`
2. **Seed scripts** — Runs idempotent SQL scripts in `seeds/` (`001_model_registry.sql`, `002_prompt_templates.sql`)
3. **Embedding population** — Embeds `relation_type_registry` canonical types via Ollama (non-blocking on failure)
4. Exits with code 0

---

## Database: `intelligence_db`

### Tables

| Table | Partitioning | Seed Data |
|-------|-------------|-----------|
| `decay_class_config` | — | 6 rows (inline) |
| `source_trust_weights` | — | 11 rows (inline) |
| `model_registry` | — | `seeds/001_model_registry.sql` |
| `prompt_templates` | — | `seeds/002_prompt_templates.sql` |
| `canonical_entities` | — | — |
| `entity_aliases` | — | — |
| `entity_embedding_state` | — | — |
| `llm_usage_log` | — | — |
| `relation_type_registry` | — | 20 rows (inline) |
| `relations` | HASH ×8 | — |
| `relation_evidence_raw` | — | — |
| `relation_evidence` | RANGE monthly (36 months) | — |
| `relation_contradiction_links` | — | — |
| `relation_summaries` | — | — |
| `claims` | RANGE monthly (36 months) | — |
| `events` | RANGE monthly (36 months) | — |
| `event_entities` | — | — |
| `provisional_entity_queue` | — | — |
| `embedding_migration_state` | — | — |
| `outbox_events` | — | — |
| `dead_letter_queue` | — | — |

### Partitioned tables

`relation_evidence`, `claims`, and `events` use RANGE partitioning by month. The 2024-01 through 2026-12 partitions are pre-seeded in the initial migration. For future months either:
- Let S7's `monthly_partition_job` create them automatically, or
- Add a new Alembic revision manually (see `services/intelligence-migrations/README.md`)

---

## Kafka Topics

None — this service produces no events and consumes nothing.

---

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `INTELLIGENCE_DB_URL` | Yes | — | Postgres connection string (`postgresql://` or `postgresql+asyncpg://`) |
| `EMBEDDING_BASE_URL` | No | `http://ollama:11434` | Ollama API endpoint for relation-type embeddings |
| `EMBEDDING_MODEL` | No | `bge-large-en-v1.5` | Embedding model used at seed time |

---

## Running Locally

```bash
# Build
docker build -t intel-migrations services/intelligence-migrations/

# Run against local Postgres
docker run \
  -e INTELLIGENCE_DB_URL=postgresql://postgres:postgres@localhost:5432/intelligence_db \
  -e EMBEDDING_BASE_URL=http://host.docker.internal:11434 \
  --network host \
  intel-migrations
```

Via dev compose (preferred):
```bash
make dev   # intelligence-migrations runs automatically before S6/S7 start
```

---

## Tests

```bash
# Integration tests (require Postgres with pgvector extension)
cd services/intelligence-migrations
INTELLIGENCE_DB_URL=postgresql://postgres:postgres@localhost:5432/intelligence_test_db \
  python -m pytest tests/ -v
```

---

## Key Pitfalls

- **Never add intelligence_db Alembic to S6 or S7.** Both services must run with `ALEMBIC_ENABLED=false`. Adding Alembic there will cause migration conflicts on the next boot.
- **Embedding failure is non-blocking.** If Ollama is unavailable, seed succeeds and S7's `EmbeddingRefreshWorker` will backfill embeddings asynchronously.
- **asyncpg URLs accepted.** `postgresql+asyncpg://` is automatically rewritten to `postgresql://` for the synchronous Alembic runner.

---

## Recent Migrations

| Revision | Description |
|----------|-------------|
| `0026` | Add UNIQUE INDEX `idx_canonical_entities_lower_name` on `canonical_entities (lower(canonical_name))` (DEF-014 / BP-384 — case-insensitive functional unique index; closes the find-then-create dedup race in `persist_enrichment` by giving the new repository helper `create_or_get` an atomic `ON CONFLICT (lower(canonical_name)) DO NOTHING` target). Plain (non-CONCURRENTLY) index — `canonical_entities` is not partitioned, so BP-393 does not apply. |
| `0027` | Add `summary_embedding_model_id TEXT` and `summary_last_embedded_at TIMESTAMPTZ` to `relation_summaries`, plus partial index `idx_relation_summaries_model_id` (DEF-022 — embedding model tracking; both columns nullable, no backfill required). |
| `0028` | Add UNIQUE INDEX `idx_temporal_events_event_id_unique` on `temporal_events (event_id)` (DEF-025 / BP-316 — replay-safe deterministic event_id; pairs with `graph_write` switching from `new_uuid7()` to `uuid5_from_parts(doc_id, subject_entity_id, event_type)` so Kafka replays land on `ON CONFLICT DO NOTHING` instead of inserting duplicate rows). Plain (non-CONCURRENTLY) index — BP-393 forbids CONCURRENTLY on partitioned parents on PG16; even though `temporal_events` is currently un-partitioned the convention keeps the DDL valid for future partitioning. Operationally a no-op given the existing `pk_temporal_events PRIMARY KEY (event_id)`, but documents the invariant explicitly. |
| `0029` | Add nullable `next_retry_at TIMESTAMPTZ` column to `provisional_entity_queue` plus partial index `idx_provisional_queue_retry_at` (predicate `status='pending' AND next_retry_at IS NOT NULL`) (DEF-033 — exponential backoff for `ProvisionalEnrichmentWorker` / `ProvisionalQueuedConsumer`).  Pre-existing rows have NULL → immediately eligible (no backfill); the modified `claim_batch` SELECT explicitly handles NULL via `next_retry_at IS NULL OR next_retry_at <= now()`.  Plain (non-CONCURRENTLY) index per the BP-393 partition-safety convention. |

---

## Related Documentation

- `services/intelligence-migrations/README.md` — detailed operational notes and partition management
- `docs/services/nlp-pipeline.md` — S6 connects to `intelligence_db` (read/write, no DDL)
- `docs/services/knowledge-graph.md` — S7 connects to `intelligence_db` (read/write, no DDL)
- `docs/MASTER_PLAN.md` §5 — intelligence_db ownership model
