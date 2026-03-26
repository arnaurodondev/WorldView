# AI Interactions

This directory contains AI-driven execution artifacts, workflow governance, and the knowledge base that compounds over time.

## Active System

The worldview project uses a **skill-based AI workflow** defined in `.claude/skills/`. Skills enforce structured pipelines with validation gates, documentation updates, and compounding knowledge.

### Entry Points
- **`CLAUDE.md`** (root) — Primary entry point, routes to skills
- **`.claude/skills/`** — 11 workflow skills (`/prd`, `/plan`, `/implement`, `/review`, `/fix-bug`, `/investigate`, `/test-feature`, `/qa`, `/security-audit`, `/refactor`, `/docs-audit`)
- **`.claude/agents/`** — 13 role-specific agent definitions
- **`.claude/review/`** — Code review framework (protocols, checklists, heuristics, knowledge)
- **`.claude/settings.json`** — Hooks for automatic enforcement

### Workflow
```
/prd (interactive)  → docs/specs/<NNNN>.md
/plan               → docs/plans/<NNNN>-plan.md
/implement (per wave) → code + tests + docs + commit
/review             → structured review report
/qa                 → full quality assurance pass
```

## Directory Structure

### Active References
| Path | Purpose | Updated By |
|------|---------|------------|
| `BUG_PATTERNS.md` | Known failure patterns (BP-001+). Mandatory pre-read for all agents. | `/fix-bug`, `/investigate`, `/review` |
| `WORKFLOW_MAP.md` | Decision tree for task types (bug fix, feature, refactor) | Manual |
| `ORCHESTRATOR_RUNBOOK.md` | 1 orchestrator + N workers topology, task state machine | Manual |
| `bug-patterns/` | Extended debugging guides and hotfix procedures | `/fix-bug` |
| `references/` | EODHD endpoint reference | Manual |
| `evals/` | Evaluation framework, session logs, outcome tracking | `/implement`, manual |

### Active Specifications (Unstructured Data Ingestion Block)
| Path | Purpose |
|------|---------|
| `agent-responses/0014-PRD-v1-final.md` | **Authoritative PRD** for S4-S7, S10 ingestion pipeline |
| `agent-responses/0011-PRD-*.md` | Merged PRD (v4.0, superseded by 0014 but useful reference) |
| `agent-prompts/0011-*` | Foundation waves (blocking fixes) |
| `agent-prompts/0012-*` | S4+S5 implementation waves (7 waves) |
| `agent-prompts/0013-*` | S6+S7+S10 implementation waves (13 waves) |
| `agent-responses/0011-response-*` | Planning responses for foundation waves |
| `agent-responses/0012-response-*` | Planning responses for S4+S5 waves |
| `agent-responses/0013-response-*` | Planning responses for S6+S7+S10 waves |
| `agent-responses/0014-response-*` | Common library extension response |

### Templates (Active)
| Path | Purpose |
|------|---------|
| `agent-planning/0000-*` | Prompt library index and conventions |
| `agent-planning/0005-*` | Generic implementation plan template |
| `agent-planning/PLANNING_TEMPLATE.md` | Planning prompt template |
| `agent-planning/PLANNING_CHECKLIST.md` | Pre-planning checklist |
| `agent-prompts/0000-*` | Execution prompt index and wave generation template |
| `agent-responses/0000-response-template.md` | Response artifact template |
| `agent-responses/0001-review-checklist.md` | Review checklist for responses |

### Archived
Historical wave artifacts (Waves 0001-0010, 0015-0016) have been moved to `docs/archive/ai-interactions/`.

## Compounding Knowledge

Every skill execution should check whether these documents need updating:
- `BUG_PATTERNS.md` — New failure patterns
- `.claude/review/heuristics/HIGH_RISK_PATTERNS.md` — New risk signals
- `.claude/review/checklists/REVIEW_CHECKLIST.md` — New checks
- `docs/STANDARDS.md` — New conventions
- Service `.claude-context.md` files — Changed capabilities

## Evaluation
Session outcomes are logged in `evals/sessions/` using `evals/SESSION_TEMPLATE.md`. Monthly reviews aggregate data into `evals/OUTCOME_LOG.md`. See `evals/EVAL_FRAMEWORK.md` for the full process.
