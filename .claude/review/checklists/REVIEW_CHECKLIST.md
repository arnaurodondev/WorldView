# Review Checklist

> Point-by-point checklist for code review. All sections must PASS or N/A for approval.
> A FAIL in sections 1-6 blocks approval.

## 1. Resource Management

- [ ] Resources acquired in try blocks have matching finally/cleanup
- [ ] Temporary files/objects are cleaned up on all paths (success AND failure)
- [ ] Partial failure doesn't leave orphaned resources (DB connections, file handles)
- [ ] Async context managers properly used for DB sessions
- [ ] Advisory/distributed locks do not span external I/O (fetch outside lock, write inside)
- [ ] Lock duration is bounded and predictable (milliseconds, not seconds)

## 2. Exception Handling

- [ ] No bare `except:` or `except Exception:` without re-raise
- [ ] Errors classified: `RetryableError` vs `FatalError` (per libs/messaging)
- [ ] `except` blocks don't swallow errors silently (at minimum, log them)
- [ ] `finally` blocks don't mask original exceptions with new ones
- [ ] Async callbacks have proper error handling (not fire-and-forget)

## 3. Storage Atomicity

- [ ] Multi-step writes use staging→final pattern (or single transaction)
- [ ] DB + Kafka dual writes use outbox pattern (never separate transactions)
- [ ] Failure during multi-step operations has cleanup or is idempotent
- [ ] MinIO writes use claim-check pattern for Kafka events
- [ ] Outbox payload field names match Avro schema exactly

## 4. Idempotency

- [ ] Kafka consumers handle duplicate events (event_id dedup or upsert)
- [ ] Processing is safe to retry (no double-counting, no duplicate notifications)
- [ ] Idempotency key checked before side effects
- [ ] Database operations use upsert or check-before-insert
- [ ] Outbox payload includes all required Avro envelope fields (event_id, event_type, schema_version, occurred_at)

## 5. Data Integrity

- [ ] UUIDv7 for all new entity IDs (`common.ids.new_uuid7()`)
- [ ] UTC-only timestamps (`common.time.utc_now()`, no naive datetimes)
- [ ] Foreign key integrity maintained (or documented as logical-only)
- [ ] Enum values validated at system boundaries
- [ ] Null handling explicit (no implicit None propagation)

## 6. Security

- [ ] Input validated at all API boundaries (Pydantic models)
- [ ] No SQL injection (parameterized queries or ORM only)
- [ ] No hardcoded secrets, tokens, or API keys
- [ ] No PII or secrets in log output
- [ ] Multi-tenant isolation: all queries filter by tenant_id
- [ ] Error messages don't leak internal details to clients
- [ ] Token comparisons use `hmac.compare_digest()` (not `==`)
- [ ] Query pagination has upper bound (max limit parameter)
- [ ] URL inputs validate scheme and reject private IP ranges (SSRF prevention)

## 6b. Schema & Data Pipeline Integrity

- [ ] Migration DDL matches ORM columns exactly — names, types, defaults, nullability (BP-008, BP-019)
- [ ] `move_to_dead_letter` INSERTs a DLQ row with original payload (not just status update) (BP-020)
- [ ] Avro contract tests exist for every schema a service produces
- [ ] `doc_id` in outbox payloads is a per-document UUIDv7 (not source/aggregate ID)
- [ ] SSRF URL validation resolves DNS hostnames, not just IP literals
- [ ] LSH/cache writes happen AFTER DB commit, not before (prevents phantom entries on rollback)

## 7. Architecture Compliance

- [ ] Domain layer has zero infrastructure imports
- [ ] Application layer depends only on domain + ports (no direct DB/Kafka)
- [ ] Infrastructure layer implements port interfaces
- [ ] No cross-service DB access (use Kafka events or REST)
- [ ] Uses shared libs correctly (`common`, `contracts`, `messaging`, `storage`, `observability`, `ml-clients`)
- [ ] No direct imports of underlying packages (no `aiokafka`, `redis.asyncio`, `Minio`, `logging.getLogger`)
- [ ] Import guards pass: `python3 scripts/import_guards/check_import_guards.py --strict --baseline scripts/import_guards/baseline.json`
- [ ] `setattr` uses field allowlist, never user-controlled keys directly

## 8. Test Coverage

- [ ] New public functions/methods have unit tests
- [ ] Happy path, edge cases, and error paths tested
- [ ] Tests use correct pytest markers (`unit`, `integration`, `contract`, `e2e`)
- [ ] Mocks are at port boundaries (not deep inside implementation)
- [ ] Tests verify side effects (events published, DB updated), not just return values
- [ ] No test interdependencies (each test is independent)
- [ ] **Blast radius verified**: if Avro schemas, DB schemas, or shared lib APIs changed, downstream tests outside the immediate scope have been identified and run (see implement skill §2.4). Key files to check: `libs/contracts/tests/test_avro_alignment.py`, `tests/contract/test_avro_schemas.py`

## 9. Test Integrity (R19 — blocks approval if violated)

- [ ] No tests were deleted to make the suite pass
- [ ] No tests were marked `skip` or `xfail` as a workaround for failures
- [ ] No assertions were weakened (e.g., `==` changed to `>=`, field counts removed)
- [ ] If a test was modified, the change is justified by a specification change (cite PRD section)
- [ ] Pre-existing test failures encountered during this change were investigated and fixed — not ignored
- [ ] Root cause is always assumed to be in the implementation first; test is only corrected after proving the test was wrong

## Scoring

| Result | Meaning |
|--------|---------|
| All PASS or N/A | **APPROVE** |
| FAIL in sections 7-8 only | **APPROVE WITH NOTES** (improvements recommended) |
| FAIL in sections 1-6 | **REQUEST CHANGES** (must fix) |
| FAIL in section 9 | **BLOCK** (test integrity violation — R19) |
| Multiple FAIL in 1-6 | **BLOCK** (serious issues) |
