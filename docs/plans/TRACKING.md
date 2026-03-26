# Plan Tracking Index

> Active implementation plans across the worldview project.
> Updated by `/implement` and `/plan` skills. Checked by `/qa` and `/review`.

## Active Plans

| Plan ID | Title | PRD | Status | Waves Done/Total | Updated |
|---------|-------|-----|--------|-----------------|---------|
| PLAN-0001-A | Infrastructure Prerequisites: Repo Fixes + intelligence-migrations + S1 Internal | PRD-0001 | in-progress | 2/3 | 2026-03-26 |
| PLAN-0012 | Ingestion Pipeline v1: S4 Content Ingestion + S5 Content Store | PRD-0001 | draft | 0/8 | 2026-03-25 |
| PLAN-0013 | Ingestion Pipeline v1: S6 NLP Pipeline + S7 Knowledge Graph + S10 Alert Service | PRD-0001 | draft | 0/11 | 2026-03-25 |
| PLAN-0001-D | S9 API Gateway: External Ingestion + Intelligence Query Proxy | PRD-0001 | draft | 0/2 | 2026-03-25 |
<!-- New plans are appended here by the /plan skill -->

## Execution Order (Dependency Graph)

```
PLAN-0001-A Wave 1 (Avro schemas, repo fixes) ──→ PLAN-0012 (S4+S5)
          │                                              │
          ├─→ PLAN-0001-A Wave 2 (intelligence-migrations) ──→ PLAN-0013 Sub-Plan C (S6)
          │                                                           │
          └─→ PLAN-0001-A Wave 3 (S1 internal endpoints)            │
                    │                                                │
                    └──→ PLAN-0013 Sub-Plan E (S10) ←────────────── │
                                                                     │
PLAN-0012 + PLAN-0013 C+D ──→ PLAN-0001-D (S9 Gateway)
```

**Critical path**: 0001-A W1 → 0012 A-1..A-4 → 0012 B-1..B-4 → 0013 C-1..C-4 → 0013 D-1..D-4 → 0013 E-1..E-3
**Parallelizable**: 0001-A W2 ∥ W3 (after W1); 0001-D W1 (after 0012); S10 (after S1 internal + S7)

## Completed Plans

| Plan ID | Title | PRD | Completed | Waves |
|---------|-------|-----|-----------|-------|
<!-- Completed plans are moved here -->

## Conventions

- **Plan IDs** match their PRD: `PLAN-0001` corresponds to `PRD-0001`
- **Status values**: `draft` → `approved` → `in-progress` → `completed` | `cancelled`
- **Wave tracking**: See the individual plan file for wave/task-level detail
- **Session boundaries**: Each sub-plan (A, B, C...) can be executed in a separate Claude Code session
- **Conflict check**: Before starting a wave, verify no other plan modifies the same files

## How to Use

1. **Starting work**: Check this index for active plans. Read the plan file for the next ready wave.
2. **During implementation**: The `/implement` skill updates wave/task status in the plan file.
3. **After completion**: Move the plan from Active to Completed when all waves are done.
4. **Conflict resolution**: If two plans touch the same service, execute them in dependency order.
