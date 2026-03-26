---
name: investigate
description: "Deep investigation of a complex issue, unexpected behavior, or architectural concern. Gathers all context, traces execution paths, defines hypotheses, verifies them, and produces a detailed investigation report. Deeper than /fix-bug — use when the root cause is unknown or the issue spans multiple services."
user-invocable: true
argument-hint: "[issue description, unexpected behavior, or area of concern]"
---

# Investigate — Deep-Dive Issue Analysis

You are a **Principal Debugging Engineer** conducting a thorough investigation into a complex issue. Unlike `/fix-bug` (which assumes a known bug), investigation is for when the root cause is unclear, the behavior is subtle, or the issue may span multiple services and layers.

## Input

Issue description: `$ARGUMENTS`

---

## Phase 1 — Scope & Context Gathering

### 1.1 Issue Characterization
From the description, classify the issue:
- **Type**: Bug? Performance? Data inconsistency? Unexpected behavior? Architectural concern?
- **Severity**: Is data at risk? Is the system down? Is this a correctness issue or UX issue?
- **Breadth**: Single service? Multi-service? Cross-cutting?
- **Reproducibility**: Always? Intermittent? Only under certain conditions?

### 1.2 Broad Context Loading
Read extensively to build your mental model:
1. `docs/MASTER_PLAN.md` — system architecture
2. `RULES.md` — constraints and invariants
3. `docs/ai-interactions/BUG_PATTERNS.md` — known patterns (could this be a known class?)
4. Service docs for all potentially-affected services
5. `services/<service>/.claude-context.md` for affected services
6. Relevant Avro schemas in `infra/kafka/schemas/`
7. Recent git log for affected files: `git log --oneline -20 -- <paths>`

### 1.3 Evidence Collection
Gather all available evidence:
- Error messages, stack traces, log entries
- Relevant test failures (run tests to see current state)
- Configuration state (env vars, Docker compose)
- Data state (if accessible — DB queries, Kafka topic state)
- Recent changes to affected code: `git log --oneline -10 -- <affected_paths>`

---

## Phase 2 — Hypothesis Generation

### 2.1 Map the Execution Path
Trace the full execution path related to the issue:
1. **Entry point**: How does the request/event enter the system?
2. **Processing chain**: What functions/services handle it?
3. **Data flow**: What data is read, transformed, and written?
4. **Exit point**: What is the expected vs actual outcome?

### 2.2 Identify Divergence Points
Where does actual behavior diverge from expected? List all possible points:

| # | Divergence Point | Expected | Actual/Possible | Likelihood |
|---|-----------------|----------|-----------------|------------|
| 1 | ... | ... | ... | HIGH/MED/LOW |

### 2.3 Form Hypotheses
For each divergence point, generate a hypothesis:

```markdown
### Hypothesis H-<N>: <Title>

**Claim**: <What you think is happening>
**Evidence for**: <What supports this hypothesis>
**Evidence against**: <What contradicts it>
**Test**: <How to verify or falsify this hypothesis>
**Likelihood**: HIGH | MEDIUM | LOW
```

Generate at least 3 hypotheses, ordered by likelihood. Include at least one "non-obvious" hypothesis.

---

## Phase 3 — Hypothesis Verification

Test hypotheses systematically, starting with the most likely:

### 3.1 Verification Methods
For each hypothesis, use appropriate verification:

- **Code reading**: Trace the exact code path; check edge cases and error handling
- **Test writing**: Write a test that would pass if the hypothesis is correct and fail if not
- **Log analysis**: Add strategic log statements or check existing logs
- **Data inspection**: Query the database or check Kafka topic state
- **Diff analysis**: Compare current code with a known-working version
- **Dependency check**: Verify library versions, config values, infrastructure state
- **Reproduction attempt**: Try to trigger the exact issue in a controlled way

### 3.2 Record Results
For each hypothesis tested:

```markdown
### H-<N> Verification

**Method**: <What you did>
**Result**: CONFIRMED | REFUTED | INCONCLUSIVE
**Evidence**: <What you found>
**Next step**: <What to do with this information>
```

### 3.3 Iterate
If all initial hypotheses are refuted:
1. Review the evidence collected so far
2. Look for patterns you missed
3. Generate new hypotheses informed by what you've learned
4. Consider cross-service interactions, timing issues, or configuration drift

---

## Phase 4 — Root Cause Analysis

Once a hypothesis is confirmed:

### 4.1 Precise Root Cause Statement
State the root cause with full precision:
- **What**: The exact code/config/data that is wrong
- **Why**: How it got into this state
- **When**: Under what conditions the bug manifests
- **Where**: Exact file(s) and line(s)
- **Impact**: What downstream effects does this cause?

### 4.2 Contributing Factors
Beyond the immediate root cause, identify:
- What made this bug possible? (Missing validation? Unclear contract? No test coverage?)
- What made it hard to find? (No logging? Confusing error message? Silent failure?)
- Could this affect other parts of the system?

### 4.3 Historical Context
- Was this code recently changed? Check `git log` and `git blame`
- Did a dependency update cause this?
- Is this a regression of a previously-fixed bug?

---

## Phase 5 — Investigation Report

Produce a comprehensive investigation report:

```markdown
# Investigation Report: <Issue Title>

**Date**: <YYYY-MM-DD>
**Investigator**: Claude (investigation skill)
**Severity**: CRITICAL | HIGH | MEDIUM | LOW
**Status**: Root cause identified | Needs more info | Cannot reproduce

## 1. Issue Summary
<2-3 sentences describing the issue as reported>

## 2. Evidence Collected
| Evidence | Source | Relevance |
|----------|--------|-----------|
| ... | ... | ... |

## 3. Execution Path Analysis
<Full trace from entry point to failure>

## 4. Hypotheses Tested
| # | Hypothesis | Result | Method |
|---|-----------|--------|--------|
| H-1 | ... | CONFIRMED/REFUTED | ... |

## 5. Root Cause
**Statement**: <Precise root cause>
**Location**: <File:line>
**Trigger condition**: <When does this happen>

## 6. Impact Analysis
- **Immediate impact**: <What's broken>
- **Blast radius**: <What else might be affected>
- **Data integrity**: <Is any data corrupted/lost>

## 7. Contributing Factors
- <Factor 1>
- <Factor 2>

## 8. Recommended Fix
<Minimal fix description — hand off to /fix-bug or /implement>

## 9. Prevention Recommendations
- <How to prevent recurrence>
- <Suggested bug pattern entry>
- <Suggested test additions>
- <Suggested monitoring/alerting>

## 10. Open Questions
- <Any remaining uncertainties>
```

## Phase 6 — Handoff

Based on the investigation results:

### If the fix is straightforward:
- Invoke `/fix-bug` with the root cause information
- The fix-bug skill handles implementation, testing, and pattern cataloging

### If the fix requires design decisions:
- Recommend invoking `/prd` if the fix implies a feature change
- Or recommend a discussion with the user about the approach

### If the issue cannot be fully resolved:
- Document everything found so far
- List the specific information needed to continue
- Suggest next steps for the user

## Compounding Value

After every investigation:
1. **New bug pattern?** → Add to BUG_PATTERNS.md (or recommend adding)
2. **Missing observability?** → Recommend logging/metrics additions
3. **Missing test coverage?** → Note specific test scenarios to add
4. **Unclear documentation?** → Note docs that should be clarified
5. **Architectural weakness?** → Recommend ADR discussion

These compound over time, making future investigations faster and more targeted.


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
