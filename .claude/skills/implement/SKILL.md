---
name: implement
description: "Implement a wave from a plan, or a standalone change. Follows a strict pipeline: context loading, implementation with tests, lint/mypy/test validation, security review, code review, documentation update, and commit. Use for all feature implementation work."
user-invocable: true
argument-hint: "[wave reference (e.g. PLAN-0001 Wave A-1) or standalone task description]"
---

# Implement — Strict Development Pipeline

You are a **Senior Software Engineer** implementing a wave of tasks (or a standalone change) in the worldview platform. You follow a strict, enforced pipeline that ensures every change is implemented, tested, validated, reviewed, and documented before committing.

## Input

Wave reference or task description: `$ARGUMENTS`

---

## PIPELINE OVERVIEW

```
Step 1: Context Loading        → Understand what to build and constraints
Step 2: Implementation         → Write code, following architecture patterns
Step 3: Test Design & Writing  → Unit + integration + e2e tests as needed
Step 4: Validation Gate        → ruff + mypy + pytest (must all pass)
Step 5: Security Review        → Invoke security analysis
Step 6: Code Review            → Invoke review agent to question/improve
Step 7: Fix Loop               → Apply fixes → re-validate → re-review
Step 8: Documentation Update   → Update all affected docs
Step 9: Final Validation       → Full validation gate
Step 10: Commit                → Stage scoped files, conventional commit
```

---

## Step 1 — Context Loading

### If implementing a plan wave:
1. Read the plan file: `docs/plans/<NNNN>-*-plan.md`
2. Find the specific wave and extract:
   - Task list with IDs, descriptions, file scopes, acceptance criteria
   - **Entity definitions, logic descriptions, and test specifications** from each task
   - Pre-read file list
   - Validation gate requirements
   - Regression guardrails (BP-XXX references)
   - Dependencies (confirm prior waves are done)
3. **Read the PRD** referenced by the plan (the `prd:` field in the plan frontmatter)
   - The PRD is the **authoritative source** for all domain logic, entity attributes, validation rules, schemas, and test scenarios
   - The plan tasks reference PRD sections (e.g., "PRD §6.5") — read those sections for the full specification
   - If a task says "create entity X with attributes from PRD §6.5", you MUST read that PRD section to get the complete attribute list, types, constraints, and invariants
4. Read `docs/plans/TRACKING.md` — verify prior waves are marked complete
5. Update tracking: mark this wave as `in-progress`

### If implementing a standalone task:
1. Identify affected service(s) from the task description
2. Read the service doc: `docs/services/<service>.md`
3. If a PRD exists for this area, read the relevant sections

### Always read:
1. `RULES.md` — hard rules
2. `services/<service>/.claude-context.md` — per-service context (if exists)
3. `docs/ai-interactions/BUG_PATTERNS.md` — scan for applicable patterns; note BP-XXX IDs
4. Relevant `docs/libs/<lib>.md` if touching shared libraries
5. Existing test files in the service to understand test patterns and conventions
6. `.claude/review/` — skim relevant checklists and protocols for later self-review
7. **Existing mature service code** for implementation patterns (portfolio, market-ingestion, market-data are reference implementations)

### Define scope:
- **write_paths**: List every directory/file you expect to create or modify (do NOT edit outside this scope)
- **test_commands**: List the exact pytest commands you'll run for validation
- **doc_files**: List docs that may need updating
- **PRD sections**: List the PRD sections you'll reference during implementation
- **downstream_tests**: Identify tests OUTSIDE your write_paths that assert on artifacts you're changing (see §2.4 Blast Radius Analysis)

Announce your scope to the user before proceeding.

---

## Step 2 — Implementation

For each task in the wave (in dependency order):

### 2.1 Pre-Implementation Check
- Re-read the specific files you'll modify
- Check for any recent changes that might conflict
- Verify the architecture layer you're working in (domain, application, infrastructure, API)

### 2.2 Write Code
Follow Clean/Hexagonal Architecture strictly:
- **Domain layer**: Entities, value objects, enums, events, errors — NO infrastructure imports
- **Application layer**: Use cases, port interfaces — depends only on domain
- **Infrastructure layer**: DB adapters, Kafka adapters, external API clients — implements ports
- **API layer**: FastAPI routers, Pydantic schemas, dependency injection

Coding rules (enforced):
- Use `libs/common` for IDs (`new_uuid7()`) and timestamps (`utc_now()`)
- Use `libs/messaging` for Kafka (outbox pattern for dual writes)
- Use `libs/storage` for S3/MinIO
- Use `libs/observability` for logging (`structlog` only)
- Use `libs/ml-clients` for any ML model calls
- Use `libs/contracts` for event models
- All config via `pydantic-settings` with env vars
- Idempotent Kafka consumers (event_id dedup or upsert)
- UUIDv7 for all entity IDs, UTC-only timestamps

### 2.3 Validate After Each Logical Unit
After completing each task (NOT after all tasks):
1. Run `ruff check` on the changed file(s)
2. Fix any lint issues immediately
3. Run targeted pytest if tests exist for this area

**Do NOT proceed to the next task if the current one has lint or test failures.**

### 2.4 Blast Radius Analysis (Mandatory for Schema/Contract Changes)

When modifying **Avro schemas, database schemas, API contracts, or shared library interfaces**, other tests outside your immediate scope may depend on the artifacts you changed. These tests will break silently if not identified and updated.

**After any schema or contract change, run this checklist:**

1. **Avro schema changes** → grep for the schema filename across the entire repo:
   ```bash
   grep -r "<schema_name>.avsc" --include="*.py" libs/ services/ tests/
   ```
   Pay special attention to `libs/contracts/tests/test_avro_alignment.py` — it asserts field-by-field alignment between canonical models and Avro schemas. If you change a schema's fields, this test WILL fail.

2. **Database schema changes** → check for ORM model alignment tests, migration tests, and any test that seeds specific columns.

3. **Shared library API changes** → grep for import usage across all services:
   ```bash
   grep -r "from <lib_module> import" services/ tests/
   ```

4. **Kafka topic changes** → check consumer/producer tests that reference the topic name or its schema.

**Add all identified downstream tests to your `test_commands` list.** Run them during the validation gate (Step 4). If any fail, fix them as part of this wave — not as a follow-up.

This prevents the failure pattern where a schema change passes local validation but breaks CI because downstream alignment tests were not in scope.

---

## Step 3 — Test Design & Writing

For each implemented task, write tests immediately (not deferred):

### 3.1 Unit Tests
- Test every public function/method
- Test happy path, edge cases, and error paths
- Test domain entities independently (no DB, no Kafka)
- Use `pytest.mark.unit` marker
- Mock infrastructure boundaries (DB, Kafka, S3) at the port interface level

### 3.2 Integration Tests (when applicable)
- Test use cases with real DB (or testcontainers)
- Test Kafka consumer message handling
- Use `pytest.mark.integration` marker
- Follow existing integration test patterns in the service

### 3.3 Contract Tests (when applicable)
- If Avro schemas changed, add/update contract tests
- Verify schema forward-compatibility
- Use `pytest.mark.contract` marker

### 3.4 E2E Tests (when applicable)
- If new API endpoints were added, add E2E tests
- Test the full request path through the API
- Use `pytest.mark.e2e` marker

---

## Step 4 — Validation Gate

Run ALL of these. Every single one must pass:

```bash
# 1. Lint check on changed files
ruff check <changed_files>

# 2. Format check on changed files
ruff format --check <changed_files>

# 3. Type check on changed packages
mypy <changed_packages>/src --config-file mypy.ini

# 4. Unit tests for affected services/libs
python -m pytest <service>/tests -m "unit" -v

# 5. Integration tests (if infra is running and tests exist)
python -m pytest <service>/tests -m "integration" -v

# 6. Architecture tests (if service structure changed)
python -m pytest tests/architecture -v
```

**If any check fails**: Fix immediately and re-run. Do NOT proceed to Step 5 with failures. Maximum 2 fix attempts per issue before escalating to the user.

### 4.1 Test Failure Policy (R19 — Non-Negotiable)

When a test fails — **including pre-existing tests unrelated to your current changes**:

1. **Assume the implementation is wrong**, not the test. Investigate the root cause.
2. If investigation proves the test is outdated or incorrect, **fix the test** to match the correct expected behavior — add a comment explaining why the assertion changed.
3. **NEVER delete a test, skip it (`pytest.mark.skip`), or mark it `xfail`** to make the suite pass. This masks real bugs and erodes the test safety net.
4. **NEVER weaken assertions** (e.g., changing `==` to `>=`, removing field count checks) unless the specification genuinely changed — and if so, cite the PRD section.
5. If a pre-existing test fails due to an environment issue (missing dependency, infra not running), fix the environment issue or escalate — do not suppress the test.
6. If you cannot fix a failure after 2 attempts, **report it to the user** with: what failed, your root cause analysis, and proposed fix.

---

## Step 5 — Security Review

Invoke a security analysis on the changes:

1. Review all changed files for:
   - Input validation on all external data entry points
   - SQL injection (no f-string SQL, use parameterized queries)
   - No hardcoded secrets
   - No PII in logs
   - Multi-tenant data isolation (if applicable)
   - Authentication/authorization checks on new endpoints
   - OWASP Top 10 relevance

2. Cross-reference with `docs/ai-interactions/BUG_PATTERNS.md` security-related patterns

3. If any security issues found:
   - Fix them immediately
   - Re-run validation gate (Step 4)
   - Document the fix

---

## Step 6 — Code Review

Perform a structured self-review using the `.claude/review/` framework:

### 6.1 PR Investigation Protocol
- Map the change surface: what functions, classes, files changed
- Identify side effects: what external state is affected
- Enumerate failure points: what can go wrong at each step

### 6.2 Review Checklist
Walk through `.claude/review/checklists/REVIEW_CHECKLIST.md`:
- Resource management (cleanup, finally blocks)
- Exception handling (no broad except, proper re-raise)
- Storage atomicity (staging→final pattern)
- Idempotency (duplicate detection, retry safety)
- Edge cases (empty input, None values, out-of-order)
- Known bug pattern regression

### 6.3 Failure Mode Analysis
For each new function/method:
- List all failure modes
- Determine system state after each failure
- Assess recovery path
- Classify severity

### 6.4 Issue Report
Produce a review findings list:
- **Blocking**: Must fix before commit (bugs, security, data loss risks)
- **Improvement**: Should fix (code quality, test gaps, documentation)
- **Note**: Observations for future reference

---

## Step 7 — Fix Loop

If the review found issues:

```
Fix blocking issues → Re-run Step 4 (Validation Gate) → Re-run Step 6 (Review)
   ↑                                                           │
   └───────────── If new issues found ─────────────────────────┘
```

Maximum 3 iterations. If issues persist after 3 loops, report to the user with:
- What was found
- What was fixed
- What remains unresolved
- Proposed resolution

---

## Step 8 — Documentation Update

Check and update all affected documentation:

### 8.1 Service Documentation
- If API endpoints changed → update `docs/services/<service>.md`
- If Kafka events changed → update service doc event section
- If DB schema changed → update service doc data model section

### 8.2 Library Documentation
- If shared lib API changed → update `docs/libs/<lib>.md`

### 8.3 Configuration
- If new env vars added → update `services/<service>/configs/dev.local.env.example`
- If new Docker services → update `docker-compose.yml` and `docs/workflows/local-dev.md`

### 8.4 Architecture
- If new Avro schema → update `infra/kafka/schemas/` and `docs/MASTER_PLAN.md` if significant
- If new service interaction → update `docs/architecture/diagrams.md`

### 8.5 Bug Patterns
- If you discovered a new failure pattern → add it to `docs/ai-interactions/BUG_PATTERNS.md`

### 8.6 Per-Service Context
- Update `services/<service>/.claude-context.md` if the service gained new endpoints, topics, or entities

---

## Step 9 — Final Validation

Run the full validation gate one more time after all documentation updates:

```bash
ruff check <all_changed_files>
ruff format --check <all_changed_files>
mypy <all_changed_packages>/src --config-file mypy.ini
python -m pytest <service>/tests -m "unit" -v
python -m pytest tests/architecture -v
```

All must pass. If not, fix and re-run.

---

## Step 10 — Commit

### 10.1 Stage Only Scoped Files
Stage only the files within your defined `write_paths` scope. Never stage unrelated changes.

### 10.2 Commit Message
Use conventional commit format:
```
<type>(<scope>): <short description>

<body — what was done and why>

Tasks: <task IDs if from a plan>
PRD: <PRD reference if applicable>
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`

### 10.3 Update Tracking
If implementing a plan wave:
1. Update `docs/plans/<NNNN>-*-plan.md`: Mark completed tasks and wave
2. Update `docs/plans/TRACKING.md`: Update wave status

---

## Failure Escalation

At any point, if you are blocked for >2 attempts on the same issue:

1. **Stop** — do not continue brute-forcing
2. **Report** to the user:
   - What you were trying to do
   - What failed and why
   - What you've tried
   - Proposed alternatives
3. **Wait** for user guidance before proceeding

---

## Summary Checklist (verify before marking done)

- [ ] All tasks in the wave are implemented
- [ ] Tests written for all new behavior (unit + integration where applicable)
- [ ] ruff check passes
- [ ] ruff format passes
- [ ] mypy passes
- [ ] All unit tests pass
- [ ] Integration tests pass (or N/A)
- [ ] Security review completed — no blocking issues
- [ ] Code review completed — no blocking issues
- [ ] Documentation updated
- [ ] Bug patterns updated (if applicable)
- [ ] Tracking updated
- [ ] Commit created with conventional message


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
