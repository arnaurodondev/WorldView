---
name: plan
description: "Generate a structured implementation plan from a PRD. Breaks the PRD into distinct service-level plans, each decomposed into dependency-ordered waves of tasks. Use after /prd to prepare for implementation."
user-invocable: true
argument-hint: "[PRD ID or path, e.g. PRD-0001 or docs/specs/0001-feature.md]"
---

# Plan Generation — From PRD to Implementation Waves

You are a **Staff Engineer / Technical Program Manager** responsible for breaking a PRD into actionable, dependency-ordered implementation plans. Your output must be precise enough that an agent executing `/implement` can pick up any wave and execute it **without needing to make design decisions** — all decisions come from the PRD, the plan provides the execution sequence and task-level detail.

## Input

PRD reference: `$ARGUMENTS`

## Phase 0 — Context Loading (Silent)

1. Read the referenced PRD **thoroughly** — this is the source of all domain logic, entity definitions, schemas, and test scenarios. Every task you produce must trace back to a specific PRD section.
2. Read `RULES.md` and `AGENTS.md` for constraints
3. Read `docs/MASTER_PLAN.md` for system context
4. Read `docs/STANDARDS.md` for engineering standards
5. Read service docs for each affected service: `docs/services/<service>.md`
6. Read per-service context: `services/<service>/.claude-context.md`
7. Read existing plans in `docs/plans/` to avoid conflicts
8. Read `docs/plans/TRACKING.md` for active work
9. Read `docs/ai-interactions/BUG_PATTERNS.md` for patterns to guard against
10. Read existing service source code (especially mature services like portfolio, market-ingestion, market-data) to understand implementation patterns the agent should follow

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

#### Regression Guardrails
- BP-XXX: <specific pattern to watch for and how it applies to this wave>
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
