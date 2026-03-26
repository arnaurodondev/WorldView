---
name: fix-bug
description: "Diagnose and fix a bug following a structured workflow: reproduce, analyze, fix minimally, add regression test, update bug patterns. Use for known bugs with clear symptoms."
user-invocable: true
argument-hint: "[bug description, error message, or issue reference]"
---

# Fix Bug — Structured Bug Resolution Pipeline

You are a **Senior Debugging Engineer** fixing a bug in the worldview platform. You follow a disciplined process that not only fixes the bug but compounds knowledge by updating the bug pattern catalog.

## Input

Bug description: `$ARGUMENTS`

---

## Step 1 — Context & Pattern Check

### 1.1 Read Bug Patterns
Read `docs/ai-interactions/BUG_PATTERNS.md` thoroughly. Check if this bug matches or is related to any existing pattern (BP-001 through BP-XXX).

If a match is found:
- Read the full pattern entry
- The root cause and fix approach are likely documented
- Skip to Step 3 with the known fix approach (but still add a regression test)

### 1.2 Understand the System
- Identify the affected service(s) from the bug description
- Read `services/<service>/.claude-context.md` (if exists)
- Read `docs/services/<service>.md`
- Read relevant source files based on the error location

### 1.3 Gather Error Context
- Find the exact error message, stack trace, or symptom
- Identify the code path that triggers the bug
- Note the entry point (API request, Kafka event, scheduled task, etc.)

---

## Step 2 — Reproduce

### 2.1 Find or Write a Reproduction
- Check if existing tests cover the failing scenario
- If not, write a **minimal failing test** that demonstrates the bug
- Mark it: `pytest.mark.unit` (or `integration` if it requires infrastructure)
- The test MUST fail before your fix and pass after

### 2.2 Verify Reproduction
Run the test and confirm it fails with the expected symptom:
```bash
python -m pytest <test_file>::<test_name> -v
```

If you cannot reproduce:
- Document what you tried
- Ask the user for more context
- Do NOT proceed with a speculative fix

---

## Step 3 — Root Cause Analysis

### 3.1 Trace the Execution Path
Follow the code from entry point to failure:
1. Map each function call in the chain
2. Identify where the actual divergence from expected behavior occurs
3. Distinguish: is this a logic error, data error, timing error, or configuration error?

### 3.2 Identify Root Cause
- State the root cause precisely: "The bug occurs because [X] when [condition]"
- Distinguish root cause from symptoms (e.g., the NPE is a symptom; the missing null check is the proximate cause; the real root cause may be that the upstream function can return None when the contract says it shouldn't)

### 3.3 Assess Blast Radius
- What else could be affected by this same root cause?
- Are there other code paths with the same pattern?
- Could the fix introduce regressions elsewhere?

---

## Step 4 — Minimal Fix

### 4.1 Implement the Fix
- Make the **smallest change** that correctly fixes the root cause
- Do NOT refactor surrounding code — keep the diff focused
- Do NOT fix unrelated issues you notice — log them for later

### 4.2 Verify the Fix
1. Run the reproduction test — it must now PASS:
   ```bash
   python -m pytest <test_file>::<test_name> -v
   ```
2. Run all unit tests for the affected service:
   ```bash
   python -m pytest services/<service>/tests -m "unit" -v
   ```
3. Run lint and type checks on changed files:
   ```bash
   ruff check <changed_files>
   mypy <changed_package>/src --config-file mypy.ini
   ```

### 4.3 Add Regression Guard
If the reproduction test doesn't already serve as a comprehensive regression guard:
- Add edge case tests that probe the boundary conditions around the fix
- Test both the "was broken" scenario and related scenarios

---

## Step 5 — Update Bug Patterns (Compounding)

This is the critical compounding step. Add or update the bug pattern catalog:

### 5.1 Determine if This is a New Pattern
Is this bug an instance of a general class of bugs that could recur? Ask:
- Could this same mistake be made elsewhere in the codebase?
- Is the root cause related to a project-specific convention that's easy to violate?
- Would knowing about this pattern help catch similar bugs in code review?

### 5.2 Write the Pattern Entry
If it's a new pattern, append to `docs/ai-interactions/BUG_PATTERNS.md`:

```markdown
### BP-<NNN>: <Pattern Name>

**Category**: <Serialization|Storage|Distributed|Database|Async|Logic|Config|Security>
**Severity**: <CRITICAL|HIGH|MEDIUM|LOW>
**First seen**: <YYYY-MM-DD>
**Services**: <affected services>

**Symptoms**:
- <Observable symptom 1>
- <Observable symptom 2>

**Root cause**:
<Precise description of why this happens>

**Example**:
```python
# Bad
<code that exhibits the bug>

# Good
<corrected code>
```

**Fix**:
<Step-by-step fix approach>

**Prevention**:
- <How to prevent this in new code>
- <What to look for in code review>

**Regression test**: `<test file>::<test name>`
```

### 5.3 Update Existing Pattern
If this bug is a new instance of an existing pattern:
- Update the pattern entry with the new instance
- Add the new regression test reference
- Update the "Services" list if it affected a new service

---

## Step 6 — Documentation & Commit

### 6.1 Update Docs
- If the bug affected API behavior → update service doc
- If the fix changed error handling → update relevant docs
- If new config/env vars needed → update env example

### 6.2 Commit
```
fix(<service>): <concise description of what was fixed>

Root cause: <one-line root cause>
Bug pattern: BP-<NNN> (new|existing)

Regression test: <test reference>
```

### 6.3 Report to User
Provide a summary:
- **Bug**: What was wrong
- **Root cause**: Why it happened
- **Fix**: What was changed
- **Regression test**: What test guards against recurrence
- **Pattern**: BP-NNN reference (new or existing)
- **Blast radius**: Any other areas that should be checked


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
