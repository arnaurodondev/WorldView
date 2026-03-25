# PLAYBOOK-004: Plan/Task Schema Formalization Pilot

improvement_id: IMPROVE-006
title: Formalize plan and task schemas
owner: tech-lead + architecture-decision-lead
timeline: 3-4 weeks
risk: medium

## Goal

Move agent plan/task definitions from convention-only markdown to machine-validated schema-backed artifacts.

## Current State

- Plan/task definitions are documented in markdown prompts, templates, and runbooks.
- Validation is manual and review-driven.

## Proposed State

- A schema (JSON Schema or equivalent) validates required fields, constraints, and lifecycle states for plans/tasks.
- CI validates plan/task artifacts before merge.

## Acceptance Criteria

- At least 3 existing workflows are migrated to schema-backed plan/task definitions.
- CI rejects invalid plan/task artifacts.
- Migration guidance and examples are published.

## Implementation Steps

1. Define minimal schema scope:
   - plan: id, objective, constraints, ordered steps, success criteria
   - task: id, preconditions, inputs, outputs, postconditions, retry policy
2. Create validation CLI (or use existing schema tooling).
3. Add CI check for plan/task files in docs/ai-interactions.
4. Migrate 3 representative workflows to new format.
5. Produce side-by-side examples (markdown narrative + schema object).
6. Publish ADR for long-term framework decision (internal schema vs OpenSpec).

## Validation Commands

- python scripts/validate_plan_task_specs.py docs/ai-interactions
- pytest tests/architecture -k plan_task_validation -v

## Rollback Plan

- Keep schema validation in advisory mode while migration coverage is below threshold.

## Risks and Mitigations

- Risk: migration overhead for existing docs.
  - Mitigation: dual-format transition period with converter templates.
- Risk: over-specification that slows execution.
  - Mitigation: start with minimal required fields and iterate.
