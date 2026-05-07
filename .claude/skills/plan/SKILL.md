---
name: plan
description: "Generate a structured implementation plan from a PRD. Breaks the PRD into distinct service-level plans, each decomposed into dependency-ordered waves of tasks. Use after /prd to prepare for implementation."
user-invocable: true
argument-hint: "[PRD ID or path, e.g. PRD-0001 or docs/specs/0001-feature.md]"
effort: medium
---

# Plan Generation — From PRD to Implementation Waves

You are a **Staff Engineer / Technical Program Manager** responsible for breaking a PRD into actionable, dependency-ordered implementation plans. Your output must be precise enough that an agent executing `/implement` can pick up any wave and execute it **without needing to make design decisions** — all decisions come from the PRD, the plan provides the execution sequence and task-level detail.

## Input

PRD reference: `$ARGUMENTS`

## Phase -1 — Pre-Flight ID Collision Check (MANDATORY — Run Before Anything Else)

Before loading any context or writing any plan content, run these mechanical checks to avoid ID collisions:

```bash
# 1. Find highest existing rule number in RULES.md
grep -oE 'R[0-9]+' RULES.md | sort -V | tail -5

# 2. Find highest existing PLAN-XXXX in TRACKING.md and docs/plans/
grep -oE 'PLAN-[0-9]+' docs/plans/TRACKING.md | sort -V | tail -5
ls docs/plans/ | grep -oE '^[0-9]+' | sort -V | tail -5

# 3. Find highest existing PRD-XXXX in docs/specs/ and TRACKING.md
ls docs/specs/ | grep -oE '^[0-9]+' | sort -V | tail -5
grep -oE 'PRD-[0-9]+' docs/plans/TRACKING.md | sort -V | tail -5

# 4. Find existing Worker IDs (e.g. W-NNN, Block 13X-N patterns)
grep -rE 'Worker-[0-9]+|Block [0-9]+-[0-9]+|W-[0-9]+' docs/plans/ | grep -oE '(Worker|Block|W)-[0-9]+' | sort -V | uniq | tail -10

# 5. Find highest Alembic migration number per affected service (to avoid number collisions)
# Run this for EVERY service the plan will create migrations for:
ls services/<service>/alembic/versions/ | sort -V | tail -3
ls services/intelligence-migrations/alembic/versions/ | sort -V | tail -3
```

**Alembic migration pre-flight rule**: For every service that will receive a new migration, record the current HEAD filename. The new migration filename must use the next integer (e.g., if HEAD is `0029_foo.py`, the new migration is `0030_bar.py`). Never assign migration numbers from memory or assumptions — the filesystem is authoritative. This prevented a PLAN-0074 collision where the plan assumed HEAD was `0024` but actual HEAD was `0029`.

Record the highest existing number for each ID class. When assigning IDs in this plan:
- **PLAN-XXXX**: next integer after the highest found above
- **R##**: next integer after the highest rule number found above
- **Worker/Block IDs**: next integer after the highest found above

> **Why mandatory**: ID collisions (e.g., two plans both claiming PLAN-0028, or two rules both claiming R28) create irreversible confusion that takes multiple sessions to untangle. The grep above takes 5 seconds and prevents the problem entirely.

## Phase 0 — Context Loading (Silent)

1. Read the referenced PRD **thoroughly** — this is the source of all domain logic, entity definitions, schemas, and test scenarios. Every task you produce must trace back to a specific PRD section.
2. Read `RULES.md` and `AGENTS.md` for constraints
3. Read `docs/MASTER_PLAN.md` for system context
4. Read `docs/STANDARDS.md` for engineering standards
5. Read service docs for each affected service: `docs/services/<service>.md`
6. Read per-service context: `services/<service>/.claude-context.md`
7. Read existing plans in `docs/plans/` to avoid conflicts
8. Read `docs/plans/TRACKING.md` for active work
9. Read `docs/BUG_PATTERNS.md` for patterns to guard against
10. Read existing service source code (especially mature services like portfolio, market-ingestion, market-data) to understand implementation patterns the agent should follow

## Phase 0.5 — PRD Pre-Flight Gate (Mandatory, Blocking)

Before decomposing a single wave, explicitly verify the PRD is ready to plan:

| Check | How to verify | Result |
|-------|--------------|--------|
| No unresolved BLOCKING open questions | Read §14 of the PRD; any OQ without "~~Resolved~~" or classified BLOCKING is a blocker | PASS/FAIL |
| No unverified external API fields | Check if §2.7 Reality Check was done; if PRD was written before this enhancement, manually verify any external fields referenced | PASS/FAIL |
| No active cross-plan conflicts | Read TRACKING.md; no other `in-progress` plan modifies the same service's tables/topics/entities | PASS/FAIL |
| PRD recency check | If PRD `Created` date is > 14 days ago AND the architecture has changed since (check git log), flag for `/revise-prd` before proceeding | PASS/WARN |
| Architecture compliance | No RULES.md violations visible in the PRD design (cross-check §6 against RULES.md) | PASS/FAIL |

**If any row is FAIL**: Present to the user and require resolution before generating waves.
**If WARN (stale PRD)**: Ask the user: "This PRD is X days old. Run `/revise-prd` first, or proceed with awareness?"

## Phase 0.6 — Checkpoint Artifact (Write Early — MANDATORY)

Before beginning any deep exploration or wave decomposition, **write a skeleton plan file** to `docs/plans/<NNNN>-<slug>-plan.md`. This is the session boundary guard: if the session hits a context limit or is interrupted mid-exploration, this artifact preserves at least the plan ID, PRD link, and high-level structure so work can resume without starting over.

Minimum skeleton to write immediately after Phase 0.5 passes:

```markdown
---
id: PLAN-<NNNN>
title: <Plan Title>
prd: PRD-<NNNN>
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# PLAN-<NNNN> — <Title>

## Overview
PRD: [PRD-<NNNN>](../specs/<NNNN>-<slug>.md)
Services affected: <list>
Total estimated waves: TBD (in progress)

## Sub-Plans
<!-- To be populated during Phase 1-2 decomposition -->

## Checkpoint: Plan generation in progress
This file was written as a session boundary guard. If you are resuming a partial plan session, continue from Phase 1 of the /plan skill.
```

Also append this plan immediately to `docs/plans/TRACKING.md` with status `draft` and `0/TBD` waves. This ensures the plan ID is registered even if the session ends before completion.

> **Why mandatory**: Multiple sessions have lost all planning work (hypotheses, service analysis, wave structure) when reaching a context limit mid-decomposition. Writing this skeleton costs 30 seconds and saves the full re-run.

## Phase 1 — Plan Decomposition Strategy

### 1.1 Identify Natural Boundaries
Break the PRD into **distinct plans** based on:
- **Service boundaries**: One plan per significantly-affected service
- **Layer boundaries**: Shared library changes get their own plan if substantial
- **Frontend/Backend split**: Frontend work is a separate plan
- **Infrastructure changes**: DB migrations, Kafka topics, Docker changes get a separate plan if substantial

**Why separate plans?** Each plan can be executed in a fresh Claude Code session, optimizing context window usage and reducing token waste.

### 1.2 Dependency Ordering Between Plans
Determine the execution order of plans:
- Infrastructure/schema plans first (DB, Kafka topics, Avro schemas)
- Shared library plans next (libs/ changes that services depend on)
- Backend service plans (in dependency order — producers before consumers)
- Frontend plans last (depend on API gateway being ready)
- Cross-cutting plans (observability, security hardening) can run in parallel with service plans

Present the plan dependency graph to the user for approval.

### 1.3 Codebase State Verification (Mandatory — Read the Code)

For each entity, table, topic, or endpoint referenced in the PRD, **read the actual source files** and document the current state. Do not rely on documentation alone — read the code.

**What to read for each affected service**:
- `services/<svc>/src/<svc>/domain/entities/*.py` — actual entity fields and types
- `services/<svc>/src/<svc>/infrastructure/db/models/*.py` — actual ORM model columns
- `services/<svc>/alembic/versions/` — most recent migration file (current schema head)
- `services/<svc>/src/<svc>/api/routers/*.py` — actual endpoint signatures (path, params, response model)
- `services/<svc>/src/<svc>/application/use_cases/*.py` — existing use case interfaces
- `services/<svc>/tests/` — existing test files (to know what tests will break)
- `infra/kafka/schemas/*.avsc` — actual Avro schema fields and types
- `libs/contracts/src/contracts/*.py` — existing canonical models

Fill in this table with actual values from code (not assumptions):

| PRD Reference | Type | Service | Actual Current State (from code) | PRD Expected State | Delta |
|--------------|------|---------|----------------------------------|--------------------|-------|
| `entity_embedding_state` | DB table | S7 | 6 columns: id, entity_id, model_id, embedding, created_at, updated_at | add `embedding_version` column | migration needed |
| `market.signal.v1` | Kafka topic / Avro schema | S6→S3 | does not exist | new | create schema + topic |
| `GET /api/v1/entities/{id}` | endpoint | S9 | returns EntityPublic (6 fields) | add `description` field | response schema change |
| ... | ... | ... | ... | ... | ... |

**Rules**:
- Every row with a Delta ≠ "none" must have a task in Wave 1 or a prerequisite wave that brings the codebase to the PRD's baseline
- Every Alembic migration delta must specify: current head revision, new revision name, column type with server_default
- Every entity extension delta must specify: which existing tests will break and how they'll be updated
- Every endpoint change must specify: whether existing frontend/consumer code will break

**Do not write any wave tasks until this table is complete.** Tasks written against a stale baseline produce broken implementations.

### 1.4 Name Verification — Mandatory `git grep` Pass (BP-405 Guard)

Before writing any task, **mechanically verify** that every class, method, port field, file path, env var, and Avro schema name mentioned in the plan actually exists in the repository (or is explicitly tagged as new). This pass is non-negotiable — humans cannot reliably catch a hallucinated class name during review because the name *reads correctly*.

**Procedure**:

1. List every class, method, port field, file path, env var, and Avro schema name you intend to mention in the plan. Include both targets you propose to *modify* and targets you propose to *call into*.
2. For each name, run a `git grep` (or `Bash` `grep -rE`) and confirm at least one definition exists. The exact tooling varies by name kind:

| Name kind | Verification command |
|---|---|
| Python class | `git grep -E "^class <Name>(\\(\|:)"` |
| Python function/method | `git grep -E "^( {4})?(async )?def <name>\\("` |
| Pydantic / dataclass field | `git grep -E "<field>: " <suspected_file>` (or scope to the class file) |
| File path | `ls <path>` (must exit 0) |
| Env var | `git grep -E "<ENV_NAME>"` (settings, env files, examples) |
| Avro schema | `ls infra/kafka/schemas/<name>.avsc` |
| Kafka topic | `git grep "<topic.name.v1>"` |
| Endpoint path | `git grep -E "['\"]<path>['\"]"` |

3. Tag every result in the plan body:
   - **Existing target** (the verification returned ≥1 hit) — fine, no tag needed.
   - **NEW target** (the verification returned no hits) — add `(NEW — created in this plan)` next to the first mention. Plan readers (and `/implement`) see this tag and know not to look for the target before this plan ships.
   - **RENAMED target** (an old name is being replaced) — add `(RENAMED in PLAN-NNNN: <old> → <new>)` and write a §0 Revision Log entry on every other plan that references the old name.
4. If a name verification fails and the target is *not* meant to be new, **stop**. Either correct the plan to use the actual name or add a precursor plan/wave that creates the target. Do not paper over it with `(NEW)` if the intent is to call into existing code.

**Why this is mandatory** (not optional):

The 2026-05-07 `/investigate` against PLAN-0066/0067/0074 found three concurrent plans that all referenced classes (`ChatOrchestratorUseCase`, `RunChatUseCase`) and port fields (`ChunkSearchRequest.entity_tickers`, `entity_mentions`) that did not exist anywhere in the repo. Each plan was reviewed by humans and approved. The names *read correctly*, so editorial review didn't catch the drift. The fix has to be mechanical. See BP-405 for the full pattern and rationale.

**Do not advance to Phase 2 (wave decomposition) until every name in your plan body has been verified or tagged.**

## Phase 2 — Wave Decomposition (Per Plan)

For each plan, decompose into **waves**. Each wave is a batch of tasks that are:
- Implemented in a single `/implement` session
- Tested and validated together
- Committed as a cohesive unit

### Wave Design Principles
1. **3-6 tasks per wave** (target); max 8 for simple tasks
2. **No cross-wave dependencies within a wave** — all tasks in a wave can be done in any order
3. **Wave N+1 may depend on Wave N** — but never on a future wave
4. **Each wave must leave the codebase in a green state** — all tests pass after the wave
5. **Effort target**: 30-90 minutes per wave (for an agent)
6. **Context efficiency**: Tasks in a wave should touch related files to minimize context loading
7. **Follow architectural layers**: Wave 1 = domain + config, Wave 2 = infrastructure/adapters, Wave 3 = application/use-cases, Wave 4 = API + wiring, Wave N = integration tests

### Task Dependency Tracking

Each task MUST include explicit dependency metadata:

```markdown
**depends_on**: [T-<ID>, ...] or "none"
**blocks**: [T-<ID>, ...] or "none"
```

**Rules**:
- Tasks with `depends_on: none` are **immediately claimable** and can run in parallel
- A task cannot start until ALL tasks in its `depends_on` list are DONE
- The `blocks` field is informational — it helps identify critical-path tasks
- When two tasks in the same wave have `depends_on: none` and touch **different services**, they can be executed in parallel worktrees via `/implement`
- The `/implement` skill MUST check dependency status before starting a task

### Task Detail Requirements

**Each task must include these sections** (not just a one-line description):

```markdown
#### T-<ID>: <Task Title>

**Type**: impl | test | config | schema | docs
**depends_on**: [T-<ID>, ...] or "none"
**blocks**: [T-<ID>, ...] or "none"
**Target files**: <exact file paths that will be created or modified>
**PRD reference**: §<section> (so the agent can look up the full spec)

**What to build**:
<2-5 sentences explaining what this task produces and why it exists in this wave>

**Entities / Components** (for impl tasks):
For each entity, class, or module this task creates:
- **Name**: <EntityName>
- **Purpose**: <why it exists>
- **Key attributes**: <list with types and validation rules — pulled from PRD §6.5>
- **Key methods**: <list with signatures and behavior>
- **Invariants**: <what must always be true>
- **Depends on**: <other entities/modules from this or prior waves>

**Port interfaces** (MANDATORY for every use case or worker task):
List every ABC port interface the use case/worker depends on. Concrete infrastructure classes MUST NOT be imported in use cases (R25).
- `IThingRepository` (ABC in `application/ports/repositories.py`) — implemented by `ThingRepository` (infra)
- `IExternalClient` (ABC in `application/ports/clients.py`) — implemented by `ExternalAPIClient` (infra)

If no port exists yet, add a sub-task: "Create ABC port `IThingRepository` in `application/ports/` before this task."

**Read/Write classification** (MANDATORY for every use case task):
- **Read-only?** YES → depends on `ReadOnlyUnitOfWork`; API route uses `ReadUoWDep` (R27)
- **Write?** YES → depends on `UnitOfWork`; API route uses `UoWDep`
- **Dual write (DB + Kafka)?** YES → outbox pattern required (R8)

**Logic & Behavior** (for impl tasks):
- <Step-by-step description of the processing logic>
- <Decision points and their resolution (from PRD)>
- <Error classification: which errors are Retryable vs Fatal>
- <Idempotency strategy if applicable>

**Tests to write** (for test tasks, or inline with impl tasks):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_<name> | <specific assertion> | unit |
| test_<name> | <specific assertion> | unit |
- Minimum test count: <number>
- Edge cases to cover: <list>
- Error paths to cover: <list>

**Downstream test impact** (mandatory for schema/config/contract tasks):
List tests OUTSIDE the target files that assert on the artifacts being changed.
These tests will break if not updated in this wave.
- `libs/contracts/tests/test_avro_alignment.py` — if any Avro schema field names/counts change
- `tests/contract/test_avro_schemas.py` — if schema file added/removed or field counts change
- `<service>/tests/` — if shared lib API, Kafka topic name, or DB schema changes

**Acceptance criteria**:
- [ ] <Specific, verifiable condition>
- [ ] <Specific, verifiable condition>
```

### Task Types
- **impl** — Write production code. Must include inline test specifications.
- **test** — Write test code only (integration, contract, E2E tests that require infrastructure)
- **config** — Configuration changes (env vars, Docker, Kafka topics)
- **schema** — Avro schema changes, DB migrations. Must include exact column types. **Must list downstream test impact.**
- **docs** — Documentation updates

### Task Granularity Rules
- Each task should touch **one layer** of one service (e.g., "Add domain entities for S4" not "Implement S4")
- A task should be completable in **15-30 minutes** by an agent
- A task should have **clear acceptance criteria** (testable, verifiable)
- A task's **file scope** must be explicit — list the directories/files that will be created/modified
- **Every entity and its attributes must be specified in the task** — pulled from the PRD. The agent should not need to read the PRD to know what fields an entity has.

### Wave Structure

Each wave must include:

```markdown
### Wave <N>: <Wave Title>

**Goal**: <One-sentence description of what this wave accomplishes>
**Depends on**: <Wave references, or "none">
**Estimated effort**: <time range>
**Architecture layer**: domain | infrastructure | application | API | integration

#### Tasks
<Detailed tasks as described above>

#### Pre-read (agent must read before starting)
- <List of specific files for context — not entire directories>

#### Validation Gate
- [ ] ruff check passes on changed files
- [ ] mypy passes on changed packages
- [ ] Unit tests pass — minimum <N> new tests
- [ ] Integration tests pass (if applicable)
- [ ] Documentation updated (if API/events/schema changed)
- [ ] No architecture violations (domain has no infra imports)

#### Architecture Compliance (MANDATORY — every wave, no exceptions)
These are the most commonly missed patterns; they must be explicitly checked per wave:
- [ ] **R25 — ABC ports**: Every new use case lists its ABC port dependency in the task spec; no concrete infrastructure class (e.g. `ChunkANNRepository`) is imported in any use case
- [ ] **R27 — ReadOnlyUoW**: Every read-only use case / GET endpoint specifies `ReadOnlyUnitOfWork` + `ReadUoWDep`; write use cases use `UnitOfWork` + `UoWDep`
- [ ] **R10 — UUIDv7**: Every new entity ID field specifies `common.ids.new_uuid7()` — never `uuid.uuid4()`
- [ ] **R11 — UTC timestamps**: Every new timestamp field specifies `common.time.utc_now()` — never `datetime.now()` or `datetime.utcnow()`
- [ ] **R12 — structlog**: Every new worker or use case specifies `structlog.get_logger(__name__)` — never `import logging` or `print()`
- [ ] **R8 — Outbox**: Any task that writes to both DB and Kafka specifies the outbox pattern from `libs/messaging`
- [ ] **R9 — No cross-service DB**: No task queries another service's database directly
- [ ] **R32 — Alembic numbers**: Migration filenames are based on verified current HEAD, not assumed HEAD

#### Break Impact (Mandatory — must not be empty)
List every file outside the target files that will break when this wave's changes are applied, and how to fix each:

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `services/S5/tests/unit/test_article.py` | Article entity gains `relevance_score` field | Add `relevance_score=None` to all Article(...) constructor calls in test fixtures |
| `libs/contracts/src/contracts/article.py` | Canonical model must match new entity | Add `relevance_score: float \| None = None` field |
| `services/S9/tests/api/test_news.py` | GET /api/v1/news response shape changed | Update assert for new `top` path and new response fields |

**Rule**: An agent picking up this wave MUST update all items in this table as part of the wave — not as a follow-up. A wave is not complete until all break-impact items are resolved and all tests pass.

#### Regression Guardrails (Mandatory — must not be empty)
Scan `docs/BUG_PATTERNS.md` and list every pattern applicable to this wave's changes:
- BP-XXX: <specific pattern, how it applies, and what the agent must do to avoid it>

At minimum one guardrail per wave. Waves touching DB: check BP-007, BP-019, BP-032. Waves touching Kafka: check BP-001, BP-017, BP-024. Waves touching external I/O: check BP-025, BP-026, BP-027.
```

## Phase 3 — Cross-Cutting Concerns

For each plan, identify:
- **Contract changes**: Which Avro schemas or API contracts change? These need contract tests.
- **Migration needs**: Which services need Alembic migrations? Order matters.
- **Event flow changes**: Any new Kafka topics or changed event semantics?
- **Configuration changes**: New env vars needed? Update dev.local.env.example.
- **Documentation updates**: Which docs need updating? (service docs, MASTER_PLAN, etc.)

## Phase 4 — Risk Assessment

For the overall implementation:
- **Critical path**: Which plan/wave blocks everything else?
- **Highest risk**: Which wave has the most complex changes or most integration points?
- **Rollback strategy**: If a plan fails mid-way, what's the recovery?
- **Testing gaps**: Are there areas where tests will be difficult?

## Phase 5 — Output

**CRITICAL: Write the plan in chunks.** Large plans should be written section by section:
1. First write the overview, dependency graph, and tracking table
2. Then write each sub-plan's waves one at a time
3. Finally write cross-cutting concerns and risk assessment

### 5.1 Master Plan File
Save to: `docs/plans/<NNNN>-<slug>-plan.md`

### 5.2 Update Tracking Index (MANDATORY)
Append the new plan to `docs/plans/TRACKING.md` Active Plans table. This is non-negotiable — a plan that exists as a file but is not in TRACKING.md is invisible to other skills.

1. **Read TRACKING.md** before appending — verify the plan ID doesn't already exist
2. **Add a row** with: Plan ID, Title, PRD, `draft`, `0/<total_waves>`, `—` (QA column), today's date
3. **Verify after writing** — re-read TRACKING.md to confirm the row was added
4. **Include TRACKING.md in the commit** alongside the plan file

### 5.3 Present Summary to User
Show the user:
- Number of plans, waves, and tasks
- Dependency graph
- Estimated total effort
- Critical path
- Recommended execution order
- Any open questions or risks that need resolution before starting

## Interaction Rules

1. **Present the decomposition strategy** before diving into wave details — get user buy-in on plan boundaries
2. **Flag when a plan is too large** — if a plan has >5 waves, consider splitting it
3. **Flag when tasks are too vague** — every task needs entity definitions, logic description, and test specs
4. **Respect existing patterns** — reference how similar work was done in existing services (read their code)
5. **Consider session boundaries** — each plan should be executable in 1-2 Claude Code sessions
6. **Track task IDs consistently** — format: `T-<plan-letter>-<wave-number>-<sequence>` (e.g., T-A-1-01)
7. **Pull detail from the PRD** — every entity, field, validation rule, and test scenario in a task should cite its PRD section. The plan is an execution sequence, the PRD is the specification.
8. **Write in chunks** — never try to output the entire plan at once. Break it into multiple write operations.


---

## Workflow Chain — Suggest Next Steps

After completing this skill, suggest the appropriate next skill to the user:
- **Primary next step**: `/implement <PLAN-ID> Wave <first-wave>` — start implementing the first wave
- **If plan needs review**: `/review` on the plan file itself
- **If requirements are unclear**: Return to `/prd` to refine before implementing

---

## Mandatory Compounding Step (All Skills)

Before completing this skill, check if any of these documents should be updated based on what you learned during this session:

| Document | Update When | Location |
|----------|------------|----------|
| **BUG_PATTERNS.md** | New failure pattern discovered | `docs/BUG_PATTERNS.md` |
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
