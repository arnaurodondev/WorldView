# S6 · NLP Pipeline Service

> **Owner**: Intelligence domain · **Port**: 8006
> **Databases**: `nlp_db` (pgvector, owned) + `intelligence_db` (shared, `ALEMBIC_ENABLED=false`)
> **Status**: Stub (🔲 Pending implementation)

---

## Mission & Boundaries

**Owns**: Full intelligence enrichment of stored articles. Runs pipeline Blocks 3–10:
sectioning, GLiNER NER (10 entity classes), additive routing score, suppression,
chunk/section embedding generation (`BAAI/bge-large-en-v1.5`, 1024-dim), two-stage
novelty gate (MinHash + Valkey LSH), 4-step entity resolution cascade, deep LLM
extraction (Qwen2.5-7B-Instruct), signal emission.

**Never does**: Store raw articles (S5 Content Store), maintain relational graph
aggregation (S7 Knowledge Graph), perform LLM completions at query time (S8 RAG/Chat).

**Database ownership note**: `nlp_db` DDL is owned by S6 (Alembic on startup).
`intelligence_db` DDL is owned exclusively by the `intelligence-migrations` init
container. S6 connects to `intelligence_db` with `ALEMBIC_ENABLED=false` and
performs read/write operations only.

---

## API Surface

| Method | Path | Description | Cache |
|--------|------|-------------|-------|
| GET | `/healthz` | Liveness | — |
| GET | `/readyz` | Readiness (DB + Ollama) | — |
| GET | `/metrics` | Prometheus | — |
| GET | `/api/v1/signals` | Signal feed (query: entity_id, type, severity) | fast |
| GET | `/api/v1/entities` | Search entities | medium |
| GET | `/api/v1/entities/{id}` | Entity detail + aliases | medium |
| GET | `/api/v1/entities/{id}/articles` | Articles linked to entity | fast |
| POST | `/api/v1/search/vector` | Vector similarity search (body: query_text, top_k) | fast |
| POST | `/api/v1/reprocess/{article_id}` | Re-run NLP on an article (admin) | — |
| GET | `/api/v1/topics` | Active topic clusters | fast |

---

## Kafka Topics

### Consumed

| Topic | Consumer Group | Purpose |
|-------|---------------|---------|
| `content.article.stored.v1` | `nlp-pipeline-group` | Trigger NLP enrichment (at-least-once; manual offset commit after all DB writes) |

### Produced

| Topic | Event Type | Key | Via |
|-------|-----------|-----|-----|
| `nlp.article.enriched.v1` | `ArticleEnrichedV1` | `article_id` | Outbox in `nlp_db` |
| `nlp.signal.detected.v1` | `SignalDetectedV1` | `entity_id` | Outbox in `nlp_db` |

---

## Pipeline Blocks (3–10)

| Block | Name | Key Operation |
|-------|------|---------------|
| 3 | **Sectioning** | Split article into logical sections (source-specific rules) |
| 4 | **GLiNER NER** | Named entity detection per section; 10 entity classes; `urchade/gliner_large-v2.1`; batch size 32 |
| 5 | **Routing Score** | Additive score from 7 signals (entity density, source tier, novelty, recency, watchlist match, doctype, yield) |
| 6 | **Suppression** | Discard documents scoring below `ROUTING_THRESHOLD_LIGHT` (0.20); no further processing |
| 7 | **Embedding** | Generate chunk-level + section-level vectors (`BAAI/bge-large-en-v1.5`, 1024-dim) via Ollama |
| 8 | **Novelty Gate** | Two-stage: Stage 1 (pre-resolution, MinHash signature); Stage 2 (post-resolution, per-entity window) |
| 9 | **Entity Resolution** | 4-step cascade: exact alias lookup → Valkey cache → GLiNER re-extraction → ANN entity profile embedding match |
| 10 | **Deep Extraction** | LLM-based (Qwen2.5-7B-Instruct via Ollama): events, claims, relations → `relation_evidence_raw` |

---

## Database Schema

### `nlp_db` (owned by S6)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE chunk_embeddings (
    id              UUID PRIMARY KEY,
    article_id      UUID NOT NULL,
    chunk_index     SMALLINT NOT NULL,
    chunk_text      TEXT NOT NULL,
    embedding       vector(1024),
    model_version   VARCHAR(50) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (article_id, chunk_index)
);
CREATE INDEX idx_chunk_emb_hnsw ON chunk_embeddings
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200);

CREATE TABLE section_embeddings (
    id              UUID PRIMARY KEY,
    article_id      UUID NOT NULL,
    section_index   SMALLINT NOT NULL,
    section_label   VARCHAR(50),
    embedding       vector(1024),
    model_version   VARCHAR(50) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (article_id, section_index)
);
CREATE INDEX idx_section_emb_hnsw ON section_embeddings
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200);

CREATE TABLE entity_profile_embeddings (
    entity_id       UUID PRIMARY KEY,
    embedding       vector(1024),
    model_version   VARCHAR(50) NOT NULL,
    updated_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_entity_profile_hnsw ON entity_profile_embeddings
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200);

CREATE TABLE entities (
    id              UUID PRIMARY KEY,
    canonical_name  TEXT NOT NULL,
    entity_type     VARCHAR(20) NOT NULL,
    metadata        JSONB,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (canonical_name, entity_type)
);

CREATE TABLE entity_aliases (
    id          UUID PRIMARY KEY,
    entity_id   UUID REFERENCES entities(id),
    alias       TEXT NOT NULL,
    alias_type  VARCHAR(20),
    UNIQUE (alias, alias_type)
);

CREATE TABLE article_entities (
    article_id      UUID NOT NULL,
    entity_id       UUID NOT NULL REFERENCES entities(id),
    confidence      REAL,
    mention_count   SMALLINT DEFAULT 1,
    PRIMARY KEY (article_id, entity_id)
);

CREATE TABLE article_events (
    id              UUID PRIMARY KEY,
    article_id      UUID NOT NULL,
    event_type      VARCHAR(50) NOT NULL,
    entity_id       UUID REFERENCES entities(id),
    severity        SMALLINT DEFAULT 1,
    details         JSONB,
    occurred_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_events_entity ON article_events(entity_id);
CREATE INDEX idx_events_type ON article_events(event_type);

CREATE TABLE article_sentiment (
    article_id      UUID PRIMARY KEY,
    score           REAL NOT NULL,
    label           VARCHAR(20) NOT NULL,
    model_version   VARCHAR(50) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE topic_clusters (
    id              UUID PRIMARY KEY,
    label           TEXT,
    centroid        vector(1024),
    article_count   INTEGER DEFAULT 0,
    is_trending     BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE article_clusters (
    article_id      UUID NOT NULL,
    cluster_id      UUID NOT NULL REFERENCES topic_clusters(id),
    similarity      REAL,
    PRIMARY KEY (article_id, cluster_id)
);
```

### `intelligence_db` (DDL owned by `intelligence-migrations`; S6 read/write only)

Key tables S6 writes to:

| Table | Operation | Notes |
|-------|-----------|-------|
| `canonical_entities` | UPSERT | From Block 9 entity resolution |
| `relation_evidence_raw` | INSERT | From Block 10 deep extraction (hot path) |
| `article_claims` | INSERT | From Block 10 (claims/temporal assertions) |

---

## ML Models

| Model | Task | Dimension | Served Via |
|-------|------|-----------|------------|
| `BAAI/bge-large-en-v1.5` | Chunk + section embeddings | 1024 | Ollama |
| `urchade/gliner_large-v2.1` | Named entity recognition (10 classes) | — | Ollama |
| `qwen2.5:7b-instruct` | Deep extraction (events, claims, relations) | — | Ollama |

---

## Key ENV Vars

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama endpoint |
| `EMBEDDING_MODEL` | `bge-large-en-v1.5` | BGE embedding model |
| `EXTRACTION_MODEL` | `qwen2.5:7b-instruct` | Qwen extraction model |
| `GLINER_MODEL` | `urchade/gliner_large-v2.1` | GLiNER NER model |
| `GLINER_BATCH_SIZE` | `32` | Sections per GLiNER batch |
| `GLINER_THRESHOLD` | `0.35` | Min confidence for routing/novelty signal |
| `GLINER_RESOLUTION_THRESHOLD` | `0.45` | Min confidence for resolution cascade |
| `MAX_OLLAMA_QUEUE_DEPTH` | `20` | Pause Kafka consumer above this depth |
| `RESUME_OLLAMA_QUEUE_DEPTH` | `5` | Resume Kafka consumer below this depth |
| `AUTO_RESOLVE_THRESHOLD` | `0.72` | Entity resolution auto-resolve score |
| `PROVISIONAL_THRESHOLD` | `0.45` | Min score for provisional entity queue |
| `SIGNAL_CONFIDENCE_MIN` | `0.80` | Min confidence to emit `nlp.signal.detected.v1` |
| `ALEMBIC_ENABLED` | `false` | Must remain false (intelligence_db DDL is external) |
| `ROUTING_WEIGHT_ENTITY_DENSITY` | `0.30` | Routing signal weight |
| `ROUTING_WEIGHT_SOURCE` | `0.20` | Routing signal weight |
| `ROUTING_THRESHOLD_DEEP` | `0.70` | Deep extraction tier lower bound |
| `ROUTING_THRESHOLD_MEDIUM` | `0.45` | Medium tier lower bound |
| `ROUTING_THRESHOLD_LIGHT` | `0.20` | Light tier (below = suppressed) |
| `OUTBOX_POLL_INTERVAL_SECONDS` | `2` | Dispatcher cadence |

---

## Internal Modules

```
services/nlp-pipeline/src/nlp_pipeline/
├── app.py              # FastAPI app factory
├── config.py           # Settings (DB, Ollama, Kafka, thresholds)
├── api/                # Signal/entity/search routes
├── domain/             # Entity, Signal, Embedding, Chunk models
├── application/        # Enrichment use-cases (blocks 3–10)
│   ├── block3_sectioning.py
│   ├── block4_gliner.py
│   ├── block5_routing.py
│   ├── block6_suppression.py
│   ├── block7_embedding.py
│   ├── block8_novelty.py
│   ├── block9_entity_resolution.py
│   └── block10_deep_extraction.py
└── infrastructure/     # DB, Kafka, Ollama adapters, MinHash/LSH
```

---

## Observability

- **Metrics**: `articles_enriched_total`, `articles_suppressed_total`, `embedding_duration_seconds`, `gliner_entities_detected_total`, `resolution_cascade_steps_total`, `signal_emitted_total`
- **Log fields**: `service=nlp-pipeline`, `article_id`, `routing_score`, `entity_count`, `block`

---

## Testing Plan

| Type | What | Command |
|------|------|---------|
| Unit | Routing score, suppression logic, entity resolution steps, novelty gate | `make test` |
| Integration | Consumer + pgvector round-trip + intelligence_db writes | `make test-integration` |

---

## Local Run

```bash
cd services/nlp-pipeline
cp configs/dev.local.env.example .env
make run       # port 8006
make test
make lint
```
