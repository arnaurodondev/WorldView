# Local Development Workflow

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11+ | `brew install python@3.12` |
| Node.js | 20+ | `brew install node@20` |
| pnpm | 9+ | `corepack enable && corepack prepare pnpm@9 --activate` |
| Docker & Compose | 27+ | Docker Desktop or `brew install docker` |
| Make | any | ships with macOS |
| Hatch | 1.12+ | `python3 -m pip install hatch` |
| pre-commit | 3+ | `python3 -m pip install pre-commit` |

---

## Quick Start (< 10 minutes)

```bash
# 1. Clone
git clone <repo-url> worldview && cd worldview

# 2. Bootstrap (installs venvs, hooks, checks Docker)
./scripts/bootstrap.sh

# 3. Start infrastructure
docker compose --profile infra up -d

# 4. Run init jobs (create DBs, topics, register schemas, run migrations)
docker compose --profile init up

# 5. Start a single service (e.g. portfolio)
cd services/portfolio
make run          # uvicorn on port 8001
```

---

## UV Workflow (Recommended)

Use one root environment for repository tooling (`pre-commit`, helper scripts, lint/test commands), and keep optional per-lib/per-service environments for isolated development.

```bash
# From repo root: create/sync tooling environment
uv sync --group dev

# Install hooks using the root tooling environment
uv run pre-commit install

# Run repo scripts through uv
uv run ./scripts/lint.sh
uv run ./scripts/test-libs.sh --integration --lib storage

# Optional: run service-local commands in that service directory
cd services/portfolio && uv sync && uv run make test
```

Notes:
- Root `uv sync` is configured as non-package at monorepo root; it installs tooling but does not build a `worldview` wheel.
- If you use separate venvs per service/library, keep doing that for day-to-day coding; use root `uv run ...` for shared scripts.

---

## Common Tasks

### Running a Service

```bash
cd services/<service-name>
make run                  # Start with hot-reload
make test                 # Run unit tests
make test-integration     # Run integration tests (requires infra)
make lint                 # Ruff check + mypy
make migrate              # Alembic upgrade head
make migrate-new MSG="..."  # Create new Alembic revision
```

### Running All Tests

```bash
# From repo root
./scripts/test.sh              # All unit tests (fast)
./scripts/test.sh --integration # + integration tests (needs infra)
```

### Linting

```bash
./scripts/lint.sh    # Ruff + mypy across all packages
```

---

## Docker Compose Profiles

| Profile | Services | When |
|---------|----------|------|
| `infra` | postgres, kafka, schema-registry, minio, valkey, ollama | Always — start first |
| `init` | DB init, topic creation, schema registration, Alembic migrations | Once after infra starts |
| `runtime` | All 9 microservices + frontend | Optional — or run services locally |
| `tools` | kafka-ui, pgweb | Optional dev tools |

```bash
docker compose --profile infra --profile tools up -d   # Infra + dev tools
docker compose --profile runtime up -d                 # Run services in containers
```

---

## Port Map

| Service | Host Port |
|---------|-----------|
| S9 · API Gateway | 8000 |
| S1 · Portfolio | 8001 |
| S2 · Market Ingestion | 8002 |
| S3 · Market Data | 8003 |
| S4 · Content Ingestion | 8004 |
| S5 · Content Store | 8005 |
| S6 · NLP Pipeline | 8006 |
| S7 · Knowledge Graph | 8007 |
| S8 · RAG / Chat | 8008 |
| Frontend (dev) | 5173 |
| PostgreSQL | 5432 |
| Kafka | 9092 |
| Schema Registry | 8081 |
| MinIO API / Console | 7480 / 7481 |
| Valkey | 6379 |
| Ollama | 11434 |
| Kafka UI | 8090 |
| pgweb | 8091 |

---

## Environment Variables

Each service reads from `configs/dev.local.env.example`. Copy to `.env`:

```bash
cp configs/dev.local.env.example configs/.env
```

Key variables are documented inline. Secrets (API keys) go in `.env` only —
never commit them.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Kafka not ready | Wait 15s after `docker compose up`; check `docker compose logs kafka` |
| MinIO permission denied | Ensure `minioadmin/minioadmin` creds match `.env` |
| Alembic "target database is not up to date" | Run `make migrate` before starting the service |
| Port conflict | Change host ports in `docker-compose.yml` or stop conflicting processes |
| `hatch env create` fails | Delete `.venv` / hatch env and retry |
