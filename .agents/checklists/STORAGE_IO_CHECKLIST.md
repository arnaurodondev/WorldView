# Storage I/O Checklist

> **Purpose**: Storage-specific checks applied on any PR containing file I/O,
> S3/MinIO operations, database writes, or artifact management.
> Supplement to [REVIEW_CHECKLIST.md](REVIEW_CHECKLIST.md).
> Cross-reference: [../knowledge/STORAGE_ATOMICITY_PATTERNS.md](../knowledge/STORAGE_ATOMICITY_PATTERNS.md).

---

## Section 1 — Write Atomicity

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 1.1 | Multi-object writes (S3, filesystem) use a staging path → copy to final → cleanup pattern | | |
| 1.2 | Final destination is either complete or empty at all times — never partially written | | |
| 1.3 | On failure during copy loop, partial objects in the final destination are deleted before raising | | |
| 1.4 | Single-file writes use an atomic rename (temp path → final path) or equivalent | | |
| 1.5 | No direct write to the final path when partial visibility is possible | | |

---

## Section 2 — Cleanup and Resource Release

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 2.1 | Temp directories are cleaned up in a `finally` block (not only on the success path) | | |
| 2.2 | Staging S3 prefixes are cleaned up in a `finally` block | | |
| 2.3 | File handles are closed via context manager (`with open(...)`) — not `.close()` in a separate line | | |
| 2.4 | Database connections and sessions are closed via context manager or explicit teardown | | |
| 2.5 | `shutil.rmtree()` in `finally` blocks uses `ignore_errors=True` to prevent masking | | |

---

## Section 3 — Error Detection and Propagation

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 3.1 | S3/MinIO response status codes are checked — not just the absence of an exception | | |
| 3.2 | Storage errors are re-raised — not logged and suppressed | | |
| 3.3 | `asyncio` write tasks are awaited — not fire-and-forget | | |
| 3.4 | Storage failure does not cause the caller to receive a success result | | |
| 3.5 | Cleanup exceptions in `finally` do not replace the original storage exception | | |

---

## Section 4 — Database Write Safety

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 4.1 | `session.add()` is followed by `session.commit()` within the same transaction scope | | |
| 4.2 | `session.flush()` without `session.commit()` is intentional and documented — data is not assumed to be persisted | | |
| 4.3 | DB writes and external writes (Kafka, S3, MLflow) are handled via the outbox pattern or compensating transaction | | |
| 4.4 | Transactions are rolled back on exception (`async with uow` handles this automatically) | | |
| 4.5 | Bulk inserts use `bulk_insert_mappings` or `insert().values()` — not per-row `session.add()` in a loop | | |

---

## Section 5 — Idempotency

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 5.1 | Re-running the write operation with the same inputs produces the same final state | | |
| 5.2 | `INSERT ... ON CONFLICT DO UPDATE` (upsert) is used where idempotent DB writes are required | | |
| 5.3 | S3 object keys are deterministic — re-upload of the same content overwrites, not appends | | |
| 5.4 | Migration scripts are idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE EXTENSION IF NOT EXISTS`) | | |

---

## Section 6 — Observability

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 6.1 | Storage operations (upload, download, delete) are logged with structlog at INFO level | | |
| 6.2 | Failures are logged with full context (key/path, error type, error message) | | |
| 6.3 | Retry attempts are logged with attempt count and back-off delay | | |
| 6.4 | Bytes written / objects written are logged for large batch operations | | |

---

## Section 7 — Configuration and Security

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 7.1 | Storage endpoints, bucket names, and credentials come from config / env vars — never hardcoded | | |
| 7.2 | No credentials appear in log output | | |
| 7.3 | Object keys do not include user-controlled values without sanitization (path traversal) | | |
| 7.4 | MinIO/S3 bucket names follow the `<service>/<domain>/<resource_id>/` key convention from `AGENTS.md` | | |

---

## Scoring

All sections must be fully PASS or N/A before the PR can be approved.

FAIL in Sections 1–3 is typically a CRITICAL or HIGH finding and **blocks approval**.
FAIL in Sections 4–5 is typically a HIGH finding.
FAIL in Sections 6–7 is typically a MEDIUM or LOW finding.
