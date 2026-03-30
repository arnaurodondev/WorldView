# Plan Tracking Index

> Active implementation plans across the worldview project.
> Updated by `/implement` and `/plan` skills. Checked by `/qa` and `/review`.

## Active Plans

| Plan ID | Title | PRD | Status | Waves Done/Total | QA | Updated |
|---------|-------|-----|--------|-----------------|-----|---------|
| PLAN-0001-D | S9 API Gateway: External Ingestion + Intelligence Query Proxy | PRD-0001 | draft | 0/2 | — | 2026-03-25 |
<!-- New plans are appended here by the /plan skill -->

## Execution Order (Dependency Graph)

```
PLAN-0001-A Wave 1 (Avro schemas, repo fixes) ──→ PLAN-0001-B (S4+S5)
          │                                              │
          ├─→ PLAN-0001-A Wave 2 (intelligence-migrations) ──→ PLAN-0001-C Sub-Plan C (S6)
          │                                                           │
          └─→ PLAN-0001-A Wave 3 (S1 internal endpoints)            │
                    │                                                │
                    └──→ PLAN-0001-C Sub-Plan E (S10) ←────────────── │
                                                                     │
PLAN-0001-B + PLAN-0001-C C+D ──→ PLAN-0001-D (S9 Gateway)
```

**Critical path**: 0001-A W1 → 0001-B A-1..A-4 → 0001-B B-1..B-4 → 0001-C C-1..C-4 → 0001-C D-1..D-4 → 0001-C E-1..E-3
**Parallelizable**: 0001-A W2 ∥ W3 (after W1); 0001-D W1 (after 0001-B); S10 (after S1 internal + S7)

## Completed Plans

| Plan ID | Title | PRD | Completed | Waves | QA |
|---------|-------|-----|-----------|-------|----|
| PLAN-0001-C | Ingestion Pipeline v1: S6 NLP Pipeline + S7 Knowledge Graph + S10 Alert Service | PRD-0001 | 2026-03-29 | 11 | 2026-03-30 |
| PLAN-0001-A | Infrastructure Prerequisites: Repo Fixes + intelligence-migrations + S1 Internal | PRD-0001 | 2026-03-26 | 3 | — |
| PLAN-0002 | Enum Standardization: Shared OutboxStatus + ContentSourceType | N/A | 2026-03-26 | 2 | — |
| PLAN-0001-B | Ingestion Pipeline v1: S4 Content Ingestion + S5 Content Store | PRD-0001 | 2026-03-27 | 8 | 2026-03-27 |
| PLAN-0001-B-R4 | S4+S5 QA Review Fixes: DLQ Fidelity, SSRF Hardening, DDL Alignment, Process Compounding | QA Review | 2026-03-27 | 4 | — |
| PLAN-0001-B-R1 | S4 QA & Review Fixes: Runtime Bugs, Lock, Watermarks, Auth, Security, Tests, Infra | Review/QA | 2026-03-26 | 7 | — |
| PLAN-0001-B-R2 | S4+S5 QA Fixes: DDL, DLQ, SSRF, LSH, Contract Tests, Compounding | QA Review | 2026-03-27 | 4 | — |
| PLAN-0001-B-R3 | S4+S5 Architecture: ABCs, BaseKafkaConsumer, MinIO GC, DomainError, Standards | QA Review | 2026-03-27 | 5 | — |
| PLAN-0003 | Observability Standardization: Service Fixes + Monitoring Stack | N/A | 2026-03-27 | 4 | 2026-03-27 |
| QA-CROSS-001 | Cross-Service QA: market-ingestion, market-data, portfolio (16 findings fixed) | N/A | 2026-03-27 | — | 2026-03-27 |
| QA-CROSS-002 | Deep Cross-Service QA: portfolio, market-ingestion, market-data (87 findings, 9 blocking/critical) | N/A | 2026-03-27 | — | 2026-03-27 |
| PLAN-0001-E | S1+S2+S3 Deep QA Fixes: Idempotency, Atomicity, Security Hardening, Architecture Consistency | QA Review (QA-CROSS-002) | 2026-03-28 | 14 | 2026-03-28 |
| PLAN-0004 | Observability Dashboards, Alerts & Recording Rules — Auto-Provisioned | N/A | 2026-03-27 | 5 | — |
| QA-E2E-001 | Comprehensive E2E Test Suite: S4+S5+S7 ASGI tests + S2→S3 cross-service + S1 security isolation (89 new tests) | N/A | 2026-03-28 | — | 2026-03-28 |
| PLAN-0005 | Provider Config Externalization — Nested Settings Pattern (S4 + S2) | N/A | 2026-03-29 | 3 | — |
| PLAN-0006 | Process Architecture & Database Standardization: S4 Decoupling + Scheduler-Worker + R/W Split | N/A | 2026-03-30 | 5 | 2026-03-30 |
| PLAN-0001-E-R1 | S1+S2+S3 Remaining Open Items: UoW commit, TOCTOU dedup, arch violations, topic mismatch, domain layer, auth | QA-CROSS-002 | 2026-03-30 | 6 | 2026-03-30 |
| PLAN-0007 | PLAN-0001-C QA Fixes: Idempotency, Valkey Hardening, Observability, Deployment Constraints | PLAN-0001-C QA | 2026-03-30 | 2 | — |
| PLAN-0008 | QA Follow-Up — Standards Enforcement, Architecture Hardening & Production Readiness | PLAN-0001-E-R1 QA | 2026-03-30 | 10 | 2026-03-30 |
| PLAN-0009 | R25 Layer Violation Remediation — S4 API Routes + ExecuteContentTaskUseCase | PLAN-0006 QA | 2026-03-30 | 4 | 2026-03-30 |
| QA-S4S5S6S7S10-001 | Full QA Pass + E2E Test Suite: S4/S5/S6/S7/S10 security fixes + ASGI e2e suites + cross-service integration + real provider tests + infra scaffold | N/A | 2026-03-30 | — | 2026-03-30 |

## Conventions

- **Plan IDs** match their PRD: `PLAN-0001` corresponds to `PRD-0001`
- **Status values**: `draft` → `approved` → `in-progress` → `completed` | `cancelled`
- **QA column**: Date when `/qa` was run against the plan. `—` means not yet QA'd. `/qa` skill MUST update this column when it runs.
- **Wave tracking**: See the individual plan file for wave/task-level detail
- **Session boundaries**: Each sub-plan (A, B, C...) can be executed in a separate Claude Code session
- **Conflict check**: Before starting a wave, verify no other plan modifies the same files

## How to Use

1. **Starting work**: Check this index for active plans. Read the plan file for the next ready wave.
2. **During implementation**: The `/implement` skill updates wave/task status in the plan file.
3. **After completion**: Move the plan from Active to Completed when all waves are done.
4. **Conflict resolution**: If two plans touch the same service, execute them in dependency order.
