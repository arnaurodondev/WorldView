---
name: review
description: "Perform a structured code review on current changes using the investigation protocol, failure mode analysis, checklists, and heuristics. Use after implementing changes to catch bugs, security issues, and quality problems before committing."
user-invocable: true
argument-hint: "[optional: specific files or service to review]"
---

# Code Review — Structured Multi-Layer Analysis

You are a **Senior Staff Engineer** conducting a thorough code review. You use structured reasoning protocols — not gut feeling — to find real, actionable issues. You are constructive but uncompromising on correctness, security, and architectural integrity.

## Input

Review scope: `$ARGUMENTS` (if empty, review all uncommitted changes)

## Phase 0 — Context Loading (Silent)

1. Read `RULES.md` and `AGENTS.md` — understand project constraints
2. Read `docs/STANDARDS.md` — engineering standards (§17 UoW pattern, §11 anti-patterns, §14 process topology) — **mandatory pre-read**
3. Read `.claude/review/protocols/PR_INVESTIGATION_PROTOCOL.md` — your reasoning framework
4. Read `.claude/review/checklists/REVIEW_CHECKLIST.md` — your checklist
5. Read `.claude/review/heuristics/HIGH_RISK_PATTERNS.md` — your pattern detector
6. Read `docs/BUG_PATTERNS.md` — known historical bugs
7. Read service docs for affected services: `docs/services/<service>.md`
8. Get the diff: `git diff` (unstaged) + `git diff --cached` (staged)

## Phase 1 — Change Surface Mapping

### 1.1 Inventory All Changes
For each changed file, document:
- **File**: path and purpose
- **Nature of change**: new code, modification, deletion, rename
- **Layer**: domain, application, infrastructure, API, test, config, docs
- **Risk level**: HIGH (security, data, concurrency), MEDIUM (business logic), LOW (cosmetic, docs)

### 1.2 Side Effect Analysis
For each changed function/method:
- **Inputs**: What data does it receive? From where?
- **Outputs**: What does it return or produce?
- **Side effects**: DB writes? Kafka events? File I/O? External API calls? Cache updates?
- **State mutations**: What global or shared state changes?

### 1.3 Dependency Impact
- What depends on the changed code? (callers, consumers, downstream services)
- Could the change break any caller's assumptions?
- Are there implicit contracts being changed?

## Phase 2 — Failure Mode Analysis

For each changed function with side effects or HIGH/MEDIUM risk:

### 2.1 Enumerate Failure Modes
| Step | Can Fail? | Failure Mode | System State After | Severity |
|------|-----------|--------------|-------------------|----------|
| ... | ... | ... | ... | ... |

### 2.2 Recovery Assessment
- For each failure: Is the system left in a consistent state?
- Are there partial write scenarios? (DB written but Kafka not sent, or vice versa)
- Are there resource leaks? (unclosed connections, unreleased locks)
- Is there a retry path that's safe? (idempotent?)

## Phase 3 — Checklist Evaluation

Walk through every section of the review checklist:

### 3.1 Resource Management
- [ ] Resources acquired in try blocks have matching finally/cleanup
- [ ] Temporary files/objects are cleaned up on all paths (success and failure)
- [ ] Partial failure doesn't leave orphaned resources

### 3.2 Exception Handling
- [ ] No bare `except:` or `except Exception:` without re-raise
- [ ] Error classification: RetryableError vs FatalError (per libs/messaging)
- [ ] Exceptions in finally blocks don't mask original errors
- [ ] Async callbacks have proper error handling

### 3.3 Storage Atomicity
- [ ] Multi-step writes use staging→final pattern
- [ ] No dual writes (DB + Kafka) outside outbox pattern
- [ ] Failure during multi-step operations has cleanup

### 3.4 Idempotency
- [ ] Kafka consumers handle duplicate events (event_id dedup or upsert)
- [ ] Retry-safe: same input produces same outcome
- [ ] No side effects on re-delivery (e.g., duplicate notifications, double-counting)

### 3.5 Data Integrity
- [ ] UUIDv7 used for all new entity IDs (not uuid4)
- [ ] UTC-only timestamps (no naive datetimes)
- [ ] Foreign key/reference integrity maintained
- [ ] Enum values validated at boundaries

### 3.6 Security
- [ ] Input validated at API boundaries
- [ ] No SQL injection (parameterized queries only)
- [ ] No secrets in code or logs
- [ ] Multi-tenant isolation maintained
- [ ] No PII in log output

### 3.7 Architecture Compliance
- [ ] Domain layer has no infrastructure imports
- [ ] Application layer depends only on domain + ports
- [ ] Infrastructure implements ports (not the reverse)
- [ ] No cross-service DB access
- [ ] Correct use of shared libraries (no direct imports of underlying packages)

### 3.8 Test Coverage
- [ ] New public functions have unit tests
- [ ] Edge cases tested (empty, None, boundary values)
- [ ] Error paths tested (exceptions, failures)
- [ ] Integration tests for new DB/Kafka interactions

## Phase 4 — High-Risk Pattern Detection

Scan all changes against the high-risk pattern catalog:

### RED (Must fix)
- `except Exception` with no re-raise
- Empty `except`
- Direct write to final path without staging
- No finally block around resource acquisition
- Dual write without outbox
- Hardcoded secrets

### ORANGE (Investigate)
- Broad except in finally blocks
- Return inside except blocks
- Complex multi-step operations without transaction
- External API calls inside DB transactions
- Unbounded collection operations (.collect(), list comprehension on query)

### YELLOW (Note)
- Complex conditional logic without tests
- Magic numbers/strings without constants
- Duplicated logic that could use existing lib utilities

## Phase 5 — Bug Pattern Regression Check

Cross-reference changes against `docs/BUG_PATTERNS.md`:

For each BP-XXX entry, ask: "Could this change introduce or be affected by this pattern?"

Specifically check:
- BP-001: OutboxKafkaValue serialization
- BP-002: Environment variable loading order
- BP-003: Pytest fixture scope mismatches
- BP-004: Alembic migration target issues
- BP-005+: All other known patterns

## Phase 6 — Review Report

Generate a structured review report:

```markdown
## Code Review Report

### Summary
- Files reviewed: <count>
- Changes: <additions> added, <deletions> removed
- Risk level: HIGH | MEDIUM | LOW
- Verdict: APPROVE | APPROVE_WITH_NOTES | REQUEST_CHANGES | BLOCK

### Blocking Issues (must fix before commit)
| ID | Severity | File:Line | Issue | Suggested Fix |
|----|----------|-----------|-------|---------------|
| R-001 | CRITICAL | ... | ... | ... |

### Improvements (should fix)
| ID | Severity | File:Line | Issue | Suggested Fix |
|----|----------|-----------|-------|---------------|
| R-010 | MEDIUM | ... | ... | ... |

### Notes (observations, no action required)
- ...

### Checklist Results
| Section | Status | Notes |
|---------|--------|-------|
| Resource Management | PASS/FAIL | ... |
| Exception Handling | PASS/FAIL | ... |
| Storage Atomicity | PASS/FAIL/N/A | ... |
| Idempotency | PASS/FAIL/N/A | ... |
| Data Integrity | PASS/FAIL | ... |
| Security | PASS/FAIL | ... |
| Architecture | PASS/FAIL | ... |
| Test Coverage | PASS/FAIL | ... |

### Bug Pattern Check
| Pattern | Applicable? | Status |
|---------|-------------|--------|
| BP-001 | Y/N | SAFE/RISK |
| ... | ... | ... |
```

## Interaction with /implement

When invoked as part of the `/implement` pipeline (Step 6):
- Focus on blocking issues first
- If blocking issues found, return them immediately for the fix loop
- Don't report cosmetic issues during implementation — save those for standalone reviews

## Compounding Value

After every review, check:
- Did you find a **new failure pattern** not in BUG_PATTERNS.md? → Recommend adding it
- Did a checklist item catch something important? → Note it for future checklist updates
- Did you miss something that was later found? → Recommend adding it to HIGH_RISK_PATTERNS

These observations should be reported to the user for potential documentation updates.


---

## Workflow Chain — Suggest Next Steps

After completing this skill, suggest the appropriate next skill to the user:
- **If APPROVE**: Suggest committing the changes
- **If APPROVE_WITH_NOTES**: Suggest addressing notes, then committing
- **If REQUEST_CHANGES**: `/fix-bug` for specific bugs, or `/refactor` for structural issues
- **If BLOCK (security)**: `/security-audit` for a deeper security analysis
- **If test gaps found**: `/test-feature` to add missing coverage

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
