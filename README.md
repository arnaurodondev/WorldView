# worldview

A thesis-grade market-intelligence platform. Worldview ingests market data and financial
news, enriches it with NLP and a knowledge graph, and serves portfolio analytics plus
grounded, RAG-powered chat through a professional-grade web terminal.

It is a Python + TypeScript monorepo: **11 backend services** (S1–S10 plus the
`intelligence-migrations` DDL container), **8 shared Python libraries**, a **Next.js 15**
frontend, and a **Docker Compose** development stack.

> **Status**: Active development — all services implemented; the Next.js frontend
> (`worldview-web`) is the canonical production UI. See
> [MASTER_PLAN.md](docs/MASTER_PLAN.md) for the full architecture.

---

## Quick Start (no API keys required)

The minimum requirement is **Docker Desktop**. The bundled seed data lets you run the full
stack and log in with the built-in **Dev Login** button — no external keys needed.

```bash
# 1. Clone
git clone <repo-url> worldview && cd worldview

# 2. Bootstrap (installs Python venvs + pnpm deps, installs git hooks, checks Docker)
./scripts/bootstrap.sh

# 3. Start the full platform (infra + all services + dev tools; ~5–10 min on first run)
make dev

# 4. Load sample data (first launch only)
make seed

# 5. Open http://localhost:3001 → click "Dev Login"
```

> **With API keys (optional)**: For live market data and the full AI pipeline, configure
> EODHD, DeepInfra, and Zitadel. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
> step-by-step setup. None are required for a local run on seed data.

Other useful Make targets: `make dev-down` (stop), `make dev-logs` (tail logs),
`make dev-ps` (status), `make dev-reset` (stop + remove volumes), `make dev-rebuild`
(rebuild images). `make dev-lean` / `make dev-full` toggle a lighter vs. full container set.

### Or develop a single service locally

```bash
# Start only infrastructure
make infra-up

# Run one service natively with hot-reload
cd services/portfolio && make run    # → http://localhost:8001/healthz

# Run the gateway + frontend to test end-to-end
cd services/api-gateway && make run  # → http://localhost:8000
cd apps/worldview-web && pnpm dev     # → http://localhost:3001
```

---

## Architecture

The frontend talks **only** to the S9 API Gateway (a Backend-for-Frontend). The gateway
authenticates the user (OIDC/PKCE via Zitadel, or Dev Login locally), mints a short-lived
RS256 internal JWT, and fans requests out to the domain services. Services never call each
other's databases — they communicate over Kafka events or internal REST.

```
┌───────────────────┐
│  worldview-web    │   Next.js 15 (App Router)
│      :3001        │   shadcn/ui + TanStack Query
└────────┬──────────┘
         │ /api/* rewrite (HTTP)
         │ ws://:8010 (WebSocket alerts — ADR-F-02 exception, the one direct hop)
┌────────▼──────────┐
│ S9 API Gateway    │   FastAPI BFF — auth, routing, caching, rate limiting
│      :8000        │   OIDC/PKCE (Zitadel) + RS256 internal JWT
└────────┬──────────┘
         │ X-Internal-JWT
    ┌────┴───────────────────────────────────────────────┐
┌───▼───────────┐  ┌──────────────────┐  ┌───────────────▼──┐
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
  + intelligence-migrations — init container; owns all DDL for intelligence_db
    (runs to completion before S6/S7 start)

Infrastructure:
  PostgreSQL — split into two instances:
    • postgres (OLTP, :5432)               — 8 transactional service DBs
    • postgres-intelligence (OLAP, :5433)  — nlp_db, intelligence_db, kg_db
      Both run timescaledb-pg16 with pgvector + Apache AGE; market_data_db uses
      TimescaleDB hypertables; the live KG graph lives in intelligence_db (AGE).
  Kafka + Schema Registry (Avro) │ MinIO (S3) │ Valkey (cache) │ Ollama (GLiNER NER)

LLM: DeepInfra (primary — embeddings, chat, extraction) → Groq → OpenRouter fallback;
     Ollama serves the local GLiNER NER model only.
```

---

## Services

| ID | Service (dir) | Port | Responsibility |
|----|---------------|------|----------------|
| S1 | `portfolio` | 8001 | Multi-tenant portfolio & holdings management, transactions, brokerage sync |
| S2 | `market-ingestion` | 8002 | Market-data ingestion scheduling & fetch orchestration |
| S3 | `market-data` | 8003 | Market data storage (TimescaleDB), screener, fundamentals, prediction markets |
| S4 | `content-ingestion` | 8004 | News polling, raw article storage, source routing |
| S5 | `content-store` | 8005 | Article cleaning, deduplication, full-text search |
| S6 | `nlp-pipeline` | 8006 | Embeddings, sentiment, NER, relation extraction, signal detection |
| S7 | `knowledge-graph` | 8007 | Apache AGE knowledge graph build, enrichment & path queries |
| S8 | `rag-chat` | 8008 | RAG-powered conversational AI (hybrid retrieval + grounded answers) |
| S9 | `api-gateway` | 8000 | BFF gateway: auth, routing, caching, rate limiting (frontend's only backend) |
| S10 | `alert` | 8010 | Alert evaluation, fan-out, email, and WebSocket delivery |
| —  | `intelligence-migrations` | — | DDL init container; owns all schema for `intelligence_db` (S6/S7 set `ALEMBIC_ENABLED=false`) |

Full per-service API, schema, and event docs live in [`docs/services/`](docs/services/).

---

## Repository Structure

```
worldview/
├── apps/
│   ├── worldview-web/       # Next.js 15 — canonical production frontend (talks only to S9)
│   └── thesis/              # Thesis source (Typst)
├── services/                # 11 services (10 FastAPI services + intelligence-migrations)
│   ├── portfolio/           # S1
│   ├── market-ingestion/    # S2
│   ├── market-data/         # S3
│   ├── content-ingestion/   # S4
│   ├── content-store/       # S5
│   ├── nlp-pipeline/        # S6
│   ├── knowledge-graph/     # S7
│   ├── rag-chat/            # S8
│   ├── api-gateway/         # S9
│   ├── alert/               # S10
│   └── intelligence-migrations/  # DDL init container for intelligence_db
├── libs/                    # 8 shared Python libraries
│   ├── common/              # Time, UUIDv7 IDs, constants, type aliases
│   ├── contracts/           # Canonical Pydantic models, event envelopes
│   ├── messaging/           # Kafka, Avro, outbox pattern, Valkey
│   ├── storage/             # S3/MinIO abstraction
│   ├── observability/       # structlog, Prometheus, OpenTelemetry
│   ├── ml-clients/          # LLM provider abstractions (DeepInfra, Groq, OpenRouter, Ollama)
│   ├── prompts/             # Versioned LLM prompt templates
│   └── tools/               # LLM tool manifest + capability registry
├── infra/                   # Infrastructure configs
│   ├── compose/             # Docker Compose stacks (dev / test / eval / prod / zitadel)
│   ├── kafka/schemas/       # Avro schemas (.avsc)
│   ├── postgres/init/       # OLTP DB init (postgres :5432)
│   ├── postgres/init-intelligence/  # OLAP DB init (postgres-intelligence :5433)
│   ├── grafana/             # Monitoring dashboards
│   └── tofu/                # OpenTofu IaC (Hetzner production)
├── docs/                    # Documentation (see index below)
├── scripts/                 # Dev scripts (bootstrap, seed, lint, test, CI, hooks)
├── Makefile                 # Repo-level targets (dev, seed, lint, test, qa)
├── CLAUDE.md                # AI agent entry point
└── AGENTS.md                # AI agent governance
```

---

## Shared Libraries

| Library | Purpose |
|---------|---------|
| `common` | UUIDv7 ID generation, UTC time helpers, constants, type aliases |
| `contracts` | Canonical Pydantic domain models and Kafka event envelopes |
| `messaging` | Kafka producer/consumer, Avro serialization, outbox pattern, Valkey client |
| `storage` | S3/MinIO object-storage abstraction |
| `observability` | structlog setup, Prometheus metrics, OpenTelemetry tracing |
| `ml-clients` | LLM provider abstractions with fallback (DeepInfra → Groq → OpenRouter; Ollama for NER) |
| `prompts` | Versioned LLM prompt templates (semver + content hash) |
| `tools` | LLM tool manifest and capability registry used by RAG chat |

Full per-library API docs live in [`docs/libs/`](docs/libs/).

---

## Key Commands

| Command | Purpose |
|---------|---------|
| `./scripts/bootstrap.sh` | One-time setup (venvs, pnpm deps, hooks, Docker check) |
| `make dev` | Start full platform with dev tools (MailHog, pgweb, kafka-ui) |
| `make seed` | Load sample data for local development |
| `make dev-down` / `make dev-reset` | Stop platform / stop + remove volumes |
| `make infra-up` / `make infra-down` | Start / stop only the infrastructure containers |
| `cd services/<name> && make run` | Run a single service locally (hot-reload) |
| `cd apps/worldview-web && pnpm dev` | Frontend dev server (http://localhost:3001) |
| `make lint` | Ruff + mypy across all packages |
| `make typecheck` | mypy type checking |
| `make test-unit` | Unit tests across all packages |
| `make test-e2e` | End-to-end tests |
| `make qa` | CI gate: `lint` + `typecheck` + `test-unit` |
| `make test-arch` | Architecture boundary tests |

---

## Developing a Single Service

Each service follows the same hexagonal structure and Makefile conventions:

```bash
cd services/<service-name>

make run                  # Start with hot-reload (uvicorn)
make test                 # Run unit tests
make test-integration     # Run integration tests (requires infra)
make lint                 # Ruff check + mypy
make migrate              # Alembic upgrade head
make migrate-new MSG="…"  # Create new Alembic revision
```

**Prerequisites**: Infrastructure must be running (`make dev` or `make infra-up`).

> **Note**: `intelligence-migrations` owns all DDL for `intelligence_db`. Services S6 and S7
> set `ALEMBIC_ENABLED=false` and must not run their own migrations against it.

See [Local Development Guide](docs/workflows/local-dev.md) for detailed setup and troubleshooting.

---

## Port Map

| Service | Port | Infrastructure | Port |
|---------|------|----------------|------|
| S9 API Gateway | 8000 | PostgreSQL `postgres` (OLTP, 8 service DBs) | 5432 |
| S1 Portfolio | 8001 | PostgreSQL `postgres-intelligence` (OLAP: nlp_db, intelligence_db, kg_db) | 5433 |
| S2 Market Ingestion | 8002 | Kafka | 9092 |
| S3 Market Data | 8003 | Schema Registry | 8081 |
| S4 Content Ingestion | 8004 | MinIO API / Console | 7480 / 7481 |
| S5 Content Store | 8005 | Valkey | 6379 |
| S6 NLP Pipeline | 8006 | Ollama | 11434 |
| S7 Knowledge Graph | 8007 | Kafka UI (dev) | 8092 |
| S8 RAG / Chat | 8008 | pgweb (dev) | 8091 |
| S10 Alert | 8010 | MailHog UI (dev) | 8025 |
| Frontend (worldview-web) | 3001 | Grafana (monitoring) | 3000 |

> The left (service) and right (infrastructure) columns are **independent** port
> listings, not a mapping. Each service's owned database is listed in its service
> doc; `portfolio_db` and the other 7 transactional DBs live on `postgres` (OLTP,
> :5432), while `nlp_db` / `intelligence_db` / `kg_db` live on `postgres-intelligence`
> (OLAP, :5433). See [MASTER_PLAN §3](docs/MASTER_PLAN.md) for the full split.

---

## Documentation

| Document | Description |
|----------|-------------|
| [MASTER_PLAN.md](docs/MASTER_PLAN.md) | Complete architecture & roadmap |
| [Local dev guide](docs/workflows/local-dev.md) | Setup, daily workflow, Docker profiles |
| [Debugging guide](docs/runbooks/debugging-guide.md) | Diagnosis loop, common failures, tooling |
| [Service docs](docs/services/) | Per-service API, schema, flow docs (S1–S10 + intelligence-migrations) |
| [API Gateway](docs/services/api-gateway.md) | Gateway endpoints, auth flow, middleware stack |
| [Frontend (worldview-web)](docs/apps/worldview-web.md) | Next.js 15 production frontend |
| [Design System](docs/ui/DESIGN_SYSTEM.md) | Tokens, component catalogue, UX patterns |
| [Library docs](docs/libs/) | Per-library public API docs (8 libraries) |
| [Architecture diagrams](docs/architecture/diagrams.md) | Mermaid component & flow diagrams |
| [Testing strategy](docs/testing/TEST_GUIDE.md) | Test layers, markers, Docker Compose stacks |
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
| Database | PostgreSQL 16 + TimescaleDB + pgvector + Apache AGE (OLTP/OLAP split) |
| ORM | SQLAlchemy 2 (async) + Alembic |
| Events | Apache Kafka + Confluent Schema Registry + Avro |
| Object Storage | MinIO (S3-compatible) |
| Cache | Valkey (Redis-compatible) |
| Auth | Zitadel (OIDC/PKCE) + RS256 internal JWT |
| LLM | DeepInfra (primary) → Groq → OpenRouter · Ollama (GLiNER NER only) |
| Observability | structlog + Prometheus + OpenTelemetry + Grafana |
| Linting | Ruff + mypy (Python) · ESLint (TypeScript) |
| Testing | pytest (backend) · Vitest + Playwright (frontend) |
| CI | GitHub Actions |
| IaC | OpenTofu (Hetzner production) |

---

## External Dependencies

Worldview integrates several external APIs. None are required for a local seed-data run:

| Dependency | Required for dev? | Free tier? | Purpose |
|------------|------------------|------------|---------|
| **Docker Desktop** | Yes | Yes | Run the full stack |
| **EODHD** | No (seed data included) | $0 / 20 req/day | Market data, news |
| **DeepInfra** | No (Ollama fallback for NER) | Free credits on sign-up | LLM, embeddings, extraction |
| **Zitadel** | No (Dev Login button) | Free self-hosted / cloud | OIDC authentication |
| **TastyTrade** | No | Yes (paper account) | Brokerage sync |

**Minimum viable local setup**: Docker Desktop only. Run `make dev` + `make seed`, then
click "Dev Login" — no API keys needed.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the step-by-step setup guide.

---

## License

University thesis project. See [LICENSE.md](LICENSE.md).
</content>
</invoke>
