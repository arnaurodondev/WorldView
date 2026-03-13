# Universal Review Checklist

> **Purpose**: Quick pre-report sanity check. Run this checklist after completing the
> full investigation protocol. Every `FAIL` must become a finding in the final report.
>
> Applied by: `senior_pr_reviewer` on every PR.
> Specialized checklists: [SPARK_PIPELINE_CHECKLIST.md](SPARK_PIPELINE_CHECKLIST.md),
> [STORAGE_IO_CHECKLIST.md](STORAGE_IO_CHECKLIST.md).

---

## Section 1 — Resource Management

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 1.1 | Every resource acquired (file handle, DB connection, temp dir, lock) is released in a `finally` block or context manager | | |
| 1.2 | Cleanup in `finally` blocks cannot raise exceptions that mask the original error (use `ignore_errors=True` or inner try/except) | | |
| 1.3 | Temp directories and staging S3 prefixes are always deleted — on success AND on failure | | |
| 1.4 | No resource leak on partial failure midway through a multi-step operation | | |

---

## Section 2 — Exception Handling

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 2.1 | No broad `except Exception: pass` or `except Exception: log(...)` without re-raise | | |
| 2.2 | Exceptions are re-raised after logging (caller knows the failure occurred) | | |
| 2.3 | Success is not returned (or `None` returned) from a code path that experienced a failure | | |
| 2.4 | `finally` block does not replace the original exception with a cleanup exception | | |
| 2.5 | Fire-and-forget async tasks have error callbacks attached | | |

---

## Section 3 — Storage Atomicity

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 3.1 | Multi-object writes use staging prefix → copy to final → cleanup (not direct write to final) | | |
| 3.2 | Final storage prefix is either complete or empty — never partial | | |
| 3.3 | On failure during copy loop, the partial final prefix is deleted before raising | | |
| 3.4 | DB writes and external writes (S3, Kafka, MLflow) are atomic via outbox pattern or compensating transaction | | |

---

## Section 4 — Idempotency

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 4.1 | Kafka consumer handlers check for duplicate delivery before processing | | |
| 4.2 | Outbox dispatcher uses atomic claim (single UPDATE with WHERE status='PENDING') | | |
| 4.3 | Running the same operation twice produces the same final state (no duplicate rows, no duplicate artifacts) | | |
| 4.4 | Pipeline retries do not produce duplicate Kafka messages or duplicate DB rows | | |

---

## Section 5 — Distributed Execution

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 5.1 | Spark lambdas do not access driver-side resources (filesystem paths, DB sessions, logger instances) | | |
| 5.2 | Spark closures do not capture non-serializable objects | | |
| 5.3 | `collect()` is not called on datasets that can grow unbounded | | |
| 5.4 | No per-element Spark actions inside a Python loop | | |
| 5.5 | Spark join output ordering is not assumed unless `ORDER BY` is explicit | | |

---

## Section 6 — Environment Consistency

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 6.1 | No hardcoded filesystem paths (use config or env var) | | |
| 6.2 | No naive datetimes (all timestamps use `timezone.utc` or `utc_now()`) | | |
| 6.3 | No `os.getcwd()` or relative path assumptions that break in containers | | |
| 6.4 | Credentials and region config come from env vars — not hardcoded | | |
| 6.5 | Code behaves identically on local dev, CI, Docker, and distributed cluster | | |

---

## Section 7 — Edge Cases

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 7.1 | Empty input is handled (not silently ignored or causes IndexError) | | |
| 7.2 | Single-element input is handled correctly | | |
| 7.3 | `None` / `null` values in expected fields are handled (not silently dropped) | | |
| 7.4 | Missing columns raise an explicit error, not a silent default | | |
| 7.5 | Out-of-order timestamps are handled or explicitly rejected | | |

---

## Section 8 — Known Bug Pattern Regression

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 8.1 | BP-001 (OutboxKafkaValue not serialized to bytes) — any new `BaseOutboxDispatcher` subclass uses `OutboxEventValueSerializer` and wires `value_serializer=` explicitly | | |
| 8.2 | All new bug patterns discovered in this PR are added to `docs/ai-interactions/BUG_PATTERNS.md` | | |

---

## Scoring

All sections must be fully PASS or N/A before the PR can be approved.

Any FAIL in Sections 1–4 is a CRITICAL or HIGH finding and **blocks approval**.

Any FAIL in Sections 5–8 is a MEDIUM or HIGH finding and typically **blocks approval**.
