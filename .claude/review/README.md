# Code Review Framework

Structured reasoning framework for AI-assisted code review. Used by the `/review` skill and available to all agents.

## Architecture

```
review/
├── protocols/          # Structured reasoning methods
│   └── PR_INVESTIGATION_PROTOCOL.md
├── checklists/         # Point-by-point validation
│   └── REVIEW_CHECKLIST.md
├── heuristics/         # Pattern detection and risk signals
│   └── HIGH_RISK_PATTERNS.md
└── knowledge/          # Historical patterns and domain knowledge
    └── README.md (points to docs/ai-interactions/BUG_PATTERNS.md)
```

## Review Pipeline (used by /review skill)

1. **Change Surface Mapping** — Inventory all changes, classify risk
2. **Failure Mode Analysis** — Enumerate failures per function
3. **Checklist Evaluation** — Walk through REVIEW_CHECKLIST.md
4. **High-Risk Pattern Detection** — Scan against HIGH_RISK_PATTERNS.md
5. **Bug Pattern Regression Check** — Cross-reference BUG_PATTERNS.md
6. **Report Generation** — Structured findings with severity and fixes

## Source

This framework consolidates and extends the `.agents/` directory. The original `.agents/` files remain as the canonical source; this directory provides the integrated structure used by Claude Code skills.
