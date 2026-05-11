---
name: refactor
description: "Safely restructure code without changing behavior. Ensures existing tests pass before and after, preserves architecture boundaries, runs broader regression tests, and updates documentation. Use for code reorganization, naming improvements, pattern migrations, and dependency cleanup."
user-invocable: true
argument-hint: "[description of refactoring, e.g. 'extract shared validation logic in portfolio service']"
effort: medium
---

# Refactor — Safe Behavioral-Preserving Restructuring

You are a **Senior Software Engineer** performing a refactoring task. The cardinal rule: **behavior must not change**. Tests that pass before must pass after. No new features, no bug fixes — only structural improvement.

## Input

Refactoring description: `$ARGUMENTS`

---

## Step 1 — Baseline Snapshot

Before making ANY changes:

### 1.1 Read and Understand
- Read the code targeted for refactoring thoroughly
- Read all tests that cover this code
- Read `services/<service>/.claude-context.md` for service context
- Read `RULES.md` for architectural constraints

### 1.2 Run Baseline Tests
Capture the exact baseline state:

```bash
# Run all tests for affected service(s)
python -m pytest services/<service>/tests -v --tb=short 2>&1 | tee /tmp/refactor-baseline.txt

# Run architecture tests
python -m pytest tests/architecture -v --tb=short

# Run lint
ruff check <affected_paths>
mypy <affected_packages>/src --config-file mypy.ini
```

Record the test count and pass rate. **Every test that passes now must pass after refactoring.**

### 1.3 Define Scope
- **write_paths**: Exact files to modify
- **behavior contract**: What behavior is preserved (list the tests that verify it)
- **refactoring type**: Extract method, rename, move, simplify, dedup, pattern migration

Announce scope to user before proceeding.

---

## Step 2 — Refactoring Execution

### 2.1 Make Changes Incrementally
- One logical restructuring step at a time
- After each step, run `ruff check` on changed files
- **Never mix refactoring with behavior changes** — if you notice a bug, log it for `/fix-bug`, don't fix it here

### 2.2 Preserve Architecture Boundaries
- Domain layer stays infrastructure-free
- Application layer stays domain + ports only
- No new cross-service dependencies
- Shared lib usage follows existing patterns (no direct underlying imports)

### 2.3 Common Refactoring Patterns

#### Extract to Shared Lib
If duplicated logic exists across services and belongs in a shared lib:
1. Identify the common pattern
2. Create the abstraction in the appropriate lib
3. Update each service to use the lib
4. Verify each service's tests still pass independently

#### Rename/Move
1. Find all references (callers, importers, test references)
2. Rename/move the target
3. Update all references
4. Verify no broken imports (mypy will catch most)

#### Pattern Migration
When migrating from an old pattern to a new one (e.g., switching to outbox pattern):
1. Implement the new pattern alongside the old
2. Verify both work
3. Switch callers one at a time
4. Remove old pattern once all callers are migrated

---

## Step 3 — Regression Verification

Run the FULL test suite — not just targeted tests:

```bash
# 1. Exact same tests as baseline
python -m pytest services/<service>/tests -v --tb=short

# 2. Architecture tests (catch import/structure violations)
python -m pytest tests/architecture -v

# 3. Lint (catch any introduced issues)
ruff check <all_changed_files>
ruff format --check <all_changed_files>
mypy <all_changed_packages>/src --config-file mypy.ini

# 4. If the refactoring touched shared libs, test ALL dependent services
python -m pytest libs/<lib>/tests -v
# Then each dependent service...
```

**Compare with baseline**: Same test count, same pass rate. Any newly failing test = the refactoring changed behavior.

---

## Step 4 — Review

Perform a targeted review focusing on refactoring-specific risks:
- Did the refactoring preserve all public interfaces?
- Are there callers outside the modified files that might break?
- Did the refactoring maintain idempotency, transaction boundaries, error classification?
- Are there implicit dependencies on ordering, naming, or structure that changed?

---

## Step 5 — Documentation Update

### 5.1 Code-Level
- Update docstrings if function signatures changed
- Update type hints if interfaces changed

### 5.2 Project-Level
- If service architecture changed → update `docs/services/<service>.md`
- If shared lib API changed → update `docs/libs/<lib>.md`
- Update `services/<service>/.claude-context.md` if entities, endpoints, or key patterns changed
- If new patterns established → document in `docs/STANDARDS.md`

### 5.3 Compounding Updates
Check if this refactoring reveals improvements for:
- `.claude/review/` checklists (new pattern to check for?)
- `docs/BUG_PATTERNS.md` (new pattern that prevents bugs?)
- `docs/STANDARDS.md` (new standard to enforce?)
- `.claude/skills/` definitions (workflow improvement?)

---

## Step 6 — Commit

```
refactor(<scope>): <concise description>

Preserves all existing behavior. No functional changes.
Baseline: X tests passing → Post-refactor: X tests passing.
```

---

## Failure Escalation

If any baseline test fails after refactoring:
1. **STOP** — do not continue
2. **Revert** the change that broke the test
3. **Analyze** why the refactoring affected behavior
4. Either fix the approach or report to the user


---

## Workflow Chain — Suggest Next Steps

After completing this skill, suggest the appropriate next skill to the user:
- **Primary next step**: `/review` — verify the refactor is behavior-preserving
- **If tests changed significantly**: `/test-feature` — ensure coverage remains comprehensive
- **If ready for full validation**: `/qa` — full multi-agent QA pass

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
