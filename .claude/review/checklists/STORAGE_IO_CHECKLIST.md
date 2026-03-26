# Storage I/O Checklist

> Checklist for database, MinIO, and Valkey storage operations in worldview services.

## 1. Database Atomicity

- [ ] Multi-step DB writes in a single transaction
- [ ] Transaction scope is minimal (no external calls inside tx)
- [ ] Rollback on any step failure (no partial commits)
- [ ] Alembic migration for all schema changes
- [ ] Migration is additive (backward-compatible)

## 2. MinIO / S3 Operations

- [ ] Key follows convention: `<service>/<domain>/<resource_id>/<artifact>/<version>.<ext>`
- [ ] Bronze layer: raw provider responses (immutable)
- [ ] Silver layer: canonical/cleaned data
- [ ] Claim-check pointer includes full key path
- [ ] MinIO unavailable treated as RetryableError
- [ ] Orphaned objects acceptable (no cascade cleanup required)

## 3. Valkey Cache Operations

- [ ] Key follows pattern: `<scope>:<version>:<resource>:<id>[:<qualifier>]`
- [ ] TTL set on all cache entries (no indefinite caching)
- [ ] Cache invalidation on source data change (DEL key, not update)
- [ ] Fail-open: Valkey unavailable → skip cache, serve from DB
- [ ] No business logic depends on cache hit (cache is optimization only)
- [ ] Negative cache sentinel for transient errors (prevents stampede)
- [ ] In-flight dedup where applicable (`asyncio.Future` pattern)

## 4. Error Detection & Classification

- [ ] DB connection errors → RetryableError
- [ ] Constraint violations → FatalError (bad data, not transient)
- [ ] MinIO timeout → RetryableError with backoff
- [ ] Valkey timeout → Skip cache, continue (fail-open)
- [ ] All errors logged with structured context (structlog)

## 5. Resource Cleanup

- [ ] DB sessions closed on all paths (async context manager)
- [ ] MinIO client handles connection cleanup
- [ ] Temporary files removed after processing
- [ ] No resource leaks in error paths (finally blocks)

## 6. Observability

- [ ] DB query duration logged or metricked
- [ ] MinIO operation duration tracked
- [ ] Cache hit/miss ratio exposed
- [ ] Slow queries identified and optimized (< 200ms p95 target)

## 7. Security

- [ ] No SQL injection (parameterized queries or ORM only)
- [ ] DB credentials from env vars (never hardcoded)
- [ ] MinIO credentials from env vars
- [ ] No PII in cache keys
- [ ] Tenant isolation in all queries (WHERE tenant_id = ?)

## Compounding Updates
This document is a living reference. Update it when:
- New storage patterns are introduced (e.g., new MinIO layer)
- Storage-related bugs are discovered
- Cache strategy changes

Last updated: 2026-03-25
