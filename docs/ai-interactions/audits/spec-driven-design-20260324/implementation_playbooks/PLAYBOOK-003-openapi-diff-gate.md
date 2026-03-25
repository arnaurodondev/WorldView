# PLAYBOOK-003: OpenAPI Lint and Diff Gate

improvement_id: IMPROVE-003
title: Add OpenAPI lint and breaking-change diff gate
owner: backend-engineer + devops-platform-engineer
timeline: 4-6 days
risk: low

## Goal

Catch API contract regressions in pull requests before merge.

## Current State

- FastAPI generates OpenAPI implicitly.
- CI does not consistently lint OpenAPI style/quality or enforce explicit breaking-change checks.

## Proposed State

- CI exports OpenAPI per changed service, lints with configured rules, and runs breaking-change diff against base branch artifact.

## Acceptance Criteria

- Every changed API service produces OpenAPI artifact in CI.
- Lint violations block merge.
- Breaking changes require explicit approval pathway.

## Implementation Steps

1. Add command to export per-service OpenAPI JSON in CI.
2. Integrate spectral lint with project ruleset.
3. Integrate openapi-diff against base branch artifact.
4. Mark critical breaking changes as hard-fail.
5. Upload lint and diff reports as CI artifacts.
6. Document exception/approval process for intentional breaks.

## Validation Commands

- python -c "from <service>.api.main import app; import json; print(json.dumps(app.openapi()))" > /tmp/openapi.json
- spectral lint /tmp/openapi.json
- openapi-diff base.json head.json

## Rollback Plan

- Keep artifact generation and lint; switch diff to warning-only until false positives are tuned.

## Risks and Mitigations

- Risk: generated spec noise from unstable ordering.
  - Mitigation: canonicalize JSON serialization before diff.
- Risk: high friction for intentional breaking changes.
  - Mitigation: codify approved override label and review process.
