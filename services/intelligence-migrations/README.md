# intelligence-migrations

DDL owner for `intelligence_db`. This is a one-shot init container — no application logic, no API, no Kafka consumers. It runs Alembic migrations against `intelligence_db` and exits.

## What this container does

- Applies all `intelligence_db` DDL via `alembic upgrade head`
- Seeds static reference data: `decay_class_config` (6 rows) and `relation_type_registry` (20 rows)
- Runs exactly once at platform boot (or on re-deploy when new migrations exist)
- Exits with code 0 on success, non-zero on any migration failure

## Boot order requirement

This container **must complete before S6 (nlp-pipeline) and S7 (knowledge-graph) start.** See PRD §12.1 step 5. Docker Compose `depends_on: condition: service_completed_successfully` enforces this.

S6 and S7 connect to `intelligence_db` with **`ALEMBIC_ENABLED=false`** — they perform read/write operations only and must never run Alembic against `intelligence_db`.

## How to run locally

```bash
# Build the image
docker build -t intel-migrations .

# Run against a local Postgres with pgvector installed
docker run \
  -e INTELLIGENCE_DB_URL=postgresql://postgres:postgres@localhost:5432/intelligence_db \
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

## Seed data

| Table | Rows | Purpose |
|-------|------|---------|
| `decay_class_config` | 6 | Defines confidence decay rates (PERMANENT → EPHEMERAL) |
| `relation_type_registry` | 20 | Canonical relation types with decay class and base confidence |
