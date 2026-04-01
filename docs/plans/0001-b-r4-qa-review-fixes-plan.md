---
id: PLAN-0001-B-R4
prd: QA Review
title: "S4+S5 QA Review Fixes: DLQ Fidelity, SSRF Hardening, DDL Alignment, Test Gaps, Process Compounding"
status: completed
created: 2026-03-27
updated: 2026-03-27
plans: 1
waves: 4
tasks: 24
supersedes: null
---

# PLAN-0001-B-R4: QA Review Fixes (Round 4)

## Overview

**Triggered by**: Multi-agent QA review of PLAN-0001-B-R2 (5 specialist agents)
**Goal**: Fix all CRITICAL, MAJOR, MINOR, and NIT findings from the R2 QA pass, expand DDL test coverage, harden SSRF defenses with async DNS + httpx transport hooks, fix DLQ requeue fidelity, and update compounding documents to prevent recurrence.
**Total Scope**: 1 plan, 4 waves, 24 tasks

### Findings Being Fixed

| QA ID | Severity | Issue | Wave |
|-------|----------|-------|------|
| F-A | CRITICAL | DLQ `requeue()` uses outbox PK as `aggregate_id` instead of doc UUID | W1 |
| F-B | CRITICAL | `socket.getaddrinfo()` blocking in async event loop, no timeout | W2 |
| F-C | MAJOR | DDL `documents.language` missing `NOT NULL` | W1 |
| F-D | MAJOR | DLQ `requeue()` hardcodes `event_type` | W1 |
| F-E | MAJOR | SSRF missing IPv4-mapped IPv6 (`::ffff:0:0/96`) + CGNAT/multicast | W2 |
| F-402 | MAJOR | `move_to_dead_letter` missing `FOR UPDATE` — race with dispatcher | W1 |
| F-101 | MAJOR | S4 DDL test missing `article_fetch_log` table | W3 |
| F-102 | MAJOR | S5 DDL test covers only 3/7 tables | W3 |
| F-203 | MAJOR | DNS rebinding TOCTOU — implement httpx transport hook | W2 |
| F-303 | MINOR | `payload_avro=b""` semantically wrong — make nullable | W1 |
| F-103 | MINOR | DLQ requeue not-found path untested | W3 |
| F-104 | MINOR | Consumer commit failure path untested | W3 |
| F-105 | MINOR | SSRF IPv6 range tests missing | W2 |
| F-405 | MINOR | LSH index failure — no metric, warning not error | W3 |
| F-306 | MINOR | `minio_silver_key or ""` hides invariant violation | W3 |
| F-305 | MINOR | Python-side vs server-side default mismatch | W1 |
| F-503 | NIT | Avro schema `dedup_result` doc values wrong | W4 |
| F-505 | NIT | `.claude-context.md` describes old LSH behavior | W4 |
| F-107 | NIT | Misleading LSH test in `test_process_article.py` | W3 |
| F-308 | NIT | Migration docstring says "7 tables" but creates 5 | W1 |
| F-506 | NIT | Plan header date inconsistency | W4 |
| — | — | Process improvement: update skills/review checklist | W4 |

### Decisions Made

| ID | Decision | Rationale |
|----|----------|-----------|
| D-1 | Add `aggregate_id` + `event_type` columns to DLQ table | More robust than extracting from payload — decouples DLQ from payload internals |
| D-2 | Move DNS resolution to async route handler with `asyncio.to_thread` | Cleanest approach — keep scheme validation in Pydantic, DNS in async handler |
| D-3 | Implement httpx transport hook for DNS rebinding prevention | Validates resolved IP at connection time, not just validation time |
| D-4 | Use `addr.is_private or addr.is_reserved or addr.is_loopback or addr.is_multicast` | Simpler, future-proof, covers all edge cases including IPv4-mapped IPv6 |
| D-5 | Consumer-level poison pill circuit breaker: **defer** | Requires Valkey counter design + consumer loop integration — separate wave |
| D-6 | MinIO orphan write ordering: **defer** | Accepted trade-off, documented in D-4 of R2 |

---

## Pre-Read (agent must read before any wave)

- `RULES.md` — hard rules (R5, R8, R12, R19)
- `docs/ai-interactions/BUG_PATTERNS.md` — BP-019, BP-020
- `services/content-store/.claude-context.md`
- `services/content-ingestion/.claude-context.md`
- `services/content-store/src/content_store/infrastructure/db/models.py` — ORM models
- `services/content-store/src/content_store/infrastructure/db/repositories/dlq.py` — current requeue logic
- `services/content-store/src/content_store/infrastructure/db/repositories/outbox.py` — current move_to_dead_letter
- `services/content-ingestion/src/content_ingestion/api/schemas.py` — SSRF validation
- `services/content-ingestion/src/content_ingestion/api/routes/internal.py` — ingest submit handler

---

## Wave 1: DLQ Fidelity + DDL Fixes ✅

**Goal**: Fix DLQ requeue data corruption (aggregate_id, event_type), add FOR UPDATE guard, fix DDL nullability, make payload_avro nullable, fix defaults.
**Depends on**: none
**Estimated effort**: 45–60 minutes
**Architecture layer**: infrastructure (schema + repositories)
**Status**: **DONE** — 2026-03-27 · 216 S5 tests pass · ruff + mypy clean

### Tasks

#### T-R4-1-01: Add `aggregate_id` + `event_type` columns to DLQ table (DDL + ORM)

**Type**: schema
**depends_on**: none
**blocks**: [T-R4-1-02, T-R4-1-03]
**Target files**: `services/content-store/alembic/versions/0001_create_content_store_schema.py`, `services/content-store/src/content_store/infrastructure/db/models.py`

**What to build**:
Add two columns to `dead_letter_queue`:
- `aggregate_type TEXT` — stores the original outbox event's `aggregate_type` (e.g., "document")
- `aggregate_id UUID` — stores the original outbox event's `aggregate_id` (the doc UUID)
- `event_type TEXT` — stores the original outbox event's `event_type`

**DDL changes** (add after `original_event_id`):
```sql
aggregate_type  TEXT,
aggregate_id    UUID,
event_type      TEXT,
```
All nullable (backward-compatible — existing DLQ rows won't have these).

**ORM changes** (`DeadLetterQueueModel`):
```python
aggregate_type: Mapped[str | None] = mapped_column(Text, nullable=True)
aggregate_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
event_type: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Also in the same migration DDL:
1. Change `payload_avro BYTEA NOT NULL` → `payload_avro BYTEA` (nullable) — F-303
2. Change `language VARCHAR(10) DEFAULT 'en'` → `language VARCHAR(10) NOT NULL DEFAULT 'en'` — F-C
3. Change migration docstring from "7 tables" to "5 tables" — F-308

**ORM changes** for `payload_avro`: Change `Mapped[bytes]` to `Mapped[bytes | None]` and add `nullable=True`.

**Downstream test impact**:
- `services/content-store/tests/unit/infrastructure/test_ddl_alignment.py` — DDL column checks must be updated for new columns + nullable changes
- `services/content-store/tests/unit/infrastructure/test_dlq_repo.py` — DLQ creation assertions

**Acceptance criteria**:
- [ ] `dead_letter_queue` DDL has `aggregate_type`, `aggregate_id`, `event_type` columns
- [ ] `payload_avro` is nullable in both DDL and ORM
- [ ] `language` has `NOT NULL` in DDL matching ORM
- [ ] Migration docstring says "5 tables"

---

#### T-R4-1-02: Fix `move_to_dead_letter` to store metadata + use FOR UPDATE

**Type**: impl
**depends_on**: [T-R4-1-01]
**blocks**: [T-R4-1-05]
**Target files**: `services/content-store/src/content_store/infrastructure/db/repositories/outbox.py`

**What to build**:
1. Add `.with_for_update()` to the SELECT on outbox.py:91 to prevent race with dispatcher
2. Store `aggregate_type`, `aggregate_id`, `event_type` from the outbox record into the DLQ row
3. Change `payload_avro=b""` to `payload_avro=None`
4. Add status guard on UPDATE: `.where(OutboxEventModel.status.in_(["pending", "processing"]))` to prevent overwriting `delivered`
5. Return boolean indicating whether move succeeded

**Logic**:
```python
async def move_to_dead_letter(self, record_id: UUID, error_detail: str = "") -> bool:
    result = await self._session.execute(
        select(OutboxEventModel).where(OutboxEventModel.id == record_id).with_for_update()
    )
    record = result.scalar_one_or_none()
    if record is None or record.status not in ("pending", "processing"):
        return False
    self._session.add(DeadLetterQueueModel(
        dlq_id=common.ids.new_uuid7(),
        original_event_id=record.id,
        aggregate_type=record.aggregate_type,
        aggregate_id=record.aggregate_id,
        event_type=record.event_type,
        topic=record.topic,
        payload_avro=None,
        payload_json=record.payload,
        error_detail=error_detail,
    ))
    # ... UPDATE with status guard
    return True
```

**Acceptance criteria**:
- [ ] SELECT uses `with_for_update()`
- [ ] DLQ row stores `aggregate_type`, `aggregate_id`, `event_type`
- [ ] `payload_avro` is `None` not `b""`
- [ ] UPDATE has status guard preventing overwrite of `delivered`
- [ ] Returns `bool` indicating success

---

#### T-R4-1-03: Fix DLQ `requeue()` to use stored metadata

**Type**: impl
**depends_on**: [T-R4-1-01]
**blocks**: [T-R4-1-05]
**Target files**: `services/content-store/src/content_store/infrastructure/db/repositories/dlq.py`

**What to build**:
1. Change `aggregate_id=entry.original_event_id` to `aggregate_id=entry.aggregate_id or entry.original_event_id` (fallback for pre-existing rows)
2. Change hardcoded `aggregate_type="document"` to `entry.aggregate_type or "document"`
3. Change hardcoded `event_type="content.article.stored.v1"` to `entry.event_type or entry.payload_json.get("event_type", "content.article.stored.v1")`

**Acceptance criteria**:
- [ ] `aggregate_id` uses stored value (falls back to `original_event_id` for old rows)
- [ ] `event_type` uses stored value (falls back to payload or default)
- [ ] `aggregate_type` uses stored value (falls back to "document")
- [ ] Backward-compatible with DLQ rows created before this change

---

#### T-R4-1-04: Fix `status`/`dedup_result` to use `server_default`

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `services/content-store/src/content_store/infrastructure/db/models.py`

**What to build**:
Change `DocumentModel`:
- `status` from `default="stored"` to `server_default=text("'stored'")` (keep Python `default` too for ORM convenience)
- `dedup_result` from `default="unique"` to `server_default=text("'unique'")` (keep Python `default` too)

This aligns Python-side and server-side defaults so both raw SQL and ORM inserts get the same value from the same source.

**Acceptance criteria**:
- [ ] Both columns have `server_default` matching DDL defaults
- [ ] Python-side `default` retained for ORM convenience

---

#### T-R4-1-05: Update DLQ tests for new columns + metadata fidelity

**Type**: test
**depends_on**: [T-R4-1-02, T-R4-1-03]
**blocks**: none
**Target files**: `services/content-store/tests/unit/infrastructure/test_dlq_repo.py`, `services/content-store/tests/unit/infrastructure/test_ddl_alignment.py`

**What to build**:
1. Update `TestMoveToDeadLetter.test_creates_dlq_row` to verify `aggregate_type`, `aggregate_id`, `event_type` are stored
2. Update `TestDLQRequeue.test_requeue_uses_original_payload` to verify `aggregate_id` is the doc UUID (not outbox PK)
3. Add `test_requeue_returns_none_when_entry_not_found` (F-103)
4. Update DDL alignment test for `dead_letter_queue` to include new columns
5. Verify `move_to_dead_letter` returns `False` when record is already `delivered`

Minimum test count: 4 new/updated tests

**Acceptance criteria**:
- [ ] Tests verify DLQ row stores all 3 new metadata fields
- [ ] Tests verify requeue uses correct aggregate_id (doc UUID)
- [ ] Tests verify not-found path returns None
- [ ] Tests verify FOR UPDATE prevents overwriting delivered records

---

### Validation Gate
- [x] `ruff check` + `mypy` clean
- [x] All existing + new tests pass
- [x] DDL alignment tests pass with new columns

---

## Wave 2: SSRF Hardening ✅

**Goal**: Complete SSRF defense: extend IP blocklist, move DNS to async, implement httpx transport hook for DNS rebinding prevention.
**Depends on**: none (parallel with Wave 1)
**Estimated effort**: 45–60 minutes
**Architecture layer**: API + infrastructure
**Status**: **DONE** — 2026-03-27 · 253 S4 tests pass · ruff + mypy clean

### Tasks

#### T-R4-2-01: Replace manual IP blocklist with Python builtins + IPv4-mapped IPv6

**Type**: impl
**depends_on**: none
**blocks**: [T-R4-2-04]
**Target files**: `services/content-ingestion/src/content_ingestion/api/schemas.py`

**What to build**:
Replace `_PRIVATE_NETWORKS` / `_PRIVATE_NETWORKS_V6` / `_is_private_ip()` with a simpler approach using Python's built-in `ipaddress` properties:

```python
def _is_private_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP is private, reserved, loopback, or multicast."""
    # Handle IPv4-mapped IPv6 (e.g., ::ffff:127.0.0.1) — extract the IPv4 part
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_private or addr.is_reserved or addr.is_loopback or addr.is_multicast or addr.is_link_local
```

Keep the explicit network lists as a constant for documentation/reference, but the actual check uses builtins. This covers IPv4-mapped IPv6, CGNAT (100.64.0.0/10), multicast (224.0.0.0/4), reserved (240.0.0.0/4), broadcast, and all future additions.

**Acceptance criteria**:
- [ ] `::ffff:127.0.0.1` is rejected
- [ ] `::ffff:10.0.0.1` is rejected
- [ ] `100.64.0.0` (CGNAT) is rejected
- [ ] `224.0.0.1` (multicast) is rejected
- [ ] `240.0.0.1` (reserved) is rejected
- [ ] `8.8.8.8` (public) is allowed
- [ ] Existing tests still pass

---

#### T-R4-2-02: Move DNS resolution from Pydantic validator to async route handler

**Type**: impl
**depends_on**: none
**blocks**: [T-R4-2-04]
**Target files**: `services/content-ingestion/src/content_ingestion/api/schemas.py`, `services/content-ingestion/src/content_ingestion/api/routes/internal.py`

**What to build**:
1. In `schemas.py`: Strip `_check_ip_not_private(hostname)` from the `validate_url_scheme_and_host` validator. The validator should only check scheme (http/https) and reject literal private IPs. DNS resolution is removed from the validator entirely.

2. Create a new async helper in `schemas.py`:
```python
async def check_url_ssrf_async(url: str) -> None:
    """Async SSRF check — resolves DNS in thread executor with timeout."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if hostname is None:
        return
    # Literal IP check (fast, sync)
    try:
        addr = ipaddress.ip_address(hostname)
        if _is_private_ip(addr):
            raise ValueError("URL must not target private IP ranges")
        return
    except ValueError as exc:
        if "private IP" in str(exc):
            raise
    # DNS resolution — async with timeout
    try:
        addr_infos = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, hostname, None),
            timeout=5.0,
        )
    except (asyncio.TimeoutError, socket.gaierror) as exc:
        raise ValueError(f"Could not resolve hostname: {hostname}") from exc
    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        addr = ipaddress.ip_address(sockaddr[0])
        if _is_private_ip(addr):
            raise ValueError("URL must not target private IP ranges")
```

3. In `internal.py`: Call `await check_url_ssrf_async(body.url)` after validation but before MinIO write:
```python
if body.url:
    await check_url_ssrf_async(body.url)
```

**Acceptance criteria**:
- [ ] Pydantic validator only checks scheme (http/https) — no DNS call
- [ ] DNS resolution runs in thread executor with 5-second timeout
- [ ] Route handler calls async SSRF check before any I/O
- [ ] Existing tests pass (update mocks as needed)

---

#### T-R4-2-03: Implement httpx transport hook for DNS rebinding prevention

**Type**: impl
**depends_on**: [T-R4-2-01]
**blocks**: [T-R4-2-04]
**Target files**: `services/content-ingestion/src/content_ingestion/infrastructure/http/ssrf_transport.py` (new), `services/content-ingestion/src/content_ingestion/app.py`

**What to build**:
Create an `SSRFSafeTransport` that wraps `httpx.AsyncHTTPTransport` and validates the resolved IP at connection time — closing the DNS rebinding TOCTOU window.

```python
class SSRFSafeTransport(httpx.AsyncBaseTransport):
    """httpx transport that validates resolved IPs before connecting.

    Prevents DNS rebinding: even if DNS returns a public IP at validation
    time and a private IP at connection time, this transport catches it.
    """
    def __init__(self, **kwargs):
        self._inner = httpx.AsyncHTTPTransport(**kwargs)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        hostname = request.url.host
        if hostname:
            addr_infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None)
            for _family, _type, _proto, _canonname, sockaddr in addr_infos:
                addr = ipaddress.ip_address(sockaddr[0])
                if _is_private_ip(addr):
                    raise httpx.ConnectError(f"SSRF blocked: {hostname} resolved to private IP {addr}")
        return await self._inner.handle_async_request(request)
```

Wire it in `app.py` lifespan where `httpx.AsyncClient` is created:
```python
from content_ingestion.infrastructure.http.ssrf_transport import SSRFSafeTransport
http_client = httpx.AsyncClient(transport=SSRFSafeTransport())
```

**Acceptance criteria**:
- [ ] Transport validates resolved IPs at connection time
- [ ] DNS rebinding attack blocked (validation passes, connection blocked)
- [ ] Normal public URLs work correctly
- [ ] Transport properly delegates to inner transport

---

#### T-R4-2-04: Add comprehensive SSRF tests (IPv6, DNS rebinding, timeout)

**Type**: test
**depends_on**: [T-R4-2-01, T-R4-2-02, T-R4-2-03]
**blocks**: none
**Target files**: `services/content-ingestion/tests/unit/api/test_ssrf.py` (extend), `services/content-ingestion/tests/unit/infrastructure/test_ssrf_transport.py` (new)

**What to build**:

**SSRF tests to add/update** (≥8):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_rejects_ipv4_mapped_ipv6 | `::ffff:127.0.0.1` rejected | unit |
| test_rejects_cgnat | `100.64.0.1` rejected | unit |
| test_rejects_multicast | `224.0.0.1` rejected | unit |
| test_rejects_ipv6_loopback_via_dns | DNS resolving to `::1` | unit |
| test_async_dns_timeout | Slow DNS times out in 5s | unit |
| test_scheme_only_in_validator | Pydantic validator only checks scheme, not DNS | unit |
| test_transport_blocks_rebinding | Transport blocks private IP at connect time | unit |
| test_transport_allows_public | Transport allows public IPs | unit |

**Acceptance criteria**:
- [ ] IPv4-mapped IPv6 bypass is tested and rejected
- [ ] DNS timeout behavior is tested
- [ ] Transport hook DNS rebinding test exists
- [ ] All 8+ tests pass

---

### Validation Gate
- [x] `ruff check` + `mypy` clean on S4 files
- [x] All S4 unit tests pass (253)
- [x] SSRF tests cover all bypass vectors

---

## Wave 3: Test Coverage + Code Fixes ✅

**Goal**: Expand DDL alignment tests to all tables, add missing test paths, fix code quality issues.
**Depends on**: Wave 1
**Estimated effort**: 30–45 minutes
**Architecture layer**: tests + minor infrastructure fixes
**Status**: **DONE** — 2026-03-27 · 221 S5 tests + 254 S4 tests pass · ruff + mypy clean

### Tasks

#### T-R4-3-01: Expand S5 DDL alignment tests to all 7 tables

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**: `services/content-store/tests/unit/infrastructure/test_ddl_alignment.py`

**What to build**:
Add test classes for the 4 missing tables:
1. `TestDedupHashesDDLAlignment` — `dedup_hashes` (migration 0002) vs `DedupHashModel`
2. `TestDuplicateClustersDDLAlignment` — `duplicate_clusters` (migration 0002) vs `DuplicateClusterModel`
3. `TestMinHashSignaturesDDLAlignment` — `minhash_signatures` (migration 0001) vs `MinHashSignatureModel`
4. `TestMinHashEntityMentionsDDLAlignment` — `minhash_entity_mentions` (migration 0001) vs `MinHashEntityMentionModel`

Read migration 0002 DDL to extract columns for `dedup_hashes` and `duplicate_clusters`.

Minimum test count: 4 new test classes

**Acceptance criteria**:
- [ ] All 7 S5 tables have DDL-vs-ORM alignment tests
- [ ] Tests would catch any column drift in new tables

---

#### T-R4-3-02: Add S4 `article_fetch_log` DDL alignment test

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**: `services/content-ingestion/tests/unit/infrastructure/test_ddl_alignment.py`

**What to build**:
Add `TestArticleFetchLogDDLAlignment` class comparing migration DDL vs `FetchLogModel` ORM columns.

Minimum test count: 1 new test class

**Acceptance criteria**:
- [ ] `article_fetch_log` has DDL-vs-ORM alignment test
- [ ] All 5 S4 tables now covered

---

#### T-R4-3-03: Add consumer commit failure + DLQ not-found tests

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**: `services/content-store/tests/unit/infrastructure/test_consumer_process.py`, `services/content-store/tests/unit/infrastructure/test_dlq_repo.py`

**What to build**:
1. In `test_consumer_process.py`: Add `test_commit_failure_rolls_back_and_raises` — set `mock_session.commit.side_effect = RuntimeError("DB connection lost")`, verify `rollback` called and exception propagates.
2. In `test_dlq_repo.py`: `test_requeue_returns_none_when_entry_not_found` (if not already added in W1).

Minimum test count: 2

**Acceptance criteria**:
- [ ] Commit failure → rollback + raise is tested
- [ ] DLQ requeue not-found → None is tested

---

#### T-R4-3-04: Add LSH index failure Prometheus counter + fix log level

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `services/content-store/src/content_store/infrastructure/consumer/article_consumer.py`, `services/content-store/src/content_store/infrastructure/metrics/prometheus.py`

**What to build**:
1. Add `s5_lsh_index_failures_total` counter to Prometheus metrics
2. In `article_consumer.py` line 127: change `log.warning("lsh_index_failed", ...)` to `log.error("lsh_index_failed", ...)` and increment the counter
3. This enables alerting on persistent LSH failures

**Acceptance criteria**:
- [ ] Prometheus counter `s5_lsh_index_failures_total` exists
- [ ] LSH failure logged at `error` not `warning`
- [ ] Counter incremented on each failure

---

#### T-R4-3-05: Add `minio_silver_key` invariant guard

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `services/content-store/src/content_store/application/use_cases/process_article.py`

**What to build**:
Replace `doc.minio_silver_key or ""` (line ~287) with an explicit guard:
```python
if doc.minio_silver_key is None:
    msg = "minio_silver_key must be set before building stored payload"
    raise ValueError(msg)
```

This makes the invariant explicit — if `minio_silver_key` is None at this point, it's a bug.

**Acceptance criteria**:
- [ ] `_build_stored_payload` raises if `minio_silver_key` is None
- [ ] Existing tests still pass (they always set silver_key)

---

#### T-R4-3-06: Fix misleading LSH test in `test_process_article.py`

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**: `services/content-store/tests/unit/application/use_cases/test_process_article.py`

**What to build**:
`test_lsh_index_failure_does_not_break_pipeline` sets `lsh_client.index.side_effect = RuntimeError("Valkey down")` but after the CR-3 refactor, `execute()` no longer calls `lsh.index()`. The side_effect is never triggered.

Fix: Remove `lsh_client.index.side_effect` line and rename test to `test_unique_article_returns_signature_for_post_commit_lsh` to reflect what it actually tests.

**Acceptance criteria**:
- [ ] Test name reflects actual behavior
- [ ] No dead mock side_effect

---

### Validation Gate
- [x] `ruff check` + `mypy` clean
- [x] All S4 + S5 unit tests pass
- [x] DDL alignment tests cover all tables in both services

---

## Wave 4: Documentation + Process Compounding ✅

**Goal**: Fix documentation issues, update compounding documents, analyze process failures.
**Depends on**: Wave 1, Wave 2, Wave 3
**Estimated effort**: 20–30 minutes
**Architecture layer**: docs only
**Status**: **DONE** — 2026-03-27 · docs only · no code changes

### Tasks

#### T-R4-4-01: Fix Avro schema `dedup_result` doc attribute

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**: `infra/kafka/schemas/content.article.stored.v1.avsc`

**What to build**:
Change the `dedup_result` field's `doc` from `"unique | corroborating | near_dup | exact_dup"` to `"unique | corroborating | semantic_near_duplicate | same_source_duplicate | duplicate_exact | duplicate_normalized"` matching the actual `DedupOutcome` enum values.

**Acceptance criteria**:
- [ ] Avro doc matches actual enum values

---

#### T-R4-4-02: Fix `.claude-context.md` pipeline description

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**: `services/content-store/.claude-context.md`

**What to build**:
Change line 19 from:
`ProcessArticleUseCase: full pipeline orchestrator (clean → dedup → silver → DB → outbox → LSH)`
to:
`ProcessArticleUseCase: pipeline orchestrator (clean → dedup → silver → DB → outbox); LSH indexed by consumer post-commit (CR-3)`

**Acceptance criteria**:
- [ ] Pipeline description reflects post-CR-3 behavior

---

#### T-R4-4-03: Update BUG_PATTERNS.md with new patterns

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**: `docs/ai-interactions/BUG_PATTERNS.md`

**What to build**:
Add:
- **BP-021**: DLQ requeue must preserve original `aggregate_id` and `event_type` — using outbox PK as aggregate_id causes silent data corruption
- **BP-022**: Blocking `socket.getaddrinfo()` in async context — always use `asyncio.to_thread` with timeout for DNS resolution
- **BP-023**: SSRF must handle IPv4-mapped IPv6 (`::ffff:`) — use Python's `addr.is_private` or explicitly block `::ffff:0:0/96`
- **BP-024**: DNS rebinding TOCTOU — validate resolved IP at connection time, not just validation time

**Acceptance criteria**:
- [ ] All 4 patterns documented with symptom, root cause, correct pattern

---

#### T-R4-4-04: Update REVIEW_CHECKLIST with DLQ + SSRF checks

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**: `.claude/review/checklists/REVIEW_CHECKLIST.md`

**What to build**:
Add to section 6b:
- [ ] DLQ `requeue()` preserves original `aggregate_id`, `aggregate_type`, `event_type` — never hardcode or use outbox PK
- [ ] DNS resolution in async context uses `asyncio.to_thread` with explicit timeout (never blocking `socket.getaddrinfo` on event loop)
- [ ] SSRF IP check uses `addr.is_private` or covers IPv4-mapped IPv6 (`::ffff:`)

**Acceptance criteria**:
- [ ] Checklist has 3 new items

---

#### T-R4-4-05: Process improvement — update skills and agents

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**: `.claude/skills/implement/SKILL.md`, `.claude/skills/qa/SKILL.md`

**What to build**:
**Root cause analysis of what failed**: The R2 implementation correctly fixed the issues it was scoped for, but the QA review found **secondary issues** in the same files that were touched. These stem from:

1. **DLQ requeue was implemented by copying the S4 pattern** but the S4 DLQ doesn't have `aggregate_id`/`event_type` columns either — the pattern itself was incomplete. **Mitigation**: Add a REVIEW_CHECKLIST item: "DLQ requeue preserves original metadata fields."

2. **SSRF validation was added correctly for IPv4 but IPv4-mapped IPv6 is a non-obvious bypass**. The original task didn't specify this vector. **Mitigation**: Add to SSRF section in review checklist: "Use `addr.is_private` builtins instead of manual IP range lists."

3. **Blocking DNS in Pydantic validator is a natural mistake** — Pydantic validators are sync, so the developer used sync DNS. The implement skill doesn't flag sync-in-async patterns. **Mitigation**: Add to HIGH_RISK_PATTERNS: "Blocking I/O in Pydantic validators called from async handlers."

4. **DDL alignment tests only covered the main tables** — the developer tested the tables they changed but didn't expand coverage proactively. **Mitigation**: Add to implement skill: "When adding DDL alignment tests, cover ALL tables in the service, not just the one being changed."

**Updates to `.claude/skills/implement/SKILL.md`**:
- Step 2.4 (Blast Radius): Add "When fixing DDL for one table, add alignment tests for ALL tables in the service"
- Step 4: Add "Verify no blocking I/O in Pydantic validators (DNS, HTTP, DB)"

**Updates to `.claude/review/heuristics/HIGH_RISK_PATTERNS.md`**:
- Add HR-XXX: "Blocking I/O in Pydantic validators" — `socket.getaddrinfo`, `requests.get`, `open()` in `field_validator` or `model_validator`

**Acceptance criteria**:
- [ ] Implement skill updated with DDL alignment and blocking I/O checks
- [ ] HIGH_RISK_PATTERNS has new pattern for blocking I/O in validators
- [ ] Root cause analysis documented

---

#### T-R4-4-06: Fix plan header date + update TRACKING.md

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**: `docs/plans/0001-b-r2-qa-fixes-plan.md`, `docs/plans/TRACKING.md`

**What to build**:
1. Fix R2 plan header: `updated: 2026-03-28` (matches wave completion dates)
2. Update TRACKING.md: Add PLAN-0001-B-R4 to active plans

**Acceptance criteria**:
- [ ] R2 plan date consistent
- [ ] R4 tracked

---

### Validation Gate
- [x] All documentation files updated
- [x] No code changes in this wave (docs only)
- [x] Bug patterns have proper ID, symptom, root cause, prevention sections

---

## Cross-Cutting Concerns

### Contract Changes
| Type | Item | Impact |
|------|------|--------|
| DDL | S5 `dead_letter_queue` + 3 columns | New columns, nullable, backward-compatible |
| DDL | S5 `documents.language` + NOT NULL | Stricter but has DEFAULT — no data loss |
| DDL | S5 `dead_letter_queue.payload_avro` nullable | Relaxed constraint |
| Code | S4 SSRF validation | Stronger — blocks more IP ranges, adds transport hook |
| Code | S5 DLQ requeue fidelity | Preserves original metadata |

### Testing Enforcement
To prevent recurrence: Wave 4 updates implement skill to require ALL-table DDL alignment tests and blocking I/O detection in validators.

---

## Risk Assessment

### Critical Path
Wave 1 (DLQ fidelity) and Wave 2 (SSRF hardening) are independent and can run in parallel. Wave 3 depends on Wave 1 (DDL tests need new columns). Wave 4 depends on all prior waves.

### Highest Risk
T-R4-2-03 (httpx transport hook) — custom transport wrapping is non-trivial. Must handle both HTTP/1.1 and HTTP/2, connection pooling, and error cases.

### Rollback Strategy
Each wave is independent and leaves the codebase green. DLQ column additions are backward-compatible (nullable). SSRF changes only make validation stricter (no false negatives introduced).

---

## Tracking

### Wave Status
| Wave | Status | Tasks Done | Tasks Total |
|------|--------|-----------|-------------|
| W1 | done | 5 | 5 |
| W2 | done | 4 | 4 |
| W3 | done | 6 | 6 |
| W4 | done | 6 | 6 |
