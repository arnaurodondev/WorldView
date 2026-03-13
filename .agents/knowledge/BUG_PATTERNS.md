# Bug Patterns (Knowledge Index)

> **Purpose**: Entry point for the historical bug pattern knowledge base.
>
> The authoritative and fully detailed bug pattern registry is maintained in:
> **`docs/ai-interactions/BUG_PATTERNS.md`**
>
> This file provides a summary index and cross-references for use during PR review.
> When a pattern is flagged below, read the full entry in the source file before
> making a finding.

---

## How to Use During PR Review

1. After completing Steps 1–9 of [PR_INVESTIGATION_PROTOCOL.md](../investigation/PR_INVESTIGATION_PROTOCOL.md),
   scan the index below for categories matching your review scope.
2. Read the full entry in `docs/ai-interactions/BUG_PATTERNS.md` for any match.
3. If reviewed code reproduces the same root cause, cite the pattern ID (e.g., `BP-001`)
   in the finding.
4. If you discover a new bug class not covered here, add an entry to
   `docs/ai-interactions/BUG_PATTERNS.md` using the template at the bottom of that file.

---

## Pattern Index

| ID | Category | Symptom | Affected areas |
|----|----------|---------|---------------|
| [BP-001](../../docs/ai-interactions/BUG_PATTERNS.md#bp-001) | Kafka / outbox serialization | `"a bytes-like object is required, not 'OutboxKafkaValue'"` | Any service implementing `BaseOutboxDispatcher` |

---

## Pattern Categories (for quick triage)

### Serialization

- `BP-001` — OutboxKafkaValue passed directly to AvroSerializer; must extract `.payload` first.
  Also: `value_serializer=` not wired into `build_serializing_producer()` — silently accepts
  any Python object, only fails at delivery time.

### Storage Atomicity

> No BP entries yet. See [STORAGE_ATOMICITY_PATTERNS.md](STORAGE_ATOMICITY_PATTERNS.md) for
> structural patterns.

### Distributed Execution

> No BP entries yet. See [DISTRIBUTED_SYSTEM_PATTERNS.md](DISTRIBUTED_SYSTEM_PATTERNS.md) for
> structural patterns.

### Database / ORM

> No BP entries yet. Likely candidates: naive datetime in TimescaleDB columns, missing
> `onupdate` on `updated_at`, ORM model leaked outside repository adapter.

### Async / Concurrency

> No BP entries yet. Likely candidates: blocking sync I/O inside `async def`,
> `asyncio.run()` called inside an already-running event loop.

---

## Source File

Full entries with root cause analysis, correct implementation patterns, and regression tests:

```
docs/ai-interactions/BUG_PATTERNS.md
```
