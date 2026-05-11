---
name: revise-prd
description: "Review an existing PRD and/or its plan for staleness, internal inconsistencies, architecture drift, and cross-PRD conflicts. Produces an inconsistency report and optionally fixes the PRD/plan in-place. Use before /plan when the PRD is >2 weeks old, after an architecture change that may affect a pending PRD, or when multiple concurrent PRDs touch overlapping domains."
user-invocable: true
argument-hint: "[PRD-NNNN or path, e.g. PRD-0017 or docs/specs/0017-entity-screener.md] [--plan] [--all-draft]"
---

# Revise PRD — Lifecycle Consistency Review

You are a **Principal Architect** performing a structured consistency audit on an existing PRD (and optionally its plan). Your goal is to identify every place the document is wrong, stale, incomplete, or in conflict with the current system state — then fix it.

**This is not a rubber-stamp.** Every assertion in the PRD is a claim about reality. Your job is to challenge each claim against the current codebase, architecture decisions, external API documentation, and the other active PRDs.

## Input

Target: `$ARGUMENTS`

Flags:
- `--plan` — also audit the corresponding plan file (same NNNN)
- `--all-draft` — audit all PRDs with `draft` status in TRACKING.md (batch mode)

---

## Phase 0 — Context Loading (Silent)

1. Read the target PRD fully
2. Read `docs/plans/TRACKING.md` — identify all active/draft PRDs and plans
3. Read `RULES.md` and `AGENTS.md` — current hard rules and coding standards
4. Read `docs/MASTER_PLAN.md` — current system architecture
5. Read `docs/STANDARDS.md` — engineering standards
6. Read `docs/BUG_PATTERNS.md` — known failure patterns
7. Read service docs for every service mentioned in the PRD: `docs/services/<service>.md`
8. Read per-service context: `services/<service>/.claude-context.md`
9. Read actual service source code for every entity, table, or endpoint the PRD modifies (not just docs — read the code)
10. If `--plan` flag: read the corresponding plan file

---

## Phase 1 — Internal Consistency Check

### 1.1 Entity ↔ API Cross-Reference
For every entity defined in §6.5, verify every attribute appears consistently in §6.2:
- API request/response bodies must use the exact same field names and types as the domain entity
- No field present in §6.2 that is absent from §6.5 (and vice versa, accounting for DTOs)
- Enum values used in API requests must match the domain enum definition

### 1.2 Entity ↔ DB Cross-Reference
For every entity in §6.5, verify its corresponding table in §6.4:
- Every entity attribute maps to a column (or is computed)
- Column types match (e.g., UUID not VARCHAR for IDs, TIMESTAMPTZ not TIMESTAMP)
- Nullable/required constraints in the entity match the column definition
- Indexes exist for every field the PRD queries by

### 1.3 Event ↔ Consumer Cross-Reference
For every Kafka event in §6.3:
- At least one consumer is named
- The consumer's service is in the affected services list (§6.1)
- The Avro schema fields cover everything the consumer's processing logic needs (check §data flow in §6.6)

### 1.4 Test ↔ Behavior Cross-Reference
For every functional requirement in §3.1:
- At least one test in §11 covers it
- Every entity invariant in §6.5 has a unit test
- Every error response in §6.2 has a corresponding test

Produce a table of gaps:
| Gap | Location | Severity |
|-----|----------|----------|
| Field `foo` in §6.2 response but absent from §6.5 entity | §6.2 POST /endpoint | HIGH |

---

## Phase 2 — Architecture Compliance Check

Walk through every design decision in the PRD and check it against `RULES.md`:

| Rule | Design Decision in PRD | Compliant? | Issue (if any) |
|------|------------------------|------------|----------------|
| R5 — Avro forward compat | Event schema in §6.3 | PASS/FAIL | ... |
| R7 — No cross-service DB | Any direct DB reference across services | PASS/FAIL | ... |
| R8 — No dual writes | Any multi-step write in §6.6 data flow | PASS/FAIL | ... |
| R9 — Kafka idempotency | Consumer processing in §6.6 | PASS/FAIL | ... |
| R10 — UUIDv7 | All entity IDs in §6.5 | PASS/FAIL | ... |
| R11 — UTC timestamps | All timestamp fields | PASS/FAIL | ... |
| R22 — Independent processes | Any new background worker in §6.1 | PASS/FAIL | ... |
| R23 — Read/write DB split | Read-only use cases in §6.1 | PASS/FAIL | ... |
| R25 — API layer isolation | API endpoints in §6.2 | PASS/FAIL | ... |
| R27 — ReadOnlyUoW for reads | Read endpoints in §6.2 | PASS/FAIL | ... |

---

## Phase 3 — Codebase Alignment Check

For every entity, table, topic, or endpoint the PRD proposes to **modify** (not create from scratch):

### 3.1 Read the actual current code
- Read the entity file, ORM model, repository, and any existing migrations
- Read the Avro schema file for any modified event
- Read the router file for any modified endpoint

### 3.2 Compare PRD claimed state vs actual state

| PRD Claim | File | Actual State | Delta |
|-----------|------|-------------|-------|
| `entity_embedding_state` uses IVFFlat index | `services/intelligence/…` | Uses HNSW | PRD wrong — must update |
| Topic `market.signal.v1` is new | `infra/kafka/schemas/` | Already exists | Check schema compat |
| ... | ... | ... | ... |

### 3.3 Flag stale assumptions
Any delta where the codebase has evolved past the PRD's assumed baseline is a **stale assumption**. These produce silent bugs when implemented (the code already exists in a different form and the new code conflicts or duplicates it).

### 3.4 Name Verification — Mandatory `git grep` Pass (BP-405 Guard)

For every class, method, port field, file path, env var, and Avro schema name the PRD/plan mentions, run a mechanical `git grep` and confirm the named target actually exists in the repo (or is explicitly marked as new). Names *read correctly* even when they have drifted from the codebase — humans cannot reliably catch this. The pass must be mechanical.

**Procedure** (mirrors `/plan` Phase 1.4):

1. Extract every class, method, port field, file path, env var, and Avro schema name mentioned in the PRD/plan body. Include both targets the PRD intends to modify and targets it merely intends to call into.
2. Run `git grep` for each name with the appropriate command:
   - Python class: `git grep -E "^class <Name>(\(|:)"`
   - Python function/method: `git grep -E "^( {4})?(async )?def <name>\("`
   - Pydantic / dataclass field: `git grep -E "<field>: " <suspected_file>`
   - File path: `ls <path>`
   - Env var: `git grep -E "<ENV_NAME>"`
   - Avro schema: `ls infra/kafka/schemas/<name>.avsc`
   - Kafka topic: `git grep "<topic.name.v1>"`
   - Endpoint path: `git grep -E "['\"]<path>['\"]"`
3. Build a verification table:

| Name (kind) | Found? | Tag/Action |
|---|---|---|
| `ChatOrchestratorUseCase` (class) | NO (actual: `ChatOrchestrator`) | **HIGH stale assumption** — rename or add precursor refactor plan |
| `ChunkSearchRequest.entity_tickers` (field) | NO | **HIGH stale assumption** — port shape doesn't exist; add precursor wave or upstream plan |
| `GET /entities/{id}/intelligence` (endpoint) | NO | mark `(NEW — created in Wave D)` if this PRD ships it; otherwise stale |

4. Every row marked **HIGH stale assumption** is a Phase 7 BLOCKING issue. The PRD/plan body must be corrected (rename, add precursor work, or tag as new) before the document is fit for `/plan` to consume.

**Why this is mandatory** (not optional): the 2026-05-07 `/investigate` against PLAN-0066/0067/0074 found three concurrent plans that all referenced classes (`ChatOrchestratorUseCase`, `RunChatUseCase`) and port fields (`ChunkSearchRequest.entity_tickers`, `entity_mentions`) that did not exist anywhere in the repo. Each plan was reviewed by humans and approved. Editorial review didn't catch the drift — fix has to be mechanical. See BP-405.

**Add the verification table to the §3 Codebase Alignment section of the inconsistency report** (Phase 7 §3) so the user can see exactly which names failed and why.

---

## Phase 4 — External API Reality Check

For every external provider field, endpoint, model ID, or SDK method the PRD references:

| Provider | Referenced Field/Method | Verified? | How Verified |
|----------|------------------------|-----------|-------------|
| EODHD | `General.Officers` | NO | Field does not exist in EODHD Fundamentals API |
| DeepInfra | `deepseek-r1-distill-qwen-32b` | ? | Verify against provider docs |
| ... | ... | ... | ... |

If a field cannot be verified: mark as **BLOCKING** — the PRD must be corrected before planning.

---

## Phase 5 — Cross-PRD Conflict Check

Read all active/draft PRDs from `docs/plans/TRACKING.md`. For each:

| Conflict Type | This PRD | Other PRD | Resolution Needed |
|--------------|----------|-----------|-------------------|
| Same Kafka topic, different schema | `market.signal.v1` (PRD-0020) | `market.signal.v1` already defined in PRD-0019 | Merge or rename |
| Same DB table modified | `articles` add column (PRD-0016) | `articles` add column (PRD-0018) | Order dependency |
| Same endpoint path | `GET /api/v1/signals` (PRD-0020) | `GET /api/v1/signals` (PRD-0021) | Deduplicate |
| Contradictory architectural decision | Model X hardcoded in PRD-0016 | Model X configurable in PRD-0017 | Align |

---

## Phase 6 — Open Questions Audit

Read §14 of the PRD. For every open question:

| OQ | Classification | Status | Blocking? |
|----|---------------|--------|-----------|
| OQ-001 | BLOCKING / DEFERRED | Resolved / Unresolved | YES/NO |

**Rule**: Any unresolved BLOCKING open question must be resolved before this PRD can be used for planning. Present each to the user and require a decision.

---

## Phase 7 — Inconsistency Report

Produce a structured report:

```markdown
# Revision Report: PRD-NNNN — <Title>

**Date**: YYYY-MM-DD
**Auditor**: Claude (revise-prd skill)
**PRD Age**: X days since creation
**Overall status**: CLEAN | NEEDS_REVISION | BLOCKED

## Summary
- Internal inconsistencies: N
- Architecture violations: N
- Stale assumptions: N
- **Failed name verifications (BP-405)**: N
- External API issues: N
- Cross-PRD conflicts: N
- Unresolved blocking OQs: N

## Name Verification Results (BP-405 guard — Phase 3.4)
| Name (kind) | Mentioned at | Found in repo? | Action |
|---|---|---|---|
| `<ClassName>` (class) | §<sec> | NO | rename / tag NEW / add precursor |
| `<port.field>` (field) | §<sec> | NO | upstream port doesn't exist — add precursor wave |

## Blocking Issues (must fix before /plan)
| ID | Category | Location | Issue | Fix |
|----|----------|----------|-------|-----|
| R-001 | Stale assumption | §6.5 EntityName | PRD says IVFFlat, code uses HNSW | Update §6.5 to HNSW; remove migration task |
| R-NNN | Failed name verification | §<sec> | Class `RunChatUseCase` not found in repo (actual: `ChatOrchestrator`) | Rename in plan to `ChatOrchestratorUseCase`; add precursor refactor plan |

## Non-blocking Issues (should fix)
| ID | Category | Location | Issue | Fix |
|----|----------|----------|-------|-----|
| R-010 | Missing test | §11 | No test for `EntityName.from_dict()` invariant | Add test row to §11 |

## Cross-PRD Conflicts
| ID | This PRD | Other PRD | Resolution |
|----|----------|-----------|-----------|

## Stale PRD Verdict
[ ] PRD is current — proceed to /plan
[ ] PRD requires in-place fixes — see blocking issues above
[ ] PRD requires user decisions — see unresolved OQs above
```

---

## Phase 8 — In-Place Fixes (With User Confirmation)

After presenting the report:

1. For each **blocking issue**, propose the exact fix: "I will change §6.5 EntityName to use HNSW instead of IVFFlat. Confirm?"
2. For each **unresolved blocking OQ**, present the options and ask the user to decide
3. Apply fixes section-by-section (write in chunks to avoid token limits)
4. After all fixes, re-run the internal consistency check (Phase 1) to confirm no new gaps were introduced

**Do not apply fixes silently.** Every change to the PRD must be confirmed by the user first.

---

## Phase 9 — Plan Audit (if `--plan` flag)

If `--plan` was specified, read the corresponding plan file and check:

### 9.1 Task ↔ PRD Section Alignment
For every task in the plan, verify:
- Its PRD reference (§N.N) still exists and has not changed in a way that invalidates the task
- The entity attributes listed in the task match the (now-revised) PRD §6.5
- The target files still exist (or are being created in a prerequisite wave)

### 9.2 Missing Tasks
After PRD revisions, check if any new entity, table, or endpoint was added that has no corresponding task in the plan.

### 9.3 Orphaned Tasks
Check if any task references an entity/table/topic that was removed from the PRD.

Produce a plan delta table:
| Plan Task | Status | Issue |
|-----------|--------|-------|
| T-A-1-03: Add `IVFFlat` index migration | ORPHANED | PRD now uses HNSW (no new migration needed) |
| (none) | MISSING | PRD-0017 §6.4 now has `price_impact_labels` table; no task covers it |

### 9.4 Per-Task Architecture Compliance (MANDATORY — applies even without --plan flag when plan files exist)

For every task in the plan that creates a use case, worker, or API endpoint, run this compliance check. These patterns are the most consistently missing and cannot be caught by reading task descriptions alone — you must actively look for absence.

| Pattern | Rule | Check (for each use case/worker task) |
|---------|------|---------------------------------------|
| **ABC port** | R25 | Does the task explicitly name the ABC port interface? If not: BLOCKING — add "depends on `IXyzRepository` (ABC in `application/ports/`)" |
| **ReadOnlyUoW** | R27 | For every GET/query use case: does it specify `ReadOnlyUnitOfWork` + `ReadUoWDep`? If not: BLOCKING |
| **UUIDv7** | R10 | For every new entity with ID field: does it specify `new_uuid7()`? If not: add guardrail |
| **UTC timestamps** | R11 | For every new timestamp field: does it specify `utc_now()`? If not: add guardrail |
| **structlog** | — | For every new worker/use case: does it specify structlog? If not: add guardrail |
| **Outbox** | R8 | For any task writing to DB + Kafka: does it specify outbox pattern? If not: BLOCKING |
| **Alembic head** | R32 | For any migration task: does it specify the verified current HEAD filename? If not: BLOCKING |

Produce a per-task architecture compliance table:
| Task ID | Use Case / Worker | ABC Port Named? | UoW Type Correct? | IDs/Timestamps OK? | Structlog? | Issues |
|---------|------------------|----------------|-------------------|---------------------|------------|--------|
| T-A-1-01 | `StoreChunkUseCase` | YES — `IChunkRepository` | YES — ReadOnly | YES | YES | PASS |
| T-B-2-03 | `SummaryWorker` | NO | — | NO (no utc_now note) | NO | 3 issues |

Fix all BLOCKING items in-place in the plan file. Non-blocking items (missing guardrails) should be added to the wave's Regression Guardrails section.

---

## Workflow Chain — Suggest Next Steps

- **If CLEAN**: `/plan <PRD-ID>` — the PRD is ready to decompose
- **If NEEDS_REVISION with fixes applied**: re-run `/revise-prd` to confirm clean, then `/plan`
- **If BLOCKED (unresolved OQs)**: resolve OQs with user, then re-run `/revise-prd`
- **If cross-PRD conflict**: resolve with user which PRD owns the conflicting resource, then update both PRDs

---

## Mandatory Compounding Step (All Skills)

Before completing this skill, check if any of these documents should be updated:

| Document | Update When | Location |
|----------|------------|----------|
| **BUG_PATTERNS.md** | New process-level failure pattern discovered | `docs/BUG_PATTERNS.md` |
| **STANDARDS.md** | New convention identified from revision | `docs/STANDARDS.md` |
| **Service .claude-context.md** | PRD revision revealed a pitfall | `services/<service>/.claude-context.md` |
| **Skill definitions** | Revision revealed a gap in `/prd` or `/plan` skill | `.claude/skills/<skill>/SKILL.md` |
| **RULES.md** | PRD violation revealed a missing rule | `RULES.md` |

**This is not optional.**
