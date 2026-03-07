# worldview

A Python + TypeScript monorepo for financial intelligence — portfolio management, market data ingestion, content analysis, NLP enrichment, knowledge graphs, RAG-powered chat, and an interactive web frontend.

> **Status**: Scaffold — architecture defined, services stubbed, docs complete. See [docs/MASTER_PLAN.md](docs/MASTER_PLAN.md) for the full vision.

---

## Quick Start (< 10 minutes)

```bash
# 1. Clone
git clone <repo-url> worldview && cd worldview

# 2. Bootstrap (installs venvs, hooks, checks Docker)
./scripts/bootstrap.sh

# 3. Start infrastructure
docker compose --profile infra up -d

# 4. Run init jobs (create DBs, topics, register schemas)
docker compose --profile init up

# 5. Start a service
cd services/portfolio && make run    # → http://localhost:8001/healthz

# 6. Start the frontend (separate terminal)
cd apps/frontend && pnpm dev         # → http://localhost:5173
```

---

## Architecture

```
┌──────────────┐
│  Frontend    │
│    :5173     │
└──────┬───────┘
       │
┌──────▼───────┐   ┌───────────────┐   ┌──────────────────┐
│ S9 Gateway   │──▶│ S1 Portfolio   │   │ S2 Mkt Ingestion │
│   :8000      │   │    :8001       │   │    :8002         │
└──────┬───────┘   └───────────────┘   └──────────────────┘
       │
       ├──▶ S3 Market Data     :8003
       ├──▶ S4 Content Ingest  :8004
       ├──▶ S5 Content Store   :8005
       ├──▶ S6 NLP Pipeline    :8006
       ├──▶ S7 Knowledge Graph :8007
       └──▶ S8 RAG / Chat     :8008

Infrastructure: PostgreSQL 16 + TimescaleDB + pgvector + AGE │ Kafka │ MinIO │ Valkey │ Ollama
```

---

## Repository Structure

```
worldview/
├── docs/                    # Documentation-first
│   ├── MASTER_PLAN.md       # Single source of truth
│   ├── architecture/        # Diagrams, ADRs
│   ├── services/            # Per-service deep docs
│   ├── libs/                # Per-library docs
│   ├── workflows/           # Dev, CI, testing, release
│   └── migration/           # Legacy repo reuse guide
├── libs/                    # Shared libraries
│   ├── common/              # Time, IDs, type aliases
│   ├── contracts/           # Canonical data models
│   ├── messaging/           # Kafka, Avro, outbox, Valkey
│   ├── storage/             # S3/MinIO abstraction
│   └── observability/       # Logging, metrics, tracing
├── apps/                    # Applications
│   └── frontend/            # React + Vite + TypeScript web UI
├── services/                # Microservices (S1–S9)
│   ├── portfolio/           # S1 — Multi-tenant portfolio management
│   ├── market-ingestion/    # S2 — Market data ingestion & scheduling
│   ├── market-data/         # S3 — Market data storage & query
│   ├── content-ingestion/   # S4 — News polling & raw storage
│   ├── content-store/       # S5 — Article cleaning & deduplication
│   ├── nlp-pipeline/        # S6 — NLP, embeddings, sentiment
│   ├── knowledge-graph/     # S7 — Apache AGE knowledge graph
│   ├── rag-chat/            # S8 — RAG-powered conversational AI
│   └── api-gateway/         # S9 — BFF API gateway
├── infra/                   # Infrastructure configs
│   ├── kafka/schemas/       # Avro schemas (.avsc)
│   ├── postgres/init/       # DB init scripts
│   └── minio/init/          # Bucket init scripts
├── scripts/                 # Dev scripts
├── docker-compose.yml       # Profiles: infra, init, runtime, tools
└── AGENTS.md                # AI agent governance
```

---

## Key Commands

| Command | Purpose |
|---------|---------|
| `./scripts/bootstrap.sh` | One-time setup |
| `docker compose --profile infra up -d` | Start infrastructure |
| `docker compose --profile init up` | Create DBs, topics, schemas |
| `cd services/<name> && make run` | Start a service |
| `./scripts/lint.sh` | Ruff + mypy all packages |
| `./scripts/test.sh` | Unit tests all packages |
| `./scripts/test.sh --integration` | + integration tests |
| `./scripts/gen-contracts.sh` | Validate Avro schemas |
| `./scripts/gen-contracts.sh --register` | + register with Schema Registry |

---

## Documentation

| Document | Description |
|----------|-------------|
| [MASTER_PLAN.md](docs/MASTER_PLAN.md) | Complete architecture & roadmap |
| [Architecture diagrams](docs/architecture/diagrams.md) | Mermaid component & flow diagrams |
| [ADR-0001](docs/architecture/decisions/0001-initial-architecture.md) | Initial architecture decisions |
| [Service docs](docs/services/) | Per-service API, schema, flow docs (S1–S9) |
| [Frontend docs](docs/apps/frontend.md) | Web UI architecture & development |
| [ADR-0002](docs/architecture/decisions/0002-frontend-tooling.md) | Frontend tooling decisions |
| [Library docs](docs/libs/) | Per-library public API docs |
| [Local dev guide](docs/workflows/local-dev.md) | Setup & daily workflow |
| [Testing strategy](docs/workflows/testing-strategy.md) | Test pyramid & conventions |
| [CI/CD pipeline](docs/workflows/ci-cd.md) | GitHub Actions workflow |
| [Migration guide](docs/migration/REUSE_FROM_ORIGINAL_THESIS.md) | Legacy repo reuse mapping |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12 (backend) · TypeScript 5 (frontend) |
| Build | Hatch (hatchling) |
| Web | FastAPI + Uvicorn |
| Database | PostgreSQL 16 + TimescaleDB + pgvector + Apache AGE |
| ORM | SQLAlchemy 2 (async) + Alembic |
| Events | Apache Kafka + Confluent Schema Registry + Avro |
| Object Storage | MinIO (S3-compatible) |
| Cache | Valkey (Redis-compatible) |
| LLM | Ollama (local) → Groq → OpenRouter → OpenAI |
| Observability | structlog + Prometheus + OpenTelemetry |
| Linting | Ruff + mypy |
| Testing | pytest |
| CI | GitHub Actions |

---

## License

University thesis project. All rights reserved.
