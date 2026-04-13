---
name: docs-audit
description: "Audit and enhance the entire project documentation, skills, agents, and review framework. Finds undocumented code, stale docs, inconsistencies, weak workflow steps, missing patterns, and bugs in the knowledge base. Applies fixes directly and produces an actionable report. Use periodically or after major changes."
user-invocable: true
argument-hint: "[optional: 'full' for complete audit, 'skills' for skill/agent audit only, or specific area like 'services' or 'libs']"
effort: heavy
---

# Documentation Audit — Completeness, Consistency & Workflow Enhancement

You are a **Technical Documentation Architect and Knowledge System Engineer** performing a comprehensive audit of the worldview project's documentation, skills, agents, and review framework. Your goal is twofold: (1) find every gap, inconsistency, and staleness issue, and (2) actively improve the knowledge system — skills, checklists, heuristics, and patterns — so future code generation, review, and planning work is more effective.

**Apply fixes directly wherever possible.** This skill does not just report — it acts.

## Input

Audit scope: `$ARGUMENTS` (default: full audit)

---

## Phase 1 — Documentation Inventory

### 1.1 Map All Documentation Sources
Read and catalog every documentation file:

| Category | Files | Purpose |
|----------|-------|---------|
| Root governance | CLAUDE.md, AGENTS.md, RULES.md, CONTRIBUTING.md, README.md | Project-level standards |
| Architecture | docs/MASTER_PLAN.md, docs/STANDARDS.md, docs/architecture/ | System design |
| Service docs | docs/services/*.md | Per-service reference |
| Service context | services/*/.claude-context.md | Agent quick-context |
| Library docs | docs/libs/*.md | Per-library reference |
| Workflow docs | docs/workflows/*.md | Dev processes |
| Testing docs | docs/testing/*.md | Test strategy/guides |
| Runbooks | docs/runbooks/*.md | Operations guides |

| Review framework | .claude/review/ | Code review protocols |
| Skills | .claude/skills/*/SKILL.md | Workflow definitions |
| Agents | .claude/agents/*.md | Role definitions |
| Specs/Plans | docs/specs/, docs/plans/ | Feature specifications |

### 1.2 Map All Code That Should Be Documented
For each service, identify:
- API endpoints (from `api/` routers)
- Kafka topics (from `messaging/` publishers/consumers)
- Domain entities (from `domain/entities/`)
- Database tables (from Alembic migrations)
- Configuration variables (from `config/` settings)
- Public library APIs (from `libs/*/src/`)

---

## Phase 1.5 — Codebase Pattern Mining (Mandatory)

Before checking documentation completeness, scan the live codebase for patterns that are being used but may not be documented. This is the most valuable part of the audit — documentation catches up to code, not the other way around.

### 1.5.1 Scan for Undocumented Architecture Patterns
```bash
# Find all custom decorators, base classes, and mixins that form patterns
grep -r "class Base" services/ libs/ --include="*.py" -l
grep -r "@staticmethod\|@classmethod\|@property" services/ --include="*.py" -l

# Find all custom exceptions — are they all in BUG_PATTERNS.md?
grep -r "class.*Error\|class.*Exception" services/ libs/ --include="*.py" | grep -v "test_"

# Find all Kafka consumer patterns
grep -r "BaseKafkaConsumer\|consume_loop\|_handle_message" services/ --include="*.py" -l

# Find all use case patterns
grep -r "class.*UseCase\|class.*Command\|class.*Query" services/ --include="*.py"
```

### 1.5.2 Scan for Bug Patterns That Should Be in BUG_PATTERNS.md
- Read `docs/BUG_PATTERNS.md` — catalog all existing BP-NNN entries
- Scan git log for commits with "fix" prefix: `git log --oneline --all | grep "^[a-f0-9]* fix" | head -50`
- For each fix commit, check if the root cause pattern is in BUG_PATTERNS.md
- Cross-reference memory files in `.claude/projects/*/memory/` for BP entries mentioned but not in the doc

### 1.5.3 Scan for HIGH_RISK_PATTERNS Gaps
- Read `.claude/review/heuristics/HIGH_RISK_PATTERNS.md`
- For each BP entry in BUG_PATTERNS.md, check: is there a corresponding HIGH_RISK_PATTERNS entry that would have caught it in review?
- Flag missing linkages: "BP-XXX would have been prevented by HR-YYY (which doesn't exist yet)"

### 1.5.4 Scan for REVIEW_CHECKLIST Gaps
- Read `.claude/review/checklists/REVIEW_CHECKLIST.md`
- For each known failure pattern, ask: "Would a reviewer following this checklist have caught it?"
- Flag checklist sections that are missing guards for known failure modes

---

## Phase 2 — Completeness Check

### 2.1 Undocumented Code
For each service:
- [ ] Every API endpoint listed in `docs/services/<service>.md`?
- [ ] Every Kafka topic (produce + consume) listed?
- [ ] Every domain entity described?
- [ ] Every config var in `dev.local.env.example`?
- [ ] `.claude-context.md` exists and is current?

For each library:
- [ ] `docs/libs/<lib>.md` exists?
- [ ] Public API documented with types?
- [ ] Usage examples provided?

### 2.2 Missing Documentation
- [ ] All services have docs in `docs/services/`
- [ ] All services have `.claude-context.md`
- [ ] All services have runbooks in `docs/runbooks/` (at least mature ones)
- [ ] All ADRs are numbered and indexed
- [ ] Bug patterns catalog is current
- [ ] Standards document covers all enforced conventions

### 2.3 Missing Patterns in Knowledge Base
Scan the codebase for patterns that should be documented but aren't:
- Error handling patterns used but not in BUG_PATTERNS.md
- Architectural patterns used but not in STANDARDS.md
- Security patterns used but not in security-audit checklists
- Testing patterns used but not in testing docs

---

## Phase 3 — Accuracy & Freshness Check

### 3.1 Code vs Documentation Drift
For each documented item, verify it matches the current code:

```bash
# Check if documented endpoints match actual routers
grep -r "router\." services/<service>/src/<service>/api/ | head -20
# Compare with docs/services/<service>.md endpoint list

# Check if documented Kafka topics match actual publishers
grep -r "topic" services/<service>/src/<service>/infrastructure/messaging/ | head -20
# Compare with docs

# Check if documented entities match actual domain
ls services/<service>/src/<service>/domain/entities/
# Compare with docs
```

### 3.2 Cross-Document Consistency
Check that facts are consistent across all documents:
- Service count (should be 10 + intelligence-migrations everywhere)
- Library count (should be 6 everywhere)
- Port numbers (consistent across docs, docker-compose, service configs)
- Database names (consistent across docs, docker-compose, Alembic configs)
- Kafka topic names (consistent across docs, Avro schemas, service code)

### 3.3 Staleness Detection
For each doc file:
- When was it last modified? (`git log -1 --format="%ai" -- <file>`)
- When was the code it documents last modified?
- If code changed more recently than docs → flag as potentially stale

---

## Phase 4 — Standards Compliance

### 4.1 Documentation Format Compliance
- [ ] All service docs follow consistent structure (mission, API, events, data, pitfalls)
- [ ] All `.claude-context.md` follow consistent structure
- [ ] All agent definitions have: mission, read-first list, responsibilities, non-goals
- [ ] All skill definitions have: description, phases, validation, compounding section
- [ ] All PRDs follow the template in `docs/specs/TEMPLATE.md`
- [ ] All plans follow the template in `docs/plans/TEMPLATE.md`

### 4.2 Review Framework Completeness
- [ ] All review checklists reference current project patterns
- [ ] High-risk patterns catalog covers current codebase risks
- [ ] Bug patterns catalog is indexed and searchable
- [ ] Edge case generators cover all service types

---

## Phase 4.5 — Skills & Agents Quality Audit

### 4.5.1 Skill Workflow Audit
For each skill in `.claude/skills/*/SKILL.md`, verify:
- [ ] Every phase has a **validation gate** before proceeding to the next (no silent skips)
- [ ] Every skill has a **Compounding Updates** section with all 10 document types
- [ ] Every skill has a **Workflow Chain** section suggesting next steps
- [ ] Every `impl` phase references `BUG_PATTERNS.md` guardrails
- [ ] Every skill that touches the DB references the Alembic/migration pitfalls
- [ ] Every skill that touches Kafka references idempotency and Avro forward-compat requirements
- [ ] Phases are ordered correctly (context → analysis → action → validate → commit)
- [ ] The skill's description in the frontmatter matches what the skill actually does

### 4.5.2 Skill Gap Analysis
For each known recurring failure in the project (from BUG_PATTERNS.md and git history):
- Does any skill have a step that would have prevented it?
- If not, which skill should have that step, and what should it say?
- Produce a list of: "Missing step in /X would prevent BP-NNN"

### 4.5.3 Agent Definition Audit
For each agent in `.claude/agents/*.md`, verify:
- [ ] Mission statement is specific (not generic)
- [ ] "Read-first" list includes the most recent relevant docs
- [ ] Non-goals are explicitly listed to prevent scope creep
- [ ] The agent's responsibilities don't overlap ambiguously with another agent

### 4.5.4 Cross-Skill Consistency
- Do all skills agree on the same Kafka topic names, DB names, service identifiers?
- Do all skills reference the same RULES.md rule numbers for the same constraints?
- Are there skills that contradict each other in their guidance?

---

## Phase 5 — Fix First, Then Report

**Default posture: apply fixes, then report what was done.** Only ask the user to decide when the fix requires a non-obvious architectural judgement call.

### 5.1 Apply Fixes Immediately (no user approval needed)
Apply these directly using Edit/Write tools:
- Fix typos, broken links, wrong file references in any doc
- Update service/lib counts where incorrect across all files
- Update port numbers or topic names that are inconsistent
- Add missing `Compounding Updates` sections to skills that lack them
- Add missing `Workflow Chain` sections to skills that lack them
- Add `BUG_PATTERNS.md` guardrail references to plan/implement skill phases that lack them
- Add missing HIGH_RISK_PATTERNS entries for known bug patterns (BP-NNN → HR-NNN)
- Add missing REVIEW_CHECKLIST items for failure modes that have no checklist guard
- Add missing `.claude-context.md` topics, pitfalls, or test commands for documented patterns
- Fix agent definitions that are generic, outdated, or missing non-goals
- Document any codebase pattern found in Phase 1.5 that has no documentation

### 5.2 Report (present to user for review)

```markdown
# Documentation Audit Report

**Date**: <YYYY-MM-DD>
**Scope**: <full | area-specific>
**Health Score**: <0-100>

## Fixes Applied (Already Done)
| Fix | File | What Was Changed |
|-----|------|-----------------|
| ... | ... | ... |

## Skills/Agents Improvements Applied
| Skill/Agent | Gap Found | What Was Added |
|-------------|-----------|----------------|
| ... | ... | ... |

## Summary
| Category | Files | Complete | Stale | Missing | Issues |
|----------|-------|----------|-------|---------|--------|
| Service docs | ... | ... | ... | ... | ... |
| Context files | ... | ... | ... | ... | ... |
| Library docs | ... | ... | ... | ... | ... |
| Agent definitions | ... | ... | ... | ... | ... |
| Skill definitions | ... | ... | ... | ... | ... |
| Review framework | ... | ... | ... | ... | ... |

## Undocumented Code
| Item | Type | Location | Action |
|------|------|----------|--------|
| ... | endpoint/topic/entity | ... | Add to docs |

## Undocumented Patterns (from Phase 1.5)
| Pattern | Used In | Should Be In | Priority |
|---------|---------|-------------|----------|
| ... | ... | ... | HIGH/MED/LOW |

## Skill Gaps Found (from Phase 4.5)
| Skill | Missing Step | Bug Pattern It Would Prevent |
|-------|-------------|------------------------------|
| ... | ... | BP-NNN |

## Stale Documentation
| File | Last Updated | Code Changed | Drift |
|------|-------------|--------------|-------|
| ... | ... | ... | ... |

## Inconsistencies
| Fact | File A Says | File B Says | Correct |
|------|------------|------------|---------|
| ... | ... | ... | ... |

## Remaining Items (need user decision)
| What's Missing | Priority | Suggested Location | Requires Decision Because |
|---------------|----------|-------------------|--------------------------|
| ... | HIGH/MED/LOW | ... | ... |

## Recommendations
1. <Highest priority fix>
2. <Second priority>
...
```

---

## Compounding Updates

After every audit:
1. **Found undocumented pattern?** → Document it in the appropriate location
2. **Found recurring staleness?** → Add a hook or checklist item to prevent it
3. **Found documentation format inconsistency?** → Update templates
4. **Found cross-doc inconsistency?** → Fix and add to audit checklist for next time

This skill itself should be updated when:
- New documentation categories are added to the project
- New consistency checks become relevant
- The audit process proves insufficient in some area

Last updated: 2026-04-12


---

## Workflow Chain — Suggest Next Steps

After completing this skill, suggest the appropriate next skill to the user:
- **If code/doc inconsistencies found**: Fix docs directly, then `/review` the doc changes
- **If undocumented code found**: `/implement` to add missing documentation as a standalone task
- **If stale architecture docs**: Consider `/investigate` to verify current state before updating

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
