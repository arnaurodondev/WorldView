# AI Execution Prompt Library (Canonical)

This directory stores implementation prompts for execution agents.

## Naming Convention

`<id>-exec-<scope>-wave-<nn>.md`

- `id` is 4-digit (`0001`, `0002`, ...)
- `scope` is the initiative (shared-libs, portfolio, market-ingestion, market-data)
- `wave` identifies the execution batch order

## Mandatory Prompt Requirements

Every execution prompt must include:

1. Source planning context links:
   - `agent-planning/<id>-...md`
   - `agent-responses/<id>-response-...md`
2. Exact task IDs to implement in this wave.
3. Parallel group vs sequential group.
4. Required tests and pass criteria.
5. Documentation updates required (mandatory for any behavior/API/event/config/schema/test-surface change).
6. Handoff evidence required in response artifacts.

## Mandatory documentation rule

Each execution prompt must explicitly state:

- update documentation in the same wave when implementation changes behavior/contracts/config/schema/API/tests
- list exact documentation files updated in handoff evidence
- if no docs are changed, include explicit `N/A` justification

## Documentation quality standard

Every execution prompt generated from the wave-generation template (`0000-exec-wave-generation-template.md`)
inherits the **Documentation quality standard** defined in that template. The standard requires:

| Criterion | Requirement |
|-----------|-------------|
| Accuracy | Every API, field, event, config var matches the final implementation |
| Diagrams | Mermaid diagram required for any flow with ≥3 components or ≥4 steps |
| Code examples | Working, copy-pasteable examples for every new public class/function |
| Abstract methods | Table documenting each abstract method (when called, what to do, return) |
| Common pitfalls | `## Common Pitfalls` section with ≥3 concrete entries in every lib/service doc |
| Lib docs | `docs/libs/<lib>.md` updated whenever `libs/` source is touched |
| Service docs | `docs/services/<service>.md` reflects final endpoints/events/schema/env vars |
| No orphans | No docs for unimplemented code; no stale docs for removed symbols |

Each wave's handoff evidence must include a **Documentation quality checklist** table confirming
each criterion is ✓ or explicitly N/A.

## Current Execution Prompt Set

| ID | File | Purpose |
|----|------|---------|
| 0000 | `0000-exec-wave-generation-template.md` | Generic template to generate full-coverage wave prompts |
| 0001 | `0001-exec-wave-shared-libs-migration-plan.md` | Wave-generation prompt for shared libs response |
| 0002 | `0002-exec-wave-portfolio-migration-plan.md` | Wave-generation prompt for portfolio response |
| 0003 | `0003-exec-wave-market-ingestion-migration-plan.md` | Wave-generation prompt for market-ingestion response |
| 0004 | `0004-exec-wave-market-data-migration-plan.md` | Wave-generation prompt for market-data response |
| 0005 | `0005-exec-eodhd-pipeline-fixes-and-extensions-wave-01.md` | EODHD pipeline bug fixes (F1–F10, O1–O2, Q1) + 8 new endpoint extensions (EXT-01–EXT-08) |
| 0006 | `0006-exec-market-data-audit-and-decoupling-wave-01.md` | Market-data audit: fundamentals read-side (18 sections + 5 section endpoints), API semantics, list filters in DB, read/write DB decoupling (read_replica_url, read session for queries) |
| 0007 | `0007-exec-market-data-fundamentals-read-optimized-wave-01.md` | Fundamentals read-optimized table: current storage/JSONB audit, narrow `fundamental_metrics` table design, write path (consumer updates section tables + metrics table), read path (timeseries + screen endpoints from metrics table) |
