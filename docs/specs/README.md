# Product Requirements Documents (PRDs)

This directory contains all product requirement documents for the worldview platform.

## Creating a New PRD

Use the `/prd` skill:
```
/prd "Add portfolio alerts when price targets are hit"
```

This starts an interactive discussion that produces a structured PRD.

## Template

See [TEMPLATE.md](TEMPLATE.md) for the standardized PRD format.

## Index

| ID | Title | Status | Priority | Services | Created |
|----|-------|--------|----------|----------|---------|
| PRD-0001 | Intelligence Pipeline | approved | P0 | S2, S3 | 2026-03 |
| PRD-0002 | Multi-Tenant SaaS Foundation | approved | P0 | S1, S9 | 2026-03 |
| PRD-0014 | Unstructured Data Pipeline (v1) | in-progress | P0 | S4, S5, S6, S7, S10 | 2026-03 |

## Conventions

- **IDs**: Sequential four-digit numbers: PRD-0001, PRD-0002, ...
- **File names**: `<NNNN>-<slug>.md` (e.g., `0001-portfolio-price-alerts.md`)
- **Status flow**: `draft` → `in-review` → `approved` → `in-progress` → `completed`
- **One PRD per feature**: Don't combine unrelated features
- **Plan linkage**: Each approved PRD gets a corresponding PLAN-NNNN in `docs/plans/`
