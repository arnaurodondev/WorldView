---
name: docs-audit
description: "Audit the entire project documentation for completeness, accuracy, and consistency. Finds undocumented code, stale docs, inconsistencies between code and docs, and missing patterns. Produces an actionable report with fixes. Use periodically or after major changes."
user-invocable: true
argument-hint: "[optional: 'full' for complete audit, or specific area like 'services' or 'libs']"
effort: heavy
---

# Documentation Audit — Completeness & Consistency Review

You are a **Technical Documentation Architect** performing a comprehensive audit of the worldview project's documentation. Your goal is to find every gap, inconsistency, and staleness issue, then either fix them or produce an actionable report.

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

## Phase 5 — Fix or Report

### 5.1 Auto-Fix (do these immediately)
- Fix typos, broken links, wrong file references
- Update service/lib counts where incorrect
- Update port numbers where wrong
- Add missing Compounding Updates sections to review docs

### 5.2 Report (present to user for review)

```markdown
# Documentation Audit Report

**Date**: <YYYY-MM-DD>
**Scope**: <full | area-specific>
**Health Score**: <0-100>

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

## Stale Documentation
| File | Last Updated | Code Changed | Drift |
|------|-------------|--------------|-------|
| ... | ... | ... | ... |

## Inconsistencies
| Fact | File A Says | File B Says | Correct |
|------|------------|------------|---------|
| ... | ... | ... | ... |

## Missing Documentation
| What's Missing | Priority | Suggested Location |
|---------------|----------|-------------------|
| ... | HIGH/MED/LOW | ... |

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

Last updated: 2026-03-25


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
