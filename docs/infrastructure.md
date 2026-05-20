# Infrastructure Guide

> Complete setup guide for new developers. Gets you from `git clone` to a fully running
> platform in under 30 minutes on macOS or Linux.
>
> **Platform**: 50+ Docker containers orchestrated by Docker Compose.
> No Kubernetes required for development or single-server production.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Quick Start](#2-quick-start)
3. [Architecture Overview](#3-architecture-overview)
4. [Service Ports Reference](#4-service-ports-reference)
5. [Infrastructure Components](#5-infrastructure-components)
6. [Environment Variables](#6-environment-variables)
7. [Docker Compose Profiles](#7-docker-compose-profiles)
8. [Makefile Reference](#8-makefile-reference)
9. [Development Workflow](#9-development-workflow)
10. [Monitoring Stack](#10-monitoring-stack)
11. [Production Deployment](#11-production-deployment)
12. [Runbooks](#12-runbooks)

---

## 1. Prerequisites

### Required Software

| Tool | Minimum Version | Install (macOS) |
|------|----------------|-----------------|
| Docker Engine | 27+ | Docker Desktop or `brew install docker` |
| Docker Compose | v2.24+ | Included in Docker Desktop |
| Python | 3.12+ | `pyenv install 3.12.7` |
| Node.js | 20+ | `brew install node@20` |
| pnpm | 10+ | `corepack enable && corepack prepare pnpm@10 --activate` |
| Make | any | Ships with macOS Xcode Command Line Tools |
| Hatch | 1.12+ | `pip install hatch` |

### Hardware Requirements

| Tier | RAM | Disk | CPU | Notes |
|------|-----|------|-----|-------|
| Minimum | 8 GB | 40 GB | 4 cores | Infrastructure + core services only |
| Recommended | 16 GB | 80 GB | 8 cores | Full stack with NLP pipeline and ML |
| Production (Hetzner) | 16 GB | 160 GB | 8 vCPU | CPX41 ~€13/month |

### Storage breakdown (approximately)

- Docker images: ~15 GB
- GLiNER model (`urchade/gliner_large-v2.1`): ~500 MB (downloaded on first run)
- Ollama models (`bge-large` + `qwen3:0.6b`): ~2 GB (downloaded on first run)
- PostgreSQL data volumes: ~2 GB (grows with live data ingestion)
- MinIO object storage: ~1 GB (grows with article content)

### macOS vs Linux

On macOS, all infra ports bind to `127.0.0.1` (localhost only) by default — this is enforced in the
compose files for security. No additional firewall configuration is needed.

On Linux with Docker Compose v2, the same applies. The `make dev` target kills any process
occupying port 3001 before starting the frontend container.

---

## 2. Quick Start

### Step 1: Clone and bootstrap

```bash
git clone <repo-url> worldview
cd worldview
./scripts/bootstrap.sh
```

`bootstrap.sh` installs pre-commit hooks, all Python shared libraries in editable mode, and
checks that Docker is running.

### Step 2: Configure secrets

The platform needs API keys for external services (EODHD, DeepInfra). For a first
install without real API keys, the platform starts and seeds demo data but live data
ingestion will be disabled.

**Option A — with real API keys** (private worldview-gitops repo required):

```bash
make fetch-secrets   # pulls credentials from private worldview-config repo
```

**Option B — without API keys** (demo/evaluation mode):

All services start and demo data is seeded. EODHD ingestion is silently skipped when
`MARKET_INGESTION_EODHD_API_KEY` is empty. DeepInfra LLM calls fall back to local Ollama.
See [Section 6](#6-environment-variables) for what each key does.

### Step 3: Start the platform

```bash
make dev
```

This runs `docker compose` with the base file + dev overlay and the `infra` profile. It:
- Starts PostgreSQL, Kafka (KRaft), Schema Registry, MinIO, Valkey, Ollama, GLiNER
- Runs all database migrations (one-shot containers)
- Creates Kafka topics and registers Avro schemas
- Creates MinIO buckets
- Starts all 10 microservices
- Starts the Next.js frontend
- Starts dev tools: MailHog, pgweb, Kafka UI

First boot takes 5–10 minutes because:
- Docker images are built from Dockerfiles (subsequent starts are fast)
- GLiNER downloads `urchade/gliner_large-v2.1` (~500 MB) — cached in `gliner_model_cache` volume
- Ollama pulls `qwen3:0.6b` and `bge-large` (~2 GB total) — cached in `ollama_data` volume

### Step 4: Seed demo data

```bash
make seed
```

Loads:
- Demo tenant, user, portfolio, holdings (AAPL, MSFT, NVDA, TSLA, AMZN)
- 10 market instruments (AAPL, MSFT, GOOGL, TSLA, AMZN, NVDA, META, JPM, NFLX, DIS)
- Canonical entities, OHLCV bars, company profiles, content ingestion sources

### Step 5: Verify

```bash
# Check all containers are healthy
make dev-ps

# Verify API gateway
curl http://localhost:8000/readyz

# Open the frontend (no Zitadel needed in dev mode — use "Dev Login")
open http://localhost:3001
```

Expected health check response: `{"status":"ok"}` or `{"status":"healthy"}`.

---

## 3. Architecture Overview

```
                      ┌────────────────────────────────┐
                      │  worldview-web (Next.js 15)     │
                      │  http://localhost:3001           │
                      └──────────────┬─────────────────┘
                                     │ /api/* rewrites
                      ┌──────────────▼─────────────────┐
                      │  S9 · API Gateway               │
                      │  http://localhost:8000           │
                      │  Auth (Zitadel OIDC/PKCE)       │
                      │  Rate limiting (Valkey)          │
                      └──┬──┬──┬──┬──┬──┬──┬──┬───────┘
                 ┌───────┘  │  │  │  │  │  │  └──────────┐
                 ▼          ▼  ▼  ▼  ▼  ▼               ▼
            ┌────────┐  ┌──────┐  ┌────────┐       ┌─────────┐
            │ S1     │  │ S3   │  │ S6/S7  │       │ S8      │
            │ Portfolio│  │ Market│  │ NLP/KG │       │ RAG/Chat│
            │ :8001  │  │ Data │  │ :8006  │       │ :8008   │
            └───┬────┘  │ :8003│  │ :8007  │       └─────────┘
                │       └──────┘  └────────┘
                └────────────────────────┐
                        Kafka (KRaft)    │
                        :9092            │
          ┌─────────────────────────────┤
          ▼              ▼              ▼
     ┌─────────┐  ┌──────────┐  ┌───────────┐
     │ S2 Mkt  │  │ S4 Cont. │  │ S10 Alert │
     │ Ingestion│  │ Ingestion│  │ :8010     │
     │ :8002   │  │ :8004    │  └───────────┘
     └─────────┘  └──────────┘
         │              │
    ┌────▼─────┐  ┌─────▼────┐
    │  EODHD   │  │ S5 Cont. │
    │  API     │  │ Store    │
    └──────────┘  │ :8005    │
                  └──────────┘

Infrastructure:
  PostgreSQL (TimescaleDB + pgvector + AGE) :5432
  Kafka + Schema Registry :9092 / :8081
  MinIO (S3-compatible) :7480 / :7481
  Valkey (Redis-compatible) :6379
  Ollama (local LLM) :11434
  GLiNER (NER server) :8090
```

**Data flows**:
- EODHD → S2 → `market.dataset.fetched` → S3 → `market.instrument.created` → S1
- RSS/News → S4 → `content.article.raw.v1` → S5 → `content.article.stored.v1` → S6 → `nlp.article.enriched.v1` → S7
- S6 → `nlp.signal.detected.v1` → S10 (alerts)
- S7 → `graph.state.changed.v1` → S10 (alerts)

---

## 4. Service Ports Reference

### Application Services

| Service | Port | Health Check URL | Database | Notes |
|---------|------|-----------------|----------|-------|
| S9 · API Gateway | 8000 | `GET /readyz` | None (stateless) | Entry point for all frontend traffic |
| S1 · Portfolio | 8001 | `GET /readyz` | `portfolio_db` | Users, portfolios, holdings, watchlists |
| S2 · Market Ingestion | 8002 | `GET /healthz` | `ingestion_db` | EODHD polling + MinIO bronze storage |
| S3 · Market Data | 8003 | `GET /healthz` | `market_data_db` (TimescaleDB) | OHLCV, quotes, fundamentals |
| S4 · Content Ingestion | 8004 | `GET /healthz` | `content_ingestion_db` | RSS/EDGAR/Finnhub news polling |
| S5 · Content Store | 8005 | `GET /readyz` | `content_store_db` | HTML cleaning, dedup, MinIO silver |
| S6 · NLP Pipeline | 8006 | `GET /readyz` | `nlp_db` + `intelligence_db` | GLiNER NER, embeddings, entity resolution |
| S7 · Knowledge Graph | 8007 | `GET /readyz` | `intelligence_db` | Relation canonicalization, graph materialization |
| S8 · RAG / Chat | 8008 | `GET /healthz` | `rag_db` | Hybrid retrieval + LLM chat (SSE) |
| S10 · Alert | 8010 | `GET /readyz` | `alert_db` | WebSocket alerts, email notifications |
| worldview-web | 3001 | `GET /` | None | Next.js 15 frontend |

### Infrastructure

| Component | Port(s) | Credentials | Purpose |
|-----------|---------|-------------|---------|
| PostgreSQL | 5432 | `postgres:postgres` | All relational data (11 databases) |
| Kafka | 9092 (external) / 29092 (internal) | None | Event backbone (KRaft mode, no ZooKeeper) |
| Schema Registry | 8081 | None | Avro schema management |
| MinIO S3 API | 7480 | `minioadmin:minioadmin` | Object storage (bronze/silver/gold) |
| MinIO Console | 7481 | `minioadmin:minioadmin` | Web UI for bucket browsing |
| Valkey | 6379 | None | Cache, rate limiting, LSH dedup |
| Ollama | 11434 | None | Local LLM inference (BGE, Qwen3) |
| GLiNER | 8090 | None | NER server (DeBERTa-large) |

### Dev Tools (dev overlay only — `make dev`)

| Tool | Port | Purpose |
|------|------|---------|
| MailHog Web UI | 8025 | View captured outbound emails from S10 |
| MailHog SMTP | 1025 | SMTP endpoint (set `ALERT_SMTP_HOST=mailhog`) |
| pgweb | 8091 | Browser-based PostgreSQL client (all 11 databases) |
| Kafka UI | 8092 | Topic browser, consumer group inspector |

### Monitoring Stack (optional — `make monitoring`)

| Component | Port | Credentials | Purpose |
|-----------|------|-------------|---------|
| Grafana | 3000 | `admin:admin` | Dashboards (12 pre-built) |
| Prometheus | 9090 | None | Metrics collection |
| Loki | 3100 | None | Log aggregation |
| Tempo | 3200 | None | Distributed tracing |
| Alertmanager | 9093 | None | Alert routing |
| Alloy | 12345 | None | Log/trace collector agent |
| Pushgateway | 9091 (localhost only) | None | Metrics from synthetic monitor |

---

## 5. Infrastructure Components

### PostgreSQL

**Purpose**: Primary relational data store for all 10 microservices.

**Image**: Custom build from `timescale/timescaledb-ha:pg16-latest` with additional extensions.

**Databases created at init** (`infra/postgres/init/init-databases.sh`):

| Database | Owner Service | Extensions |
|----------|--------------|------------|
| `portfolio_db` | S1 Portfolio | uuid-ossp |
| `ingestion_db` | S2 Market Ingestion | uuid-ossp |
| `market_data_db` | S3 Market Data | uuid-ossp, **TimescaleDB** |
| `content_ingestion_db` | S4 Content Ingestion | uuid-ossp, pgcrypto |
| `content_store_db` | S5 Content Store | uuid-ossp |
| `nlp_db` | S6 NLP Pipeline | uuid-ossp, **pgvector** |
| `intelligence_db` | S6+S7 (DDL: intelligence-migrations) | uuid-ossp, pgvector, pg_trgm |
| `kg_db` | S7 Knowledge Graph | uuid-ossp, **Apache AGE** |
| `rag_db` | S8 RAG/Chat | uuid-ossp |
| `gateway_db` | S9 API Gateway | uuid-ossp |
| `alert_db` | S10 Alert | uuid-ossp |

**Special configuration**:
- The `postgres` container also responds to the hostname `timescaledb` (network alias). S3 Market Data uses this alias in its docker.env.
- `intelligence_db` is shared between S6 and S7. **Only `intelligence-migrations` runs DDL on it** — S6 and S7 set `ALEMBIC_ENABLED=false`.
- `kg_db` has Apache AGE installed with the `market_kg` graph created at init time. AGE enables Cypher query language over the relational schema.

**Verify health**:
```bash
docker exec worldview-postgres-1 pg_isready -U postgres
docker exec worldview-postgres-1 psql -U postgres -c "\list"   # all databases
```

**Migrations**: Each service owns its own Alembic migrations, run by one-shot `<service>-migrate` containers at startup. After `make dev`, all databases are at `head`.

---

### Apache Kafka (KRaft mode)

**Purpose**: Event backbone for asynchronous inter-service communication.

**Image**: `confluentinc/cp-kafka:7.6.0` in KRaft mode (no ZooKeeper dependency).

**Topics** (created by `infra/kafka/init/create-topics.sh`):

| Topic | Partitions | Retention | Flow |
|-------|-----------|-----------|------|
| `portfolio.events.v1` | 3 | 7d | S1 → audit |
| `portfolio.watchlist.updated.v1` | 12 | 7d | S1 → S6, S10 |
| `market.dataset.fetched` | 6 | **30d** | S2 → S3, S7 |
| `market.instrument.created` | 3 | 7d | S2 → S7 |
| `market.instrument.updated` | 3 | 7d | S2 → S7 |
| `market.instrument.discovered.v1` | 3 | 7d | S2 → S7 |
| `content.article.raw.v1` | 12 | **30d** | S4 → S5 |
| `content.article.stored.v1` | 12 | **30d** | S5 → S6 |
| `nlp.article.enriched.v1` | 12 | **30d** | S6 → S7 |
| `nlp.signal.detected.v1` | 24 | 14d | S6 → S10 |
| `graph.state.changed.v1` | 12 | 14d | S7 → S10 |
| `intelligence.contradiction.v1` | 12 | **30d** | S7 → S10 |
| `relation.type.proposed.v1` | 4 | **30d** | S7 → ops |
| `entity.canonical.created.v1` | 12 | 7d | S7 → S7 internal |
| `alert.delivered.v1` | 12 | 7d | S10 → audit |
| `market.prediction.v1` | 8 | **30d** | S4 → S3 |
| `entity.dirtied.v1` | 24 | **compacted** | S7 → S7 workers |
| `*.dead-letter.v1` | 8–12 | 7d | DLQ topics |

**Schema Registry**: Confluent Schema Registry (BACKWARD compatibility) manages Avro schemas for all topics. Schemas are in `infra/kafka/schemas/*.avsc`. One-shot `schema-registry-init` registers them at startup.

**Verify health**:
```bash
curl http://localhost:8081/subjects   # list all registered schemas
docker exec worldview-kafka-1 kafka-broker-api-versions --bootstrap-server localhost:9092
```

**Check consumer lag**:
```bash
docker exec worldview-kafka-1 kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --all-groups
```

---

### MinIO (Object Storage)

**Purpose**: S3-compatible object storage for raw/canonical/enriched content at three data quality layers.

**Image**: `minio/minio:RELEASE.2025-04-08T15-41-24Z`

**Buckets** (created by `infra/minio/init/init-buckets.sh`):

| Bucket | Content | Owner |
|--------|---------|-------|
| `market-data` | Market data objects | S2 |
| `content-data` | Content objects | S4 |
| `intelligence-data` | Intelligence artifacts | S6/S7 |
| `rag-data` | RAG/chat artifacts | S8 |
| `market-bronze` | Raw EODHD JSON | S2 |
| `market-canonical` | Normalized Parquet | S2 |
| `worldview-bronze` | Raw article HTML/JSON | S4 |
| `worldview-silver` | Cleaned article text | S5 |
| `worldview` | General platform objects | Various |

**Object path conventions**:
- Bronze: `bronze/<service>/<source>/<id>/raw/v1.<ext>`
- Silver: `silver/<service>/<source>/<id>/canonical/v1.<ext>`
- Gold: `gold/<service>/<entity>/<id>/<artifact>/v1.<ext>`

**Verify health**:
```bash
curl http://localhost:7480/minio/health/live   # → 200
# Or open MinIO console:
open http://localhost:7481   # admin: minioadmin/minioadmin
```

---

### Valkey (Redis-compatible Cache)

**Purpose**: Multi-role cache used by multiple services.

**Image**: `valkey/valkey:7.2-alpine`

**Use cases**:
- S9 API Gateway: quote caching (30s TTL), OHLCV caching (2 min), rate limiting counters, PKCE state
- S5 Content Store: LSH dedup fingerprints for near-duplicate detection
- S6 NLP Pipeline: watchlist cache for entity routing
- S10 Alert: watchlist resolution cache (10 min TTL)
- S8 RAG/Chat: completion cache (24h TTL)

**Key naming convention**: `{scope}:{version}:{resource}:{id}[:{qualifier}]`
Example: `gw:v1:quote:01900000-0000-7000-8000-000000001001`

**Verify health**:
```bash
docker exec worldview-valkey-1 valkey-cli ping   # → PONG
docker exec worldview-valkey-1 valkey-cli dbsize  # number of cached keys
```

---

### GLiNER (NER Server)

**Purpose**: Named Entity Recognition for the NLP pipeline. Identifies 11 entity classes in article text (company, person, location, product, etc.).

**Image**: Custom build from `infra/gliner/Dockerfile` using `python:3.12-slim`.

**Model**: `urchade/gliner_large-v2.1` (DeBERTa-large backbone, ~500 MB). Downloaded from HuggingFace on first start and cached in the `gliner_model_cache` Docker volume.

**First-boot time**: Up to 10 minutes (600s health check `start_period`) due to model download on slow connections. Subsequent starts are instant from the volume cache.

**GPU support**: Optional. Uncomment the `deploy.resources` block in `docker-compose.yml` to enable NVIDIA GPU passthrough. Reduces NER latency from ~0.5–3s to ~50ms per batch.

**Environment variables** (set in compose):
- `GLINER_MODEL_PATH`: HuggingFace model identifier (default: `urchade/gliner_large-v2.1`)
- `HF_HUB_DISABLE_XET=1`: Disables xet transfer protocol that throttles to ~63 KB/s on some hosts

**Verify health**:
```bash
curl http://localhost:8090/healthz   # → {"status":"ok"}
```

---

### Ollama (Local LLM)

**Purpose**: Local inference server for embeddings and intent classification. Used as fallback when DeepInfra API keys are unavailable.

**Image**: `ollama/ollama:0.6.7`

**Models pulled automatically** by `ollama-init` container:
- `qwen3:0.6b` (522 MB) — intent classification in S8 RAG/Chat
- `bge-large` (1.2 GB) — text embeddings (1024-dim BERT, used by S6 NLP and S8 RAG)

**Optional model** (not auto-pulled, needed for DEEP extraction tier):
```bash
docker exec worldview-ollama-1 ollama pull qwen2.5:7b-instruct   # 4 GB
```

**GPU support**: Uncomment `deploy.resources` in `docker-compose.yml` for NVIDIA GPU passthrough.

**Verify health**:
```bash
curl http://localhost:11434/api/tags   # lists loaded models
docker exec worldview-ollama-1 ollama list
```

**Note**: The BGE-large model has a 512-token BERT limit. All input is truncated to ≤1500 characters before embedding to avoid GGML assertion crashes (BP-121).

---

### Zitadel (OIDC Identity Provider)

**Purpose**: OIDC/PKCE authentication provider. **Optional for local development** — `make dev` works without it using "Dev Login".

**Dev Login (no Zitadel needed)**:
When Zitadel is not configured, `POST /v1/auth/dev-login` on S9 API Gateway issues a valid JWT for the demo user. The frontend login page shows a "Dev Login" button automatically when `NEXT_PUBLIC_ZITADEL_URL` is not set to a reachable instance.

**Option A — Self-hosted local Zitadel**:
```bash
docker compose -f infra/compose/docker-compose.zitadel.yml up -d
# Console: http://localhost:8088
# Admin: zitadel-admin@zitadel.localhost / Password1!
```

**Option B — Zitadel Cloud** (free tier, ≤25k MAU):
See `infra/zitadel/README.md` for full setup steps.

**Option C — Terraform automation**:
```bash
cd infra/zitadel/terraform
tofu init && tofu plan && tofu apply
```

**Required S9 env vars when Zitadel is configured**:
```bash
API_GATEWAY_OIDC_ISSUER_URL=https://<instance>.zitadel.cloud
API_GATEWAY_OIDC_CLIENT_ID=<client-id>
API_GATEWAY_OIDC_AUDIENCE=<client-id>
API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY=<rsa-2048-pem>
API_GATEWAY_INTERNAL_JWT_PUBLIC_KEY=<rsa-2048-pem>
```

Generate the RSA-2048 keypair:
```bash
./scripts/generate-internal-keypair.sh
```

---

## 6. Environment Variables

Each service reads configuration from `services/<service>/configs/docker.env` when running
in Docker, or from `services/<service>/configs/.env` when running locally.

### Obtaining API Keys

| Key | Service | Where to Get |
|-----|---------|--------------|
| `MARKET_INGESTION_EODHD_API_KEY` | S2 Market Ingestion | [eodhd.com](https://eodhd.com) — free tier available |
| `CONTENT_INGESTION_EODHD_API_KEY` | S4 Content Ingestion | Same EODHD account |
| `NLP_PIPELINE_EMBEDDING_API_KEY` | S6 NLP Pipeline | [deepinfra.com](https://deepinfra.com) — pay-per-token |
| `KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY` | S7 Knowledge Graph | Same DeepInfra account |
| `RAG_CHAT_DEEPINFRA_API_KEY` | S8 RAG/Chat | Same DeepInfra account |
| `KNOWLEDGE_GRAPH_GOOGLE_AI_API_KEY` | S7 (entity descriptions) | [aistudio.google.com](https://aistudio.google.com) — free tier |
| `PORTFOLIO_SNAPTRADE_CLIENT_ID` | S1 Portfolio | [snaptrade.com](https://snaptrade.com) — free ≤5 users |
| `PORTFOLIO_TASTY_CLIENT_ID` | S1 Portfolio | [tastytrade.com](https://tastytrade.com) — brokerage API |

**Running without API keys**: Services degrade gracefully. Market Ingestion skips EODHD polling (logs warning). NLP Pipeline falls back to local Ollama for embeddings. Knowledge Graph skips LLM extraction. Demo data from `make seed` still loads and the UI works with static data.

### Key Environment Variable Patterns

All services use `pydantic-settings` to load config. Each variable follows the pattern `<SERVICE_PREFIX>_<NAME>`.

**Database URLs** (asyncpg for SQLAlchemy):
```bash
PORTFOLIO_DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/portfolio_db
```

**Kafka**:
```bash
NLP_PIPELINE_KAFKA_BOOTSTRAP_SERVERS=kafka:29092           # Docker-internal
# or for local (non-Docker) run:
NLP_PIPELINE_KAFKA_BOOTSTRAP_SERVERS=localhost:9092
```

**MinIO/S3**:
```bash
MARKET_INGESTION_STORAGE_ENDPOINT=http://minio:9000       # Docker-internal
MARKET_INGESTION_STORAGE_ACCESS_KEY=minioadmin
MARKET_INGESTION_STORAGE_SECRET_KEY=minioadmin
```

**Valkey/Redis**:
```bash
API_GATEWAY_VALKEY_URL=redis://valkey:6379/0
```

**Internal JWT auth** (S9 signs, all backends verify):
```bash
# Set these on S9 only:
API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY=<rsa-2048-pem>
API_GATEWAY_INTERNAL_JWT_PUBLIC_KEY=<rsa-2048-pem>
# Backend services fetch the public key from S9 at startup via /internal/jwks
```

**ML providers** (with Ollama fallback):
```bash
NLP_PIPELINE_EMBEDDING_PROVIDER=deepinfra          # or: ollama
NLP_PIPELINE_EMBEDDING_API_KEY=<deepinfra-key>     # empty = use Ollama
NLP_PIPELINE_EMBEDDING_BASE_URL=http://ollama:11434 # Ollama fallback
```

### Security notes

- All infra ports bind to `127.0.0.1` in dev (not `0.0.0.0`) — enforcement from compose sec rule SEC-007.
- Default credentials (`postgres:postgres`, `minioadmin:minioadmin`) are suitable for local dev only. **Always change these before any internet-exposed deployment.**
- Production uses the `docker-compose.prod.yml` overlay which removes all infra port bindings and routes through Traefik.

---

## 7. Docker Compose Profiles

All compose files are in `infra/compose/`. Never run `docker compose` without specifying `-f infra/compose/docker-compose.yml`.

### Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Base: infra + all 10 services + frontend + monitoring stack |
| `docker-compose.dev.yml` | Dev overlay: MailHog, pgweb, Kafka UI |
| `docker-compose.prod.yml` | Production overlay: Traefik TLS + hardened env + port removal |
| `docker-compose.test.yml` | Isolated test stack (separate ports, clean DB names) |
| `docker-compose.eval.yml` | Eval stack: API servers only, no ingestion workers |
| `docker-compose.zitadel.yml` | Optional self-hosted Zitadel for OIDC |

### Profiles

| Profile | Services Started | Use When |
|---------|-----------------|----------|
| `infra` | All infra + all 10 microservices + frontend | Full platform (dev or prod) |
| `monitoring` | Prometheus, Grafana, Loki, Tempo, Alloy, Alertmanager | Adding observability |
| `all` | Everything | Full system including monitoring |
| `lib-test` | MinIO only | Running lib-level integration tests |
| `eval` | Infra + API servers only (no ingestion workers) | Retrieval quality evaluation |

### Manual compose commands

```bash
# Full platform (what `make dev` runs):
docker compose \
  -f infra/compose/docker-compose.yml \
  -f infra/compose/docker-compose.dev.yml \
  --profile infra up -d

# With monitoring:
docker compose \
  -f infra/compose/docker-compose.yml \
  -f infra/compose/docker-compose.dev.yml \
  --profile infra --profile monitoring up -d

# Tail a single service:
docker compose -f infra/compose/docker-compose.yml logs -f nlp-pipeline

# Restart a single service:
docker compose -f infra/compose/docker-compose.yml restart knowledge-graph
```

---

## 8. Makefile Reference

Run `make help` for a summary. All targets below are at the repo root.

### Development Environment

| Target | Description |
|--------|-------------|
| `make dev` | Start full dev stack (infra + services + dev tools). Kills port 3001 first. |
| `make dev-down` | Stop dev stack gracefully (5s timeout). |
| `make dev-reset` | Stop + remove all volumes (clean slate). Destructive — deletes all data. |
| `make dev-logs` | Tail all container logs in follow mode (last 50 lines). |
| `make dev-ps` | Show container health status. |
| `make dev-rebuild` | Rebuild all Docker images without cache and restart. Use after Dockerfile changes. |
| `make dev-clean` | Remove all `docker.env` files (re-run `setup-dev.sh` from worldview-gitops to restore). |
| `make seed` | Load sample data: SQL fixtures + Python demo data (tenant, user, instruments, entities). |

### Testing

| Target | Description |
|--------|-------------|
| `make qa` | CI gate: lint + typecheck + unit tests. No infra required. |
| `make lint` | Ruff check + format check for all libs and services. |
| `make typecheck` | mypy for all services and libs. |
| `make test-unit` | All unit + contract tests. |
| `make test-unit SERVICE=<svc>` | Unit tests for a single service (e.g., `SERVICE=portfolio`). |
| `make test-arch` | Architecture/standards compliance tests. |
| `make test-all` | Full suite: lint + unit + integration + E2E (requires infra). |
| `make test-e2e` | E2E tests (all services). |
| `make test-e2e SERVICE=<svc>` | E2E tests for a single service. |
| `make infra-up` | Start test Docker Compose stack (isolated ports, clean names). |
| `make infra-down` | Stop test stack. |

### QA

| Target | Description |
|--------|-------------|
| `make qa-exhaustive` | Backend + frontend exhaustive QA vs live dev stack. Requires `make dev` + `make seed` first. |
| `make qa-exhaustive-backend` | Backend endpoint coverage, auth, security, schema validation. |
| `make qa-exhaustive-frontend` | All routes, states, screenshots, a11y, security headers (Playwright). |
| `make qa-live-stack` | Frontend vs real API, no mocks. Exposes broken backends. |
| `make qa-contract` | Verify frontend mock fixtures match real API response shapes. |

### Kafka Schema Management

| Target | Description |
|--------|-------------|
| `make schema-set-compat` | Pin BACKWARD compatibility on all Schema Registry subjects. Idempotent. |

### Monitoring

| Target | Description |
|--------|-------------|
| `make monitoring` | Start observability stack (Prometheus, Grafana, etc.) after `make dev`. |
| `make monitoring-down` | Stop monitoring stack. |

### Retrieval Evaluation

| Target | Description |
|--------|-------------|
| `make test` | Boot minimal eval stack (API servers only, no ingestion workers). |
| `make test-rebuild` | Rebuild eval images from scratch. |
| `make test-down` | Stop eval stack. |
| `make seed-eval` | Seed SQL + demo data + 225 synthetic eval chunks with BGE embeddings. |
| `make eval` | Run retrieval evaluation harness (NDCG@10, MRR, P@5, Recall@20). |

### Production

| Target | Description |
|--------|-------------|
| `make prod` | Start production stack with Traefik TLS. Requires `DOMAIN` and `ACME_EMAIL` env vars. |
| `make prod-down` | Stop production stack. |
| `make prod-rebuild` | Rebuild all images without cache and restart production stack. |

---

## 9. Development Workflow

### Restarting a Single Service

```bash
# Restart without rebuilding (picks up env changes):
docker compose -f infra/compose/docker-compose.yml restart <service>

# Rebuild image and restart (picks up code changes):
docker compose -f infra/compose/docker-compose.yml up -d --build --no-deps <service>
```

Common service names: `api-gateway`, `portfolio`, `market-data`, `nlp-pipeline`, `knowledge-graph`, `rag-chat`, `alert`, `worldview-web`.

### Viewing Logs

```bash
# All services (last 50 lines, follow):
make dev-logs

# Single service:
docker compose -f infra/compose/docker-compose.yml logs -f nlp-pipeline
docker logs -f worldview-nlp-pipeline-1

# All containers matching a pattern:
docker compose -f infra/compose/docker-compose.yml logs -f | grep "knowledge-graph"

# Last N lines without following:
docker compose -f infra/compose/docker-compose.yml logs --tail=100 api-gateway
```

### Database Operations

```bash
# Connect to a database:
docker exec -it worldview-postgres-1 psql -U postgres -d portfolio_db

# Browse all databases (pgweb):
open http://localhost:8091

# Run a migration manually:
docker compose -f infra/compose/docker-compose.yml run --rm portfolio-migrate

# Reset a single database (destructive):
docker exec worldview-postgres-1 psql -U postgres -c "DROP DATABASE portfolio_db;"
docker exec worldview-postgres-1 psql -U postgres -c "CREATE DATABASE portfolio_db;"
# Then re-run the migration container:
docker compose -f infra/compose/docker-compose.yml up -d --no-deps portfolio-migrate
```

### Scaling a Worker

Content Ingestion Worker supports horizontal scaling:

```bash
docker compose -f infra/compose/docker-compose.yml up -d --scale content-ingestion-worker=3
```

### Running Tests Against Live Infrastructure

```bash
# Unit tests (no infra needed):
make test-unit

# Single service unit tests:
cd services/portfolio && python -m pytest tests/ -m unit -v

# Integration tests (requires make dev running):
cd services/portfolio && python -m pytest tests/ -m integration -v

# E2E tests for one service:
make test-e2e SERVICE=portfolio

# Full platform E2E:
make test-all
```

### Checking Kafka Consumer Lag

```bash
# List all consumer groups with lag:
docker exec worldview-kafka-1 kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --all-groups \
  | awk '$NF > 0'   # show only groups with lag > 0

# Or use Kafka UI (all topics + groups visualized):
open http://localhost:8092
```

### Resetting the Entire Stack

```bash
# Stop everything and remove all data volumes:
make dev-reset

# Restart from scratch:
make dev
make seed
```

---

## 10. Monitoring Stack

Start the observability stack after `make dev` (monitoring targets running services):

```bash
make monitoring
```

Or include it in the initial start:

```bash
docker compose \
  -f infra/compose/docker-compose.yml \
  -f infra/compose/docker-compose.dev.yml \
  --profile infra --profile monitoring up -d
```

### Grafana

Access at **http://localhost:3000** (admin/admin).

Pre-built dashboards (auto-provisioned from `infra/grafana/dashboards/`):

| Dashboard | Purpose |
|-----------|---------|
| Service Overview | Request rates, error rates, latency per service |
| API Gateway | Auth success/failure, rate limiting, upstream errors |
| Kafka Pipeline | Topic throughput, consumer lag, dead-letter growth |
| Content Pipeline | Article throughput, ingestion stages |
| Outbox Health | Outbox event backlog, dispatch failures |
| Alert Service | Alert delivery rates, WebSocket connections |
| RAG Chat | Retrieval quality, LLM latency |
| EODHD Health | API quota usage, rate limit proximity |
| Error Observability | Cross-service error rates and top errors |
| API Usage Analytics | Request patterns, top endpoints |
| Logs Explorer | Loki log search |

### Alertmanager

Prometheus alerting rules are in `infra/prometheus/rules/`. Key alerts:
- `SyntheticProbeDown` — any synthetic monitor probe fails for >5 minutes
- `ValkeyDown` — Valkey unreachable
- `KafkaConsumerLagHigh` — consumer group lag exceeds threshold
- SLO budget burn rate alerts for each service

Alertmanager config is at `infra/alertmanager/alertmanager.yml`. Configure SMTP receivers for email alerts (test with `scripts/test-alertmanager-email.sh`).

### Synthetic Monitor

A lightweight probe process (`infra/synthetic/synthetic_monitor.py`) runs three probes every 60 seconds:
1. `probe_api_gateway_health` — `GET /health` must return 200
2. `probe_market_data_quote` — `GET /api/v1/market-data/AAPL/quote` must not 5xx
3. `probe_portfolio_holdings` — `GET /api/v1/portfolio/holdings` (skipped if no JWT)

Results are pushed to Pushgateway and scraped by Prometheus.

---

## 11. Production Deployment

**Target**: Single Hetzner server (Docker Compose + Traefik TLS). No Kubernetes required.

### Architecture

```
Internet → Traefik (ports 80/443, Let's Encrypt TLS)
  api.${DOMAIN}       → api-gateway:8000
  ws.${DOMAIN}        → alert:8010 (WebSocket)
  ${DOMAIN}           → worldview-web:3001
  grafana.${DOMAIN}   → grafana:3000
All other ports are removed from host binding in production overlay.
```

### Quick Deploy

```bash
# 1. Provision server (see infra/gitops/docs/hetzner-setup.md)
# Minimum: Hetzner CPX31 (4 vCPU, 8 GB RAM, Ubuntu 24.04)
# Recommended: CPX41 (8 vCPU, 16 GB RAM) for NLP pipeline

# 2. Bootstrap server (installs Docker, creates swap, configures UFW)
ssh root@<server-IP>
bash /tmp/hetzner-bootstrap.sh

# 3. Clone repos on server
cd /opt/worldview
git clone <repo-url> worldview
git clone <gitops-repo-url> worldview-gitops

# 4. Configure env
cd worldview-gitops
cp templates/platform.env.template env/prod/platform.env
# Edit: DOMAIN, ACME_EMAIL, ZITADEL_URL, ZITADEL_CLIENT_ID
./scripts/setup-prod.sh

# 5. Generate internal JWT keypair
cd ../worldview
./scripts/generate-internal-keypair.sh
# Add output to env/prod/api-gateway.env

# 6. Deploy
export $(grep -v '^#' ../worldview-gitops/env/prod/platform.env | xargs)
make prod
```

### Required Production Env Vars

| Variable | Description |
|----------|-------------|
| `DOMAIN` | Root domain (e.g., `worldview.example.com`) |
| `ACME_EMAIL` | Email for Let's Encrypt expiry notifications |
| `ZITADEL_URL` | Zitadel Cloud issuer URL |
| `ZITADEL_CLIENT_ID` | PKCE application client ID |
| `NEXT_PUBLIC_WS_BASE_URL` | WebSocket URL (must be `wss://`, not `ws://`) |

### OpenTofu / Terraform

Infrastructure as code for Hetzner provisioning is in `infra/tofu/`. It provisions:
- Servers (control plane + worker nodes)
- Hetzner private network
- Firewall rules
- Floating IP

```bash
cd infra/tofu
cp terraform.tfvars.example terraform.tfvars
tofu init && tofu plan && tofu apply
```

### Kubernetes (Local / GitOps)

`scripts/local-k8s.sh` bootstraps a local k3d cluster for GitOps workflow testing. Kubernetes Helm charts are not included in this repository — production uses Docker Compose on a single Hetzner node.

### Backup and Disaster Recovery

See `infra/gitops/docs/disaster-recovery.md` for full procedures. Summary:

**Nightly cron on production server**:
```bash
# Add to crontab
0 3 * * * docker exec worldview-postgres-1 pg_dumpall -U postgres | gzip > /opt/backups/worldview-$(date +\%Y\%m\%d).sql.gz
15 3 * * * find /opt/backups -name "worldview-*.sql.gz" -mtime +7 -delete
30 3 * * * mc mirror --overwrite prod-minio/worldview-bronze b2/worldview-prod-bronze
```

**RTO**: < 2 hours | **RPO**: < 24 hours

---

## 12. Runbooks

### Platform Won't Start

**Symptom**: `make dev` hangs or containers fail to become healthy.

**Diagnosis**:
```bash
make dev-ps                          # check which containers are unhealthy
docker compose -f infra/compose/docker-compose.yml logs postgres | tail -30
docker compose -f infra/compose/docker-compose.yml logs kafka | tail -30
docker compose -f infra/compose/docker-compose.yml logs gliner-server | tail -20
```

**Common causes and fixes**:

| Cause | Fix |
|-------|-----|
| Port already in use | `lsof -ti :<PORT> \| xargs kill -9` then retry |
| Kafka not ready (takes ~15s) | Wait longer; check `docker logs worldview-kafka-1 \| grep "started"` |
| GLiNER downloading model (up to 10 min on slow connection) | Wait — health check has 600s start_period |
| Ollama downloading models | Wait — `docker logs worldview-ollama-init-1` shows progress |
| Docker disk space full | `docker system prune -f`; free at least 15 GB |
| Postgres volume corruption | `make dev-reset` (destroys data) then `make dev && make seed` |
| api-gateway unhealthy before backends | Backends wait for `api-gateway:service_healthy`; check api-gateway logs first |

---

### Service Crashes on Startup

**Symptom**: A service container shows as `Exited` or stuck in restart loop.

**Diagnosis**:
```bash
docker logs worldview-<service>-1 --tail=50
# Look for: ImportError, ValidationError, ConnectionRefused, JWKS fetch failed
```

**Common causes**:

| Error | Cause | Fix |
|-------|-------|-----|
| `ModuleNotFoundError` | Missing lib in Docker image | Rebuild: `docker compose ... build --no-cache <service>` |
| `pydantic_settings ValidationError` | Missing required env var | Check `services/<svc>/configs/docker.env` — add missing var |
| `JWKS fetch failed` | api-gateway not ready when service started | Ensure `api-gateway: condition: service_healthy` in depends_on |
| `alembic: target database is not up to date` | Migration container failed | Check `docker logs worldview-<svc>-migrate-1` |
| `ConnectionRefused localhost:5432` | Service using localhost instead of postgres hostname | Check DATABASE_URL in docker.env — must use `postgres:5432` |

---

### Kafka Consumer Lag Growing

**Symptom**: Messages accumulate on a topic; consumer group offset falls behind.

**Diagnosis**:
```bash
# Check lag for all groups:
docker exec worldview-kafka-1 kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --all-groups

# Check if the consumer is running:
docker ps | grep nlp-pipeline-article-consumer

# Check consumer logs for errors:
docker logs worldview-nlp-pipeline-article-consumer-1 --tail=100
```

**Common causes**:

| Cause | Fix |
|-------|-----|
| Consumer container not running | `docker compose ... up -d <consumer>` |
| Consumer crashed in processing loop | Check logs for `dead_letter` or `Exception`; fix the error; container auto-restarts |
| Upstream service (GLiNER/Ollama) too slow | Check GLiNER latency; consider GPU passthrough |
| Dead-letter accumulation | `open http://localhost:8092` → check `*.dead-letter.*` topics for poison messages |
| Backpressure from DB | Check Postgres connection pool stats in Grafana |

---

### Database Migration Failure

**Symptom**: Migration container exits non-zero; service won't start.

**Diagnosis**:
```bash
docker logs worldview-<service>-migrate-1
# Look for: "column already exists", "relation already exists", "could not connect"
```

**Common causes**:

| Cause | Fix |
|-------|-----|
| Postgres not ready | Migration ran before healthcheck passed; retry: `docker compose ... up -d <svc>-migrate` |
| Conflicting migration state | `alembic current` inside the container; may need `alembic stamp head` for a fresh DB |
| S6/S7 running own Alembic | These must set `ALEMBIC_ENABLED=false` — only `intelligence-migrations` owns `intelligence_db` DDL |
| Forward-incompatible migration | Check for column removals or renames without defaults (violates R11) |

---

### GLiNER Container OOM (Out of Memory)

**Symptom**: `gliner-server` exits with error code 137 (OOM killed).

**Cause**: GLiNER (DeBERTa-large) uses ~2–3 GB RAM on CPU. If the Docker host has under 8 GB free, the container is OOM-killed under load.

**Fixes**:

```bash
# Option 1: Add swap (Hetzner bootstrap script does this automatically — 4 GB)
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile

# Option 2: Reduce NLP batch size (env var in nlp-pipeline docker.env)
NLP_PIPELINE_NER_BATCH_SIZE=5   # default: 20

# Option 3: Use GPU passthrough (uncomment in docker-compose.yml)
# deploy.resources.reservations.devices → NVIDIA GPU

# Option 4: Increase container memory limit (docker-compose.yml)
# deploy.resources.limits.memory: 4g
```

---

### Dead-Letter Topics Growing

**Symptom**: Messages accumulate in `*.dead-letter.v1` topics without being processed.

**Investigation**:
```bash
# Open Kafka UI and inspect messages in the dead-letter topic:
open http://localhost:8092
# Navigate to: Topics → kg.dead-letter.v1 → Messages

# Or use CLI to consume a few messages:
docker exec worldview-kafka-1 kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic kg.dead-letter.v1 \
  --from-beginning \
  --max-messages 5
```

Dead-letter messages include the original event payload plus an `error_reason` field.
Fix the root cause (usually a code bug or missing data), then replay the events by
re-consuming from the dead-letter topic with a corrected consumer.

---

### High Memory on NLP / KG Containers

**Symptom**: nlp-pipeline or knowledge-graph containers use >4 GB RAM.

**Investigation**:
```bash
docker stats worldview-nlp-pipeline-1 worldview-knowledge-graph-1
```

**Common causes**:
- Python asyncpg connection pool too large (default usually fine)
- Embedding batch too large (reduce `NLP_PIPELINE_EMBEDDING_BATCH_SIZE`)
- SQLAlchemy session not closed (check for missing `async with uow:` blocks)
- Memory leak in a long-running worker

Restart the affected worker container to recover:
```bash
docker compose -f infra/compose/docker-compose.yml restart nlp-pipeline-article-consumer
```

---

### Certificate Issues (Production)

**Symptom**: HTTPS not working; Traefik logs show ACME errors.

```bash
docker logs worldview-traefik-1 2>&1 | grep -i "acme\|certificate\|error"
```

| Error | Fix |
|-------|-----|
| `DNS not propagated` | Wait for DNS TTL; check `dig A ${DOMAIN}` returns server IP |
| `Port 80 blocked` | Check UFW: `ufw allow 80/tcp` |
| `Rate limited` | Wait up to 7 days or use staging CA (see `infra/gitops/docs/disaster-recovery.md`) |
| `certificate stored but invalid` | Delete `traefik_letsencrypt` volume and restart (loses existing cert — use staging first) |

---

*See also*:
- `docs/workflows/local-dev.md` — detailed local development guide
- `infra/gitops/docs/hetzner-setup.md` — first-time server provisioning
- `infra/gitops/docs/production-deployment.md` — production deployment runbook
- `infra/gitops/docs/disaster-recovery.md` — backup and recovery procedures
- `infra/zitadel/README.md` — Zitadel OIDC setup (all three options)
- `docs/runbooks/debugging-guide.md` — debugging individual service failures
- `docs/BUG_PATTERNS.md` — known failure patterns and fixes
