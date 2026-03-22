# Execution Prompt 0011 — Ingestion Pipeline v1 Foundations · Wave 04

## Context (read first)

- **Planning response**: `docs/ai-interactions/agent-responses/0011-response-20260322-ingestion-pipeline-v1-foundations.md`
- **Authoritative spec**: `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md` §6.4, §6.5, §8, §12.1

## Assigned agent profile(s)

- `.claude/agents/data-platform-engineer.md`

## Mandatory pre-read

1. `AGENTS.md`
2. `CLAUDE.md`
3. `RULES.md`
4. `docs/ai-interactions/agent-responses/0011-response-20260322-ingestion-pipeline-v1-foundations.md` — task specs for T-F-010, T-F-011
5. `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md` §6.4 (full intelligence_db DDL), §6.5 (alert_db DDL), §8 (relation_type_registry 20-row seed), §12.1 (boot order)
6. `.claude/agents/data-platform-engineer.md` — partition rules, STORED column constraint
7. `services/content-ingestion/` — stub pattern reference for T-F-011 service scaffold
8. `services/portfolio/pyproject.toml` — scaffold reference
9. `services/knowledge-graph/` — alembic env.py pattern reference (async setup)

## Objective

Execute two tasks in parallel: create the `intelligence-migrations` init container with the complete `intelligence_db` DDL (T-F-010, XL effort) and create the S10 Alert Service stub with `alert_db` migration (T-F-011, M effort). Both are independent of each other and can proceed concurrently.

**No service application logic in this wave.** T-F-010 is DDL-only. T-F-011 is service scaffold + DDL-only (no consumer or handler implementation).

## Task scope for this wave

### Parallel group — both tasks are independent

| Task | What | Files touched |
|------|------|---------------|
| **T-F-010** | `intelligence-migrations` init container: Dockerfile + Alembic + full `intelligence_db` DDL + seed data | `services/intelligence-migrations/` (all new) |
| **T-F-011** | S10 Alert Service stub + `alert_db` Alembic migration | `services/alert/` (all new), `docs/services/alert.md` |

**Wave 03 must be fully committed before Wave 04 begins.** T-F-010 does not depend on T-F-007/008/009 but the migration pattern from those waves is a useful reference.

## Implementation instructions

### T-F-010 — `intelligence-migrations` init container

#### Purpose

This is a standalone init container — no application logic, no API, no Kafka consumers. It runs exactly once at boot (step 5 in PRD §12.1 boot order), applies all `intelligence_db` DDL, seeds static reference data, and exits. S6 (`nlp-pipeline`) and S7 (`knowledge-graph`) connect to `intelligence_db` with `ALEMBIC_ENABLED=false` — they are forbidden from running Alembic against this database.

#### Directory layout

```
services/intelligence-migrations/
  Dockerfile
  requirements.txt
  alembic.ini
  alembic/
    env.py
    versions/
      0001_create_intelligence_db.py
  README.md
```

#### Step 1 — Container scaffold

**`Dockerfile`**:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY alembic/ alembic/
COPY alembic.ini .
ENTRYPOINT ["alembic", "upgrade", "head"]
```

**`requirements.txt`**:
```
alembic>=1.13
psycopg2-binary>=2.9
sqlalchemy>=2.0
structlog>=24.0
```

**`alembic.ini`**:
```ini
[alembic]
script_location = alembic
prepend_sys_path = .
version_path_separator = os

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

**`alembic/env.py`** — sync configuration (one-shot container; no async needed):
```python
import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None

def get_url() -> str:
    url = os.environ.get("INTELLIGENCE_DB_URL")
    if not url:
        raise RuntimeError("INTELLIGENCE_DB_URL environment variable is required")
    # Replace asyncpg driver with psycopg2 for sync Alembic runs
    return url.replace("postgresql+asyncpg://", "postgresql://")

def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

run_migrations_online()
```

#### Step 2 — Migration `0001_create_intelligence_db.py`

Create `alembic/versions/0001_create_intelligence_db.py`. The revision hash may be any valid 12-character hex string (e.g., `a1b2c3d4e5f6`).

Implement `upgrade()` in the following strict order to respect FK constraints:

**Block A — Extensions**:
```python
op.execute("CREATE EXTENSION IF NOT EXISTS vector")
op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
```

**Block B — `decay_class_config`** (seeded immediately; FK target for `relations` and `relation_type_registry`):
```python
op.execute("""
CREATE TABLE decay_class_config (
    decay_class               VARCHAR(20) PRIMARY KEY,
    half_life_days            FLOAT,
    decay_alpha               FLOAT        NOT NULL,
    recompute_interval_minutes INT         NOT NULL,
    description               TEXT
)
""")
op.execute("""
INSERT INTO decay_class_config VALUES
    ('PERMANENT',  NULL,   0.000000, 10080, 'Board membership, incorporation facts'),
    ('DURABLE',    730.0,  0.000950, 10080, 'Long-term contracts, credit ratings'),
    ('SLOW',       180.0,  0.003851, 1440,  'Supplier relationships, strategic partnerships'),
    ('MEDIUM',     60.0,   0.011552, 360,   'Market share claims, analyst ratings'),
    ('FAST',       14.0,   0.049510, 60,    'Sentiment signals, short-term price targets'),
    ('EPHEMERAL',  3.0,    0.231049, 15,    'Intraday momentum, real-time sentiment')
""")
```

**Block C — `model_registry`**:
```python
op.execute("""
CREATE TABLE model_registry (
    registry_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id         VARCHAR(200) NOT NULL,
    provider         VARCHAR(50)  NOT NULL,
    capability       VARCHAR(50)  NOT NULL,
    version          VARCHAR(50),
    dimension        INT,
    max_input_tokens INT          NOT NULL,
    is_active        BOOLEAN      NOT NULL DEFAULT true,
    performance_tier VARCHAR(20)  NOT NULL DEFAULT 'PRIMARY',
    config           JSONB,
    registered_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (model_id, provider, version)
)
""")
```

**Block D — `prompt_templates`** (FK target for `relation_summaries`):
```python
op.execute("""
CREATE TABLE prompt_templates (
    template_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             VARCHAR(200) NOT NULL,
    version          INT          NOT NULL,
    capability       VARCHAR(50)  NOT NULL,
    template_text    TEXT         NOT NULL,
    output_schema    JSONB        NOT NULL,
    model_constraints JSONB,
    is_active        BOOLEAN      NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (name, version)
)
""")
```

**Block E — `canonical_entities` + `entity_aliases` + `entity_profile_embeddings`**:
```python
op.execute("""
CREATE TABLE canonical_entities (
    entity_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name VARCHAR(500)  NOT NULL,
    entity_type    VARCHAR(50)   NOT NULL,
    isin           VARCHAR(20),
    ticker         VARCHAR(20),
    exchange       VARCHAR(20),
    metadata       JSONB,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
)
""")
op.execute("""
CREATE INDEX idx_entities_ticker_exchange ON canonical_entities (ticker, exchange)
    WHERE ticker IS NOT NULL
""")
op.execute("CREATE INDEX idx_entities_isin ON canonical_entities (isin) WHERE isin IS NOT NULL")
op.execute("CREATE INDEX idx_entities_type ON canonical_entities (entity_type)")

op.execute("""
CREATE TABLE entity_aliases (
    alias_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id   UUID        NOT NULL REFERENCES canonical_entities(entity_id) ON DELETE CASCADE,
    alias_text  VARCHAR(500) NOT NULL,
    alias_type  VARCHAR(30)  NOT NULL,
    source      VARCHAR(50),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
)
""")
op.execute("CREATE UNIQUE INDEX uidx_entity_aliases_exact ON entity_aliases (lower(alias_text)) WHERE alias_type = 'EXACT'")
op.execute("CREATE INDEX idx_entity_aliases_text ON entity_aliases USING gin (alias_text gin_trgm_ops)")
op.execute("CREATE INDEX idx_entity_aliases_entity ON entity_aliases (entity_id)")

op.execute("""
CREATE TABLE entity_profile_embeddings (
    embedding_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id         UUID        NOT NULL REFERENCES canonical_entities(entity_id) ON DELETE CASCADE,
    embedding         VECTOR(1024) NOT NULL,
    model_id          VARCHAR(200) NOT NULL,
    profile_text      TEXT,
    embedding_stale   BOOLEAN      NOT NULL DEFAULT false,
    last_refreshed_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (entity_id, model_id)
)
""")
op.execute("""
CREATE INDEX idx_entity_profile_emb_hnsw ON entity_profile_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WHERE embedding_stale = false
""")
```

**Block F — `relations` (HASH-partitioned ×8)**:

CRITICAL constraint: `partition_key` is `GENERATED ALWAYS AS (abs(hashtext(subject_entity_id::text)) % 8) STORED`. Never include it in INSERT statements. The PRIMARY KEY must include `subject_entity_id` because Postgres requires the partition key to be part of every unique/primary key on a partitioned table.

```python
op.execute("""
CREATE TABLE relations (
    relation_id              UUID         NOT NULL DEFAULT gen_random_uuid(),
    subject_entity_id        UUID         NOT NULL,
    canonical_type           VARCHAR(100) NOT NULL,
    object_entity_id         UUID         NOT NULL,
    semantic_mode            VARCHAR(20)  NOT NULL DEFAULT 'RELATION_STATE',
    decay_class              VARCHAR(20)  NOT NULL REFERENCES decay_class_config(decay_class),
    decay_alpha              FLOAT        NOT NULL,
    base_confidence          FLOAT        NOT NULL DEFAULT 0.5,
    confidence               FLOAT,
    confidence_stale         BOOLEAN      NOT NULL DEFAULT true,
    confidence_last_computed_at TIMESTAMPTZ,
    first_evidence_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    latest_evidence_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    evidence_count           INT          NOT NULL DEFAULT 0,
    valid_from               TIMESTAMPTZ,
    valid_to                 TIMESTAMPTZ,
    valid_to_confidence      FLOAT,
    valid_to_source          VARCHAR(30),
    invalidated_by_event_id  UUID,
    relation_period_type     VARCHAR(20)  NOT NULL DEFAULT 'ONGOING',
    strongest_contra_score   FLOAT        NOT NULL DEFAULT 0.0,
    contra_count_by_type     JSONB        NOT NULL DEFAULT '{}',
    latest_contra_at         TIMESTAMPTZ,
    contra_stale             BOOLEAN      NOT NULL DEFAULT false,
    summary_stale            BOOLEAN      NOT NULL DEFAULT true,
    partition_key            INT          NOT NULL
        GENERATED ALWAYS AS (abs(hashtext(subject_entity_id::text)) % 8) STORED,
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (relation_id, subject_entity_id)
) PARTITION BY HASH (subject_entity_id)
""")

for i in range(8):
    op.execute(f"""
CREATE TABLE relations_p{i} PARTITION OF relations
    FOR VALUES WITH (MODULUS 8, REMAINDER {i})
""")

op.execute("CREATE UNIQUE INDEX uidx_relations_triple ON relations (subject_entity_id, canonical_type, object_entity_id)")
op.execute("CREATE INDEX idx_relations_subject ON relations (subject_entity_id, canonical_type, confidence DESC)")
op.execute("CREATE INDEX idx_relations_object ON relations (object_entity_id, canonical_type)")
op.execute("""
CREATE INDEX idx_relations_stale_confidence ON relations (decay_class, latest_evidence_at DESC)
    WHERE confidence_stale = true
""")
op.execute("""
CREATE INDEX idx_relations_stale_summary ON relations (confidence DESC, latest_evidence_at DESC)
    WHERE summary_stale = true
""")
op.execute("""
CREATE INDEX idx_relations_valid ON relations (subject_entity_id, canonical_type)
    WHERE valid_to IS NULL AND relation_period_type = 'ONGOING'
""")
```

**Block G — `relation_evidence_raw`** (hot-path staging, append-only):
```python
op.execute("""
CREATE TABLE relation_evidence_raw (
    raw_id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_entity_id     UUID        NOT NULL,
    object_entity_id      UUID        NOT NULL,
    canonical_type        VARCHAR(100) NOT NULL,
    polarity              VARCHAR(20)  NOT NULL DEFAULT 'positive',
    claim_id              UUID,
    chunk_id              UUID,
    source_document_id    UUID         NOT NULL,
    extraction_confidence FLOAT        NOT NULL,
    source_trust_weight   FLOAT        NOT NULL DEFAULT 1.0,
    extracted_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    processed             BOOLEAN      NOT NULL DEFAULT false,
    processed_at          TIMESTAMPTZ,
    worker_claim_id       UUID,
    partition_key         INT          NOT NULL
        GENERATED ALWAYS AS (abs(hashtext(subject_entity_id::text)) % 8) STORED
)
""")
op.execute("""
CREATE INDEX idx_raw_evidence_unprocessed ON relation_evidence_raw (extracted_at)
    WHERE processed = false
""")
op.execute("CREATE INDEX idx_raw_evidence_subject ON relation_evidence_raw (subject_entity_id, extracted_at DESC)")
op.execute("""
CREATE INDEX idx_raw_evidence_partition_unprocessed
    ON relation_evidence_raw (partition_key, extracted_at)
    WHERE processed = false
""")
```

**Block H — `relation_evidence`** (RANGE-partitioned by month, immutable):

Pre-seed monthly partitions from 2024-01 through 2026-12 (36 partitions). Use a loop:
```python
op.execute("""
CREATE TABLE relation_evidence (
    evidence_id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    relation_id           UUID        NOT NULL,
    doc_id                UUID        NOT NULL,
    chunk_id              UUID,
    evidence_text         TEXT,
    canonicalized_evidence_text TEXT,
    extraction_confidence FLOAT       NOT NULL,
    source_weight         FLOAT       NOT NULL DEFAULT 1.0,
    evidence_date         TIMESTAMPTZ NOT NULL,
    claim_id              UUID,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
) PARTITION BY RANGE (evidence_date)
""")

import calendar
for year in range(2024, 2027):
    for month in range(1, 13):
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1
        partition_name = f"relation_evidence_{year}_{month:02d}"
        op.execute(f"""
CREATE TABLE {partition_name} PARTITION OF relation_evidence
    FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{next_year}-{next_month:02d}-01')
""")

op.execute("CREATE INDEX idx_rel_evidence_relation ON relation_evidence (relation_id, evidence_date DESC)")
op.execute("CREATE INDEX idx_rel_evidence_doc ON relation_evidence (doc_id)")
op.execute("CREATE INDEX idx_rel_evidence_claim ON relation_evidence (claim_id) WHERE claim_id IS NOT NULL")
```

**Block I — `relation_contradiction_links`**:
```python
op.execute("""
CREATE TABLE relation_contradiction_links (
    link_id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    relation_evidence_id UUID        NOT NULL REFERENCES relation_evidence(evidence_id),
    claim_id             UUID        NOT NULL,
    contradiction_type   VARCHAR(50) NOT NULL,
    strength             FLOAT       NOT NULL DEFAULT 1.0,
    detected_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    invalidated_at       TIMESTAMPTZ,
    invalidation_reason  TEXT,
    UNIQUE (relation_evidence_id, claim_id)
)
""")
op.execute("CREATE INDEX idx_contra_links_evidence ON relation_contradiction_links (relation_evidence_id)")
op.execute("CREATE INDEX idx_contra_links_claim ON relation_contradiction_links (claim_id)")
op.execute("""
CREATE INDEX idx_contra_links_active ON relation_contradiction_links (detected_at DESC)
    WHERE invalidated_at IS NULL
""")
```

**Block J — `relation_summaries`** (with HNSW index on `summary_embedding`):
```python
op.execute("""
CREATE TABLE relation_summaries (
    summary_id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    relation_id        UUID        NOT NULL,
    summary_text       TEXT        NOT NULL,
    evidence_count     INT         NOT NULL,
    evidence_hash      VARCHAR(64) NOT NULL,
    summary_embedding  VECTOR(1024),
    embedding_model    VARCHAR(200),
    generated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    model_id           VARCHAR(200) NOT NULL,
    prompt_template_id UUID        NOT NULL REFERENCES prompt_templates(template_id),
    is_current         BOOLEAN     NOT NULL DEFAULT true,
    generation_trigger VARCHAR(50) NOT NULL
)
""")
op.execute("""
CREATE UNIQUE INDEX uidx_relation_summaries_current ON relation_summaries (relation_id)
    WHERE is_current = true
""")
op.execute("CREATE INDEX idx_relation_summaries_relation ON relation_summaries (relation_id, generated_at DESC)")
op.execute("""
CREATE INDEX idx_relation_summary_emb_hnsw ON relation_summaries
    USING hnsw (summary_embedding vector_cosine_ops)
    WHERE is_current = true AND summary_embedding IS NOT NULL
""")
```

**Block K — `claims`** (RANGE-partitioned, monthly):

Pre-seed 2024-01 through 2026-12:
```python
op.execute("""
CREATE TABLE claims (
    claim_id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id                UUID        NOT NULL,
    chunk_id              UUID,
    claimer_entity_id     UUID,
    subject_entity_id     UUID,
    claim_type            VARCHAR(100) NOT NULL,
    polarity              VARCHAR(20)  NOT NULL DEFAULT 'positive',
    claim_text            TEXT         NOT NULL,
    extraction_confidence FLOAT        NOT NULL,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
) PARTITION BY RANGE (created_at)
""")
for year in range(2024, 2027):
    for month in range(1, 13):
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1
        op.execute(f"""
CREATE TABLE claims_{year}_{month:02d} PARTITION OF claims
    FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{next_year}-{next_month:02d}-01')
""")
op.execute("""
CREATE INDEX idx_claims_contradiction_detection ON claims
    (subject_entity_id, claim_type, polarity, created_at DESC)
    WHERE subject_entity_id IS NOT NULL AND polarity != 'neutral'
""")
op.execute("""
CREATE INDEX idx_claims_by_claimer ON claims
    (claimer_entity_id, claim_type, created_at DESC)
    WHERE claimer_entity_id IS NOT NULL
""")
```

**Block L — `events`** (RANGE-partitioned, monthly):

Pre-seed 2024-01 through 2026-12:
```python
op.execute("""
CREATE TABLE events (
    event_id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id                UUID        NOT NULL,
    subject_entity_id     UUID,
    event_type            VARCHAR(100) NOT NULL,
    event_date            TIMESTAMPTZ,
    event_text            TEXT,
    extraction_confidence FLOAT        NOT NULL,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
) PARTITION BY RANGE (created_at)
""")
for year in range(2024, 2027):
    for month in range(1, 13):
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1
        op.execute(f"""
CREATE TABLE events_{year}_{month:02d} PARTITION OF events
    FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{next_year}-{next_month:02d}-01')
""")
op.execute("""
CREATE INDEX idx_events_subject ON events (subject_entity_id, event_type, event_date DESC)
    WHERE subject_entity_id IS NOT NULL
""")
```

**Block M — `embedding_migration_state`**:
```python
op.execute("""
CREATE TABLE embedding_migration_state (
    migration_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    model_from         VARCHAR(200) NOT NULL,
    model_to           VARCHAR(200) NOT NULL,
    target_table       VARCHAR(100) NOT NULL,
    phase              VARCHAR(30)  NOT NULL,
    backfill_progress  FLOAT        NOT NULL DEFAULT 0.0,
    started_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    completed_at       TIMESTAMPTZ,
    notes              TEXT
)
""")
```

**Block N — `provisional_entity_queue`**:
```python
op.execute("""
CREATE TABLE provisional_entity_queue (
    queue_id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    mention_text       VARCHAR(500) NOT NULL,
    mention_class      VARCHAR(50)  NOT NULL,
    context_snippet    TEXT,
    status             VARCHAR(20)  NOT NULL DEFAULT 'pending',
    assigned_entity_id UUID,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    resolved_at        TIMESTAMPTZ,
    retry_count        INT          NOT NULL DEFAULT 0
)
""")
op.execute("CREATE INDEX idx_provisional_pending ON provisional_entity_queue (created_at) WHERE status = 'pending'")
```

**Block O — `outbox_events` + `dead_letter_queue`**:
```python
op.execute("""
CREATE TABLE outbox_events (
    event_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic          VARCHAR(200)  NOT NULL,
    partition_key  TEXT          NOT NULL,
    payload_avro   BYTEA         NOT NULL,
    status         VARCHAR(20)   NOT NULL DEFAULT 'pending',
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    dispatched_at  TIMESTAMPTZ,
    retry_count    INT           NOT NULL DEFAULT 0,
    failed_at      TIMESTAMPTZ
)
""")
op.execute("CREATE INDEX idx_outbox_intel_pending ON outbox_events (created_at) WHERE status = 'pending'")

op.execute("""
CREATE TABLE dead_letter_queue (
    dlq_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_event_id UUID         NOT NULL,
    topic             VARCHAR(200) NOT NULL,
    payload_avro      BYTEA        NOT NULL,
    error_detail      TEXT,
    status            VARCHAR(20)  NOT NULL DEFAULT 'failed',
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    resolved_at       TIMESTAMPTZ,
    resolution_note   TEXT
)
""")
```

**Block P — `relation_type_registry`** (20-row seed from PRD §8):
```python
op.execute("""
CREATE TABLE relation_type_registry (
    type_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_type  VARCHAR(100) NOT NULL UNIQUE,
    semantic_mode   VARCHAR(20)  NOT NULL,
    decay_class     VARCHAR(20)  NOT NULL REFERENCES decay_class_config(decay_class),
    base_confidence FLOAT        NOT NULL DEFAULT 0.5,
    description     TEXT,
    is_active       BOOLEAN      NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
)
""")
op.execute("""
INSERT INTO relation_type_registry (canonical_type, semantic_mode, decay_class, base_confidence, description)
VALUES
    ('employs',              'RELATION_STATE',  'DURABLE',   0.70, 'Board, C-suite roles; event-invalidatable'),
    ('board_member_of',      'RELATION_STATE',  'DURABLE',   0.75, NULL),
    ('subsidiary_of',        'RELATION_STATE',  'SLOW',      0.65, NULL),
    ('acquired_by',          'RELATION_STATE',  'PERMANENT', 0.85, 'Finalized by merger_completed event'),
    ('listed_on',            'RELATION_STATE',  'DURABLE',   0.80, 'Invalidated by delisted event'),
    ('supplier_of',          'RELATION_STATE',  'SLOW',      0.55, NULL),
    ('partner_of',           'RELATION_STATE',  'SLOW',      0.50, NULL),
    ('competes_with',        'RELATION_STATE',  'MEDIUM',    0.45, NULL),
    ('regulates',            'RELATION_STATE',  'DURABLE',   0.75, NULL),
    ('headquartered_in',     'RELATION_STATE',  'PERMANENT', 0.80, NULL),
    ('analyst_rating',       'TEMPORAL_CLAIM',  'FAST',      0.60, 'Historically anchored; not validity-gated'),
    ('market_share_claim',   'TEMPORAL_CLAIM',  'MEDIUM',    0.50, NULL),
    ('price_target',         'TEMPORAL_CLAIM',  'FAST',      0.55, NULL),
    ('earnings_guidance',    'TEMPORAL_CLAIM',  'MEDIUM',    0.60, NULL),
    ('sentiment_signal',     'TEMPORAL_CLAIM',  'EPHEMERAL', 0.45, NULL),
    ('credit_rating',        'TEMPORAL_CLAIM',  'DURABLE',   0.70, NULL),
    ('investment_in',        'RELATION_STATE',  'MEDIUM',    0.60, NULL),
    ('owns_stake_in',        'RELATION_STATE',  'MEDIUM',    0.65, NULL),
    ('issues_debt',          'TEMPORAL_CLAIM',  'MEDIUM',    0.55, NULL),
    ('produces',             'RELATION_STATE',  'SLOW',      0.60, 'Commodity production')
""")
```

#### Step 3 — `downgrade()` function

Drop all tables in reverse FK order:
```python
def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS relation_type_registry CASCADE")
    op.execute("DROP TABLE IF EXISTS dead_letter_queue CASCADE")
    op.execute("DROP TABLE IF EXISTS outbox_events CASCADE")
    op.execute("DROP TABLE IF EXISTS provisional_entity_queue CASCADE")
    op.execute("DROP TABLE IF EXISTS embedding_migration_state CASCADE")
    op.execute("DROP TABLE IF EXISTS events CASCADE")
    op.execute("DROP TABLE IF EXISTS claims CASCADE")
    op.execute("DROP TABLE IF EXISTS relation_summaries CASCADE")
    op.execute("DROP TABLE IF EXISTS relation_contradiction_links CASCADE")
    op.execute("DROP TABLE IF EXISTS relation_evidence CASCADE")
    op.execute("DROP TABLE IF EXISTS relation_evidence_raw CASCADE")
    op.execute("DROP TABLE IF EXISTS relations CASCADE")
    op.execute("DROP TABLE IF EXISTS entity_profile_embeddings CASCADE")
    op.execute("DROP TABLE IF EXISTS entity_aliases CASCADE")
    op.execute("DROP TABLE IF EXISTS canonical_entities CASCADE")
    op.execute("DROP TABLE IF EXISTS prompt_templates CASCADE")
    op.execute("DROP TABLE IF EXISTS model_registry CASCADE")
    op.execute("DROP TABLE IF EXISTS decay_class_config CASCADE")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS vector")
```

#### Step 4 — `services/intelligence-migrations/README.md`

Required content:
- What this container does (DDL owner for `intelligence_db`; runs once at boot)
- Boot order requirement: must run before S6 and S7 start (§12.1 step 5)
- How to run locally for testing: `docker build -t intel-migrations . && docker run -e INTELLIGENCE_DB_URL=postgresql://postgres:postgres@localhost:5432/intelligence_db intel-migrations`
- Warning: S6 and S7 must set `ALEMBIC_ENABLED=false` — never add `intelligence_db` Alembic config to those services
- How to create a new partition (for S7 monthly_partition_job reference)

**Validation gate** (run before marking T-F-010 done):
```bash
# Verify directory structure
ls services/intelligence-migrations/
# Must show: Dockerfile  alembic/  alembic.ini  requirements.txt  README.md

# Validate migration file is valid Python
python -c "
import ast
with open('services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py') as f:
    ast.parse(f.read())
print('Migration syntax OK')
"

# If Postgres + pgvector available (integration test):
# docker run -e INTELLIGENCE_DB_URL=postgresql://postgres:postgres@localhost:5432/intelligence_db intel-migrations
# After run:
# psql -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" intelligence_db
# Must return 20+ tables

# Verify seed data counts (after migration run):
# psql -c "SELECT count(*) FROM decay_class_config" intelligence_db   # must = 6
# psql -c "SELECT count(*) FROM relation_type_registry" intelligence_db  # must = 20
# psql -c "SELECT count(*) FROM pg_inherits WHERE inhparent = 'relations'::regclass" intelligence_db  # must = 8
```

---

### T-F-011 — S10 Alert Service stub + `alert_db` Alembic migration

#### Purpose

Create `services/alert/` as a functional stub: pyproject.toml, config.py, alembic setup, and the `alert_db` Alembic migration. **No Kafka consumers, no FastAPI routes, no application logic.** The stub must be importable, lintable, and the migration must be runnable.

#### Directory layout

```
services/alert/
  Makefile
  README.md
  pyproject.toml
  alembic.ini
  alembic/
    env.py
    versions/
      0001_create_alert_db.py
  src/
    alert/
      __init__.py
      config.py
  tests/
    __init__.py
  configs/
    dev.local.env.example
```

#### Step 1 — `pyproject.toml`

Follow the pattern of `services/content-ingestion/pyproject.toml`. Package name: `alert`. Import name: `alert`. Port: 8010.

Required dependencies: `fastapi>=0.111`, `uvicorn[standard]>=0.29`, `pydantic-settings>=2.0`, `sqlalchemy[asyncio]>=2.0`, `asyncpg>=0.29`, `alembic>=1.13`, `structlog>=24.0`.

Dev dependencies: `pytest>=8`, `pytest-asyncio`, `ruff`, `mypy`.

Tool configuration:
- ruff: `line-length = 120`, same rules as other services
- mypy: `strict = true`
- pytest: `asyncio_mode = "auto"`

#### Step 2 — `src/alert/config.py`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ALERT_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    s1_portfolio_base_url: str = "http://localhost:8001"
    internal_service_token: str = ""
    watchlist_cache_ttl_seconds: int = 300
    alert_dedup_window_seconds: int = 3600
    pending_alert_ttl_days: int = 7
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/alert_db"
    kafka_bootstrap_servers: str = "localhost:9092"
    schema_registry_url: str = "http://localhost:8081"
    valkey_url: str = "redis://localhost:6379/0"


settings = Settings()
```

Note: `env_prefix="ALERT_"` means env vars are `ALERT_DATABASE_URL`, `ALERT_KAFKA_BOOTSTRAP_SERVERS`, etc.

#### Step 3 — `alembic.ini` + `alembic/env.py`

`alembic.ini`: same structure as `services/content-ingestion/alembic.ini`. `sqlalchemy.url` is overridden by `env.py` from `ALERT_DATABASE_URL` env var.

`alembic/env.py`: async-compatible (for consistency with other services). Read `ALERT_DATABASE_URL`.

#### Step 4 — `alembic/versions/0001_create_alert_db.py`

```python
"""create alert_db schema

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-03-22
"""
from alembic import op


def upgrade() -> None:
    op.execute("""
    CREATE TABLE alert_subscriptions (
        subscription_id UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id         UUID        NOT NULL,
        entity_id       UUID        NOT NULL,
        watchlist_id    UUID        NOT NULL,
        alert_types     TEXT[]      NOT NULL DEFAULT '{}',
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        deleted_at      TIMESTAMPTZ,
        UNIQUE (user_id, entity_id, watchlist_id)
    )
    """)
    op.execute("""
    CREATE INDEX idx_subscriptions_entity ON alert_subscriptions (entity_id)
        WHERE deleted_at IS NULL
    """)
    op.execute("""
    CREATE INDEX idx_subscriptions_user ON alert_subscriptions (user_id)
        WHERE deleted_at IS NULL
    """)

    op.execute("""
    CREATE TABLE alerts (
        alert_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
        entity_id       UUID        NOT NULL,
        alert_type      VARCHAR(100) NOT NULL,
        source_event_id UUID        NOT NULL,
        source_topic    VARCHAR(200) NOT NULL,
        payload         JSONB       NOT NULL,
        dedup_key       VARCHAR(200) NOT NULL,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (dedup_key)
    )
    """)
    op.execute("CREATE INDEX idx_alerts_entity ON alerts (entity_id, created_at DESC)")

    op.execute("""
    CREATE TABLE alert_deliveries (
        delivery_id  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
        alert_id     UUID        NOT NULL REFERENCES alerts(alert_id),
        user_id      UUID        NOT NULL,
        channel      VARCHAR(20) NOT NULL DEFAULT 'websocket',
        status       VARCHAR(20) NOT NULL DEFAULT 'delivered',
        delivered_at TIMESTAMPTZ,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """)
    op.execute("CREATE INDEX idx_deliveries_alert ON alert_deliveries (alert_id)")
    op.execute("""
    CREATE INDEX idx_deliveries_user_pending ON alert_deliveries (user_id, created_at DESC)
        WHERE status = 'pending'
    """)

    op.execute("""
    CREATE TABLE pending_alerts (
        pending_id   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id      UUID        NOT NULL,
        alert_id     UUID        NOT NULL REFERENCES alerts(alert_id),
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        delivered_at TIMESTAMPTZ,
        UNIQUE (user_id, alert_id)
    )
    """)
    op.execute("""
    CREATE INDEX idx_pending_alerts_user ON pending_alerts (user_id, created_at)
        WHERE delivered_at IS NULL
    """)

    op.execute("""
    CREATE TABLE outbox_events (
        event_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        topic          VARCHAR(200)  NOT NULL,
        partition_key  TEXT          NOT NULL,
        payload_avro   BYTEA         NOT NULL,
        status         VARCHAR(20)   NOT NULL DEFAULT 'pending',
        created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
        dispatched_at  TIMESTAMPTZ,
        retry_count    INT           NOT NULL DEFAULT 0,
        failed_at      TIMESTAMPTZ
    )
    """)
    op.execute("CREATE INDEX idx_outbox_s10_pending ON outbox_events (created_at) WHERE status = 'pending'")

    op.execute("""
    CREATE TABLE dead_letter_queue (
        dlq_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        original_event_id UUID         NOT NULL,
        topic             VARCHAR(200) NOT NULL,
        payload_avro      BYTEA        NOT NULL,
        error_detail      TEXT,
        status            VARCHAR(20)  NOT NULL DEFAULT 'failed',
        created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
        resolved_at       TIMESTAMPTZ,
        resolution_note   TEXT
    )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dead_letter_queue CASCADE")
    op.execute("DROP TABLE IF EXISTS outbox_events CASCADE")
    op.execute("DROP TABLE IF EXISTS pending_alerts CASCADE")
    op.execute("DROP TABLE IF EXISTS alert_deliveries CASCADE")
    op.execute("DROP TABLE IF EXISTS alerts CASCADE")
    op.execute("DROP TABLE IF EXISTS alert_subscriptions CASCADE")
```

#### Step 5 — `configs/dev.local.env.example`

```bash
ALERT_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/alert_db
ALERT_KAFKA_BOOTSTRAP_SERVERS=localhost:9092
ALERT_SCHEMA_REGISTRY_URL=http://localhost:8081
ALERT_VALKEY_URL=redis://localhost:6379/0
ALERT_S1_PORTFOLIO_BASE_URL=http://localhost:8001
ALERT_INTERNAL_SERVICE_TOKEN=dev-token
ALERT_WATCHLIST_CACHE_TTL_SECONDS=300
ALERT_ALERT_DEDUP_WINDOW_SECONDS=3600
ALERT_PENDING_ALERT_TTL_DAYS=7
```

#### Step 6 — `Makefile`

```makefile
.PHONY: run test lint migrate

run:
	uvicorn alert.main:app --host 0.0.0.0 --port 8010 --reload

test:
	python -m pytest tests/ -x -q

lint:
	ruff check src/ tests/
	mypy src/

migrate:
	alembic upgrade head
```

**Validation gate** (run before marking T-F-011 done):
```bash
# Lint and type-check
cd services/alert
ruff check src/ tests/
mypy src/

# Verify config import
python -c "from alert.config import Settings; s = Settings(); assert 'alert_db' in s.database_url; print('Config OK')"

# Verify migration syntax
python -c "
import ast
with open('alembic/versions/0001_create_alert_db.py') as f:
    ast.parse(f.read())
print('Migration syntax OK')
"
```

#### Documentation: `docs/services/alert.md`

Create `docs/services/alert.md` with all 8 documentation quality criteria met:

1. **Service overview**: S10 Alert Service — consumes `portfolio.watchlist.updated.v1`, `graph.state.changed.v1`, `nlp.signal.detected.v1`; produces `alert.delivered.v1`. Fan-out to users watching affected entities.
2. **Kafka topics table**: consumed topics with partition key + producer; produced topics.
3. **Database schema section**: all 6 `alert_db` tables with column summaries. Include ER diagram (Mermaid) of `alerts → alert_deliveries`, `alerts → pending_alerts`, `alert_subscriptions`.
4. **ENV vars table**: all 9 `ALERT_*` vars with defaults.
5. **Dedup key formula**: `sha256(entity_id + alert_type + source_event_id + floor(epoch_seconds / alert_dedup_window_seconds))`.
6. **Valkey cache pattern**: `s10:v1:watchlist:by_entity:{entity_id}` — TTL = `watchlist_cache_ttl_seconds`; invalidated on `watchlist.item_added` and `watchlist.item_deleted` events.
7. **Common pitfalls** (≥ 3): (1) not invalidating Valkey cache on watchlist delete — causes phantom alerts; (2) dedup_key collision across dedup windows — document correct floor division; (3) writing to `intelligence_db` from S10 (forbidden — cross-database logical FKs only); (4) running Alembic against `intelligence_db` from S10.
8. **Readiness contract**: S10 `/ready` requires `alert_db` connection healthy + Valkey reachable + Kafka consumer group assigned.

#### Update `docs/MASTER_PLAN.md §3 Service Catalog`

Add S10 Alert Service row to the service catalog table:
- Service ID: S10
- Name: Alert Service
- Port: 8010
- DB: `alert_db`
- Key topics consumed: `portfolio.watchlist.updated.v1`, `graph.state.changed.v1`, `nlp.signal.detected.v1`
- Key topics produced: `alert.delivered.v1`
- Status: stub

## Constraints

- Do NOT implement any FastAPI routes, Kafka consumers, or business logic in either service.
- Do NOT create a `main.py` in `services/alert/` — stub only needs config + migration.
- Do NOT modify `services/knowledge-graph/` (its config was fixed in Wave 01).
- T-F-010: use `op.execute("""...""")` for ALL DDL — never `op.create_table()` or `op.create_index()` for complex DDL like HASH partitions or HNSW indexes.
- T-F-010: `partition_key` STORED column — never include in INSERT statements in any test fixture.
- T-F-010: pre-seed `relation_evidence`, `claims`, and `events` with 2024-01 through 2026-12 partitions (36 months each).
- T-F-011: `dedup_key` field on `alerts` must have `UNIQUE` constraint — this is the dedup gate.

## Scope & token budget

**write_paths**:
```
services/intelligence-migrations/Dockerfile                           # T-F-010
services/intelligence-migrations/requirements.txt                     # T-F-010
services/intelligence-migrations/alembic.ini                          # T-F-010
services/intelligence-migrations/alembic/env.py                       # T-F-010
services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py  # T-F-010
services/intelligence-migrations/README.md                            # T-F-010
services/alert/pyproject.toml                                         # T-F-011
services/alert/alembic.ini                                            # T-F-011
services/alert/alembic/env.py                                         # T-F-011
services/alert/alembic/versions/0001_create_alert_db.py              # T-F-011
services/alert/src/alert/__init__.py                                  # T-F-011
services/alert/src/alert/config.py                                    # T-F-011
services/alert/tests/__init__.py                                      # T-F-011
services/alert/configs/dev.local.env.example                          # T-F-011
services/alert/Makefile                                               # T-F-011
docs/services/alert.md                                                # T-F-011
docs/MASTER_PLAN.md                                                   # T-F-011 (add S10 to service catalog)
```

**Exploration bound**: Read at most 8 files total before making any edit. The response document (T-F-010/T-F-011 specs) and PRD §6.4/§6.5/§8 contain all column specifications — do not explore further.

**Stop condition**: If a pre-existing service's Alembic setup has a pattern incompatible with the approach described here, read `services/portfolio/alembic/` as the reference; do not read more than one additional reference.

## Required tests

```bash
# T-F-010 — Python syntax validation (can run without Postgres)
python -c "
import ast
with open('services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py') as f:
    ast.parse(f.read())
print('T-F-010 migration syntax OK')
"

# T-F-011 — lint + type-check
cd services/alert
ruff check src/ tests/
mypy src/
python -c "from alert.config import Settings; s = Settings(); assert 'alert_db' in s.database_url; print('T-F-011 config OK')"
python -c "
import ast
with open('alembic/versions/0001_create_alert_db.py') as f:
    ast.parse(f.read())
print('T-F-011 migration syntax OK')
"
```

**Integration tests** (require Postgres + pgvector; run separately, marked `@pytest.mark.integration`):

For T-F-010:
```python
# tests/test_intelligence_migrations.py
import pytest
import subprocess

@pytest.mark.integration
def test_migration_creates_all_tables(intelligence_db_url):
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd="services/intelligence-migrations",
        env={"INTELLIGENCE_DB_URL": intelligence_db_url, "PATH": ...},
        capture_output=True
    )
    assert result.returncode == 0
    # Then introspect via psycopg2:
    # assert 20+ tables exist in public schema
    # assert relations has 8 child partition tables in pg_inherits
    # assert decay_class_config has 6 rows
    # assert relation_type_registry has 20 rows
    # assert partition_key on relations is attgenerated='s' in pg_attribute
```

For T-F-011:
```python
@pytest.mark.integration
def test_alert_migration(alert_db_url):
    # Run alembic upgrade head, introspect all 6 tables + indexes
    # assert UNIQUE (dedup_key) on alerts
    # assert partial indexes on alert_subscriptions WHERE deleted_at IS NULL
    # assert UNIQUE (user_id, alert_id) on pending_alerts
```

**Pass criteria**:
- T-F-010 migration file parses as valid Python (syntax check)
- T-F-011: `ruff check` and `mypy --strict` pass on `src/`
- T-F-011: `from alert.config import Settings` imports without error
- `docs/services/alert.md` exists with all 8 quality criteria
- `docs/MASTER_PLAN.md §3` updated with S10 row

## Incremental quality gates (mandatory)

Run these gates **immediately after each task** — do not batch.

**After T-F-010**:
```bash
python -c "import ast; ast.parse(open('services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py').read()); print('OK')"
# Check 36 relation_evidence partition CREATE statements present
grep -c "PARTITION OF relation_evidence" services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py
# Must be 36

# Check 36 claims partitions
grep -c "PARTITION OF claims" services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py
# Must be 36

# Check 8 relations partitions
grep -c "PARTITION OF relations" services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py
# Must be 8

# Check seed data rows
grep -c "'PERMANENT'" services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py
# Must be >= 2 (in decay_class_config INSERT and in relation_type_registry INSERT)
```

**After T-F-011**:
```bash
cd services/alert
ruff check src/ tests/
# Must exit 0

mypy src/
# Must exit 0

python -c "from alert.config import Settings; s = Settings(); assert 'alert_db' in s.database_url; print('OK')"
# Must print OK

grep "UNIQUE (dedup_key)" alembic/versions/0001_create_alert_db.py
# Must return a result — dedup gate must be present
```

**No Deferred Fixes**: Do not carry ruff/mypy failures from T-F-010 into T-F-011. Fix immediately before continuing.

## Documentation requirements

All documentation must meet the **Documentation quality standard** (8 criteria from `docs/ai-interactions/agent-prompts/0000-exec-wave-generation-template.md`).

**Files to update in this wave**:
- `docs/services/alert.md` (create new) — full service documentation per T-F-011 step 6
- `docs/MASTER_PLAN.md §3` — add S10 to service catalog table
- `services/intelligence-migrations/README.md` — init container usage guide

**N/A criteria for this wave**:
- Diagrams for non-trivial flows: `docs/services/alert.md` must include an ER diagram for the alert_db schema (`alerts → alert_deliveries`, `alerts → pending_alerts`, `alert_subscriptions` standalone). This is NOT N/A.
- Realistic code examples: N/A for T-F-010 (DDL-only container). For T-F-011: `docs/services/alert.md` must include a realistic code example of instantiating `Settings` and reading `dedup_key` computation.
- Abstract methods documented: N/A — no abstract classes introduced.
- Common pitfalls: REQUIRED — see T-F-011 step 6 for ≥ 4 pitfalls.
- Lib docs updated: N/A — no libs modified.
- Service docs: `docs/services/alert.md` is the primary output; must reflect final implementation state.

## Required handoff evidence

The executing agent must provide:

1. **Changed files list** (exact paths)
2. **Validation ledger**:
   | Command | Scope | Exit code | Result |
   |---------|-------|-----------|--------|
   | `python -c "import ast; ast.parse(...0001_create_intelligence_db.py...)"` | T-F-010 | 0 | ✓ |
   | `grep -c "PARTITION OF relation_evidence" ...0001_create_intelligence_db.py` | T-F-010 | 0 | 36 |
   | `grep -c "PARTITION OF relations" ...0001_create_intelligence_db.py` | T-F-010 | 0 | 8 |
   | `ruff check services/alert/src/ tests/` | T-F-011 | 0 | ✓ |
   | `mypy services/alert/src/` | T-F-011 | 0 | ✓ |
   | `from alert.config import Settings` | T-F-011 | 0 | ✓ |
   | `grep "UNIQUE (dedup_key)" ...0001_create_alert_db.py` | T-F-011 | 0 | ✓ |

3. **Documentation quality checklist**:
   | Criterion | Status | Notes |
   |-----------|--------|-------|
   | Accuracy verified | ✓ | DDL matches PRD §6.4 and §6.5 exactly |
   | Diagrams for non-trivial flows | ✓ | ER diagram in docs/services/alert.md |
   | Realistic code examples | ✓ | Settings instantiation + dedup_key formula in alert.md |
   | Abstract methods documented | N/A | No abstract classes |
   | Common pitfalls section | ✓ | ≥ 4 pitfalls in docs/services/alert.md |
   | Lib docs updated | N/A | No lib surface change |
   | Service docs reflect final state | ✓ | docs/services/alert.md + MASTER_PLAN §3 updated |
   | No orphan documentation | ✓ | |

4. **Commit message proposal**:
   ```
   feat: intelligence-migrations init container + S10 Alert Service stub

   Create intelligence-migrations standalone DDL container with full intelligence_db
   schema (20+ tables, 8-partition relations, RANGE-partitioned evidence/claims/events,
   6-row decay seed, 20-row relation_type_registry seed). Create services/alert/
   stub with alert_db Alembic migration (6 tables including dedup-gated alerts).
   ```

## Definition of done

- [ ] `services/intelligence-migrations/` exists with `Dockerfile`, `alembic.ini`, `requirements.txt`, `alembic/env.py`
- [ ] Migration `0001_create_intelligence_db.py` creates all 20+ `intelligence_db` tables
- [ ] `decay_class_config` seeded with exactly 6 rows
- [ ] `relation_type_registry` seeded with exactly 20 rows
- [ ] `relations` HASH-partitioned into exactly 8 partitions (relations_p0 through relations_p7)
- [ ] `partition_key` on `relations` and `relation_evidence_raw` is `GENERATED ALWAYS AS ... STORED`
- [ ] `relation_evidence`, `claims`, `events` RANGE-partitioned with 2024-01 through 2026-12 (36 partitions each)
- [ ] `idx_raw_evidence_partition_unprocessed` partial index on `relation_evidence_raw`
- [ ] HNSW indexes on `entity_profile_embeddings` and `relation_summaries` created via `op.execute()`
- [ ] pg_trgm trigram index on `entity_aliases.alias_text` created via `op.execute()`
- [ ] `downgrade()` drops all tables in reverse FK order
- [ ] `services/intelligence-migrations/README.md` explains boot order, local test command, ALEMBIC_ENABLED=false requirement
- [ ] `services/alert/` exists as functional stub (importable, lintable)
- [ ] `config.py` with all 9 `ALERT_*` ENV vars from PRD §4.5
- [ ] All 6 `alert_db` tables created with correct columns, indexes, and constraints
- [ ] `UNIQUE (dedup_key)` on `alerts` table present
- [ ] `UNIQUE (user_id, alert_id)` on `pending_alerts` present
- [ ] `ruff check` passes on all new Python files
- [ ] `mypy --strict` passes on `services/alert/src/`
- [ ] `docs/services/alert.md` created with all 8 documentation quality criteria met
- [ ] `docs/MASTER_PLAN.md §3` updated with S10 service catalog row
- [ ] Incremental quality gates passed for each task (no deferred failures)
- [ ] Commit message proposal provided
