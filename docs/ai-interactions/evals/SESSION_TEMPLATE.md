---
date: YYYY-MM-DD
skill: /implement | /fix-bug | /investigate | /review | /prd | /plan | /qa | /test-feature | /security-audit
scope: "<brief description of what was done>"
plan-ref: "PLAN-NNNN Wave X-Y (if applicable)"
duration: "~Xm"
success: true | false | partial
---

# Session Log: <Date> — <Brief Title>

## Task
<What was the goal of this session?>

## Outcome
<What was accomplished? If partial/failed, what was missing?>

## Validation Results

| Check | Result | Notes |
|-------|--------|-------|
| ruff check | PASS/FAIL | First attempt? |
| ruff format | PASS/FAIL | |
| mypy | PASS/FAIL | |
| Unit tests | PASS/FAIL | Count: X passed, Y failed |
| Integration tests | PASS/FAIL/SKIP | |
| Architecture tests | PASS/FAIL | |
| Review | APPROVE/CHANGES | Findings count: X |

## Manual Interventions
<How many times did the human need to correct/redirect the agent?>

| # | What Happened | Why | Could Be Prevented By |
|---|--------------|-----|----------------------|
| 1 | ... | ... | Better skill definition / hook / pattern |

## Issues Found

### By Validation (caught early)
- <Issue caught by lint/test/hook>

### By Review (caught late)
- <Issue caught by /review that implementation missed>

### Missed (caught after session)
- <Issue found after the session ended>

## Bug Patterns
- **Referenced**: BP-001, BP-003 (checked during implementation)
- **New pattern discovered**: <none | BP-XXX description>

## Documentation Updated
- [ ] Service doc
- [ ] .claude-context.md
- [ ] BUG_PATTERNS.md
- [ ] MASTER_PLAN.md
- [ ] env example

## Improvement Recommendations
<What should be improved in the workflow/skills/hooks/templates based on this session?>

- **Skill improvement**: <e.g., "/implement should also check X">
- **Hook improvement**: <e.g., "pre-commit should catch Y">
- **Template improvement**: <e.g., "PRD template should include Z">
- **Pattern to add**: <e.g., "New bug pattern for W">
