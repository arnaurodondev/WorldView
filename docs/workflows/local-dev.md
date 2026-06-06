# Local Development Workflow

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.12+ | `brew install python@3.12` or `pyenv install 3.12.7` |
| Node.js | 20+ | `brew install node@20` |
| pnpm | 10+ | `corepack enable && corepack prepare pnpm@10 --activate` |
| Docker & Compose | 27+ | Docker Desktop or `brew install docker` |
| Make | any | Ships with macOS |
| Hatch | 1.12+ | `python3 -m pip install hatch` |
| pre-commit | 3+ | `python3 -m pip install pre-commit` |

---

## Quick Start (< 10 minutes)

```bash
# 1. Clone
git clone <repo-url> worldview && cd worldview

# 2. Bootstrap (installs venvs, hooks, checks Docker)
./scripts/bootstrap.sh

# 3. Fetch secrets (API keys, OIDC credentials from private worldview-config repo)
make fetch-secrets

# 4. Start the full platform (infra + services + dev tools)
make dev

# 5. Load sample data (first launch only)
make seed

# 6. Open http://localhost:3001 → click "Dev Login" (no Zitadel needed)
```

> **Note**: `make dev` uses the dev overlay (`docker-compose.dev.yml`) which includes
> MailHog, pgweb, and kafka-ui for local development. See [Dev Tools](#dev-tools) below.

---

## Launching the Entire Platform

### Option A: `make dev` (simplest)

```bash
make dev            # Start infra + services + dev tools (MailHog, pgweb, kafka-ui)
make seed           # Load sample data (first launch only)
make dev-ps         # Check container status
make dev-logs       # Tail all logs
make dev-down       # Stop everything
make dev-reset      # Stop + remove volumes (clean slate)
make dev-rebuild    # Rebuild all images without cache and restart
```

**Result**: All services running at their default ports (see port map below), frontend at http://localhost:3001, dev tools at :8025 (MailHog), :8091 (pgweb), :8090 (kafka-ui).

### Option B: Infrastructure in Docker + services locally (recommended for hot-reload)

> `make dev` is the simplest path. Use Option B when you need hot-reload on Python or frontend code.

```bash
# 1. Infrastructure only (Postgres, Kafka, MinIO, Valkey, Ollama)
docker compose -f infra/compose/docker-compose.yml --profile infra up -d

# 2. Start the services you need, each in a separate terminal:
cd services/api-gateway && make run     # :8000 — always needed for frontend
cd services/portfolio && make run       # :8001
cd services/market-data && make run     # :8003
# ... add more as needed

# 3. Frontend with hot-reload (not containerized — faster iteration)
cd apps/worldview-web && pnpm dev       # :3001
```

**Advantage**: Hot-reload on Python + frontend code changes, faster iteration, less Docker overhead.

---

## Developing a Single Service

### Setup

```bash
cd services/<service-name>

# Copy environment config
cp configs/dev.local.env.example configs/.env
# Edit configs/.env if needed (most defaults work for local dev)
```

### Daily Commands

| Command | Purpose |
|---------|---------|
| `make run` | Start with hot-reload (uvicorn) |
| `make test` | Run unit tests |
| `make test-integration` | Run integration tests (requires infra running) |
| `make lint` | Ruff check + mypy |
| `make migrate` | Alembic upgrade head |
| `make migrate-new MSG="add X"` | Create new Alembic revision |

### Service Dependencies

Most services need at minimum:
- **PostgreSQL** (port 5432) — for their database
- **Kafka** (port 9092) — for event publishing/consuming

Some services have additional dependencies:
- **MinIO** (port 7480) — S2, S4, S5, S6, S8 (object storage)
- **Valkey** (port 6379) — S9 (caching, rate limiting, PKCE state)
- **Ollama** (port 11434) — S6, S8 (local LLM inference)
- **Schema Registry** (port 8081) — any service producing Avro events

All of these are started by `make dev` (or `docker compose --profile infra up -d`).

> **Ollama + embedding-retry-worker (DP-F005)**: `nlp-pipeline-embedding-retry-worker` no longer declares a hard `depends_on: ollama` because the primary embedding path is DeepInfra (`NLP_PIPELINE_EMBEDDING_PROVIDER=deepinfra`). If you unset `NLP_PIPELINE_EMBEDDING_API_KEY` for offline local dev, start Ollama manually (`docker compose --profile infra up -d ollama ollama-init`) before this worker, otherwise its fallback embedding path will fail.

### Service Port Map

| Service | Port | Database |
|---------|------|----------|
| S1 Portfolio | 8001 | portfolio_db |
| S2 Market Ingestion | 8002 | ingestion_db |
| S3 Market Data | 8003 | market_data_db |
| S4 Content Ingestion | 8004 | content_ingestion_db |
| S5 Content Store | 8005 | content_store_db |
| S6 NLP Pipeline | 8006 | nlp_db + intelligence_db (shared) |
| S7 Knowledge Graph | 8007 | kg_db + intelligence_db (shared) |
| S8 RAG / Chat | 8008 | rag_db |
| S9 API Gateway | 8000 | None (stateless) |
| S10 Alert | 8010 | alert_db |

### Infrastructure Ports

| Service | Port |
|---------|------|
| PostgreSQL | 5432 |
| Kafka | 9092 |
| Schema Registry | 8081 |
| MinIO API / Console | 7480 / 7481 |
| Valkey | 6379 |
| Ollama | 11434 |
| Kafka UI (dev tool) | 8092 |
| pgweb (dev tool) | 8091 |
| MailHog SMTP / UI (dev tool) | 1025 / 8025 |

---

## Frontend Development

### worldview-web (Next.js 15 — canonical)

```bash
cd apps/worldview-web
pnpm install
cp .env.example .env.local
pnpm dev                    # → http://localhost:3001
```

**Requires**: S9 API Gateway running on :8000 (all API calls proxy through it).

**Dev Login**: When Zitadel is not configured (the default for local dev), the login page automatically shows a "Dev Login" button. Clicking it calls `POST /v1/auth/dev-login` on S9, which returns a valid internal JWT for a demo user without requiring any OIDC setup. Run `make seed` first to populate the demo user and sample data.

| Command | Purpose |
|---------|---------|
| `pnpm dev` | Dev server (http://localhost:3001) |
| `pnpm build` | Production build |
| `pnpm test` | Vitest unit tests |
| `pnpm test:coverage` | Tests with coverage report |
| `pnpm test:e2e` | Playwright E2E tests |
| `pnpm lint` | ESLint |
| `pnpm typecheck` | TypeScript check |

---

## Docker Compose Profiles

All compose files live under `infra/compose/`. The primary file is `docker-compose.yml`, with overlays for dev and production.

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Base: infra + all services + frontend |
| `docker-compose.dev.yml` | Dev overlay: adds MailHog, pgweb, kafka-ui |
| `docker-compose.prod.yml` | Production overlay |
| `docker-compose.test.yml` | Test infrastructure |

| Profile | Services | When to Use |
|---------|----------|-------------|
| `infra` | All infra + all 10 microservices + worldview-web frontend | Full platform |
| `monitoring` | Prometheus, Grafana, Loki, Tempo, Alloy, Alertmanager | Observability stack |
| `all` | Everything (infra + monitoring + all services + frontend) | Full system |

```bash
# Recommended: use make targets (they handle -f and overlay flags)
make dev              # Start full platform + dev tools
make dev-down         # Stop everything
make dev-logs         # Tail all logs
make dev-ps           # Container status

# Manual patterns (always specify -f path)
docker compose -f infra/compose/docker-compose.yml --profile infra up -d            # Full platform
docker compose -f infra/compose/docker-compose.yml --profile infra --profile monitoring up -d  # + observability
docker compose -f infra/compose/docker-compose.yml --profile infra down             # Stop everything
docker compose -f infra/compose/docker-compose.yml logs -f portfolio                # Tail one service
docker compose -f infra/compose/docker-compose.yml logs -f worldview-web            # Tail frontend
```

---

## Running Tests

### Quick validation (no infrastructure needed)

```bash
# From repo root
./scripts/lint.sh              # Ruff + mypy across all packages
./scripts/test.sh              # Unit tests across all packages
make qa                        # CI gate: lint + typecheck + unit

# Single service
cd services/portfolio && make test    # Unit tests only
cd services/portfolio && make lint    # Ruff + mypy
```

### With infrastructure (integration tests)

```bash
# Start test infrastructure
docker compose --profile infra up -d

# Run integration tests
./scripts/test.sh --integration

# Single service integration tests
cd services/portfolio && make test-integration
```

### Full platform tests

```bash
# Start everything
docker compose --profile infra up -d
docker compose --profile init up
docker compose --profile runtime up -d

# Run full suite
./scripts/test-full.sh                 # lint + unit + integration + E2E
make test-all                          # Alternative via Make

# Single service E2E
make test-e2e SERVICE=portfolio
```

### Frontend tests

```bash
cd apps/worldview-web
pnpm test                  # Vitest unit
pnpm test:coverage         # + coverage
pnpm test:e2e              # Playwright (auto-starts dev server)
```

### Test markers (pytest)

| Marker | What | Infra needed |
|--------|------|-------------|
| `@pytest.mark.unit` | Fast, isolated tests | No |
| `@pytest.mark.integration` | DB/Kafka/MinIO tests | Yes |
| `@pytest.mark.contract` | Avro schema compatibility | No |
| `@pytest.mark.e2e` | Full request path | Full stack |
| `@pytest.mark.slow` | Long-running tests | Varies |

```bash
# Run specific marker
cd services/portfolio
python -m pytest tests/ -m "unit" -v
python -m pytest tests/ -m "integration" -v
python -m pytest tests/ -m "contract" -v
```

---

## Environment Variables

Each service reads from `configs/dev.local.env.example`. Copy to `.env`:

```bash
cd services/<service-name>
cp configs/dev.local.env.example configs/.env
```

Key patterns:
- **`<SERVICE>_DATABASE_URL`**: PostgreSQL connection string (`postgresql+asyncpg://postgres:postgres@localhost:5432/<db>`)
- **`<SERVICE>_KAFKA_BOOTSTRAP_SERVERS`**: Kafka broker (`localhost:9092`)
- **`<SERVICE>_SCHEMA_REGISTRY_URL`**: Schema Registry (`http://localhost:8081`)
- **`<SERVICE>_STORAGE_ENDPOINT`**: MinIO (`http://localhost:7480`)
- **`<SERVICE>_VALKEY_URL`**: Valkey (`redis://localhost:6379/0`)
- **`<SERVICE>_LOG_LEVEL`**: Logging (`DEBUG` for dev, `INFO` for prod)

**Secrets** (API keys, OIDC credentials) go in `.env` only — never committed. Run `make fetch-secrets` to pull credentials from the private `worldview-config` GitHub repo. See `docs/runbooks/secrets-management.md` for details.

### Generating Auth Keys

For S9 API Gateway (OIDC + internal JWT):

```bash
# Generate RS256 keypair for internal JWT
./scripts/generate-internal-keypair.sh

# Output goes to stdout — copy into configs/.env:
# API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY=<PEM>
# API_GATEWAY_INTERNAL_JWT_PUBLIC_KEY=<PEM>
```

---

## Database Migrations

```bash
cd services/<service-name>

# Apply all pending migrations
make migrate

# Create a new migration
make migrate-new MSG="add user_preferences table"

# Check migration status
alembic history --verbose
alembic current
```

**Important**: S6 (NLP Pipeline) and S7 (Knowledge Graph) share `intelligence_db`. Only the `intelligence-migrations` service owns DDL. S6/S7 set `ALEMBIC_ENABLED=false`.

---

## UV Workflow (Alternative)

Use one root environment for repository tooling and keep per-service environments for isolated development:

```bash
# From repo root: create/sync tooling environment
uv sync --group dev

# Install hooks using the root tooling environment
uv run pre-commit install

# Run repo scripts through uv
uv run ./scripts/lint.sh
uv run ./scripts/test-libs.sh --integration --lib storage

# Optional: service-local commands
cd services/portfolio && uv sync && uv run make test
```

---

## Observability (Local)

### Logs

Services use structlog JSON logging by default. For human-readable logs in development:

```bash
# Set in configs/.env
<SERVICE>_LOG_FORMAT=console    # instead of json
<SERVICE>_LOG_LEVEL=DEBUG
```

### Monitoring Stack (optional)

```bash
# Start Prometheus + Grafana + Loki + Tempo
docker compose --profile monitoring up -d

# Grafana: http://localhost:3000 (admin/admin)
# Pre-built dashboards: content-pipeline, kafka-pipeline, api-gateway, outbox-health
```

### Dev Tools

The dev overlay (`docker-compose.dev.yml`, started by `make dev`) includes three additional tools:

| Tool | URL | Purpose |
|------|-----|---------|
| **MailHog** | http://localhost:8025 | Captures all outbound email (SMTP on :1025). View alert emails, registration confirmations without a real mail server. |
| **pgweb** | http://localhost:8091 | Browser-based PostgreSQL client. Browse all 11 databases, run ad-hoc queries. |
| **Kafka UI** | http://localhost:8092 | Inspect topics, consumer groups, messages. Useful for debugging event pipelines. |

These tools are **not** included in the production overlay.

```bash
# If running Option B (hybrid), start dev tools manually:
docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.dev.yml up -d

# MinIO Console — browse object storage (always available with infra profile)
# http://localhost:7481 (minioadmin/minioadmin)
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Kafka not ready | Wait 15s after `docker compose up`; check `docker compose logs kafka` |
| MinIO permission denied | Ensure `minioadmin/minioadmin` creds match `.env` |
| Alembic "target database is not up to date" | Run `make migrate` before starting the service |
| Port conflict | Change host ports in `infra/compose/docker-compose.yml` or stop conflicting processes (`lsof -i :PORT`) |
| `hatch env create` fails | Delete `.venv` / hatch env and retry |
| Service can't connect to Postgres | Verify `docker compose --profile infra ps` shows postgres as "healthy" |
| Service can't connect to Kafka | Kafka needs ~15s to start; check `docker compose logs kafka` for "started" |
| Schema Registry errors | Run `docker compose --profile init up` to register schemas |
| S9 auth errors | Ensure OIDC vars are set; for dev without Zitadel, set `API_GATEWAY_OIDC_DISCOVERY_OPTIONAL=true` |
| Frontend shows blank page | Ensure S9 is running on :8000; check browser console for CORS/network errors |
| `pnpm install` fails | Check Node version (`node -v`, need 20+); try `pnpm store prune` |
| Python import errors | Run `./scripts/bootstrap.sh` to reinstall editable libs |
| pre-commit ruff conflict | Use ruff from `~/.cache/pre-commit/` (not uvx/venv); see BP-023 |
| Ollama model not found | Run `docker exec ollama ollama pull nomic-embed-text` |
| Tests fail with "event loop" | Use `asyncio.run()` not `get_event_loop().run_until_complete()`; see BP-133 |
| Helm/k3d issues | Check `docker info`; ensure Docker Desktop is running |

---

## Pre-Deployment Checklist (Before Hetzner / Production)

Production deployment uses Docker Compose + Traefik (not Kubernetes). See
`infra/gitops/docs/production-deployment.md` for the full first-deploy runbook.

### Tier 1 — Always Run (< 5 minutes)

```bash
make qa                                  # lint + typecheck + unit tests
```

### Tier 2 — Before First Deploy on Hetzner (< 15 minutes)

```bash
# Validate the merged production compose config locally (no containers started):
DOMAIN=worldview.example.com ACME_EMAIL=ops@example.com \
  docker compose \
    -f infra/compose/docker-compose.yml \
    -f infra/compose/docker-compose.prod.yml \
    --profile infra config > /dev/null && echo "Config valid"

# Confirm NEXT_PUBLIC_WS_BASE_URL will be wss:// in the merged config (BP-324):
DOMAIN=worldview.example.com ACME_EMAIL=ops@example.com \
  docker compose \
    -f infra/compose/docker-compose.yml \
    -f infra/compose/docker-compose.prod.yml \
    --profile infra config | grep NEXT_PUBLIC_WS_BASE_URL
# Expected: NEXT_PUBLIC_WS_BASE_URL: wss://ws.worldview.example.com
```

### Tier 3 — Post-Deploy Smoke Tests

Run from Hetzner server after `make prod` completes:

```bash
# From worldview-gitops (after cloning on server):
export DOMAIN=worldview.example.com
./scripts/verify-prod-health.sh

# Manual checks:
curl -I https://${DOMAIN}                # → 200
curl -I https://api.${DOMAIN}/v1/health  # → 200
curl -I http://${DOMAIN}                 # → 301 to https:// (Traefik redirect)

# Verify no infra ports are directly exposed (should all be empty):
ss -tlnp | grep -E "8000|5432|6379|9092"
```
