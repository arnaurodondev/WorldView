# AGENTS.md — AI Agent Operating Guide

> **Scope**: Instructions for any AI coding agent (Copilot, Claude, Cursor, etc.)
> working in this repository. Read this before writing any code.

---

## 1. Repository Overview

This is a **Python + TypeScript monorepo** for a thesis-grade market intelligence platform.
It consists of 9 microservices (S1–S9), 1 frontend web application, 5 shared Python libraries,
and supporting infrastructure.

```
worldview/
├── services/        # 9 FastAPI microservices (S1–S9, each with src/, tests/, alembic/)
├── apps/
│   └── frontend/    # React + Vite + TypeScript web application
├── libs/            # 5 shared Python packages (messaging, storage, contracts, observability, common)
├── infra/           # Docker Compose, Kafka schemas, Postgres init, MinIO init
├── scripts/         # Bootstrap, lint, test, schema generation scripts
├── docs/            # All documentation (MASTER_PLAN, per-service, per-lib, workflows)
└── .github/         # CI workflows
```

## 2. Coding Standards

### Python
- **Version**: 3.11+ (target 3.12)
- **Formatter/Linter**: ruff (config in `ruff.toml`)
- **Type checker**: mypy strict mode (config in `mypy.ini`)
- **Test framework**: pytest with asyncio_mode=auto
- **Packaging**: Hatch (pyproject.toml per service/lib)
- **Async**: use `async`/`await` throughout; SQLAlchemy async sessions
- **Logging**: `structlog` only — never use `print()` or stdlib `logging` directly

### Naming Conventions
- **Services**: `services/<name>/` → Python package `<name>` (e.g., `services/portfolio/src/portfolio/`)
- **Libs**: `libs/<name>/` → Python package `<name>` (e.g., `libs/messaging/src/messaging/`)
- **Kafka topics**: `<domain>.<entity>.<verb_past>` (e.g., `market.dataset.fetched`)
- **Avro schemas**: `<event_type>.avsc` in `infra/kafka/schemas/`
- **Database names**: `<service>_db` (e.g., `portfolio_db`, `content_db`)
- **Env vars**: `UPPER_SNAKE_CASE` with service prefix (e.g., `MARKET_DATA_DB_URL`)
- **MinIO keys**: `<service>/<domain>/<resource_id>/<artifact>/<version>.<ext>`
- **Valkey cache keys**: `<scope>:<version>:<resource>:<id>[:<qualifier>]`

### TypeScript / Frontend
- **Runtime**: Node.js 20+
- **Package manager**: pnpm 9+
- **Bundler**: Vite 5
- **Framework**: React 18 with TypeScript strict mode
- **Data fetching**: TanStack Query
- **Test framework**: Vitest (unit) + Playwright (E2E)
- **Linter**: ESLint 9 + Prettier

### Architecture Pattern
Every service follows **Clean/Hexagonal Architecture**:
```
src/<service>/
├── api/            # FastAPI routers, Pydantic schemas, dependencies
├── application/    # Use cases and port interfaces
│   ├── ports/      # Abstract repository/adapter interfaces
│   └── use_cases/  # Business logic orchestration
├── domain/         # Pure domain model (entities, value objects, events, errors)
│   ├── entities/
│   ├── enums.py
│   ├── events.py
│   ├── errors.py
│   └── value_objects.py
└── infrastructure/ # Adapters (DB, Kafka, S3, external APIs)
    ├── config/
    ├── db/
    └── messaging/
```

## 3. Before You Code — Checklist

- [ ] Read `docs/MASTER_PLAN.md` to understand overall architecture
- [ ] Read the relevant `docs/services/<service>.md` for the service you're changing
- [ ] Read relevant `docs/libs/<lib>.md` if touching a shared library
- [ ] Check `docs/architecture/decisions/` for ADRs that may constrain your design
- [ ] Search for existing patterns in `libs/` before creating new utilities
- [ ] Verify the Avro schemas in `infra/kafka/schemas/` if your change involves events
- [ ] **Read `docs/ai-interactions/BUG_PATTERNS.md`** — scan the index for categories
      matching your task. If any pattern applies, read the full entry before writing code.

## 4. After You Code — Checklist

- [ ] **Tests**: Add or update tests (unit + integration) for every behavior change
- [ ] **Docs**: Update `docs/services/<service>.md` if you changed API, events, or schema
- [ ] **Schema compatibility**: If you modified an Avro schema, ensure it's forward-compatible
        (add fields with defaults; never remove or rename fields)
- [ ] **Lint + Type check**: Run `scripts/lint.sh` — must pass with zero errors
- [ ] **Migrations**: If you changed a DB model, create an Alembic migration
- [ ] **Env vars**: If you added a new config var, update `configs/dev.local.env.example`
- [ ] **MASTER_PLAN.md**: If you changed system-wide behavior, update the master doc

## 5. Hard Rules

See `RULES.md` for the complete list. Key ones:

1. **No cross-service database access** — services communicate via Kafka events or REST APIs
2. **Outbox pattern for dual writes** — never write to DB and Kafka in separate transactions
3. **Idempotent consumers** — every Kafka consumer must handle duplicate events
4. **Claim-check for large payloads** — Kafka events carry MinIO pointers, not data
5. **UUIDv7 for all entity IDs** — time-sortable, globally unique
6. **UTC-only timestamps** — never use naive datetimes
7. **No secrets in code** — use env vars or secret managers

## 6. How to Propose Architectural Changes

1. Create an ADR using `docs/architecture/decisions/ADR_TEMPLATE.md`
2. Name it `NNNN-<short-title>.md` (next sequential number)
3. Include: context, decision, consequences, alternatives considered
4. Reference the ADR in your PR description
5. ADR must be reviewed and merged before implementation begins

## 7. How to Use Tools and Scripts

```bash
# Bootstrap local dev environment
./scripts/bootstrap.sh

# Lint all code (ruff + mypy)
./scripts/lint.sh

# Run all tests
./scripts/test.sh

# Run tests for a specific service
./scripts/test.sh services/portfolio

# Generate/validate Avro schemas
./scripts/gen-contracts.sh

# Start infrastructure (Postgres, Kafka, MinIO, Valkey)
docker compose -f infra/compose/docker-compose.yml --profile infra up -d

# Run a specific service locally
cd services/portfolio && make run
```

## 8. Service-Specific Entry Points

| Service | API Port | Module | Run Command |
|---------|----------|--------|-------------|
| Portfolio | 8000 | `portfolio.api.main:app` | `make run` |
| Market Ingestion | 8001 | `app.api.main:app` | `make run` |
| Market Data | 8003 | `market_data.main:app` | `make run` |
| Content | 8004 | `content.api.main:app` | `make run` |
| Intelligence | 8005 | `intelligence.api.main:app` | `make run` |
| RAG/Chat | 8006 | `rag.api.main:app` | `make run` |
| API Gateway | 8080 | `gateway.main:app` | `make run` |

## 9. Event Envelope Standard

All Kafka events MUST include these envelope fields:

```json
{
  "event_id": "UUIDv7",
  "event_type": "domain.entity.verb_past",
  "schema_version": 1,
  "occurred_at": "ISO-8601 UTC timestamp",
  "correlation_id": "UUIDv7 (optional, for tracing)",
  "causation_id": "UUIDv7 (optional, event that caused this)"
}
```

## 10. When in Doubt

1. Prefer **simplicity** over cleverness
2. Prefer **explicit** over implicit
3. Prefer **tested patterns** from existing services over novel approaches
4. Ask: "Will this make the thesis demo more reliable?"
5. Check if WorldMonitor solved the same problem — we borrow their patterns
