# Workflow Map: Agent Task Execution

Last updated: 2026-03-24

## End-to-End Flow

1. Understand context
2. Plan work
3. Define tasks
4. Implement in small validated steps
5. Run test layers
6. Validate against architecture and contracts
7. Update docs
8. Complete and archive

## Decision Tree

### Bug fix

1. check `docs/ai-interactions/BUG_PATTERNS.md`
2. reproduce failure
3. add regression test
4. implement minimal fix
5. re-run targeted tests

### Feature or enhancement

1. prepare plan and tasks
2. identify contract impacts
3. implement with tests
4. run integration/e2e if cross-service
5. update docs and archives

### Refactor

1. keep behavior unchanged
2. preserve architecture boundaries
3. run broader tests to prevent regressions

## Test Layer Sequence

1. Architecture tests
2. Library tests
3. Service fast-path tests (`not integration and not e2e and not live and not slow`)
4. Contract tests
5. Integration tests
6. E2E tests

## Execution Anchors

- quick run: `scripts/test-quick.sh`
- full run: `scripts/test-full.sh`
- compose readiness: `scripts/wait-for-services.sh`
- infrastructure guide: `docs/testing/DOCKER_COMPOSE_TEST_GUIDE.md`

## Service Interaction Snapshot

- frontend -> api-gateway (REST)
- services exchange events through Kafka + Avro
- object payloads follow claim-check with MinIO references
- read APIs use service-owned stores, not cross-service DB joins
