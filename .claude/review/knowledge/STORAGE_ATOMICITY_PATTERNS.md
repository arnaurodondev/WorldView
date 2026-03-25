# Storage Atomicity Patterns

> Known patterns where storage operations can violate atomicity. Cross-reference during `/review`.

## SA-001: Partial Write Visible to Consumers

**Pattern**: A multi-step write operation is interrupted, leaving partial data visible.

**Example**: Writing article metadata to DB succeeds, but writing cleaned text to MinIO fails. Consumers see article with no content.

**Worldview relevance**: S5 (content store: DB + MinIO), S2 (ingestion: DB + MinIO), S3 (market data: DB write + event publish).

**Fix**: Write MinIO first (idempotent), then DB. Or use outbox pattern for eventual consistency.

## SA-002: No Cleanup on Failure

**Pattern**: Operation creates intermediate state (temp files, partial DB rows) but failure path doesn't clean up.

**Example**: Alembic migration creates table but fails on index creation. Table exists without index.

**Worldview relevance**: All services with Alembic migrations, MinIO operations.

**Fix**: Use transactions. For MinIO: overwrite is idempotent, so orphaned objects are acceptable.

## SA-003: Cleanup Exception Masks Original Error

**Pattern**: Error occurs during processing. Cleanup in `finally` block also fails, masking the original error.

**Example**: DB write fails (original error). Session rollback also fails (masking error). Log shows only rollback failure.

**Fix**: Log original error BEFORE cleanup. Use `try/except` in `finally` to catch cleanup failures separately.

## SA-004: Dual Write Without Outbox

**Pattern**: Application writes to DB in one transaction, then publishes to Kafka in a separate operation. If Kafka fails, DB has data but no event.

**Example**: S4 inserts article to DB, then publishes `content.article.raw.v1`. Kafka down → article exists but S5 never processes it.

**Worldview relevance**: ALL services that produce Kafka events. This is the #1 pattern to guard against.

**Fix**: Outbox pattern (libs/messaging). Write DB + outbox row in same transaction. Dispatcher publishes from outbox.

## SA-005: Non-Atomic Cache Invalidation

**Pattern**: Source data updated in DB, but cache not invalidated. Consumers read stale cache.

**Example**: Portfolio watchlist updated → Valkey cache not DEL'd → S10 alert service reads stale watchlist.

**Worldview relevance**: S1 (watchlist reverse-index cache), S9 (API gateway response cache), S3 (quote cache 5s TTL).

**Fix**: DEL cache key after DB write (eventual consistency acceptable). Use short TTLs as safety net.

## SA-006: Over-Broad Exception Suppression

**Pattern**: `except Exception: pass` in storage code silently swallows write failures. Caller thinks write succeeded.

**Example**: MinIO put wrapped in broad except → upload failure silently ignored → claim-check pointer points to nothing.

**Worldview relevance**: Any infrastructure adapter that catches exceptions.

**Fix**: Catch specific exceptions. Classify as RetryableError or FatalError. Never suppress without logging.

## Compounding Updates
This document is a living reference. Update it when:
- A new atomicity pattern is discovered
- An existing pattern's fix proves insufficient
- A new storage backend is introduced

Last updated: 2026-03-25
