# Evaluation Framework for Continuous Improvement

> Lightweight framework for measuring and improving AI-agent-driven development quality.

## Purpose

Track the effectiveness of AI-assisted development workflows to identify weak spots, compound improvements, and measure ROI. This is not a heavy evaluation suite — it's a structured feedback loop.

## What We Track

### 1. Session Outcomes

After every significant AI session (implementation wave, bug fix, investigation), log the outcome using the template in `SESSION_TEMPLATE.md`.

Key metrics per session:
- **Skill used**: Which `/skill` was invoked
- **Task scope**: What was being done (wave ref, bug description, etc.)
- **Duration**: Approximate session time
- **Success**: Did the task complete successfully?
- **Manual interventions**: How many times did the human need to correct/redirect the agent?
- **Validation results**: Did lint/tests/review pass on first try?
- **Issues found late**: Bugs caught by review that implementation missed
- **Documentation updates**: Were docs kept current?

### 2. Quality Metrics (Aggregated Monthly)

| Metric | How to Measure | Target |
|--------|---------------|--------|
| First-pass validation rate | % of waves where lint+mypy+tests pass on first validation | >80% |
| Review finding rate | Avg blocking issues found per review | <1.0 (decreasing) |
| Bug pattern reuse | % of bugs that match existing BP-XXX patterns | Increasing |
| Manual intervention rate | Avg redirections per session | <2 (decreasing) |
| Documentation freshness | % of changed APIs with updated docs | >90% |
| Test coverage trend | Are new features getting better test coverage? | Increasing |

### 3. Skill Effectiveness

Track per skill:
| Skill | Usage Count | Avg Success Rate | Common Failure Modes |
|-------|------------|-----------------|---------------------|
| /implement | ... | ... | ... |
| /review | ... | ... | ... |
| /fix-bug | ... | ... | ... |
| /prd | ... | ... | ... |
| /plan | ... | ... | ... |
| /investigate | ... | ... | ... |
| /test-feature | ... | ... | ... |
| /qa | ... | ... | ... |
| /security-audit | ... | ... | ... |

### 4. Compounding Indicators

Track how the system improves over time:
- **BUG_PATTERNS.md growth**: New patterns added per month
- **Template evolution**: Updates to PRD/Plan/Wave templates
- **Skill refinement**: Updates to skill definitions
- **Review checklist updates**: New items added from real findings
- **Hook effectiveness**: Issues caught by hooks vs issues caught later

## How to Collect Data

### During Sessions
The `/implement`, `/fix-bug`, and `/investigate` skills should produce structured output that includes:
- Validation gate results (pass/fail per check)
- Review findings (count and severity)
- Bug patterns referenced or discovered
- Documentation updates made

### After Sessions
Use the session template to log:
```bash
# Create a new session log
cp docs/ai-interactions/evals/SESSION_TEMPLATE.md \
   docs/ai-interactions/evals/sessions/YYYY-MM-DD-<slug>.md
# Edit with session details
```

### Monthly Review
Run the `/eval-review` process (manual or invoke an agent):
1. Read all session logs from the past month
2. Compute aggregate metrics
3. Identify patterns:
   - Which skills are most/least effective?
   - What are the common failure modes?
   - Which hooks catch the most issues?
   - What patterns should be added to BUG_PATTERNS.md?
4. Recommend improvements:
   - Skill definition updates
   - New hook rules
   - Template improvements
   - Review checklist additions

## Improvement Actions

When a weak spot is identified, the improvement flows into:

| Weak Spot | Improvement Target | Updated By |
|-----------|-------------------|------------|
| Agent misses a class of bugs | `BUG_PATTERNS.md` + `HIGH_RISK_PATTERNS.md` | `/fix-bug`, manual |
| Agent skips a workflow step | Skill definition (e.g., `implement/SKILL.md`) | Manual |
| Hook misses a check | Hook script (e.g., `pre-commit-validate.sh`) | Manual |
| Template missing a section | Template (e.g., `docs/specs/TEMPLATE.md`) | Manual |
| Review misses an issue | `REVIEW_CHECKLIST.md` | `/review`, manual |
| Agent needs more context | `.claude-context.md` for service | Manual |
| Recurring security issue | `security-audit/SKILL.md` | `/security-audit`, manual |

## File Structure

```
docs/ai-interactions/evals/
├── EVAL_FRAMEWORK.md          # This file — framework description
├── SESSION_TEMPLATE.md        # Template for session logs
├── OUTCOME_LOG.md            # Running summary of all sessions
└── sessions/                  # Individual session logs (YYYY-MM-DD-slug.md)
```

## Anti-Patterns

- Don't log sessions that were trivial (< 5 minutes, single file edit)
- Don't over-optimize metrics — the goal is to improve workflow, not hit numbers
- Don't change skill definitions after every session — batch improvements monthly
- Don't treat this as a performance review — it's a system improvement tool
