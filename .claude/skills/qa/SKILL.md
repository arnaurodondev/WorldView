---
name: qa
description: "Run a full Quality Assurance pass across the entire codebase or a specific service. Executes all test layers in order, validates architecture compliance, checks documentation freshness, and produces a QA report. Use before releases, after major changes, or at wave boundaries."
user-invocable: true
argument-hint: "[optional: specific service or 'full' for complete QA]"
---

# QA — Full Quality Assurance Pipeline

You are a **QA Lead** running a comprehensive quality assurance pass. You execute all test layers in the correct order, validate architecture compliance, check documentation, and produce a definitive quality report.

## Input

Scope: `$ARGUMENTS` (if empty, run QA on all changed code since last commit on main)

---

## Test Layer Execution Order

Execute tests strictly in this order. Each layer must pass before proceeding to the next:

### Layer 1: Architecture Tests
```bash
python -m pytest tests/architecture -v
```
**Purpose**: Verify service structure, import guards, layer boundaries, outbox contracts
**Pass criteria**: 29/29 tests pass (or all tests pass)
**If fails**: STOP — architecture violations must be fixed first

### Layer 2: Lint & Type Check
```bash
# Ruff check
ruff check libs/ services/

# Ruff format
ruff format --check libs/ services/

# mypy
mypy libs/*/src services/*/src --config-file mypy.ini
```
**Pass criteria**: Zero errors
**If fails**: Log all failures, continue to collect full picture, but mark QA as FAILED

### Layer 3: Shared Library Tests
```bash
for lib in libs/*/tests; do
  python -m pytest "$lib" -m "unit" -v
done
```
**Purpose**: Libraries are shared foundations — failures here cascade
**Pass criteria**: All library tests pass

### Layer 4: Service Unit Tests (Fast Path)
```bash
for svc in services/*/tests; do
  python -m pytest "$svc" -m "unit" -v --tb=short
done
```
**Purpose**: Core business logic correctness
**Pass criteria**: All unit tests pass across all services

### Layer 5: Contract Tests
```bash
python -m pytest services/*/tests -m "contract" -v
```
**Purpose**: Avro schema compatibility, API contract verification
**Pass criteria**: All contract tests pass

### Layer 6: Integration Tests
```bash
# Verify infrastructure is running
./scripts/wait-for-services.sh

# Run integration tests
for svc in services/*/tests; do
  python -m pytest "$svc" -m "integration" -v --tb=short
done
```
**Purpose**: DB, Kafka, S3 integration correctness
**Pass criteria**: All integration tests pass (or skip with note if infra not available)
**Note**: If infra is not running, log as SKIPPED (not FAILED)

### Layer 7: E2E Tests
```bash
python -m pytest services/*/tests -m "e2e" -v --tb=short
```
**Purpose**: Full request path through services
**Pass criteria**: All E2E tests pass

### Layer 8: Frontend Tests (if applicable)
```bash
cd apps/frontend && pnpm test
cd apps/frontend && pnpm typecheck
```
**Purpose**: Frontend unit tests and type safety
**Pass criteria**: All frontend tests and type checks pass

### Layer 9: Frontend E2E (if applicable)
```bash
cd apps/frontend && pnpm exec playwright test
```
**Purpose**: Full browser-based E2E testing
**Pass criteria**: All Playwright tests pass

---

## Supplementary Checks

### S1: Import Guard Validation
```bash
python scripts/import_guards/check_import_guards.py
```

### S2: Service Structure Validation
```bash
python scripts/structure_checks/check_service_structure.py --strict
```

### S3: Avro Schema Validation
```bash
./scripts/gen-contracts.sh
```

### S4: Documentation Freshness
Check for staleness:
- For each service with code changes since last main merge, verify `docs/services/<service>.md` was also updated
- Check `docs/MASTER_PLAN.md` last modified vs last architectural change
- Check `.claude-context.md` files are current

### S5: Security Quick Scan
Run `scripts/hooks/security-scan.sh` on all changed files

### S6: Dependency Check
- Check for outdated or vulnerable dependencies (if tooling available)
- Verify no new dependencies were added without updating pyproject.toml

---

## QA Report

Produce a comprehensive QA report:

```markdown
# QA Report

**Date**: <YYYY-MM-DD>
**Scope**: <full | service-specific>
**Branch**: <current branch>
**Verdict**: PASS | PASS_WITH_WARNINGS | FAIL

## Summary
| Layer | Tests | Passed | Failed | Skipped | Status |
|-------|-------|--------|--------|---------|--------|
| Architecture | ... | ... | ... | ... | PASS/FAIL |
| Lint (ruff) | ... | ... | ... | ... | PASS/FAIL |
| Type Check (mypy) | ... | ... | ... | ... | PASS/FAIL |
| Library Unit | ... | ... | ... | ... | PASS/FAIL |
| Service Unit | ... | ... | ... | ... | PASS/FAIL |
| Contract | ... | ... | ... | ... | PASS/FAIL |
| Integration | ... | ... | ... | ... | PASS/FAIL/SKIP |
| E2E | ... | ... | ... | ... | PASS/FAIL/SKIP |
| Frontend Unit | ... | ... | ... | ... | PASS/FAIL/N/A |
| Frontend E2E | ... | ... | ... | ... | PASS/FAIL/N/A |

## Supplementary Checks
| Check | Status | Notes |
|-------|--------|-------|
| Import Guards | PASS/FAIL | ... |
| Service Structure | PASS/FAIL | ... |
| Schema Validation | PASS/FAIL | ... |
| Doc Freshness | PASS/WARN | ... |
| Security Scan | PASS/WARN | ... |

## Failures Detail
<For each failure, list: test name, error message, likely cause>

## Warnings
<Documentation staleness, skipped layers, non-critical issues>

## Recommendations
- <Specific fixes needed before merge/release>
- <Test gaps identified>
- <Documentation updates needed>
```

---

## Scope-Specific Behavior

### Full QA (`/qa full`)
Run all 9 layers + all supplementary checks

### Service QA (`/qa portfolio`)
Run layers 1-7 but only for the specified service + its dependencies in libs/

### Changed-only QA (`/qa` with no args)
Detect changes vs main, run only relevant layers for changed services/libs

---

## Compounding Value

After each QA run:
1. **New failure pattern?** → Recommend adding to BUG_PATTERNS.md
2. **Flaky test found?** → Flag for investigation, note in report
3. **Missing test coverage?** → Recommend invoking `/test-feature`
4. **Documentation drift?** → List specific docs that need updates


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
