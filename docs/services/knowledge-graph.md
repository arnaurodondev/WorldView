# S7 · Knowledge Graph Service

> **Owner**: Intelligence domain · **Database**: `kg_db` (Apache AGE) · **Port**: 8007
> **Status**: New

---

## Mission & Boundaries

**Owns**: Knowledge graph maintenance (Apache AGE), graph traversal queries,
entity relationship management, neighborhood queries, Cypher query execution.

**Never does**: Generate embeddings or run NLP (S6 NLP Pipeline), store articles
(S5 Content Store), perform LLM completions (S8 RAG/Chat).

---

## API Surface

| Method | Path | Description | Cache |
|--------|------|-------------|-------|
| GET | `/healthz` | Liveness | — |
| GET | `/readyz` | Readiness (DB) | — |
| GET | `/metrics` | Prometheus | — |
| GET | `/api/v1/entities/{id}/graph` | KG neighborhood (query: depth, limit) | medium |
| GET | `/api/v1/graph/query` | Execute Cypher query (admin) | — |
| GET | `/api/v1/graph/stats` | Graph statistics | slow |

---

## Kafka Topics

### Consumed

| Topic | Consumer Group | Purpose |
|-------|---------------|---------|
| `nlp.article.enriched.v1` | `knowledge-graph` | Update KG with new entities/relations |

### Produced

None.

---

## Knowledge Graph Schema (Apache AGE)

- **Graph name**: `market_kg`
- **Node types**: Company, Person, Event, Article, Sector, Topic
- **Edge types**: HAS_EXECUTIVE, IN_SECTOR, INVOLVED_IN, MENTIONS, REPORTS_ON,
  ABOUT_TOPIC, SUBSIDIARY_OF, PARTNER_OF, COMPETES_WITH, MOVED_TO, CAUSED_BY

```sql
-- kg_db
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

SELECT create_graph('market_kg');

-- Example Cypher queries executed via AGE SQL wrapper:
-- SELECT * FROM cypher('market_kg', $$ MATCH (c:Company)-[:HAS_EXECUTIVE]->(p:Person) RETURN c, p $$) AS (c agtype, p agtype);
```

---

## Internal Modules

```
services/knowledge-graph/src/knowledge_graph/
├── app.py              # FastAPI app factory
├── config.py           # Settings
├── api/                # Graph query routes
├── domain/             # Graph entities
├── application/        # KG maintenance use-cases
└── infrastructure/     # Apache AGE adapter, Kafka consumer
```

---

## Observability

- **Metrics**: graph_nodes_total, graph_edges_total, cypher_query_duration_seconds
- **Log fields**: `service=knowledge-graph`, `entity_id`, `query_type`

---

## Testing Plan

| Type | What | Command |
|------|------|---------|
| Unit | Cypher query construction, entity mapping | `make test` |
| Integration | AGE extension round-trip | `make test-integration` |

---

## Local Run

```bash
cd services/knowledge-graph
cp configs/dev.local.env.example .env
make run       # port 8007
make test
make lint
```
