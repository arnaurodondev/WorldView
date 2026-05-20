# AGENTS.md — AI Agent Operating Guide

> **Scope**: Instructions for any AI coding agent (Copilot, Claude, Cursor, etc.)
> working in this repository. Read this before writing any code.

---

## 1. Repository Overview

This is a **Python + TypeScript monorepo** for a thesis-grade market intelligence platform.
It consists of 10 microservices (S1–S10) + intelligence-migrations, 1 frontend web application,
6 shared Python libraries, and supporting infrastructure.

```
worldview/
├── services/        # 10 FastAPI microservices (S1–S10) + intelligence-migrations (DDL owner for intelligence_db)
├── apps/
│   └── worldview-web/    # Next.js 15 App Router + shadcn/ui + TypeScript web application
├── libs/            # 8 shared Python packages (messaging, storage, contracts, observability, common, ml-clients, prompts, tools)
├── infra/           # Docker Compose, Kafka schemas, Postgres init, MinIO init
├── scripts/         # Bootstrap, lint, test, schema generation scripts
├── docs/            # All documentation (MASTER_PLAN, per-service, per-lib, workflows, ui)
└── .github/         # CI workflows
```

## 1b. Tool Usage (Claude Code Agents)

**NEVER use Bash commands when a dedicated tool exists.** This repository path contains spaces (`Final Thesis`), which causes issues with shell escaping. Use built-in tools instead:

| Task | Use This | NOT This |
|------|----------|----------|
| Find files by pattern | `Glob` tool | `find`, `ls` |
| Search file contents | `Grep` tool | `grep`, `rg` |
| Read file contents | `Read` tool | `cat`, `head`, `tail` |
| Edit files | `Edit` tool | `sed`, `awk` |
| Create files | `Write` tool | `echo >`, `cat <<EOF` |

Only use Bash for commands that have no dedicated tool equivalent (e.g., `pytest`, `ruff`, `mypy`, `git`, `docker compose`).

---

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
- **Package manager**: pnpm (exact versions, no `^`; `pnpm audit` must show 0 CVEs)
- **Framework**: Next.js 15 (App Router) — **not** Vite or CRA
- **UI library**: shadcn/ui (Radix UI primitives + Tailwind CSS) — **only** shadcn, no other component library
- **Language**: TypeScript strict mode (no `any`)
- **Data fetching**: TanStack Query v5 (no `useState+useEffect` for server state)
- **Theme**: Dark mode only (`class="dark"` on `<html>` permanently)
- **Test framework**: Vitest (unit) + Playwright (E2E)
- **Linter**: ESLint 9 + Prettier
- **Design canvas**: pencil.dev (via MCP) — see `/design-ui` skill
- **Design system**: `docs/ui/DESIGN_SYSTEM.md` — read before any UI work

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
- [ ] **Read `docs/BUG_PATTERNS.md`** — scan the index for categories
      matching your task. If any pattern applies, read the full entry before writing code.
- [ ] Define a task-scoped `write_paths` list and avoid edits outside it
- [ ] Define task-scoped validation commands (targeted pytest + changed-path ruff + changed-package mypy)

## 4. After You Code — Checklist

- [ ] **Tests**: Add or update tests (unit + integration) for every behavior change
- [ ] **Docs**: Update `docs/services/<service>.md` if you changed API, events, or schema
- [ ] **Schema compatibility**: If you modified an Avro schema, ensure it's forward-compatible
        (add fields with defaults; never remove or rename fields)
- [ ] **Task-scoped quality gates first**: run targeted pytest + changed-path `ruff check` + changed-package `mypy`; fix all failures immediately
- [ ] **Lint + Type check (broad)**: Run `scripts/lint.sh` at wave/final handoff boundary
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
8. **No deferred quality debt** — do not leave ruff/mypy/test failures for a later pass
9. **No done-state without green gates** — a task is not complete unless its required checks pass
10. **No unbounded exploration** — if scope is known, begin implementation after focused reads

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

# Copy dev env files from worldview-gitops (first-time setup)
# (worldview-gitops must be cloned alongside this repo)
../worldview-gitops/scripts/setup-dev.sh

# ── CI gate (fast: lint + typecheck + unit tests) ─────────────────────────────
make qa

# ── Linting and type checking ─────────────────────────────────────────────────
make lint         # ruff check + ruff format --check
make typecheck    # mypy for all services and libs

# ── Testing ───────────────────────────────────────────────────────────────────
make test-unit                        # All unit + contract tests (no infra)
make test-unit SERVICE=portfolio      # Unit tests for a single service
make test-e2e                         # Full E2E suite (starts compose)
make test-e2e SERVICE=portfolio       # E2E tests for a single service
make test-arch                        # Architecture/standards compliance

# ── Dev environment ───────────────────────────────────────────────────────────
make dev          # Start full dev stack (all services, MailHog, pgweb, kafka-ui, MinIO)
make dev-down     # Stop dev stack
make dev-reset    # Stop + wipe all volumes (clean reset)
make dev-logs     # Follow logs for all services
make dev-ps       # Show container health status
make dev-rebuild  # Rebuild all images and restart
make seed         # Load sample data (instruments, entities, articles)

# ── Observability (run AFTER make dev) ────────────────────────────────────────
make monitoring        # Start Prometheus + Grafana + Loki + Tempo
make monitoring-down   # Stop monitoring stack

# ── Avro schemas ──────────────────────────────────────────────────────────────
./scripts/gen-contracts.sh           # Generate/validate Avro schemas

# ── Run a specific service locally (outside compose) ─────────────────────────
cd services/portfolio && make run
```

Full test reference: `docs/testing/TEST_GUIDE.md`

## 8. Service-Specific Entry Points

> Ports are the **host-side** mapped port from docker-compose. Internal container port is typically 8000 unless noted.

| Service | ID | Host Port | Internal Port | Run Command |
|---------|----|-----------|---------------|-------------|
| Portfolio | S1 | 8001 | 8000 | `make run` |
| Market Ingestion | S2 | 8002 | 8002 | `make run` |
| Market Data | S3 | 8003 | 8003 | `make run` |
| Content Ingestion | S4 | 8004 | 8000 | `make run` |
| Content Store | S5 | 8005 | 8005 | `make run` |
| NLP Pipeline | S6 | 8006 | 8006 | `make run` |
| Knowledge Graph | S7 | 8007 | 8007 | `make run` |
| RAG/Chat | S8 | 8008 | 8008 | `make run` |
| API Gateway | S9 | 8000 | 8000 | `make run` |
| Alert | S10 | 8010 | 8010 | `make run` |
| intelligence-migrations | — | none | none | one-shot init container |

Dev tool UIs (started by `make dev`):

| Tool | URL | Purpose |
|------|-----|---------|
| Frontend | http://localhost:3001 | worldview-web Next.js app |
| API Gateway | http://localhost:8000 | S9 REST entrypoint |
| MailHog | http://localhost:8025 | Email preview (alert emails) |
| pgweb | http://localhost:8091 | Postgres browser |
| Kafka UI | http://localhost:8092 | Topic/consumer group browser (dev only, `make dev`) |
| MinIO Console | http://localhost:7481 | Object storage browser |
| Grafana | http://localhost:3000 | Metrics dashboard (after `make monitoring`) |
| Prometheus | http://localhost:9090 | Metrics scrape (after `make monitoring`) |

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
