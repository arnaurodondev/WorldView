# PLAYBOOK-002: Avro Mirror Parity Gate

improvement_id: IMPROVE-002
title: Add Avro mirror parity check
owner: data-platform-engineer + devops-platform-engineer
timeline: 2-3 days
risk: low

## Goal

Prevent drift between centralized Kafka schemas and service-local mirror schemas.

## Current State

- Schemas exist in both infra/kafka/schemas and service-level messaging schema dirs.
- Validation checks syntax/parse, but parity across locations is not strictly gated.

## Proposed State

- CI parity check compares canonical and mirror schema files and fails on mismatch.
- CI uploads parity diff artifact for troubleshooting.

## Acceptance Criteria

- Every mirrored schema is byte-equal or semantically equivalent to canonical source.
- CI blocks merge on mismatches.
- A local make/script command reproduces the parity check.

## Implementation Steps

1. Define canonical source of truth path and mirror map.
2. Implement parity checker script:
   - file existence parity
   - normalized JSON semantic equality
   - optional schema fingerprint match
3. Add CI job after checkout and before long-running tests.
4. Add artifact output with mismatch details.
5. Add remediation docs for contributors.

## Validation Commands

- python scripts/check_schema_parity.py
- python scripts/check_schema_parity.py --report-json /tmp/schema-parity.json

## Rollback Plan

- Downgrade parity gate to warning while resolving mapping/normalization edge cases.

## Risks and Mitigations

- Risk: canonical-vs-mirror ownership confusion.
  - Mitigation: codify ownership in docs and script metadata.
- Risk: formatting-only diffs produce noise.
  - Mitigation: compare normalized parsed JSON, not raw bytes only.
