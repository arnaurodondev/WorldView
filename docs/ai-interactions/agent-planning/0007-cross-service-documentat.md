# Prompt 0007 — Cross-service documentation and implementation consistency audit

Act as both:

- Tech Lead (.claude/agents/tech-lead.md)
- Architecture Decision Lead (.claude/agents/architecture-decision-lead.md)
- QA Test Engineer (.claude/agents/qa-test-engineer.md)

## Goal

Produce a full-system consistency audit (NO implementation code unless explicitly requested)
that compares documented architecture/contracts/operations against the actual codebase,
then outputs a precise, evidence-backed divergence report and a dependency-ordered
remediation plan.

Primary outcome: identify every meaningful mismatch between documentation and code,
including stale docs, missing implementations, contract breakages, and infra/config gaps.

## Mandatory pre-read

- worldview/AGENTS.md
- worldview/CLAUDE.md
- worldview/RULES.md
- worldview/docs/MASTER_PLAN.md
- worldview/docs/index.md
- worldview/docs/services/**
- worldview/docs/libs/**
- worldview/docs/apps/**
- worldview/docs/architecture/**
- worldview/docs/workflows/**
- worldview/docs/runbooks/**
- worldview/docs/ai-interactions/BUG_PATTERNS.md (relevant sections only)

## Mandatory scan scope

### Documentation corpus (must read fully)

- worldview/**/*.md

### Implementation corpus (must inspect)

- worldview/services/**
- worldview/libs/**
- worldview/apps/frontend/**
- worldview/infra/**
- worldview/scripts/**
- worldview/docker-compose.yml

### Contract and schema context (must inspect)

- worldview/infra/kafka/**
- worldview/libs/contracts/**
- worldview/services/**/alembic/**
- worldview/services/**/src/**/api/**
- worldview/services/**/src/**/infrastructure/messaging/**

## Audit procedure (strict)

1. Build system inventory from code:
  - all services/apps/libs present
  - runtime/framework
  - exposed ports
  - owned database/schema
  - Kafka producer/consumer responsibilities
2. Build documented-claims inventory from docs:
  - service responsibilities
  - API endpoints
  - Kafka topics and payload contracts
  - table/schema definitions
  - env/config requirements
3. Reconcile inventories and classify each claim:
  - full match
  - partial match
  - no implementation
  - stale doc
4. Validate inter-service contracts:
  - producer-service and consumer-service ownership
  - topic names and versioning
  - schema compatibility and envelope expectations
  - REST caller/callee path and schema compatibility
5. Validate database/documentation consistency:
  - model vs migration parity
  - column names/types/nullability
  - key indexes and constraints
6. Validate infrastructure/config consistency:
  - compose services vs actual dependencies
  - env vars referenced in code vs declared in env/compose docs
  - startup dependencies, ports, healthchecks, mounts
7. Validate test coverage claims:
  - tests documented vs present
  - coverage depth per critical capability

## Divergence taxonomy (use exact values)

- doc_vs_code
- schema_mismatch
- missing_impl
- stale_doc
- contract_mismatch
- config_gap
- test_gap
- ownership_drift

## What must be checked (non-negotiable)

### A. Documentation vs code divergence

- Every major architectural claim in docs has corresponding implementation evidence.
- Every documented endpoint exists with matching method/path/request/response shape.
- Every documented table/model aligns with migrations and ORM declarations.
- Every documented env var exists and is actually consumed.

### B. Inter-service contract consistency

- Kafka topics:
  - producer exists in documented owner service
  - consumer exists in documented dependent service(s)
  - topic name/version and schema usage align across both sides
- REST dependencies:
  - caller expectations match callee implementation
  - request/response field compatibility validated

### C. Missing implementation detection

- Services or components described in docs but absent in code tree.
- Tables/indices/events/endpoints documented but not implemented.
- Outbox/consumer workflows documented but not wired.

### D. Stale documentation detection

- Old table/topic/endpoint names still present in docs.
- Docs describing deprecated or removed behaviors.
- Runbook/ops commands inconsistent with current project layout.

### E. Configuration and infrastructure gaps

- Missing runtime dependencies in compose (Kafka/Valkey/MinIO/Postgres/etc.).
- Env vars required by code but absent in compose/env examples.
- Port conflicts, missing volumes, missing healthchecks, or invalid dependency ordering.

### F. Test and quality-gate alignment

- Features documented as production-ready but lacking adequate tests.
- Missing unit/integration/contract test layers for critical paths.
- Docs claiming validation steps that no longer exist.

## Output format (strict)

### 1. Services inventory

Table columns (exact):

Service Name | Framework | Database | Kafka Producer | Kafka Consumer | Test Coverage (yes/partial/none)

### 2. Documentation coverage map

Table columns (exact):

Component | Documented (file refs) | Implemented (file refs) | Match Quality (full/partial/none)

### 3. Divergence log

One entry per divergence using this structure:

- Divergence ID: D-001, D-002, ...
- Type: one of taxonomy values
- Description: exact mismatch
- Evidence:
  - doc location(s): file path + line(s)
  - code location(s): file path + line(s)
- Severity: critical/significant/minor
- Recommended fix:
  - exact file(s) to change
  - exact corrective action
  - whether change should be code, docs, or both

### 4. Required updates by service

For each service/app/lib, provide a checklist of remediation tasks to restore
contract and documentation alignment.

### 5. Required documentation updates

List every documentation file requiring edits, with:

- what is inaccurate/incomplete
- what new source-of-truth content should replace it

### 6. Suggested implementation order

Dependency-ordered sequence of all required changes with:

- blocking dependencies
- safe parallel workstreams
- rollout notes to avoid broken intermediate states

### 7. Open questions and assumptions

- unresolved ambiguities
- decisions requiring product/architecture input before execution

## Quality bar (non-negotiable)

- No generalized findings. Every finding must have concrete evidence.
- Every non-trivial claim must include path + line references.
- If uncertain, mark as unknown and state what evidence is missing.
- Distinguish clearly between:
  - code must change
  - docs must change
  - both must change

## Response artifact required

Create a report file at:

- worldview/docs/ai-interactions/agent-responses/

Filename:

- 0007-response-<YYYYMMDD>-cross-service-consistency-audit.md

The report must include all required sections, complete divergence IDs, and
evidence-backed remediation actions.
