---
name: qa
description: "Run a full Quality Assurance pass with multi-agent specialist review. Spawns parallel agents (QA, Security, Data Platform, Distributed Systems, Architecture) that each analyze the full implementation from their perspective, then consolidates findings, applies fixes, and runs all tests across all services."
user-invocable: true
argument-hint: "[--plan PLAN-ID] [service-name] ['full']"
---

# QA — Multi-Agent Quality Assurance Pipeline

You are a **QA Lead** orchestrating a comprehensive quality assurance pass. You coordinate 5 specialist review agents in parallel, consolidate their findings, triage fixes, and run the full test suite across every service and library.

## Input

Scope: `$ARGUMENTS`
- `--plan PLAN-0001-A` → scope review to files/services changed by that plan
- `portfolio` → scope to a specific service + its lib dependencies
- `full` → review everything
- (empty) → review all changes on current branch vs `main`

---

## Phase 0: Scope Resolution

Determine the set of files and services under review.

### If `--plan <PLAN-ID>` is provided:
1. Read the plan file from `docs/plans/` matching the PLAN-ID
2. Extract all task target files and services mentioned
3. Collect the full list of changed/created files across all waves
4. Identify which services and libs are affected

### If a service name is provided:
1. Collect all files under `services/<name>/` and its lib dependencies in `libs/`

### If `full`:
1. All files under `libs/`, `services/`, `infra/`, `apps/frontend/`

### If empty (default — changed-only):
1. Run `git diff --name-only main...HEAD` to get changed files
2. Group by service/lib/infra

**Output of Phase 0**: A structured scope object:
```
scope:
  services: [list of service names]
  libs: [list of lib names]
  infra_files: [list of infra files]
  frontend: true/false
  all_files: [complete file list]
```

---

## Phase 1: Context Loading

Before spawning agents, load the shared context they will all need:

1. Read `RULES.md` — hard rules all agents must enforce
2. Read `AGENTS.md` — coding standards and architecture patterns
3. For each service in scope, read `services/<service>/.claude-context.md`
4. If `--plan` was given, read the full plan file for task requirements and acceptance criteria
5. Collect the diff or file contents for all files in scope

---

## Phase 2: Parallel Specialist Review

Spawn **5 agents in parallel** using the Agent tool. Each agent receives:
- The full list of files in scope (they read files themselves)
- Their specialist mandate and review materials
- A structured output format they must follow

### Agent Prompts

Each agent MUST produce findings in this exact format:
```markdown
### Finding F-NNN
- **Severity**: BLOCKING | CRITICAL | MAJOR | MINOR | NIT
- **Category**: <agent-specific category>
- **File**: `path/to/file.py:line_number`
- **Confidence**: HIGH | MEDIUM | LOW
- **Flagged by**: <list of agent names that independently found this>
- **Issue**: <clear description of what is wrong>
- **Evidence**: <code snippet or reference>
- **Suggestion**: <specific fix or recommendation>
- **Auto-fixable**: YES | NO
- **Requires decision**: YES | NO — <what decision is needed>
```

### Agent 1: QA / Test Engineer

**Agent definition**: `.claude/agents/qa-test-engineer.md`
**Review materials**: `.claude/review/checklists/REVIEW_CHECKLIST.md` (sections 8-9), `.claude/review/heuristics/EDGE_CASE_GENERATION.md`

**Mandate — answer these questions for every changed file**:
1. Is every public function/method covered by at least one test?
2. Are edge cases tested? Apply the 7 edge-case generators from `EDGE_CASE_GENERATION.md`:
   - Data volume extremes (empty, single, max, overflow)
   - Null/None/missing fields
   - Timestamps & temporal edge cases
   - Schema & type boundaries
   - Concurrency & retry scenarios
   - External dependency failures
   - Worldview-specific edge cases (MinHash, entity resolution, partitions, compacted topics)
3. Are error paths tested (not just happy paths)?
4. Do tests actually assert meaningful behavior (not just "doesn't crash")?
5. R19 compliance: are any tests deleted, skipped, weakened, or have assertions loosened?
6. Are integration tests present where DB/Kafka/MinIO interactions exist?
7. Are contract tests present for Avro schemas and API shapes?
8. Is test isolation correct (no shared mutable state between tests)?
9. Do async tests use `asyncio_mode=auto` and proper fixtures?
10. Are pytest markers applied correctly (unit, integration, contract, e2e)?

**Categories**: `test-coverage`, `test-quality`, `test-edge-case`, `test-isolation`, `test-r19-violation`, `test-marker`

---

### Agent 2: Security Engineer

**Agent definition**: `.claude/agents/security-engineer.md`
**Review materials**: `.claude/review/checklists/REVIEW_CHECKLIST.md` (section 6), `.claude/review/heuristics/HIGH_RISK_PATTERNS.md`

**Mandate — answer these questions for every changed file**:
1. Input validation: are all API inputs validated via Pydantic schemas at the boundary?
2. SQL injection: any raw SQL or f-string SQL? (HR-006 — RED severity)
3. Secrets: any hardcoded credentials, API keys, or tokens? (HR-005 — RED)
4. Authentication: are internal endpoints protected (`X-Internal-Token` or equivalent)?
5. Authorization: do queries filter by `tenant_id`? Any cross-tenant data leakage risk?
6. Deserialization: are Kafka events validated before processing? Malformed event handling?
7. Claim-check: does MinIO/S3 access enforce authorization? Can one tenant read another's objects?
8. Content injection: for content ingestion (S4), is external HTML/RSS sanitized?
9. Logging: are secrets, PII, or tokens ever logged? (structlog only, never stdlib)
10. Config: all secrets via env vars / pydantic-settings? No defaults for production secrets?
11. DDL safety: for migrations, are there destructive operations (DROP, TRUNCATE) without safeguards?
12. Dependency: any new dependencies with known CVEs?

**Categories**: `security-injection`, `security-auth`, `security-secrets`, `security-tenant-isolation`, `security-input-validation`, `security-config`, `security-logging`

---

### Agent 3: Data Platform Engineer

**Agent definition**: `.claude/agents/data-platform-engineer.md`
**Review materials**: `.claude/review/checklists/KAFKA_PIPELINE_CHECKLIST.md`, `.claude/review/checklists/STORAGE_IO_CHECKLIST.md`, `.claude/review/knowledge/STORAGE_ATOMICITY_PATTERNS.md`, `.claude/review/roles/data_pipeline_reviewer.md`

**Mandate — answer these questions for every changed file**:
1. Avro schemas: do all schemas have required envelope fields (event_id, event_type, schema_version, occurred_at)?
2. Schema evolution: are new fields added with defaults (forward-compatible)? Any removed/renamed fields?
3. Kafka topics: correct naming, partition count, retention, cleanup policy?
4. Outbox pattern: is DB + Kafka always via outbox (never separate transactions)? (SA-004 — BLOCKING)
5. Claim-check: payloads > 1MB use MinIO with pointer in Kafka event?
6. DDL correctness: column types match Avro field types? Indexes correct? Partitions correct?
7. Seed data: values match PRD exactly (decay_alpha formulas, trust weights, relation types)?
8. Partition strategy: `relations` hash-partitioned by subject_entity_id (8 partitions)? `partition_key` GENERATED ALWAYS AS STORED?
9. pgvector: HNSW indexes on correct columns with correct dimensions (1024)?
10. MinIO key format: follows `KeyBuilder` convention? Bronze/silver layer separation?
11. Consumer idempotency: event_id dedup or upsert on natural key?
12. DLQ: unprocessable events routed to dead letter queue?

**Categories**: `data-schema`, `data-kafka`, `data-outbox`, `data-ddl`, `data-seed`, `data-partition`, `data-storage`, `data-idempotency`

---

### Agent 4: Distributed Systems Reviewer

**Review role**: `.claude/review/roles/distributed_systems_reviewer.md`
**Review materials**: `.claude/review/knowledge/DISTRIBUTED_SYSTEM_PATTERNS.md`, `.claude/review/checklists/KAFKA_PIPELINE_CHECKLIST.md`, `.claude/review/roles/failure_mode_investigator.md`, `.claude/review/protocols/FAILURE_MODE_ANALYSIS.md`

**Mandate — answer these questions for every changed file with side effects**:
1. For each function with side effects (DB write, Kafka publish, cache mutation, API call, file I/O):
   - Decompose into discrete steps
   - What happens if each step fails?
   - Is the system left in a consistent state?
2. Consumer safety: offset committed after processing (not before)? Rebalance-safe?
3. Concurrent writes: race conditions on shared state? Upsert or compare-and-swap?
4. Cross-service: no direct DB access across service boundaries? Only Kafka or REST?
5. Eventual consistency: is it acceptable for each cross-service interaction?
6. intelligence_db: S6 and S7 write different table sets? Conflict resolution present?
7. Cache consistency: Valkey cache invalidated on source-of-truth changes?
8. Backpressure: S6/S7 with Ollama — semaphore, queue depth monitoring, consumer pause/resume?
9. Known patterns: check against DS-001 through DS-007 and SA-001 through SA-006
10. Partial failure: what is the worst-case system state after any single step failure?

**Categories**: `ds-failure-mode`, `ds-consistency`, `ds-idempotency`, `ds-concurrency`, `ds-cross-service`, `ds-cache`, `ds-backpressure`, `ds-known-pattern`

---

### Agent 5: Architecture Decision Lead

**Agent definition**: `.claude/agents/architecture-decision-lead.md`
**Review materials**: `.claude/review/protocols/PR_INVESTIGATION_PROTOCOL.md`, `.claude/review/protocols/INVARIANT_ANALYSIS.md`

**Mandate — answer these questions across the full scope**:
1. Layer boundaries: does any domain module import from infrastructure? Any API module import from infrastructure directly (bypassing application)?
2. Port pattern: are application-layer ports (ABCs) defined for all infrastructure dependencies?
3. Forward-compatibility: are all schema changes additive? New fields have defaults?
4. PRD alignment: if `--plan` scope, does the implementation match the plan's acceptance criteria?
5. Cross-cutting consistency: do naming conventions, error patterns, and config patterns match existing services (portfolio, market-ingestion, market-data)?
6. Event envelope: all events include event_id (UUIDv7), event_type, schema_version, occurred_at?
7. Shared lib usage: `common.ids.new_uuid7()` for IDs? `common.time.utc_now()` for timestamps? `structlog` for logging?
8. Config pattern: pydantic-settings with env vars? No hardcoded config values?
9. Service dependencies: correct in docker-compose? Init containers before services?
10. Documentation: are `.claude-context.md`, service docs, and MASTER_PLAN consistent with implementation?
11. If `--plan` scope: verify every task's acceptance criteria is satisfied

**Categories**: `arch-layer-violation`, `arch-port-pattern`, `arch-compatibility`, `arch-prd-alignment`, `arch-consistency`, `arch-config`, `arch-docs`, `arch-dependency`

---

## Phase 3: Consolidation

After all 5 agents complete:

### 3.1 Collect all findings
Gather findings from all agents into a single list.

### 3.2 Deduplicate and Score Confidence
If two or more agents report the same issue (same file + same line + same underlying problem), merge into one finding. Keep the most specific description and the highest severity.

**Assign a confidence level to each finding:**
- **HIGH (85-100)**: Flagged by 2+ agents independently, or backed by concrete evidence (failing test, lint error, explicit rule violation)
- **MEDIUM (50-84)**: Flagged by 1 agent with clear reasoning and code reference
- **LOW (0-49)**: Flagged by 1 agent based on heuristic/pattern match without concrete evidence

**Confidence rules:**
- Issues flagged by multiple agents independently → automatically upgrade to HIGH
- Issues matching a known bug pattern (BP-XXX) or high-risk pattern (HR-XXX) → upgrade one level
- Findings with confidence < 50 → downgrade to NIT regardless of original severity
- Include confidence in the finding format: `- **Confidence**: HIGH | MEDIUM | LOW`
- Include which agents flagged it: `- **Flagged by**: [agent names]`

### 3.3 Classify and sort
Sort findings by: severity (`BLOCKING` > `CRITICAL` > `MAJOR` > `MINOR` > `NIT`), then by confidence (HIGH > MEDIUM > LOW) within each severity level.

### 3.4 Triage into action buckets

**Bucket A — Auto-fixable** (apply immediately):
- Lint/formatting issues (ruff can fix)
- Missing type annotations caught by mypy
- Import ordering
- Missing `# noqa` annotations for known exceptions (S105, S106, N818, DTZ001)

**Bucket B — Clear fix, needs confirmation** (present to user, apply after approval):
- Missing test for a public function
- Missing pytest marker
- Missing Pydantic validation on an endpoint
- Incorrect Avro schema field

**Bucket C — Requires decision** (present to user, wait for direction):
- Architectural choices (e.g., "should this be an event or a REST call?")
- Missing acceptance criteria interpretation
- Trade-offs between approaches

### 3.5 Present consolidated report

```markdown
# QA Review Report

**Date**: YYYY-MM-DD
**Scope**: <plan ID | service name | full | changed-only>
**Branch**: <current branch>
**Agents**: QA/Test, Security, Data Platform, Distributed Systems, Architecture

## Summary
| Severity | Count | Auto-fixable | Needs Confirmation | Needs Decision |
|----------|-------|-------------|-------------------|----------------|
| BLOCKING | N | N | N | N |
| CRITICAL | N | N | N | N |
| MAJOR    | N | N | N | N |
| MINOR    | N | N | N | N |
| NIT      | N | N | N | N |

## Agent Coverage
| Agent | Files Reviewed | Findings | Highest Severity | HIGH Confidence | MEDIUM | LOW |
|-------|---------------|----------|-----------------|-----------------|--------|-----|
| QA/Test | N | N | ... | N | N | N |
| Security | N | N | ... | N | N | N |
| Data Platform | N | N | ... | N | N | N |
| Distributed Systems | N | N | ... | N | N | N |
| Architecture | N | N | ... | N | N | N |

## BLOCKING Issues (must fix before merge)
<findings detail>

## CRITICAL Issues (should fix before merge)
<findings detail>

## MAJOR Issues
<findings detail>

## MINOR Issues
<findings detail>

## NITs
<findings detail>

## Decisions Needed
| ID | Question | Context | Options |
|----|----------|---------|---------|
```

---

## Phase 4: Fix Application

### 4.1 Auto-fix (Bucket A)
Apply auto-fixable changes:
```bash
ruff check --fix libs/ services/
ruff format libs/ services/
```
For other auto-fixable items (missing markers, noqa annotations), apply directly.

### 4.2 User-confirmed fixes (Bucket B)
Present each fix to the user. Apply after confirmation. If the user says to fix all, apply all at once.

### 4.3 Decision items (Bucket C)
Present decisions needed. Wait for user input on each. Do NOT proceed with Phase 5 until all BLOCKING decisions are resolved.

---

## Phase 5: Full Validation — All Services, All Test Layers

Execute the **complete** test suite across **every** service and library, regardless of scope. This is the final gate — nothing is excluded.

### Layer 1: Architecture Tests
```bash
python -m pytest tests/architecture -v 2>&1 || true
```
**Pass criteria**: All architecture tests pass
**If fails**: STOP — architecture violations must be fixed first

### Layer 2: Lint & Type Check
```bash
# Ruff lint — all libs and services
ruff check libs/ services/

# Ruff format check
ruff format --check libs/ services/

# mypy — all libs and services
# Run per-service/lib to respect individual mypy.ini configs
for svc_src in services/*/src; do
  svc_dir=$(dirname "$svc_src")
  if [ -f "$svc_dir/mypy.ini" ]; then
    mypy "$svc_src" --config-file "$svc_dir/mypy.ini"
  fi
done
for lib_src in libs/*/src; do
  lib_dir=$(dirname "$lib_src")
  if [ -f "$lib_dir/mypy.ini" ]; then
    mypy "$lib_src" --config-file "$lib_dir/mypy.ini"
  fi
done
```
**Pass criteria**: Zero errors
**If fails**: Log all failures, continue to collect full picture, mark QA as FAILED

### Layer 3: Shared Library Unit Tests
Run unit tests for **every** library:
```bash
for lib in libs/*/; do
  lib_name=$(basename "$lib")
  if [ -d "$lib/tests" ]; then
    echo "=== Testing lib: $lib_name ==="
    (cd "$lib" && python -m pytest tests/ -m "unit" -v --tb=short) || FAILURES="$FAILURES $lib_name"
  fi
done
```
**Pass criteria**: All library tests pass across all libs

### Layer 4: Service Unit Tests
Run unit tests for **every** service:
```bash
for svc in services/*/; do
  svc_name=$(basename "$svc")
  if [ -d "$svc/tests" ]; then
    echo "=== Testing service: $svc_name ==="
    (cd "$svc" && python -m pytest tests/ -m "unit" -v --tb=short) || FAILURES="$FAILURES $svc_name"
  fi
done
```
**Pass criteria**: All unit tests pass across all services (portfolio, market-ingestion, market-data, content-ingestion, market-analytics, nlp-enrichment, knowledge-graph, rag-query, api-gateway, alert-delivery, intelligence-migrations)

### Layer 5: Contract Tests
Run contract tests for **every** service:
```bash
for svc in services/*/; do
  svc_name=$(basename "$svc")
  if [ -d "$svc/tests" ]; then
    echo "=== Contract tests: $svc_name ==="
    (cd "$svc" && python -m pytest tests/ -m "contract" -v --tb=short) || FAILURES="$FAILURES $svc_name"
  fi
done
```
Also run any top-level contract tests:
```bash
if [ -d "tests/contract" ]; then
  python -m pytest tests/contract -v --tb=short
fi
```
**Pass criteria**: All contract tests pass

### Layer 6: Integration Tests
Requires infrastructure. Check and start if needed:
```bash
# Check if test infra is running
if ! docker compose -f infra/compose/docker-compose.test.yml --profile all ps --services --filter "status=running" 2>/dev/null | grep -q postgres; then
  echo "Starting test infrastructure..."
  docker compose -f infra/compose/docker-compose.test.yml --profile all up -d --build --wait
fi
```

Run integration tests for **every** service:
```bash
for svc in services/*/; do
  svc_name=$(basename "$svc")
  if [ -d "$svc/tests" ]; then
    echo "=== Integration tests: $svc_name ==="
    (cd "$svc" && python -m pytest tests/ -m "integration" -v --tb=short) || FAILURES="$FAILURES $svc_name"
  fi
done
```
Also run library integration tests:
```bash
for lib in libs/*/; do
  lib_name=$(basename "$lib")
  if [ -d "$lib/tests" ]; then
    echo "=== Integration tests lib: $lib_name ==="
    (cd "$lib" && python -m pytest tests/ -m "integration" -v --tb=short) || FAILURES="$FAILURES $lib_name"
  fi
done
```
**Pass criteria**: All integration tests pass
**Note**: If infra cannot be started, log as SKIPPED (not FAILED) with clear reason

### Layer 7: E2E Tests
Run E2E tests for **every** service (requires full infra from Layer 6):
```bash
for svc in services/*/; do
  svc_name=$(basename "$svc")
  if [ -d "$svc/tests" ]; then
    echo "=== E2E tests: $svc_name ==="
    (cd "$svc" && python -m pytest tests/ -m "e2e" -v --tb=short) || FAILURES="$FAILURES $svc_name"
  fi
done
```
**Pass criteria**: All E2E tests pass

### Layer 8: Frontend Unit Tests (if applicable)
```bash
if [ -d "apps/frontend" ] && [ -f "apps/frontend/package.json" ]; then
  (cd apps/frontend && pnpm test 2>&1) || FAILURES="$FAILURES frontend-unit"
  (cd apps/frontend && pnpm typecheck 2>&1) || FAILURES="$FAILURES frontend-type"
fi
```
**Pass criteria**: All frontend tests and type checks pass

### Layer 9: Frontend E2E (if applicable)
```bash
if [ -d "apps/frontend" ] && [ -f "apps/frontend/package.json" ]; then
  (cd apps/frontend && pnpm exec playwright test 2>&1) || FAILURES="$FAILURES frontend-e2e"
fi
```
**Pass criteria**: All Playwright tests pass

---

## Supplementary Checks

Run these regardless of scope:

### S1: Import Guard Validation
```bash
if [ -f "scripts/import_guards/check_import_guards.py" ]; then
  python scripts/import_guards/check_import_guards.py
fi
```

### S2: Service Structure Validation
```bash
if [ -f "scripts/structure_checks/check_service_structure.py" ]; then
  python scripts/structure_checks/check_service_structure.py --strict
fi
```

### S3: Avro Schema Validation
```bash
if [ -f "scripts/gen-contracts.sh" ]; then
  ./scripts/gen-contracts.sh
fi
```

### S4: Documentation Freshness
For each service in the repository, check:
- `docs/services/<service>.md` exists and was updated if code changed
- `services/<service>/.claude-context.md` is current
- `docs/MASTER_PLAN.md` reflects any architectural changes

### S5: Security Quick Scan
```bash
if [ -f "scripts/hooks/security-scan.sh" ]; then
  ./scripts/hooks/security-scan.sh $(find libs/ services/ -name '*.py' -newer .git/refs/heads/main)
fi
```

### S6: Dependency Check
- Check for new dependencies added without `pyproject.toml` updates
- Verify no known CVEs in new dependencies (if tooling available)

---

## QA Report — Final Output

Produce the final consolidated report combining review findings and test results:

```markdown
# QA Report

**Date**: YYYY-MM-DD
**Scope**: <plan-scoped | service | full | changed-only>
**Branch**: <current branch>
**Verdict**: PASS | PASS_WITH_WARNINGS | FAIL

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| QA/Test | N | N | N | N | N | N | N |
| Security | N | N | N | N | N | N | N |
| Data Platform | N | N | N | N | N | N | N |
| Distributed Systems | N | N | N | N | N | N | N |
| Architecture | N | N | N | N | N | N | N |
| **Total** | — | **N** | **N** | **N** | **N** | **N** | **N** |

### Cross-Agent Signals (HIGH Confidence)
<Issues flagged by 2+ agents independently — these are the highest-confidence findings and should be prioritized>

### Fixes Applied
| Finding | Fix | Status |
|---------|-----|--------|
| F-001 | Auto-fixed: ruff format | APPLIED |
| F-005 | Added missing test | APPLIED (confirmed) |
| ... | ... | ... |

### Decisions Made
| Finding | Decision | Rationale |
|---------|----------|-----------|
| F-012 | Deferred to next wave | User decision: not blocking |
| ... | ... | ... |

### Open Items
| Finding | Status | Owner |
|---------|--------|-------|
| F-017 | Needs follow-up | User |
| ... | ... | ... |

---

## Test Execution Results

| Layer | Scope | Tests | Passed | Failed | Skipped | Status |
|-------|-------|-------|--------|--------|---------|--------|
| Architecture | full | N | N | N | N | PASS/FAIL |
| Lint (ruff) | full | — | — | N errors | — | PASS/FAIL |
| Type Check (mypy) | full | — | — | N errors | — | PASS/FAIL |
| Library Unit | all libs | N | N | N | N | PASS/FAIL |
| Service Unit | all services | N | N | N | N | PASS/FAIL |
| Contract | all services | N | N | N | N | PASS/FAIL |
| Integration | all services | N | N | N | N | PASS/FAIL/SKIP |
| E2E | all services | N | N | N | N | PASS/FAIL/SKIP |
| Frontend Unit | apps/frontend | N | N | N | N | PASS/FAIL/N/A |
| Frontend E2E | apps/frontend | N | N | N | N | PASS/FAIL/N/A |

### Per-Service Breakdown
| Service | Unit | Contract | Integration | E2E | Overall |
|---------|------|----------|-------------|-----|---------|
| portfolio | P/F | P/F | P/F | P/F | PASS/FAIL |
| market-ingestion | P/F | P/F | P/F | P/F | PASS/FAIL |
| market-data | P/F | P/F | P/F | P/F | PASS/FAIL |
| content-ingestion | P/F | P/F | P/F | P/F | PASS/FAIL |
| market-analytics | P/F | P/F | P/F | P/F | PASS/FAIL |
| nlp-enrichment | P/F | P/F | P/F | P/F | PASS/FAIL |
| knowledge-graph | P/F | P/F | P/F | P/F | PASS/FAIL |
| rag-query | P/F | P/F | P/F | P/F | PASS/FAIL |
| api-gateway | P/F | P/F | P/F | P/F | PASS/FAIL |
| alert-delivery | P/F | P/F | P/F | P/F | PASS/FAIL |
| intelligence-migrations | P/F | P/F | P/F | P/F | PASS/FAIL |

### Per-Library Breakdown
| Library | Unit | Integration | Overall |
|---------|------|-------------|---------|
| common | P/F | P/F | PASS/FAIL |
| contracts | P/F | P/F | PASS/FAIL |
| messaging | P/F | P/F | PASS/FAIL |
| storage | P/F | P/F | PASS/FAIL |
| observability | P/F | P/F | PASS/FAIL |
| ml-clients | P/F | P/F | PASS/FAIL |

---

## Supplementary Checks
| Check | Status | Notes |
|-------|--------|-------|
| Import Guards | PASS/FAIL | ... |
| Service Structure | PASS/FAIL | ... |
| Schema Validation | PASS/FAIL | ... |
| Doc Freshness | PASS/WARN | ... |
| Security Scan | PASS/WARN | ... |
| Dependency Check | PASS/WARN | ... |

---

## Failures Detail
<For each failure: test name, error message, likely cause, suggested fix>

## Warnings
<Documentation staleness, skipped layers, non-critical issues>

## Recommendations
- <Specific fixes needed before merge/release>
- <Test gaps identified — consider invoking `/test-feature`>
- <Documentation updates needed>
```

---

## Verdict Logic

- **PASS**: Zero BLOCKING/CRITICAL findings remaining + all test layers PASS
- **PASS_WITH_WARNINGS**: Zero BLOCKING findings + all test layers PASS + some CRITICAL/MAJOR items acknowledged
- **FAIL**: Any BLOCKING finding unresolved OR any test layer FAIL (not SKIP)

---

## TRACKING.md Update (MANDATORY)

After producing the QA verdict, you MUST update `docs/plans/TRACKING.md`:

1. **If `--plan` scope**: Find the plan row in Active or Completed tables and set the `QA` column to today's date (e.g., `2026-03-27`).
2. **If service or full scope**: Find ALL plans that touch the reviewed services and update their `QA` column.
3. **If the plan is not in TRACKING.md**: Add it (this indicates a `/plan` or `/implement` skill failed to register it).
4. **Commit the TRACKING.md update** — include it in any fix commits from Phase 4, or create a standalone commit if no fixes were needed.

The `QA` column tracks when the last QA pass was run. `—` means never QA'd. This is non-negotiable — skipping it means the QA pass is unrecorded and may be repeated unnecessarily.

---

## Compounding Value

After each QA run:
1. **New failure pattern?** → Add to `docs/ai-interactions/BUG_PATTERNS.md`
2. **Flaky test found?** → Flag for investigation, note in report
3. **Missing test coverage?** → Recommend invoking `/test-feature`
4. **Documentation drift?** → List specific docs that need updates
5. **New high-risk pattern?** → Add to `.claude/review/heuristics/HIGH_RISK_PATTERNS.md`
6. **Review checklist gap?** → Add to `.claude/review/checklists/REVIEW_CHECKLIST.md`

---

## Workflow Chain — Suggest Next Steps

After completing this skill, suggest the appropriate next skill to the user:
- **If PASS**: Ready to create PR or merge
- **If PASS_WITH_WARNINGS**: Address warnings, then create PR
- **If FAIL (test failures)**: `/fix-bug` for each failing test
- **If FAIL (security issues)**: `/security-audit` for deeper analysis
- **If FAIL (architecture violations)**: `/refactor` to fix structural issues
- **If test gaps identified**: `/test-feature` to add missing coverage

---

## Mandatory Compounding Step (All Skills)

Before completing this skill, check if any of these documents should be updated based on what you learned during this session:

| Document | Update When | Location |
|----------|------------|----------|
| **BUG_PATTERNS.md** | New failure pattern discovered | `docs/ai-interactions/BUG_PATTERNS.md` |
| **STANDARDS.md** | New convention or best practice identified | `docs/STANDARDS.md` |
| **HIGH_RISK_PATTERNS.md** | New code pattern that signals risk | `.claude/review/heuristics/HIGH_RISK_PATTERNS.md` |
| **REVIEW_CHECKLIST.md** | New check that would have caught an issue | `.claude/review/checklists/REVIEW_CHECKLIST.md` |
| **Service .claude-context.md** | Service gained/changed endpoints, topics, entities, pitfalls | `services/<service>/.claude-context.md` |
| **Service docs** | API, events, schema, data model, or config changed | `docs/services/<service>.md` |
| **MASTER_PLAN.md** | System-wide architectural change | `docs/MASTER_PLAN.md` |
| **Skill definitions** | Workflow step proved insufficient or needs improvement | `.claude/skills/<skill>/SKILL.md` |
| **Agent definitions** | Agent guidance needs refinement based on real usage | `.claude/agents/<agent>.md` |
| **RULES.md** | New hard rule identified from a failure | `RULES.md` |

**This is not optional.** The compounding effect is what makes the system improve over time. Even if no updates are needed, explicitly confirm: "Compounding check: no updates needed."
