# worldview

A Python + TypeScript monorepo for financial intelligence — portfolio management, market data ingestion, content analysis, NLP enrichment, knowledge graphs, RAG-powered chat, and a professional-grade web terminal.

> **Status**: Active development — all 10 microservices (S1–S10) implemented; Next.js frontend (`worldview-web`) in active development. See [MASTER_PLAN.md](docs/MASTER_PLAN.md) for the full architecture.

---

## Quick Start (< 10 minutes)

```bash
# 1. Clone
git clone <repo-url> worldview && cd worldview

# 2. Bootstrap (installs venvs, hooks, checks Docker)
./scripts/bootstrap.sh

# 3. Fetch secrets (API keys, OIDC credentials)
make fetch-secrets

# 4. Start full platform (infra + services + dev tools)
make dev

# 5. Load sample data (first launch only)
make seed

# 6. Open http://localhost:3001 → click "Dev Login"
```

Other useful Make targets: `make dev-down` (stop), `make dev-logs` (tail logs), `make dev-ps` (status), `make dev-reset` (clean slate), `make dev-rebuild` (rebuild images).

### Or develop a single service locally

```bash
# Start only infrastructure
docker compose --profile infra up -d
docker compose --profile init up

# Run one service natively with hot-reload
cd services/portfolio && make run    # → http://localhost:8001/healthz

# Run the gateway + frontend to test end-to-end
cd services/api-gateway && make run  # → http://localhost:8000
cd apps/worldview-web && pnpm dev    # → http://localhost:3001
```

---

## Architecture

```
┌───────────────────┐
│  worldview-web    │   Next.js 15 (App Router)
│    :3001          │   shadcn/ui + TanStack Query
└────────┬──────────┘
         │ /api/* rewrite
┌────────▼──────────┐
│ S9 API Gateway    │   FastAPI BFF — auth, routing, caching
│   :8000           │   OIDC/PKCE (Zitadel) + RS256 internal JWT
└────────┬──────────┘
         │ X-Internal-JWT
    ┌────┴─────────────────────────────────────────────┐
    │                                                   │
┌───▼───────────┐  ┌──────────────────┐  ┌─────────────▼────┐
│ S1 Portfolio  │  │ S2 Mkt Ingestion │  │ S3 Market Data   │
│    :8001      │  │    :8002         │  │    :8003         │
└───────────────┘  └──────────────────┘  └──────────────────┘
┌───────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ S4 Content In │  │ S5 Content Store │  │ S6 NLP Pipeline  │
│    :8004      │  │    :8005         │  │    :8006         │
└───────────────┘  └──────────────────┘  └──────────────────┘
┌───────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ S7 Knowledge  │  │ S8 RAG / Chat    │  │ S10 Alert        │
│    :8007      │  │    :8008         │  │    :8010         │
└───────────────┘  └──────────────────┘  └──────────────────┘

Infrastructure: PostgreSQL 16 + TimescaleDB + pgvector + AGE │ Kafka │ MinIO │ Valkey │ Ollama
```

---

## Repository Structure

```
worldview/
├── apps/
│   ├── worldview-web/       # Next.js 15 — canonical production frontend
│   └── frontend/            # React + Vite — legacy (being phased out)
├── services/                # 10 FastAPI microservices
│   ├── portfolio/           # S1 — Multi-tenant portfolio management
│   ├── market-ingestion/    # S2 — Market data ingestion & scheduling
│   ├── market-data/         # S3 — Market data storage, screener, prediction markets
│   ├── content-ingestion/   # S4 — News polling & raw storage
│   ├── content-store/       # S5 — Article cleaning, deduplication, search
│   ├── nlp-pipeline/        # S6 — NLP, embeddings, sentiment, signal detection
│   ├── knowledge-graph/     # S7 — Apache AGE knowledge graph
│   ├── rag-chat/            # S8 — RAG-powered conversational AI
│   ├── api-gateway/         # S9 — BFF API gateway (auth, routing, caching)
│   └── alert-service/       # S10 — Alert fan-out, email, WebSocket
├── libs/                    # 6 shared Python libraries
│   ├── common/              # Time, IDs, type aliases
│   ├── contracts/           # Canonical data models, event envelopes
│   ├── messaging/           # Kafka, Avro, outbox, Valkey
│   ├── storage/             # S3/MinIO abstraction
│   ├── observability/       # structlog, Prometheus, OpenTelemetry
│   └── ml-clients/          # LLM provider abstractions (Ollama, Groq, OpenRouter)
├── infra/                   # Infrastructure configs
│   ├── kafka/schemas/       # Avro schemas (.avsc)
│   ├── postgres/init/       # DB init scripts (11 databases)
│   ├── minio/init/          # Bucket init scripts
│   ├── grafana/             # Monitoring dashboards
│   └── tofu/                # OpenTofu IaC (Hetzner production)
├── docs/                    # Documentation (see index below)
├── scripts/                 # Dev scripts (bootstrap, lint, test, CI)
├── Makefile                 # Repo-level targets (lint, test, qa)
├── CLAUDE.md                # AI agent entry point
└── AGENTS.md                # AI agent governance
```

---

## Key Commands

| Command | Purpose |
|---------|---------|
| `./scripts/bootstrap.sh` | One-time setup (venvs, hooks, Docker check) |
| `make dev` | Start full platform with dev tools (MailHog, pgweb, kafka-ui) |
| `make seed` | Load sample data for local development |
| `make fetch-secrets` | Pull credentials from private `worldview-config` repo |
| `make dev-down` / `make dev-reset` | Stop platform / stop + remove volumes |
| `cd services/<name> && make run` | Run a single service locally (hot-reload) |
| `cd apps/worldview-web && pnpm dev` | Frontend dev server (http://localhost:3001) |
| `./scripts/lint.sh` | Ruff + mypy across all packages |
| `./scripts/test.sh` | Unit tests across all packages |
| `./scripts/test.sh --integration` | Unit + integration tests |
| `./scripts/test-full.sh` | Full suite: lint + unit + integration + E2E |
| `make qa` | CI gate: lint + typecheck + unit tests |
| `make test-unit SERVICE=<name>` | Unit tests for one service |
| `make test-e2e SERVICE=<name>` | E2E tests for one service |

---

## Developing a Single Service

Each service follows the same structure and Makefile conventions:

```bash
cd services/<service-name>

make run                  # Start with hot-reload (uvicorn)
make test                 # Run unit tests
make test-integration     # Run integration tests (requires infra)
make lint                 # Ruff check + mypy
make migrate              # Alembic upgrade head
make migrate-new MSG="…"  # Create new Alembic revision
```

**Prerequisites**: Infrastructure must be running (`make dev` or `docker compose --profile infra up -d` + `docker compose --profile init up`).

See [Local Development Guide](docs/workflows/local-dev.md) for detailed setup and troubleshooting.

---

## Port Map

| Service | Port | Service | Port |
|---------|------|---------|------|
| S9 API Gateway | 8000 | PostgreSQL | 5432 |
| S1 Portfolio | 8001 | Kafka | 9092 |
| S2 Market Ingestion | 8002 | Schema Registry | 8081 |
| S3 Market Data | 8003 | MinIO API / Console | 7480 / 7481 |
| S4 Content Ingestion | 8004 | Valkey | 6379 |
| S5 Content Store | 8005 | Ollama | 11434 |
| S6 NLP Pipeline | 8006 | Kafka UI | 8090 |
| S7 Knowledge Graph | 8007 | pgweb | 8091 |
| S8 RAG / Chat | 8008 | Frontend (worldview-web) | 3001 |
| S10 Alert | 8010 | Frontend (legacy Vite) | 5173 |
| | | MailHog UI (dev) | 8025 |

---

## Documentation

| Document | Description |
|----------|-------------|
| [MASTER_PLAN.md](docs/MASTER_PLAN.md) | Complete architecture & roadmap |
| [Local dev guide](docs/workflows/local-dev.md) | Setup, daily workflow, Docker profiles |
| [Debugging guide](docs/runbooks/debugging-guide.md) | Diagnosis loop, common failures, tooling |
| [Service docs](docs/services/) | Per-service API, schema, flow docs (S1–S10) |
| [API Gateway](docs/services/api-gateway.md) | 55+ endpoints, auth flow, middleware stack |
| [Frontend (worldview-web)](docs/apps/worldview-web.md) | Next.js 15 production frontend |
| [Design System](docs/ui/DESIGN_SYSTEM.md) | Tokens, component catalogue, UX patterns |
| [Library docs](docs/libs/) | Per-library public API docs |
| [Architecture diagrams](docs/architecture/diagrams.md) | Mermaid component & flow diagrams |
| [Testing strategy](docs/testing/TESTING_GUIDE.md) | Test layers, markers, Docker Compose stacks |
| [CI/CD pipeline](docs/workflows/ci-cd.md) | GitHub Actions workflow |
| [ADRs](docs/architecture/decisions/) | Architecture decision records |
| [Specs](docs/specs/) | Product requirements documents |
| [Plans](docs/plans/) | Implementation plans with wave tracking |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12 (backend) · TypeScript 5 (frontend) |
| Build | Hatch (hatchling) · pnpm |
| Web | FastAPI + Uvicorn (backend) · Next.js 15 (frontend) |
| UI | shadcn/ui + Radix UI + Tailwind CSS |
| Database | PostgreSQL 16 + TimescaleDB + pgvector + Apache AGE |
| ORM | SQLAlchemy 2 (async) + Alembic |
| Events | Apache Kafka + Confluent Schema Registry + Avro |
| Object Storage | MinIO (S3-compatible) |
| Cache | Valkey (Redis-compatible) |
| Auth | Zitadel (OIDC/PKCE) + RS256 internal JWT |
| LLM | Ollama (local) → Groq → OpenRouter |
| Observability | structlog + Prometheus + OpenTelemetry + Grafana |
| Linting | Ruff + mypy (Python) · ESLint (TypeScript) |
| Testing | pytest (backend) · Vitest + Playwright (frontend) |
| CI | GitHub Actions |
| IaC | OpenTofu (Hetzner production) |

---

## License

University thesis project. All rights reserved.
