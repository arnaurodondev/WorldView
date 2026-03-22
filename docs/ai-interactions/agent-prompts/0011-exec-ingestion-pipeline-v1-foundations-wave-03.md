# Execution Prompt 0011 — Ingestion Pipeline v1 Foundations · Wave 03

## Context (read first)

- **Planning response**: `docs/ai-interactions/agent-responses/0011-response-20260322-ingestion-pipeline-v1-foundations.md`
- **Authoritative spec**: `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md` §6.1, §6.2, §6.3

## Assigned agent profile(s)

- `.claude/agents/data-platform-engineer.md`

## Mandatory pre-read

1. `AGENTS.md`
2. `CLAUDE.md`
3. `RULES.md`
4. `docs/ai-interactions/agent-responses/0011-response-20260322-ingestion-pipeline-v1-foundations.md` — task specs for T-F-007, T-F-008, T-F-009
5. `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md` §6.1 (content_ingestion_db), §6.2 (content_store_db), §6.3 (nlp_db)
6. `.claude/agents/data-platform-engineer.md` — MinHash INTEGER[] constraint
7. `services/portfolio/alembic/` — reference Alembic implementation pattern
8. `services/content-ingestion/alembic.ini`
9. `services/content-store/alembic.ini`
10. `services/nlp-pipeline/alembic.ini`

## Objective

Create Alembic migrations for three service databases: `content_ingestion_db` (S4), `content_store_db` (S5), and `nlp_db` (S6). These migrations are the prerequisite for all S4/S5/S6 service implementation in Prompts 0016 and 0017.

**No application logic in this wave.** Only database schema migrations.

**Wave 01 must be complete before starting this wave** (§1.4 fixes unblock service work).

## Task scope for this wave

### Parallel group — all three tasks are independent (different services, different databases)

| Task | Database | Owner service | Tables |
|------|----------|---------------|--------|
| **T-F-007** | `content_ingestion_db` | S4 Content Ingestion | `fetch_log`, `outbox_events`, `dead_letter_queue` |
| **T-F-008** | `content_store_db` | S5 Content Store | `documents`, `minhash_signatures` (INTEGER[]), `minhash_entity_mentions`, `outbox_events`, `dead_letter_queue` |
| **T-F-009** | `nlp_db` | S6 NLP Pipeline | 9 tables including `chunk_embeddings` (HNSW), `section_embeddings` (HNSW) |

Execute all three in parallel if possible. Each is completely independent.

## Why this chunk

These three migrations are the DB foundations for S4, S5, and S6. Prompt 0016 (S4/S5 implementation) and Prompt 0017 (S6 implementation) cannot run Alembic against non-existent schemas. This wave creates the Alembic targets that those service implementations will read, verify, and extend.

## Implementation instructions

### T-F-007 — `content_ingestion_db` Alembic migration (S4)

**Pre-checks**:
1. Read `services/content-ingestion/alembic.ini` — verify `sqlalchemy.url` references `content_ingestion_db`.
2. Read `services/content-ingestion/alembic/versions/` — if any prior versions exist, chain from them.
3. Read `services/portfolio/alembic/versions/` — reference the Alembic version file structure.

**Create migration** `services/content-ingestion/alembic/versions/0001_create_content_ingestion_schema.py`:

```python
"""Create content_ingestion_db initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-03-22
"""
from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("""
        CREATE TABLE fetch_log (
            fetch_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_type    VARCHAR(50)  NOT NULL,
            source_url     TEXT         NOT NULL,
            fetched_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
            status         VARCHAR(20)  NOT NULL DEFAULT 'success',
            raw_minio_key  TEXT,
            content_hash   VARCHAR(64),
            error_detail   TEXT
        )
    """)
    op.execute("CREATE INDEX idx_fetch_log_source_fetched ON fetch_log (source_type, fetched_at DESC)")
    op.execute("CREATE INDEX idx_fetch_log_hash ON fetch_log (content_hash) WHERE content_hash IS NOT NULL")

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
    op.execute("CREATE INDEX idx_outbox_s4_pending ON outbox_events (created_at) WHERE status = 'pending'")

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
    op.execute("DROP TABLE IF EXISTS dead_letter_queue")
    op.execute("DROP TABLE IF EXISTS outbox_events")
    op.execute("DROP TABLE IF EXISTS fetch_log")
```

Important: use `op.execute("""...""")` for all DDL — DO NOT use `op.create_table` / `op.create_index` for complex SQL that Alembic cannot generate correctly (partial indexes, non-standard defaults).

**Validation gate** (after T-F-007):
```bash
# Requires Postgres testcontainer or local DB named content_ingestion_db
cd services/content-ingestion
alembic upgrade head
# Verify tables exist:
python -c "
import sqlalchemy as sa
engine = sa.create_engine('postgresql://postgres:postgres@localhost:5432/content_ingestion_db')
insp = sa.inspect(engine)
tables = insp.get_table_names()
assert 'fetch_log' in tables
assert 'outbox_events' in tables
assert 'dead_letter_queue' in tables
# Verify partial index
with engine.connect() as conn:
    result = conn.execute(sa.text(\"SELECT indexdef FROM pg_indexes WHERE indexname='idx_outbox_s4_pending'\")).fetchone()
    assert 'pending' in result[0], f'Partial index missing WHERE clause: {result[0]}'
print('content_ingestion_db migration OK')
"
alembic downgrade base
alembic upgrade head  # Idempotency: must succeed
```

---

### T-F-008 — `content_store_db` Alembic migration (S5)

**CRITICAL constraint**: `minhash_signatures.signature` MUST be `INTEGER[]` — never `BYTEA`, never `TEXT[]`, never `JSONB`. Verify this after migration.

**Pre-checks**: same pattern as T-F-007.

**Create migration** `services/content-store/alembic/versions/0001_create_content_store_schema.py`:

Tables to create in dependency order:

1. `documents` — first (referenced by minhash_signatures FK):
```sql
CREATE TABLE documents (
    doc_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type      VARCHAR(50)  NOT NULL,
    source_url       TEXT,
    title            TEXT,
    published_at     TIMESTAMPTZ,
    ingested_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    content_hash     VARCHAR(64)  NOT NULL,
    normalized_hash  VARCHAR(64)  NOT NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'stored',
    minio_silver_key TEXT         NOT NULL,
    word_count       INT,
    language         VARCHAR(10)  DEFAULT 'en',
    UNIQUE (content_hash)
);
CREATE INDEX idx_documents_normalized_hash ON documents (normalized_hash);
CREATE INDEX idx_documents_source_published ON documents (source_type, published_at DESC);
```

2. `minhash_signatures` — `INTEGER[]` is non-negotiable:
```sql
CREATE TABLE minhash_signatures (
    sig_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id        UUID NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    signature     INTEGER[] NOT NULL,
    shingle_type  VARCHAR(50) NOT NULL DEFAULT 'word_bigram_char3gram',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (doc_id)
);
CREATE INDEX idx_minhash_sig_created ON minhash_signatures (created_at DESC);
```

3. `minhash_entity_mentions` — dual-key table. `entity_id` is a logical FK to `intelligence_db.canonical_entities` — NO Postgres-level FK constraint here:
```sql
CREATE TABLE minhash_entity_mentions (
    sig_id              UUID   NOT NULL REFERENCES minhash_signatures(sig_id) ON DELETE CASCADE,
    mention_text_hash   BIGINT NOT NULL,
    mention_text        VARCHAR(300),
    entity_id           UUID,
    resolution_status   VARCHAR(20) NOT NULL DEFAULT 'UNRESOLVED',
    resolved_at         TIMESTAMPTZ,
    PRIMARY KEY (sig_id, mention_text_hash)
);
CREATE INDEX idx_minhash_mentions_hash ON minhash_entity_mentions (mention_text_hash, sig_id);
CREATE INDEX idx_minhash_mentions_entity ON minhash_entity_mentions (entity_id, sig_id)
    WHERE entity_id IS NOT NULL;
```

4. `outbox_events` and `dead_letter_queue` — same pattern as T-F-007 (use `idx_outbox_s5_pending` for the index name).

**Validation gate** (after T-F-008):
```bash
cd services/content-store
alembic upgrade head
python -c "
import sqlalchemy as sa
engine = sa.create_engine('postgresql://postgres:postgres@localhost:5432/content_store_db')
insp = sa.inspect(engine)
# Verify INTEGER[] type on signature column
cols = {c['name']: c for c in insp.get_columns('minhash_signatures')}
sig_type = str(cols['signature']['type'])
print(f'signature type: {sig_type}')
# PostgreSQL reports INTEGER[] as ARRAY(INTEGER()); check it contains 'ARRAY' or 'integer'
assert 'ARRAY' in sig_type.upper() or 'integer' in sig_type.lower(), f'Expected INTEGER[], got: {sig_type}'

# Verify NO FK constraint from minhash_entity_mentions.entity_id to another table
fks = insp.get_foreign_keys('minhash_entity_mentions')
fk_cols = [fk['constrained_columns'][0] for fk in fks]
assert 'entity_id' not in fk_cols, 'entity_id must NOT have a Postgres FK constraint'
print('content_store_db migration OK')
"
alembic downgrade base && alembic upgrade head
```

---

### T-F-009 — `nlp_db` Alembic migration (S6)

**Key requirements**:
- `pgvector` extension must be created first
- Two HNSW indexes with partial predicates (`WHERE (expires_at IS NULL OR expires_at > now())`)
- HNSW indexes must be created via `op.execute("""CREATE INDEX ... USING hnsw ...""")` — Alembic does not natively support `USING hnsw`
- S6 must set `ALEMBIC_ENABLED=false` for `intelligence_db` — add a comment in the env.py or alembic.ini

**Pre-checks**: Read `services/nlp-pipeline/alembic.ini` and `services/nlp-pipeline/alembic/env.py`.

**Create migration** `services/nlp-pipeline/alembic/versions/0001_create_nlp_schema.py`:

Create tables in dependency order:

1. **Extensions**:
```python
op.execute("CREATE EXTENSION IF NOT EXISTS vector")
```

2. **`sections`**:
```sql
CREATE TABLE sections (
    section_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id         UUID        NOT NULL,
    section_index  INT         NOT NULL,
    section_type   VARCHAR(50),
    title          TEXT,
    char_start     INT         NOT NULL,
    char_end       INT         NOT NULL,
    token_count    INT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sections_doc ON sections (doc_id, section_index);
```

3. **`chunks`** (references sections):
```sql
CREATE TABLE chunks (
    chunk_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id              UUID        NOT NULL,
    section_id          UUID        NOT NULL REFERENCES sections(section_id) ON DELETE CASCADE,
    chunk_index         INT         NOT NULL,
    char_start          INT         NOT NULL,
    char_end            INT         NOT NULL,
    token_count         INT         NOT NULL,
    sentence_start_idx  INT,
    sentence_end_idx    INT,
    speaker             TEXT,
    heading_path        TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_chunks_doc ON chunks (doc_id, chunk_index);
CREATE INDEX idx_chunks_section ON chunks (section_id);
```

4. **`entity_mentions`** (references sections):
```sql
CREATE TABLE entity_mentions (
    mention_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id                UUID        NOT NULL,
    section_id            UUID REFERENCES sections(section_id) ON DELETE SET NULL,
    mention_text          TEXT        NOT NULL,
    mention_class         VARCHAR(50) NOT NULL,
    confidence            FLOAT       NOT NULL,
    char_start            INT         NOT NULL,
    char_end              INT         NOT NULL,
    resolved_entity_id    UUID,
    resolution_confidence FLOAT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_entity_mentions_doc ON entity_mentions (doc_id, mention_class);
CREATE INDEX idx_entity_mentions_resolved ON entity_mentions (resolved_entity_id)
    WHERE resolved_entity_id IS NOT NULL;
```

5. **`chunk_entity_mentions`** (junction table):
```sql
CREATE TABLE chunk_entity_mentions (
    chunk_id   UUID NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    mention_id UUID NOT NULL REFERENCES entity_mentions(mention_id) ON DELETE CASCADE,
    PRIMARY KEY (chunk_id, mention_id)
);
```

6. **`chunk_embeddings`** — VECTOR(1024) + HNSW partial index:
```sql
CREATE TABLE chunk_embeddings (
    embedding_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id         UUID         NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    embedding        VECTOR(1024) NOT NULL,
    model_id         VARCHAR(200) NOT NULL,
    embedding_status VARCHAR(20)  NOT NULL DEFAULT 'ready',
    expires_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (chunk_id, model_id)
);
```
Then via `op.execute`:
```sql
CREATE INDEX idx_chunk_emb_hnsw ON chunk_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WHERE (expires_at IS NULL OR expires_at > now());
CREATE INDEX idx_chunk_emb_pending ON chunk_embeddings (created_at)
    WHERE embedding_status = 'pending';
CREATE INDEX idx_chunk_emb_expires ON chunk_embeddings (expires_at)
    WHERE expires_at IS NOT NULL;
```

7. **`section_embeddings`** — separate HNSW index:
```sql
CREATE TABLE section_embeddings (
    embedding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_id   UUID         NOT NULL REFERENCES sections(section_id) ON DELETE CASCADE,
    embedding    VECTOR(1024) NOT NULL,
    model_id     VARCHAR(200) NOT NULL,
    expires_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (section_id, model_id)
);
```
Then via `op.execute`:
```sql
CREATE INDEX idx_section_emb_hnsw ON section_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WHERE (expires_at IS NULL OR expires_at > now());
```

8. **`routing_decisions`**:
```sql
CREATE TABLE routing_decisions (
    decision_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id              UUID        NOT NULL,
    routing_tier        VARCHAR(20) NOT NULL,
    composite_score     FLOAT       NOT NULL,
    feature_scores_json JSONB       NOT NULL,
    decided_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_routing_doc ON routing_decisions (doc_id);
```

9. **`outbox_events`** (index: `idx_outbox_s6_pending`) and **`dead_letter_queue`** — same pattern as T-F-007.

**Downgrade**: Drop tables in reverse FK order. HNSW indexes are dropped with their tables automatically (CASCADE).

**Validation gate** (after T-F-009):
```bash
cd services/nlp-pipeline
alembic upgrade head
python -c "
import sqlalchemy as sa
engine = sa.create_engine('postgresql://postgres:postgres@localhost:5432/nlp_db')
# Verify HNSW indexes
with engine.connect() as conn:
    hnsw_indexes = conn.execute(sa.text(
        \"SELECT indexname, indexdef FROM pg_indexes WHERE indexname LIKE '%hnsw%' AND tablename IN ('chunk_embeddings','section_embeddings')\"
    )).fetchall()
    assert len(hnsw_indexes) == 2, f'Expected 2 HNSW indexes, got {len(hnsw_indexes)}'
    for name, defn in hnsw_indexes:
        assert 'hnsw' in defn.lower(), f'Not HNSW: {defn}'
        assert 'expires_at' in defn, f'Missing partial predicate: {defn}'
        print(f'HNSW OK: {name}')
print('nlp_db migration OK')
"
alembic downgrade base && alembic upgrade head
```

## Constraints

- Do NOT implement any application logic (no SQLAlchemy models for use in services, no repositories, no use cases).
- Do NOT run Alembic migrations for `intelligence_db` in any S4/S5/S6 service — `intelligence_db` is owned exclusively by `intelligence-migrations` (T-F-010 in Wave 04).
- `minhash_signatures.signature` is `INTEGER[]` — never `BYTEA`. If you write `BYTEA`, stop and correct immediately.
- `minhash_entity_mentions.entity_id` must NOT have a Postgres FK constraint to any table. It's a logical FK to a different database.
- HNSW indexes must be created with `op.execute(...)` — not `op.create_index(...)`.
- All timestamp columns must be `TIMESTAMPTZ` (with timezone) — never `TIMESTAMP`.

**write_paths**:
```
services/content-ingestion/alembic/versions/0001_create_content_ingestion_schema.py
services/content-ingestion/alembic.ini                    # verify/update only
services/content-store/alembic/versions/0001_create_content_store_schema.py
services/content-store/alembic.ini                        # verify/update only
services/nlp-pipeline/alembic/versions/0001_create_nlp_schema.py
services/nlp-pipeline/alembic.ini                         # verify/update only
services/nlp-pipeline/alembic/env.py                      # add pgvector setup note
```

## Required tests

```bash
# T-F-007
cd services/content-ingestion && alembic upgrade head
python -m pytest tests/ -k "migration" -v  # If migration tests exist

# T-F-008
cd services/content-store && alembic upgrade head
python -c "..."  # signature type check (see T-F-008 gate)

# T-F-009
cd services/nlp-pipeline && alembic upgrade head
python -c "..."  # HNSW index check (see T-F-009 gate)
```

**Pass criteria**:
- All 3 migrations `upgrade head` without error
- All 3 migrations `downgrade base` without error
- All 3 migrations are idempotent (upgrade → downgrade → upgrade succeeds)
- `minhash_signatures.signature` is `INTEGER[]` (verified via introspection)
- `minhash_entity_mentions.entity_id` has no FK constraint
- `idx_chunk_emb_hnsw` and `idx_section_emb_hnsw` are HNSW indexes with partial predicates

## Incremental quality gates (mandatory)

**After T-F-007**:
```bash
cd services/content-ingestion
alembic upgrade head
alembic downgrade base
alembic upgrade head  # Verify idempotency
ruff check alembic/versions/
```

**After T-F-008**:
```bash
cd services/content-store
alembic upgrade head
# Verify INTEGER[] type (see validation gate above)
alembic downgrade base && alembic upgrade head
ruff check alembic/versions/
```

**After T-F-009**:
```bash
cd services/nlp-pipeline
alembic upgrade head
# Verify 2 HNSW indexes with partial predicates (see validation gate above)
alembic downgrade base && alembic upgrade head
ruff check alembic/versions/
```

**No Deferred Fixes**: Every Alembic migration must be clean (no Python syntax errors, no SQL errors) before moving to the next.

## Documentation requirements

**Files to create or update in this wave**:
- `docs/services/content-ingestion.md` (if exists): add/update **Database Schema** section — list all 3 tables with columns
- `docs/services/content-store.md` (if exists): add/update **Database Schema** section — list all 5 tables; document `INTEGER[]` constraint with explanation ("MinHash is compared band-by-band as integers; BYTEA would require custom Jaccard implementation")
- `docs/services/nlp-pipeline.md` (if exists): add/update **Database Schema** section — list all 9 tables; document why two separate HNSW indexes exist (chunk vs section embeddings must not pollute each other's ANN results)

**Documentation quality standard** applied:
1. Accuracy: every table and column must match the migration exactly
2. Diagrams: N/A for schema-only changes (no control flow)
3. Realistic code examples: N/A (no new public API)
4. Abstract methods: N/A
5. Common pitfalls: add to service docs — at least 2 pitfalls per service:
   - S5: "Using BYTEA for MinHash signatures" and "Adding Postgres FK from minhash_entity_mentions.entity_id to intelligence_db"
   - S6: "Creating HNSW index without partial predicate" and "Running Alembic against intelligence_db from S6"
6. Lib docs: N/A (no lib changed)
7. Service docs: ✓ (updated above)
8. No orphan docs: ✓

## Required handoff evidence

1. **Changed files list**
2. **Validation ledger**:
   | Command | Scope | Exit code | Result |
   |---------|-------|-----------|--------|
   | `cd services/content-ingestion && alembic upgrade head` | S4 | 0 | ✓ |
   | `cd services/content-ingestion && alembic downgrade base` | S4 | 0 | ✓ |
   | `cd services/content-store && alembic upgrade head` | S5 | 0 | ✓ |
   | `signature type is INTEGER[]` (introspection) | S5 | True | ✓ |
   | `entity_id has no FK constraint` (introspection) | S5 | True | ✓ |
   | `cd services/nlp-pipeline && alembic upgrade head` | S6 | 0 | ✓ |
   | `2 HNSW indexes with partial predicate` (introspection) | S6 | True | ✓ |

3. **Documentation quality checklist**:
   | Criterion | Status | Notes |
   |-----------|--------|-------|
   | Accuracy verified | ✓ | Columns match PRD §6 exactly |
   | Diagrams | N/A | No control flow introduced |
   | Realistic code examples | N/A | No new public API |
   | Abstract methods | N/A | |
   | Common pitfalls | ✓ | 2+ pitfalls per service doc |
   | Lib docs updated | N/A | No lib changed |
   | Service docs reflect final state | ✓ | Schema sections updated |
   | No orphan docs | ✓ | |

4. **Commit message proposal**:
   ```
   feat(db): initial Alembic migrations for content_ingestion_db, content_store_db, nlp_db

   Create content_ingestion_db (fetch_log, outbox, DLQ), content_store_db (documents,
   minhash_signatures INTEGER[], minhash_entity_mentions, outbox, DLQ), and nlp_db (sections,
   chunks, embeddings with HNSW indexes, entity mentions, routing decisions, outbox, DLQ).
   All migrations include up/down and idempotency verification.
   ```

## Definition of done

- [ ] `content_ingestion_db`: 3 tables + partial indexes; upgrade/downgrade passes
- [ ] `content_store_db`: 5 tables; `minhash_signatures.signature` is `INTEGER[]` (verified); no FK on `entity_id`; upgrade/downgrade passes
- [ ] `nlp_db`: 9 tables; pgvector extension; 2 HNSW indexes with `WHERE (expires_at IS NULL OR expires_at > now())`; upgrade/downgrade passes
- [ ] All 3 migrations are idempotent (upgrade after already-migrated DB is no-op)
- [ ] `ruff check` passes on all migration files
- [ ] Service docs updated (schema sections for content-ingestion, content-store, nlp-pipeline)
- [ ] Documentation quality checklist completed (all 8 criteria ✓ or explicitly N/A)
- [ ] Incremental quality gates passed for each task (no deferred failures)
- [ ] Commit message proposal provided
