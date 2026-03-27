# CLAUDE.md — Claude Operating Guide

> **Purpose**: Primary entry point for Claude agents working in the worldview repository.
> Routes to the correct skill, context, and workflow for any task.

---

## Quick Start: Choose Your Workflow

| Task | Skill | Description |
|------|-------|-------------|
| **New feature/project** | `/prd` | Interactive PRD generation through discussion |
| **Break PRD into tasks** | `/plan` | Generate implementation plans with waves |
| **Implement a wave/change** | `/implement` | Full pipeline: code → test → validate → review → commit |
| **Review current changes** | `/review` | Structured code review with checklists and failure analysis |
| **Fix a known bug** | `/fix-bug` | Diagnose, fix, test, update bug patterns |
| **Deep investigation** | `/investigate` | Multi-hypothesis investigation for complex issues |
| **Write tests** | `/test-feature` | Design and implement comprehensive test coverage |
| **Full QA pass** | `/qa` | All test layers + architecture + lint + docs check |
| **Security review** | `/security-audit` | OWASP, multi-tenant, injection, secrets scan |
| **Refactoring** | `/refactor` | Safe behavior-preserving restructure |
| **Documentation audit** | `/docs-audit` | Find gaps, staleness, inconsistencies in docs |

**Always use a skill for non-trivial work.** Skills enforce the correct workflow, validation gates, and mandatory compounding updates.

---

## Context Loading: What to Read

### For any task, read:
1. **This file** — workflow rules below
2. **`services/<service>/.claude-context.md`** — per-service context (entities, topics, pitfalls, test commands)

### For deeper context (when needed):
3. `RULES.md` — 18 hard rules (MUST/NEVER)
4. `AGENTS.md` — coding standards, architecture patterns, shared libraries
5. `docs/PRODUCT_CONTEXT.md` — product vision, target users, journeys, constraints (for `/prd` and product discussions)
6. `docs/MASTER_PLAN.md` — full system architecture
7. `docs/services/<service>.md` — detailed service documentation
8. `docs/BUG_PATTERNS.md` — known failure patterns

### For review/quality work:
9. `.claude/review/checklists/REVIEW_CHECKLIST.md` — review checklist
10. `.claude/review/heuristics/HIGH_RISK_PATTERNS.md` — risk signal catalog
11. `.claude/review/protocols/PR_INVESTIGATION_PROTOCOL.md` — investigation protocol

---

## Hard Rules (Always Enforced)

These are non-negotiable. Hooks enforce several of them automatically.

1. **Small, focused diffs** — one logical change per edit; refactors separate from features
2. **Validate after every change** — ruff + mypy + targeted tests immediately (not deferred)
3. **Fix failures before continuing** — never proceed with lint/test/type errors
4. **Tests with every behavior change** — no code without tests; no deferred test writing
5. **Outbox pattern for dual writes** — never DB + Kafka in separate transactions
6. **UUIDv7 for all IDs** — `common.ids.new_uuid7()`, never `uuid.uuid4()`
7. **UTC-only timestamps** — `common.time.utc_now()`, never naive datetimes
8. **No secrets in code** — env vars via pydantic-settings
9. **No cross-service DB access** — use Kafka events or REST
10. **structlog only** — never stdlib logging
11. **Forward-compatible schemas** — add fields with defaults, never remove/rename
12. **Domain layer independence** — no infrastructure imports in domain layer
13. **Use shared libs** — `common`, `contracts`, `messaging`, `storage`, `observability`, `ml-clients`
14. **Frontend → S9 only** — frontend never talks to backend services directly
15. **Update docs** — every API/event/schema/config change must update docs

---

## Hooks (Automatic Enforcement)

These hooks fire automatically — you don't need to invoke them:

| Hook | Trigger | What It Does |
|------|---------|-------------|
| Pre-commit validation | Before `git commit` | Runs ruff + mypy + unit tests on changed files |
| Pre-PR checklist | Before `gh pr create` | Full lint + tests + architecture + schema + docs check |
| Post-edit validation | After editing `.py` files | Runs ruff + targeted tests for the edited service |
| Schema guard | After editing `.avsc` files | Validates Avro schema forward-compatibility |
| Migration guard | After editing entity/model files | Warns if Alembic migration is missing |
| Security scan | After editing/writing `.py` files | Scans for injection, secrets, unsafe patterns |

---

## Architecture Reference

```
worldview/
├── services/           # 10 FastAPI microservices (S1-S10) + intelligence-migrations
│   └── <service>/
│       ├── .claude-context.md    # ← Agent context (read this first!)
│       ├── src/<service>/
│       │   ├── api/              # FastAPI routers, Pydantic schemas
│       │   ├── application/      # Use cases, port interfaces
│       │   ├── domain/           # Entities, value objects, events, errors
│       │   └── infrastructure/   # DB adapters, Kafka, external APIs
│       ├── tests/                # unit, integration, contract, e2e
│       └── alembic/              # DB migrations
├── libs/               # 6 shared Python libraries
│   ├── common/         # IDs, time, constants
│   ├── contracts/      # Canonical Pydantic models, event envelopes
│   ├── messaging/      # Kafka, Avro, outbox, Valkey
│   ├── storage/        # S3/MinIO abstraction
│   ├── observability/  # structlog, metrics, tracing
│   └── ml-clients/     # ML model abstraction (embedding, NER, extraction)
├── apps/frontend/      # React + TypeScript + Vite (talks only to S9)
├── infra/              # Docker Compose, Kafka schemas, Postgres init
├── docs/               # MASTER_PLAN, service docs, lib docs, specs, plans
│   ├── specs/          # PRDs (generated by /prd)
│   ├── plans/          # Implementation plans (generated by /plan)
│   ├── audits/         # QA audits and cross-service reports
│   └── references/     # External API references (EODHD, etc.)
├── .claude/
│   ├── agents/         # 13 role-specific agent definitions
│   ├── skills/         # 11 workflow skills (/prd, /plan, /implement, /review, etc.)
│   ├── review/         # Code review framework (protocols, checklists, heuristics)
│   ├── evals/          # Evaluation framework, session logs, improvement loop
│   └── prompts/        # Reusable prompt templates
└── scripts/            # Bootstrap, lint, test, hooks
```

---

## Plan & Task Tracking

Active plans are tracked in `docs/plans/TRACKING.md`. The workflow:

```
/prd → docs/specs/<NNNN>.md → /plan → docs/plans/<NNNN>-plan.md → /implement (per wave)
```

Each plan file contains:
- Sub-plans (one per service/area)
- Waves within each sub-plan (3-6 tasks per wave)
- Task status tracking (pending → in-progress → done)
- Validation gates per wave

---

## Common Pitfalls

1. **Naive datetimes** → Use `common.time.utc_now()` or `datetime.now(tz=timezone.utc)`
2. **Direct DB cross-service** → Use Kafka events or REST APIs
3. **Dual writes** → Use outbox pattern from `libs/messaging`
4. **Hardcoded config** → All config via pydantic-settings with env vars
5. **Blocking sync I/O in async** → Use `asyncio.run_in_executor()` or async alternatives
6. **Missing idempotency** → Every Kafka consumer must handle re-delivery
7. **intelligence_db Alembic** → Only `intelligence-migrations` owns DDL; S6/S7 set `ALEMBIC_ENABLED=false`

---

## Evaluation & Improvement

After significant sessions, log outcomes in `.claude/evals/sessions/`.
Monthly review identifies weak spots and compounds improvements into:
- Bug patterns (`docs/BUG_PATTERNS.md`)
- Review checklists (`REVIEW_CHECKLIST.md`)
- Skill definitions (`.claude/skills/`)
- Hook scripts (`scripts/hooks/`)

See `.claude/evals/EVAL_FRAMEWORK.md` for details.

---

## When Uncertain

1. Check how existing mature services (Portfolio, Market Ingestion, Market Data) solved it
2. Read the `.claude-context.md` for the service you're working on
3. If the pattern doesn't exist, propose an ADR before implementing
4. Prefer the simplest solution that maintains architectural invariants
5. If stuck after 2 attempts, summarize the blocker instead of retrying blindly
