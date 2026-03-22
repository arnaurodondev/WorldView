# Prompt 0006 — Portfolio service capability evaluation (watchlist + alerts readiness)

Act as both:

- Backend Engineer (.claude/agents/backend-engineer.md)
- Architecture Decision Lead (.claude/agents/architecture-decision-lead.md)

## Goal

Produce an exhaustive gap analysis (NO implementation code unless explicitly requested)
for the Portfolio service in worldview, with primary focus on watchlist capabilities
required by the Intelligence Layer and downstream alerting workflows.

You must identify what exists, what is partial, what is missing, and what must be
changed to reach implementation readiness.

## Mandatory pre-read

- worldview/AGENTS.md
- worldview/CLAUDE.md
- worldview/RULES.md
- worldview/docs/MASTER_PLAN.md
- worldview/docs/services/portfolio.md
- worldview/docs/services/api-gateway.md
- worldview/docs/workflows/testing-strategy.md
- worldview/docs/ai-interactions/BUG_PATTERNS.md (relevant sections only)

## Directories to scan (mandatory)

### Primary target scope

- worldview/services/portfolio/**

### Required shared dependencies (read-only for contract/context verification)

- worldview/libs/contracts/**
- worldview/libs/messaging/**
- worldview/libs/common/**
- worldview/libs/observability/**

### Supporting infra/context (read-only)

- worldview/infra/kafka/**
- worldview/infra/postgres/**
- worldview/configs/** (if present)

## Audit procedure (strict)

1. Inventory the entire Portfolio service tree and classify files by layer:
   - api
   - application/use_cases
   - domain
   - infrastructure/db
   - infrastructure/messaging
   - consumers/background workers
   - tests
   - alembic/migrations
2. Read every file in the Portfolio service.
   - If a file is empty, explicitly mark it as empty.
   - If a function/class is a stub/TODO/pass, explicitly mark it as incomplete.
3. Cross-reference implementation against required capabilities (below).
4. Verify data model + migration consistency:
   - ORM models vs Alembic revisions vs actual expected schema ownership.
   - missing indexes on FKs and filter columns.
   - orphaned schemas/models/repositories.
5. Verify messaging consistency:
   - topic naming format
   - event envelope fields
   - schema/version alignment
   - outbox/idempotency expectations where applicable.
6. Verify test coverage and identify missing test classes by capability.

## Required capabilities to audit

### A. Watchlist management

- CRUD endpoints for watchlists (create, read, update, delete)
- Add/remove entities in a watchlist by canonical entity_id
- Multiple watchlists per user
- Reverse-index lookup endpoint/repository query:
  - input: entity_id
  - output: all user_ids that track that entity
  - required by alert service S10
- Watchlist mutation Kafka events on every add/remove operation:
  - topic: portfolio.watchlist.updated.v1
  - payload includes at minimum: user_id, entity_id, operation (added|removed)
- Valkey reverse-index cache:
  - key pattern for entity_id -> user_ids
  - explicit TTL
  - mutation-triggered invalidation/update strategy

### B. Portfolio management

- Position model with entry_price, quantity, asset_type
- Association between positions and canonical entity_id from Knowledge Graph
- Validation rules (quantity > 0, price >= 0, etc.) at API + domain boundaries

### C. Alert subscriptions

- Per-user alert preference storage for:
  - signal
  - contradiction
  - confidence_drop
  - new_event
- Per-entity suppression or opt-out preferences
- Read/write API or internal application ports for preference retrieval by alerting

### D. Kafka integration

- Producer wiring in mutation path (not dead code)
- Versioned topic names + schema compatibility rules
- Retry/error handling classification for publish failures
- Idempotency/duplicate-handling strategy documented or implemented

### E. Database quality

- All required tables migrated; no pending required schema changes
- Indexes on:
  - foreign keys
  - high-frequency WHERE columns
  - uniqueness constraints for watchlist membership if needed
- No model/schema/table drift (ORM != migration)
- No orphaned model/schema references to absent tables

### F. API and contract quality

- Request/response schemas complete and validated
- Error responses consistent and explicit
- Pagination/filtering where list growth is unbounded
- Auth/tenant scoping assumptions explicit in code/docs

### G. Operational readiness

- Structured logging around mutations and publish outcomes
- Metrics/tracing hooks for watchlist and alert preference operations
- Config variables present and documented (Kafka, Valkey, DB, feature flags)

## Output format (strict)

### 1. Codebase summary

- Framework/runtime/ORM/migration tooling
- Module map by architecture layer
- Test suite status and gaps

### 2. Capability audit table

Use this exact column set:

Capability | Status (exists/partial/missing) | Evidence (file path + symbol) | Notes/Risk

### 3. Detailed gap descriptions

For each capability marked partial/missing, include all of the following:

- Current state (what exists now)
- Missing/incomplete behavior
- Files to create/modify (exact paths)
- DB design required:
  - tables
  - columns (name + type + nullability)
  - PK/FK
  - indexes
  - uniqueness constraints
- API contract required:
  - method
  - path
  - request schema
  - response schema
  - error cases/status codes
- Messaging contract required (if applicable):
  - topic
  - key
  - value schema
  - envelope fields
  - schema_version considerations
- Cache strategy (if applicable):
  - key format
  - TTL
  - invalidation/update trigger points
- Dependencies:
  - other service expectations
  - shared lib dependencies
  - infra prerequisites
- Required tests:
  - unit
  - service/container integration
  - contract tests (if event/API surface changes)

### 4. Prioritized implementation plan

Provide dependency-ordered, execution-ready tasks. For each task include:

- ID
- Title
- Objective
- Depends_on
- Can_run_with
- Target paths
- Implementation steps
- Tests required + pass evidence
- Docs updates required
- Effort (small/medium/large)

### 5. Open questions and decision points

- Ambiguities needing human/product/architecture input
- Explicit trade-off options and recommended default

### 6. Risk register

- Top migration/compatibility risks
- Probability/impact
- Mitigation and rollback notes

## Quality bar (non-negotiable)

- Be exhaustive and explicit; do not summarize away missing detail.
- Every non-trivial claim must include concrete evidence path(s).
- If something is unknown, state unknown and explain what evidence is missing.
- Do not claim feature completeness without tracing API + use-case + repository + DB + tests.

## Response artifact required

Create a report file at:

- worldview/docs/ai-interactions/agent-responses/

Filename:

- 0006-response-<YYYYMMDD>-portfolio-watchlist-gap-analysis.md

The report must include:

- executive summary
- complete audit table
- detailed gaps
- prioritized implementation backlog
- open questions
- risk register
