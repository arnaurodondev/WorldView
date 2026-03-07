# S6 · NLP Pipeline Service

> **Owner**: Intelligence domain · **Database**: `nlp_db` (pgvector) · **Port**: 8006
> **Status**: New

---

## Mission & Boundaries

**Owns**: Embedding generation (MiniLM-L6-v2), entity linking (spaCy NER +
alias table), sentiment analysis (DistilBERT), event extraction, topic
clustering, novelty detection, signal emission, vector similarity search.

**Never does**: Store raw articles (S5 Content Store), maintain knowledge graph
(S7 Knowledge Graph), perform LLM completions (S8 RAG/Chat).

---

## API Surface

| Method | Path | Description | Cache |
|--------|------|-------------|-------|
| GET | `/healthz` | Liveness | — |
| GET | `/readyz` | Readiness (DB) | — |
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
| `content.article.stored.v1` | `nlp-pipeline` | Trigger NLP enrichment |

### Produced

| Topic | Event Type | Key |
|-------|-----------|-----|
| `nlp.article.enriched.v1` | `ArticleEnrichedV1` | `article_id` |
| `nlp.signal.detected.v1` | `SignalDetectedV1` | `entity_id` |

---

## Database Schema

```sql
-- nlp_db
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE article_embeddings (
    article_id      UUID PRIMARY KEY,
    embedding       vector(384),
    model_version   VARCHAR(30) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_embeddings_hnsw ON article_embeddings
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
    article_id  UUID PRIMARY KEY,
    score       REAL NOT NULL,
    label       VARCHAR(20) NOT NULL,
    model_version VARCHAR(30) NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE topic_clusters (
    id              UUID PRIMARY KEY,
    label           TEXT,
    centroid        vector(384),
    article_count   INTEGER DEFAULT 0,
    is_trending     BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE article_clusters (
    article_id  UUID NOT NULL,
    cluster_id  UUID NOT NULL REFERENCES topic_clusters(id),
    similarity  REAL,
    PRIMARY KEY (article_id, cluster_id)
);
```

---

## ML Models

| Model | Task | Dimension | Size |
|-------|------|-----------|------|
| `sentence-transformers/all-MiniLM-L6-v2` | Embeddings | 384 | 23MB |
| spaCy `en_core_web_sm` | NER | — | 12MB |
| `distilbert-base-uncased-finetuned-sst-2-english` | Sentiment | — | 260MB |

---

## Internal Modules

```
services/nlp-pipeline/src/nlp_pipeline/
├── app.py              # FastAPI app factory
├── config.py           # Settings
├── api/                # Signal/entity/search routes
├── domain/             # Entity, Signal, Embedding models
├── application/        # Enrichment use-cases
└── infrastructure/     # DB, Kafka, ML model adapters
```

---

## Testing Plan

| Type | What | Command |
|------|------|---------|
| Unit | Entity linking rules, dedup, signal thresholds | `make test` |
| Integration | Consumer + pgvector round-trip | `make test-integration` |

---

## Local Run

```bash
cd services/nlp-pipeline
cp configs/dev.local.env.example .env
make run       # port 8006
make test
make lint
```
