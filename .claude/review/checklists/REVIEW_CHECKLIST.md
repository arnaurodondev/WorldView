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
- [ ] MinIO write before DB commit: compensating delete implemented on rollback (§4.4)
- [ ] Compensating GC failures logged as WARNING, original exception preserved and re-raised

## 4. Idempotency

- [ ] Kafka consumers handle duplicate events (event_id dedup or upsert)
- [ ] Processing is safe to retry (no double-counting, no duplicate notifications)
- [ ] Idempotency key checked before side effects
- [ ] Database operations use upsert or check-before-insert
- [ ] Outbox payload includes all required Avro envelope fields (event_id, event_type, schema_version, occurred_at)
- [ ] **Atomic dedup**: `is_duplicate` + `process_message` + `mark_processed` are NOT in separate transactions — use BP-035/BP-045 `INSERT…ON CONFLICT DO NOTHING RETURNING` inside the same UoW as business logic; `is_duplicate()` → `return False`; `mark_processed()` → no-op (HR-021)
- [ ] **All storage steps have skip-if-exists (D-008)**: if `_store_bronze` has an `exists()` guard, `_store_canonical` and any other storage steps must have the same guard — partial guards break retry idempotency (BP-048)

## 4b. Unit of Work / Transaction Integrity (R26)

- [ ] UoW `__aexit__`: no `else: await self.commit()` — only rolls back on exception (R26, HR-025)
- [ ] Every mutating use case calls `await uow.commit()` explicitly before returning (not relying on `__aexit__`)
- [ ] Rollback is wrapped in try/except; session close is in the `finally` block (prevents session leak when rollback raises)
- [ ] Post-commit hooks run INSIDE `commit()` via `_drain_post_commit_hooks()` — NOT in `__aexit__()` (see STANDARDS.md §17.3)
- [ ] Post-commit hook failures are caught and logged — never propagated (a cache-flush failure must not dead-letter a successfully-committed message)

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
- [ ] Error messages don't leak internal details to clients — **`/readyz` and `/healthz` endpoints return opaque `"error"` strings in HTTP body, never raw exception messages** (BP-047, HR-023)
- [ ] Token comparisons use `hmac.compare_digest()` (not `==`)
- [ ] Query pagination has upper bound (max limit parameter)
- [ ] URL inputs validate scheme and reject private IP ranges (SSRF prevention)
- [ ] **JWT decode passes `issuer=` parameter** — `jwt.decode(token, key, algorithms=["RS256"], issuer=expected_issuer)` — missing issuer= enables issuer-spoofing auth bypass (BP-145, HR-026)
- [ ] **One-time-use Valkey state (PKCE codes, nonces) uses atomic `GETDEL`**, not `GET` then `DEL` — two-command pipeline creates replay window (BP-146, HR-027)
- [ ] **Middleware reads `app.state` inside `dispatch()`, not at `__init__` time** — constructors run before lifespan, capturing `None` permanently disables features (BP-144, HR-028)
- [ ] **Repository `save()` methods do NOT call `session.rollback()`** — repo-level rollback poisons the shared session; only the use-case `async with session_factory()` context owns rollback (BP-141, HR-029)
- [ ] **`InternalJWTMiddleware` is mounted on all services that accept internal requests** — adding a new service without it bypasses auth entirely (PLAN-0025 pattern)

## 6b. Schema & Data Pipeline Integrity

- [ ] Migration DDL matches ORM columns exactly — names, types, defaults, nullability (BP-008, BP-019)
- [ ] `move_to_dead_letter` INSERTs a DLQ row with original payload (not just status update) (BP-020)
- [ ] DLQ `requeue()` preserves original `aggregate_id`, `aggregate_type`, `event_type` from stored DLQ columns — never hardcode or use outbox PK as `aggregate_id` (BP-024)
- [ ] DNS resolution in async context uses `asyncio.to_thread(socket.getaddrinfo, ...)` with explicit timeout — never blocking `socket.getaddrinfo` directly on event loop (BP-025)
- [ ] SSRF IP check uses `addr.is_private or addr.is_reserved or addr.is_loopback or addr.is_multicast` — covers IPv4-mapped IPv6 (`::ffff:`) after extracting `addr.ipv4_mapped` (BP-026)
- [ ] Avro contract tests exist for every schema a service produces
- [ ] `doc_id` in outbox payloads is a per-document UUIDv7 (not source/aggregate ID)
- [ ] SSRF URL validation resolves DNS hostnames, not just IP literals
- [ ] LSH/cache writes happen AFTER DB commit, not before (prevents phantom entries on rollback)
- [ ] **Cache invalidation uses `schedule_post_commit(cache.invalidate(id))`**, never `await cache.invalidate(id)` inside `process_message()` — invalidating before commit enables stale-read-into-cache races (BP-046, HR-022, M-005)
- [ ] **Avro record names are valid Java identifiers (PascalCase)** — no dots, no version suffixes in `"name"` field; dots belong in `"namespace"` only (BP-051)
- [ ] **Avro namespace uses canonical format `com.worldview.<service>.events`** — all schemas in a service share the same namespace; inconsistent namespaces create divergent Schema Registry subjects (BP-052)
- [ ] **`schema_version` base class default is `1`, not `0`** — default 0 means subclasses that forget to override emit version-0 events silently (BP-053)
- [ ] **`asyncio.Event.set()` in confluent-kafka delivery callbacks uses `loop.call_soon_threadsafe(event.set)`** — direct `event.set()` from librdkafka C thread is not thread-safe (BP-050, HR-024)
- [ ] **Repositories with read/write session splitting: `get_or_create` reads back via write session after INSERT** — never call `self.get()` (read session) immediately after INSERT on write session (BP-049)

## 7. Architecture Compliance

- [ ] Domain layer has zero infrastructure imports
- [ ] Application layer depends only on domain + ports (no direct DB/Kafka)
- [ ] Application layer has `application/ports/` directory with port ABCs (R20, DOMAIN-PORTS)
- [ ] Infrastructure layer implements port interfaces
- [ ] No cross-service DB access (use Kafka events or REST)
- [ ] Uses shared libs correctly (`common`, `contracts`, `messaging`, `storage`, `observability`, `ml-clients`)
- [ ] No direct imports of underlying packages (no `aiokafka`, `redis.asyncio`, `Minio`, `logging.getLogger`)
- [ ] Import guards pass: `python3 scripts/import_guards/check_import_guards.py --strict --baseline scripts/import_guards/baseline.json`
- [ ] `setattr` uses field allowlist, never user-controlled keys directly
- [ ] All Kafka consumers extend `BaseKafkaConsumer` — no direct `confluent_kafka.Consumer` (R20)
- [ ] `domain/errors.py` defines `DomainError(Exception)` — all other exceptions inherit from it (R21)
- [ ] Service-specific error alias defined as subclass, not assignment (e.g., `class MyServiceError(DomainError):`)

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

## 10. Frontend / TypeScript (applies when `apps/frontend/` files are changed)

Mark N/A for pure backend changes.

### 10a. Architecture
- [ ] **Frontend only calls S9** — no direct backend service URLs anywhere in `apps/frontend/` (HR-030, R14)
- [ ] All API calls go through `gatewayClient.<method>()` in `src/lib/gateway-client.ts`
- [ ] New gateway endpoints are added as typed methods (no raw `fetch()` calls in components)
- [ ] Next.js app routes follow the `app/(protected)/` auth-guarded layout for all pages requiring auth

### 10b. TypeScript Correctness
- [ ] **No `any` types** — all gateway responses, hook return values, and handler params are typed (HR-032)
- [ ] `pnpm typecheck` passes with 0 errors
- [ ] Interfaces used for object shapes; `type` for unions/intersections

### 10c. State Management
- [ ] **TanStack Query for all server state** — no `useState+useEffect` for API calls (HR-033)
- [ ] `enabled: Boolean(id)` guard on all entity-specific queries
- [ ] Auth token stored in React state only — never `localStorage`, never client-accessible cookie (HR-035)

### 10d. UI States (Required — not optional)
- [ ] **Every data-dependent component handles all 3 states**: loading skeleton, error card with retry, empty state (HR-034)
- [ ] Skeletons match the shape of loaded content
- [ ] Error states include a recovery action (retry button, navigation link)

### 10e. Security
- [ ] **No `dangerouslySetInnerHTML` without DOMPurify sanitization** (HR-031)
- [ ] No PII in `localStorage` or `sessionStorage`
- [ ] No secrets or API keys in `NEXT_PUBLIC_*` env vars or client-side code
- [ ] WebSocket auth uses `?token=<access_token>`, not `?user_id=` (HR-038, ADR-F-02)
- [ ] SSE streams use `AbortController` with cleanup on unmount (HR-039)

### 10f. Dark Theme Compliance
- [ ] All colors use CSS variables from `docs/ui/DESIGN_SYSTEM.md §2` — no hardcoded hex (HR-037)
- [ ] Positive values use `--positive` (green), negative use `--negative` (red) — consistently
- [ ] `class="dark"` remains on `<html>` — no conditional theme switching

### 10g. Dependencies
- [ ] **Exact version pins** in `package.json` (no `^` or `~`) (HR-036)
- [ ] `pnpm audit` shows 0 vulnerabilities after any dependency change
- [ ] No UI libraries added other than shadcn/ui (Radix primitives + Tailwind)
- [ ] `pnpm-lock.yaml` committed and in sync

### 10h. Tests
- [ ] Every new component has at minimum: loading state test + happy path test
- [ ] Gateway client is mocked at the `gatewayClient` boundary (not `fetch`)
- [ ] E2E test added for new pages (smoke + data flow)

---

## Scoring

| Result | Meaning |
|--------|---------|
| All PASS or N/A | **APPROVE** |
| FAIL in sections 7-8 only | **APPROVE WITH NOTES** (improvements recommended) |
| FAIL in sections 1-6 | **REQUEST CHANGES** (must fix) |
| FAIL in section 9 | **BLOCK** (test integrity violation — R19) |
| FAIL in section 10a, 10b, 10e | **REQUEST CHANGES** (frontend arch/security violations) |
| Multiple FAIL in 1-6 | **BLOCK** (serious issues) |
