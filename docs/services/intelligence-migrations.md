# intelligence-migrations · DDL Init Container

> **Owner**: Intelligence domain (shared) · **Database**: `intelligence_db`
> **Port**: None (one-shot init container)
> **Status**: Production-ready — runs as `condition: service_completed_successfully` before S6 and S7

---

## Mission

`intelligence-migrations` is the **sole DDL owner for `intelligence_db`**. It is not a long-running
service — it runs once at startup, applies all Alembic migrations, seeds reference data, and exits
with code 0.

This init container exists because `intelligence_db` is shared between two services — S6
(NLP Pipeline) and S7 (Knowledge Graph). A single owner prevents migration conflicts: both S6 and S7
connect to `intelligence_db` with `ALEMBIC_ENABLED=false` and perform read/write operations only.

**intelligence-migrations does NOT**:
- Serve HTTP requests
- Consume Kafka events
- Hold any long-running processes after migrations complete
- Allow S6 or S7 to run Alembic against `intelligence_db`

---

## What It Does on Startup

The `entrypoint.sh` script runs three sequential steps:

### Step 1 — Alembic Migrations

```bash
alembic upgrade head
```

Creates all tables, indexes, partitions, extensions, and seed data. After running, the script
asserts the current revision equals the head revision — any partial apply exits with code 1.

### Step 2 — Seed SQL Scripts

Runs all `.sql` files in `seeds/` in alphabetical order:

| File | Contents |
|------|---------|
| `001_model_registry.sql` | Registers ML models (BGE, Qwen, Llama, Gemini) in `model_registry` |
| `002_prompt_templates.sql` | Loads LLM prompt templates into `prompt_templates` |

All seed scripts are idempotent (`ON CONFLICT DO NOTHING` or `INSERT ... WHERE NOT EXISTS`).

### Step 3 — Relation Type Embeddings (non-blocking)

Runs `scripts/populate_embeddings.py` via Ollama to embed all rows in `relation_type_registry`
that have `embedding IS NULL`. This enables the ANN soft-map in S7's Block 11 canonicalization.

**Non-blocking**: if Ollama is unavailable (e.g. slow start, no GPU), this step is skipped with
`|| true`. S7's `EmbeddingRefreshWorker` will backfill embeddings asynchronously on its next cycle.

---

## Boot Order

```
postgres (healthy)
    └── intelligence-migrations (completed successfully)
            ├── nlp-pipeline-migrate (completed successfully)
            │       └── nlp-pipeline (healthy)
            └── knowledge-graph (healthy)
```

Docker Compose enforces this with:

```yaml
# S6 and S7 both declare:
depends_on:
  intelligence-migrations:
    condition: service_completed_successfully
```

If `intelligence-migrations` exits non-zero, all dependent services fail to start.

---

## Database: `intelligence_db`

### Extensions

```sql
CREATE EXTENSION IF NOT EXISTS vector;    -- pgvector for 1024-dim embeddings
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- trigram similarity for fuzzy entity resolution
CREATE EXTENSION IF NOT EXISTS age;      -- Apache AGE for Cypher queries (must be pre-installed)
```

pgvector and pg_trgm are created by migration `0001`. Apache AGE must be installed on the
PostgreSQL server before migrations run.

### Tables

| Table | Partitioning | Seeded by | Purpose |
|-------|-------------|-----------|---------|
| `decay_class_config` | — | Migration 0001 (6 rows) | Decay class parameters for confidence formula |
| `source_trust_weights` | — | Migration 0001 (11 rows) | Source type reliability weights for routing signal |
| `model_registry` | — | `seeds/001_model_registry.sql` | Registered ML models with capability/dimension metadata |
| `prompt_templates` | — | `seeds/002_prompt_templates.sql` | LLM prompts used by S6/S7 workers |
| `canonical_entities` | — | Migration 0009 (224 bootstrap entities) | Resolved entity registry |
| `entity_aliases` | — | Migration 0009 | Alias index with type (EXACT, TICKER, ISIN, CUSIP, FIGI, LEI, NAME) |
| `entity_embedding_state` | — | — | Multi-view 1024-dim embeddings (3 rows per entity) |
| `entity_narrative_versions` | — | — | Version-controlled LLM narratives |
| `llm_usage_log` | — | — | Per-call LLM cost + latency tracking |
| `relation_type_registry` | — | Migration 0001 (20 rows), 0004 (+7 rows) | Canonical relation types with decay_class and semantic_mode |
| `relations` | HASH ×8 on `subject_entity_id` | — | Aggregated relation state |
| `relation_evidence_raw` | — | — | Append-only staging (hot path) |
| `relation_evidence` | RANGE monthly (36 months) | — | Processed relation evidence |
| `relation_contradiction_links` | — | — | Detected claim contradictions |
| `relation_summaries` | — | — | LLM summaries with HNSW embedding index |
| `claims` | RANGE monthly (36 months) | — | Temporal claims and point-in-time assertions |
| `events` | RANGE monthly (36 months) | — | Extracted events with `structured_data` JSONB |
| `event_entities` | — | — | Entity-to-event linkage |
| `temporal_events` | — | — | Geopolitical/macro events |
| `entity_event_exposures` | — | — | Entity exposure to temporal events |
| `provisional_entity_queue` | — | — | Unresolved entities awaiting S7 Worker 13E enrichment |
| `path_insights` | — | — | Pre-computed multi-hop paths (PLAN-0074) |
| `embedding_migration_state` | — | — | State tracking for embedding migrations |
| `outbox_events` | — | — | Transactional outbox for S7 Kafka messages |
| `dead_letter_queue` | — | — | S7 dead-letter messages |

### Partitioned Tables

`relation_evidence`, `claims`, and `events` use **RANGE partitioning by month**.

Partitions pre-seeded in migration `0001`: **2024-01 through 2026-12** (36 months each).

For months beyond 2026-12, partitions are created automatically by S7's `MonthlyPartitionWorker`
(APScheduler, runs on the 1st of each month and at startup). If S7 has not yet run and new data
arrives for a future month, the INSERT will fail with a partition violation error. Resolve by:

1. Letting S7's worker run (it creates next-month partitions automatically), OR
2. Adding a new Alembic revision manually:

```bash
# From services/intelligence-migrations/
alembic revision -m "add_partitions_2027"
```

Then in the migration file:

```python
def upgrade() -> None:
    for table in ("relation_evidence", "claims", "events"):
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS {table}_2027_01
            PARTITION OF {table}
            FOR VALUES FROM ('2027-01-01') TO ('2027-02-01')
        """)
        # ... repeat for each month
```

### Critical DDL Invariants

**`partition_key` is `GENERATED ALWAYS AS STORED`** in `relations` and `relation_evidence_raw`.
This column must NEVER appear in INSERT statements — PostgreSQL raises an error if it does.
The correct INSERT lists all columns explicitly, omitting `partition_key`.

---

## Migration History

### Current head

Migration `0038_seed_demo_entities.py` (38 applied revisions).

### Complete migration sequence

| Revision | Description |
|----------|-------------|
| `0001` | Create full intelligence_db schema: extensions, all 21 tables, 108 partitions, seed decay_class_config + source_trust_weights + relation_type_registry (20 rows) |
| `0002` | Enhance events and relations: add `event_subtype`, `structured_data` JSONB to events; add `relation_source` fields |
| `0003` | Remove `fundamentals_ohlcv` view from `entity_embedding_state` for non-company entities |
| `0004` | Add geopolitical/AGE-related temporal events support; 7 new relation types |
| `0005` | Add `extraction_model_id` column to `claims` |
| `0006` | Extend `llm_usage_log`: add provider, cost, latency columns |
| `0007` | Idempotent `CREATE TABLE IF NOT EXISTS temporal_events` (guard for stale volumes) |
| `0008` | Add partial UNIQUE index `uidx_entity_aliases_entity_norm_type` on `entity_aliases (entity_id, normalized_alias_text, alias_type) WHERE is_active=true`; pre-cleans existing duplicates |
| `0009` | Bootstrap 224 canonical entities across 9 NER classes (currency, regulatory_body, government_body, location, person, financial_institution, commodity, macroeconomic_indicator, index) with EXACT self-alias + embedding_state rows |
| `0010` | Partial index for Stage-2 PRIMARY_TICKER resolution lookups (non-CONCURRENTLY) |
| `0011` | CONCURRENT version of alias normalization index for production use |
| `0012` | Backfill EXACT aliases for mature canonicals missing them |
| `0013` | Seed `relation_type_registry.embedding` for existing rows via Ollama |
| `0018` | Add `corporate_event_type` to EventType enum |
| `0019` | Add `evidence_text` column to `relation_evidence_raw` (was missing from hot path) |
| `0020` | Add `'noise'` to `provisional_entity_queue.status` CHECK constraint (Worker 13E two-layer filter) |
| `0021` | Add `ck_canonical_entity_type` CHECK constraint on `canonical_entities.entity_type` (12 valid values) |
| `0022` | Add enrichment fields to `canonical_entities`: `enrichment_status`, `enrichment_attempts`, `last_enriched_at` |
| `0023` | Add source fields to `relation_type_registry`: `source_paper`, `source_url` |
| `0024` | Add `relation_source` tracking columns to `relations` |
| `0025` | Add index on `relations.relation_id` for efficient joins |
| `0026` | Add UNIQUE INDEX `idx_canonical_entities_lower_name` on `lower(canonical_name)` (DEF-014 / BP-384 — closes find-then-create dedup race; partial `WHERE entity_type != 'financial_instrument'`) |
| `0027` | Add `summary_embedding_model_id TEXT` and `summary_last_embedded_at TIMESTAMPTZ` to `relation_summaries` + partial index for drift auditing (DEF-022) |
| `0028` | Add UNIQUE INDEX `idx_temporal_events_event_id_unique` on `temporal_events(event_id)` (DEF-025 / BP-316 — replay-safe deterministic event IDs) |
| `0029` | Add nullable `next_retry_at TIMESTAMPTZ` to `provisional_entity_queue` + partial index for exponential backoff filter (DEF-033) |
| `0030` | Add `processing_started_at TIMESTAMPTZ` to `provisional_entity_queue` (stuck-job reclaim support) |
| `0031` | Add `entity_narrative_versions` table (PLAN-0074 narrative generation) |
| `0032` | Add `path_insights` + `path_insight_queue` + `path_templates` tables (PLAN-0074 Wave E) |
| `0033` | Activate previously unused columns on `relations` (wave A cleanup) |
| `0034` | Verify and recreate `relation_summaries` HNSW embedding index if missing |
| `0035` | Add source fields to `relation_evidence_raw`: `source_name`, `source_url` |
| `0036` | Add `path_templates` seed data |
| `0037` | Recreate `temporal_events` table idempotently to resolve volume/schema divergence |
| `0038` | Seed demo entities for local development |

---

## Kafka Topics

None. `intelligence-migrations` produces no events and consumes nothing.

---

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `INTELLIGENCE_DB_URL` | Yes | — | PostgreSQL connection string. Both `postgresql://` and `postgresql+asyncpg://` are accepted (asyncpg prefix is automatically rewritten to `postgresql://` for the synchronous Alembic runner). |
| `EMBEDDING_BASE_URL` | No | `http://ollama:11434` | Ollama API endpoint used to embed `relation_type_registry` canonical types during Step 3. |
| `EMBEDDING_MODEL` | No | `bge-large:latest` | Embedding model name. Must be the same model as S6/S7 use (`BAAI/bge-large-en-v1.5` compatible, 1024-dim). |

---

## How to Run Locally

### Recommended: via Docker Compose

```bash
# From the repo root:
make dev
# intelligence-migrations runs automatically before S6 and S7 start.
```

### Direct Docker run

```bash
# Build the image
cd services/intelligence-migrations
docker build -t intel-migrations .

# Run against a local Postgres with pgvector and AGE installed
docker run \
  -e INTELLIGENCE_DB_URL=postgresql://postgres:postgres@localhost:5432/intelligence_db \
  -e EMBEDDING_BASE_URL=http://host.docker.internal:11434 \
  -e EMBEDDING_MODEL=bge-large:latest \
  --network host \
  intel-migrations
```

### Manual Alembic (for development/debugging)

```bash
cd services/intelligence-migrations

# Check current revision
alembic current

# Apply all migrations
alembic upgrade head

# Check for drift between code and DB
alembic check

# Roll back one step
alembic downgrade -1

# View migration history
alembic history
```

### PostgreSQL requirements

`intelligence_db` requires:
- **PostgreSQL 16** (minimum version for `GENERATED ALWAYS AS STORED` columns)
- **pgvector extension** — install from https://github.com/pgvector/pgvector
- **pg_trgm extension** — built into PostgreSQL, just needs `CREATE EXTENSION`
- **Apache AGE extension** — install from https://age.apache.org/; see AGE installation docs

Check extensions are available before running migrations:

```sql
SELECT name FROM pg_available_extensions WHERE name IN ('vector', 'pg_trgm', 'age');
```

---

## How to Run Tests

```bash
# Integration tests (require running Postgres with pgvector; AGE optional)
cd services/intelligence-migrations

INTELLIGENCE_DB_URL=postgresql://postgres:postgres@localhost:5432/intelligence_test_db \
  python -m pytest tests/ -v

# Validate migration syntax only (no DB required)
alembic check
```

Tests verify:
- Each migration applies cleanly to a fresh database
- Migrations are reversible (downgrade + upgrade roundtrip)
- Seed data is idempotent (double-run does not fail)
- Key constraints and indexes exist after migration head

Currently tested migrations: `0034`, `0035`, `0036`, `0037`, `0038`.

---

## How to Add a New Migration

```bash
# From services/intelligence-migrations/
alembic revision -m "describe_your_change"
```

Edit the generated file in `alembic/versions/`. Follow these rules:

1. **NEVER create indexes with `CONCURRENTLY`** on partitioned tables (PostgreSQL 16 restriction,
   BP-393). Use plain `CREATE INDEX` inside a migration. For very large tables in production,
   create indexes manually after deployment.
2. **Add columns with defaults, never remove or rename** (R12 forward-compatibility).
3. **`partition_key` columns are STORED** — never include them in INSERT statement examples in
   migration comments.
4. **Test rollback**: every `upgrade()` must have a working `downgrade()`.
5. **Document the migration purpose** in the module docstring with the relevant PRD/DEF number.

For partition management, prefer letting S7's `MonthlyPartitionWorker` create them automatically
rather than adding a migration.

---

## DDL Ownership Model

This is the most important architectural invariant for the intelligence domain. Violating it
causes migration chain conflicts on the next boot.

```
intelligence-migrations         S6 (nlp-pipeline)        S7 (knowledge-graph)
─────────────────────────       ──────────────────        ─────────────────────
Runs Alembic                    ALEMBIC_ENABLED=false     ALEMBIC_ENABLED=false
CREATE TABLE                    READ/WRITE only            READ/WRITE only
ALTER TABLE                     NO DDL                     NO DDL
CREATE INDEX                    NO DDL                     NO DDL
Runs ONCE at startup            Runs continuously          Runs continuously
```

If S6 or S7 run Alembic against `intelligence_db`:
- On the next restart, `intelligence-migrations` will try to re-apply migrations that S6/S7
  already applied, causing checksum failures or duplicate object errors.
- The `RuntimeError` guard in the session factory (`alembic_enabled=False` check) is the
  last line of defence, but it is better to never reach it.

**How to detect a violation**: `alembic current` in `intelligence-migrations` will show a
revision ID that does not match the head from `alembic heads`, or `alembic check` will fail.

---

## Common Pitfalls

1. **Never add `intelligence_db` Alembic config to S6 or S7.** Both services must run with
   `ALEMBIC_ENABLED=false`. Any Alembic configuration for `intelligence_db` in these services
   will cause migration conflicts on the next boot.

2. **Embedding failure is non-blocking.** Step 3 runs `|| true`, so Ollama unavailability does
   not fail the migration container. Embeddings remain NULL until S7's `EmbeddingRefreshWorker`
   backfills them. The ANN soft-map in S7 Block 11 will return no matches until this backfill
   completes — relation types will be proposed via `relation.type.proposed.v1` rather than
   canonicalized.

3. **asyncpg URLs are accepted.** `INTELLIGENCE_DB_URL=postgresql+asyncpg://...` works — the
   entrypoint script rewrites it to `postgresql://` for the synchronous Alembic + psql runner.

4. **CONCURRENTLY is forbidden on partitioned tables** (PostgreSQL 16, BP-393). Do not add
   `CONCURRENTLY` to index creation in migrations for `relations`, `relation_evidence`,
   `claims`, `events`, or `events`. Use plain `CREATE INDEX`.

5. **Monthly partition gap**: If S7's `MonthlyPartitionWorker` has not yet run and data for
   a new month arrives, INSERTs into `relation_evidence`, `claims`, or `events` will fail.
   Resolve by running the worker once or adding a migration with the new partitions.

6. **Demo entity UUIDs are stable**: Migration `0038` seeds demo entities with hardcoded UUIDs.
   Re-running the migration (e.g., on a fresh DB) is idempotent because `ON CONFLICT DO NOTHING`
   is used. Do not change these UUIDs after production deployment — they may be referenced by
   `provisional_entity_queue` rows.

---

## Related Documentation

- `docs/services/nlp-pipeline.md` — S6 connects to `intelligence_db` (read/write, no DDL)
- `docs/services/knowledge-graph.md` — S7 connects to `intelligence_db` (read/write, no DDL)
- `docs/MASTER_PLAN.md` §5 — intelligence_db ownership model and shared-database rationale
- `services/intelligence-migrations/README.md` — operational notes, partition management
