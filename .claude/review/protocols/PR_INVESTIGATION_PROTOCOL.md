# PR Investigation Protocol

> Structured reasoning method for analyzing code changes. Follow this protocol step-by-step.

## Step 1: Map Change Surface

For each changed file:
- **File path** and purpose in the architecture
- **Nature**: new code, modification, deletion, rename
- **Layer**: domain, application, infrastructure, API, test, config, docs
- **Functions/classes changed**: list with one-line descriptions
- **Risk level**: HIGH (security, data, concurrency), MEDIUM (business logic), LOW (cosmetic)

## Step 2: Identify Side Effects

For each changed function/method:
- **Inputs**: parameters, config reads, DB reads
- **Outputs**: return values, DB writes, Kafka events, HTTP responses
- **External actions**: API calls, file I/O, cache mutations
- **State mutations**: global state, class state, DB state, cache state

## Step 3: Enumerate Failure Points

For each function with side effects:

| Step in function | Can fail? | How? | System state after failure | Recovery? |
|-----------------|-----------|------|---------------------------|-----------|
| 1. Read from DB | Yes | Connection timeout | Unchanged | Retry |
| 2. Transform data | Yes | Validation error | Unchanged | Return error |
| 3. Write to DB | Yes | Constraint violation | Unchanged (tx rollback) | Fix data |
| 4. Publish event | Yes | Kafka unavailable | DB written, event lost | Outbox retry |

## Step 4: Validate Invariants

Check each invariant category against the change:

### Data Integrity
- [ ] All entity IDs use UUIDv7 (not uuid4)
- [ ] All timestamps are UTC-aware
- [ ] Foreign key references are valid
- [ ] Enum values are validated at boundaries

### Transaction Boundaries
- [ ] No dual writes (DB + Kafka) outside outbox pattern
- [ ] Transactions are scoped to minimum necessary
- [ ] Long-running operations don't hold transactions open

### Ordering
- [ ] Events are produced in logical order
- [ ] Consumer handles out-of-order delivery
- [ ] Idempotent processing of duplicate events

### Idempotency
- [ ] Event_id dedup or upsert semantics
- [ ] No side effects on re-delivery (notifications, counting, etc.)
- [ ] Idempotency key checked before processing

### Visibility
- [ ] Changes are visible to dependent services (events published)
- [ ] Cache invalidation occurs when source data changes
- [ ] Query results reflect committed state

## Step 5: Assess Blast Radius

- What depends on the changed code? (callers, consumers, downstream)
- Could the change break any caller's assumptions?
- Are there implicit contracts being changed?
- What's the worst case if this code is wrong?

## Step 6: Check Architecture Compliance

- [ ] Domain layer has no infrastructure imports
- [ ] Application layer depends only on domain + ports
- [ ] Infrastructure implements ports
- [ ] No cross-service DB access
- [ ] Correct use of shared libraries

## Step 7: Security Scan

- [ ] Input validated at API boundaries
- [ ] No SQL injection vectors
- [ ] No secrets in code or logs
- [ ] Multi-tenant isolation maintained

## Step 8: Test Coverage Assessment

- [ ] New public functions have tests
- [ ] Edge cases covered
- [ ] Error paths tested
- [ ] Integration tests for new external interactions

## Step 9: Documentation Impact

- [ ] API changes reflected in service docs
- [ ] Event changes reflected in service docs
- [ ] Config changes in env example files
- [ ] Architecture diagrams still accurate

## Step 10: Synthesize Findings

Classify all findings:
- **BLOCKING**: Must fix before merge (bugs, security, data integrity)
- **IMPROVEMENT**: Should fix (code quality, test coverage, documentation)
- **NOTE**: Observations for future reference
