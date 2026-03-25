# Debugging Log

Last updated: 2026-03-24

## Issues Found and Fixed

### Issue 001: Missing centralized test execution map

- Symptom: difficult to reason about current test tiers and coverage gaps from one place.
- Root cause: service-local testing evolved faster than shared documentation.
- Fix applied: created `docs/testing/TEST_INFRASTRUCTURE_MAP.md` and `docs/testing/TEST_EXECUTION_REPORT.md`.
- Verification: files added and aligned with discovered repository structure.

### Issue 002: Missing local layered test wrappers

- Symptom: no single root command for quick versus full layered execution.
- Root cause: existing scripts focused on broad service/lib runs without explicit test pyramid flow.
- Fix applied: added `scripts/test-quick.sh`, `scripts/test-full.sh`, `scripts/wait-for-services.sh`.
- Verification: shell syntax checks run successfully.

### Issue 003: No repository-level reusable contract test templates

- Symptom: contract testing patterns were repeated and concentrated in specific services.
- Root cause: lack of shared base classes for Avro/OpenAPI/integration contracts.
- Fix applied: added `tests/contract/templates/` with reusable base classes.
- Verification: contract template module import and test collection pass.

## Known Open Issues

### Open 001: Cross-service contract parity not complete

- Status: open
- Impact: medium/high for spec-driven maturity
- Next step: add service-specific contract suites for market-data, market-ingestion, content services, gateway.

### Open 002: Full all-layer execution not completed in this wave

- Status: open
- Impact: medium
- Next step: execute `scripts/test-full.sh` in a clean environment with Docker resources available and capture final numbers.
