# PLAYBOOK-001: Contract Test Baseline

improvement_id: IMPROVE-001
title: Enforce per-service contract test baseline
owner: qa-test-engineer + service owners
timeline: 5-7 days
risk: low

## Goal

Ensure every event-producing service has contract tests that validate event schema compliance and core compatibility behavior.

## Current State

- Contract testing exists but is concentrated in selected services.
- Some event-producing services rely on architecture checks without dedicated contract tests.

## Proposed State

- Every event-producing service has at least one contract test module under tests/contract.
- CI fails when event-producing service has no contract tests.

## Acceptance Criteria

- A matrix exists mapping event producers to contract test files.
- CI job validates matrix completeness and fails on missing coverage.
- Each contract test validates at least: schema parse, required envelope fields, sample payload conformance.

## Implementation Steps

1. Build producer-service matrix from current Avro topics and service ownership.
2. Add/normalize tests at services/<service>/tests/contract/test_<topic>_contract.py.
3. Add reusable contract test fixtures in shared test utility module if needed.
4. Add CI script: fail if producer service has zero contract tests.
5. Update docs/services/<service>.md with contract test references.
6. Run targeted checks:
   - pytest services/<service>/tests -m contract -v
   - ruff check services/<service>/tests/contract
   - mypy (if typed fixtures/helpers are added)

## Validation Commands

- scripts/test.sh services/<service>
- pytest services/<service>/tests -m contract -v --tb=short

## Rollback Plan

- Remove CI gating for completeness script while retaining newly added tests.
- Re-enable in warning-only mode until false positives are resolved.

## Risks and Mitigations

- Risk: false negatives in producer detection.
  - Mitigation: maintain explicit producer registry file reviewed by service owners.
- Risk: flaky tests with external infra.
  - Mitigation: keep contract tests infra-free where possible.
