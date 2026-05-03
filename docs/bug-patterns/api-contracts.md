# Bug Patterns — API & Contracts

> **Category**: api-contracts
> **Description**: FastAPI routing, Pydantic schemas, API contract drift, PRD/plan assumption failures, cross-service field name mismatches
> **Count**: 37 patterns
> **Back to index**: [BUG_PATTERNS.md](../BUG_PATTERNS.md)

---

## BP-056: Infrastructure Lib Imported in Domain Layer via Multiple Inheritance

**Severity**: MAJOR — architecture violation (R12)
**Service**: market-data (S3); generalizes to any service

### Pattern

```python
# WRONG — domain/errors.py pulls in messaging lib
from messaging.kafka.consumer.errors import FatalError

class ParseError(MarketDataError, FatalError):  # R12 violation
    ...
```

Using multiple inheritance to "conveniently" combine a domain error with an infrastructure error type pulls the infrastructure library into the domain layer. This breaks hexagonal architecture boundaries and creates a hidden coupling that is hard to detect through normal code review.

### Why it happens

The intent is that Kafka consumer routing treats `ParseError` as `FatalError` so the message is dead-lettered. Multiple inheritance feels like a neat shortcut. But it violates R12: domain layer must have zero infrastructure imports.

### Fix

Keep `ParseError` as a pure domain exception. Consumer infrastructure code maps it:

```python
# CORRECT — infrastructure/messaging/consumers/foo_consumer.py
except ParseError as exc:
    raise FatalError(str(exc)) from exc
```

Or, if the consumer already raises a messaging-layer error directly (e.g. `MalformedDataError`), no mapping is needed at all.

### Regression Guard

Add a unit test that walks the MRO and asserts no `messaging` module appears:

```python
def test_parse_error_is_pure_domain() -> None:
    mro_names = [c.__module__ for c in ParseError.__mro__]
    assert not any("messaging" in m for m in mro_names)
```

---

---

## BP-062

**Category**: Cross-service contract — field name mismatch for stable ID

**Symptom**: Portfolio `InstrumentRef.id` is always a new `uuid7()` for each Kafka replay. `InstrumentRef.entity_id` is always `None`. Stable ID guarantee (M-017) is violated.

**Root cause**: Market-data emits events with `instrument_id` as the stable identifier. Portfolio consumer reads `value.get("entity_id")` for the stable ID. The field was never populated, so M-017 (stable ID via `entity_id`) was silently broken.

**Fix**: The producer must populate `entity_id = instrument_id` in the event payload. Use `event_to_outbox_payload()` which sets `entity_id = instrument_id` before the outbox write.

**Affected areas**: S3→S1 instrument sync; any cross-service event containing a stable entity identifier under a different name than the consumer expects.

---

---

## BP-064

**Category**: FastAPI — status code 204 with non-Response return type

**Symptom**: FastAPI raises a validation error or returns malformed response when using `@router.delete(..., status_code=204)` with a function that returns `None` or a dict in FastAPI ≤0.111.

**Root cause**: FastAPI 0.111 requires a `Response` return type annotation (or `response_class=Response`) to correctly handle status 204 without a body. Returning `None` from an endpoint with `status_code=204` triggers internal validation.

**Fix**: Use `status_code=200` and return a dict, OR explicitly annotate the return type as `Response`:

```python
# Option A (simplest):
@router.delete("/alerts/{alert_id}/ack")
async def ack(alert_id: UUID) -> dict[str, str]:
    ...
    return {"status": "acknowledged"}

# Option B (proper 204 no-content):
from fastapi import Response
@router.delete("/alerts/{alert_id}/ack", status_code=204)
async def ack(alert_id: UUID) -> Response:
    ...
    return Response(status_code=204)
```

**Affected areas**: Any FastAPI ≤0.111 DELETE/POST endpoint that returns 204.

---

## BP-065

**Category**: pre-commit hooks — stash/unstash conflict during commit

**Symptom**: Pre-commit hook succeeds in auto-fixing files but then fails with "Stashed changes conflicted with hook auto-fixes... Rolling back fixes...". The commit never succeeds despite ruff reporting no errors after the fix.

**Root cause**: pre-commit stashes unstaged changes before running hooks. If the hooks modify staged files AND there are untracked directories (e.g., `tests/e2e/`), the stash restore conflicts with the hook's in-place edits.

**Fix**: Run `uvx ruff format` + `uvx ruff check --fix` on all staged files BEFORE `git add` and BEFORE `git commit`. The staged index must be identical to the working tree for the files being committed:

```bash
uvx ruff format services/<service>/
uvx ruff check --fix services/<service>/
git add -u services/<service>/
git commit -m "..."
```

**Affected areas**: Any commit that includes new Python files alongside untracked directories in the repo (e.g., e2e test scaffolds, scratch dirs).

---

---

## BP-066

**Category**: SQLAlchemy ORM — `Mapped[datetime]` unresolvable with `from __future__ import annotations`

**Symptom**: `sqlalchemy.exc.ArgumentError: Could not resolve all types within mapped annotation: "Mapped[datetime]"` when running tests that import ORM models.

**Root cause**: `from __future__ import annotations` makes ALL annotations strings (PEP 563 lazy evaluation). SQLAlchemy 2.x uses `get_type_hints()` at class-definition time to resolve `Mapped[X]` annotations. If `datetime` is imported only under `TYPE_CHECKING`, it is not in the module namespace at runtime and cannot be resolved.

**Fix**: Move `from datetime import datetime` (and any other types used in `Mapped[...]` columns) to a **runtime import** — outside the `TYPE_CHECKING` block:

```python
# WRONG — causes ArgumentError
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from datetime import datetime

# CORRECT — datetime available at runtime for SQLAlchemy
from datetime import datetime
from typing import TYPE_CHECKING, Any
```

**Affected areas**: All SQLAlchemy ORM model files using `Mapped[datetime]`, `Mapped[date]`, `Mapped[Decimal]`, or any other stdlib type that is only imported under `TYPE_CHECKING`.

---

---

## BP-082 — SQLAlchemy ORM enum column: `ValueError` when seed data uses wrong case

**Affected areas**: Tests that insert rows into tables with `Enum`-typed columns via raw SQL or dict-based inserts

**Symptom**

Test fails with:

```
ValueError: 'breakout_signal' is not a valid AlertType
```

when loading ORM rows after seeding the database.

**Root Cause**

SQLAlchemy `Enum` column types backed by Python `StrEnum` (or `enum.Enum`) coerce the stored string back into the enum member on load. If the stored value does not exactly match a member value (including case), the coercion raises `ValueError`. Test seeds using lowercase (`"signal"`) or arbitrary strings (`"breakout_signal"`) that are not valid enum member values cause this error when any code path loads those rows through the ORM.

**Fix**

Always use the exact enum member value (uppercase for `StrEnum` with uppercase values):

```python
# Wrong:
alert_type="signal"
alert_type="breakout_signal"

# Correct:
alert_type="SIGNAL"
alert_type="GRAPH_CHANGE"
```

**Prevention**

- Test seed functions must use enum member values, not arbitrary strings
- When adding a new enum value, search all test seeds for usages of that column and update them
- Consider defining seed constants from the actual enum class: `AlertType.SIGNAL.value`

---

---

## BP-083 — DLQ pagination: `total` field returns page count instead of DB total

**Affected areas**: Any paginated list API endpoint where `total` should reflect the full DB count

**Symptom**

API response returns `total = len(page)` (e.g., `2`) when the actual DB count is larger (e.g., `5`), causing pagination-aware clients or tests to undercount available records.

**Root Cause**

A common mistake when implementing paginated list endpoints:

```python
entries = await repo.list_failed(limit=limit, offset=offset)
return DLQListResponse(entries=entries, total=len(entries))  # ← wrong
```

`len(entries)` is the count of items in the current page, not the total across all pages.

**Fix**

Add a separate `count_failed()` query to the repository and use it for the `total` field:

```python
entries = await use_case.list_failed(limit=limit, offset=offset)
total = await use_case.count_failed()
return DLQListResponse(entries=[...], total=total)
```

Requires adding `count_failed()` to the port ABC, concrete repository, and use case.

**Prevention**

- All paginated endpoints MUST derive `total` from a `COUNT(*)` query, not `len(page)`
- Review checklist: when reviewing any paginated list endpoint, verify `total` comes from a separate count query
- Port ABCs for repositories should include `count_*()` methods alongside `list_*()` methods from the start

---

---

## BP-093 — EODHD API: Assumed fields don't exist (`General.Officers`, `Holders.Institutions`, `Financials.Revenue_Segment`)

**Symptom**: Implementation fetches `payload.get("General", {}).get("Officers", {})` but always gets `{}` even for large-cap companies with many executives. Similarly, `Holders.Institutions` and `Financials.Revenue_Segment` always return empty/absent.

**Root Cause**: These three sections (`General.Officers`, `Holders.Institutions`, `Financials.Revenue_Segment`) **do not exist** in the EODHD Fundamentals API response. They were assumed based on EODHD documentation that describes different response formats from different API tiers/endpoints.

**Affected Areas**: S7 `FundamentalsConsumer`, any code reading EODHD fundamentals payload from MinIO, PRD/plan sections referencing these fields.

**Correct Data Sources**:
| Intended Signal | Correct EODHD Source |
|-----------------|---------------------|
| Company officers / executives | `GET /insider-transactions?code={ticker}.US` — `ownerName` + `ownerTitle` |
| Institutional ownership | `SharesStats.PercentInstitutions` (aggregate %, from fundamentals payload) |
| Insider ownership | `SharesStats.PercentInsiders` (aggregate %, from fundamentals payload) |
| Geographic revenue breakdown | Not available — derive from `headquartered_in` + macro context |

**Fields That DO Exist** in EODHD fundamentals payload:
- `General.FullTimeEmployees` (int)
- `Highlights.RevenueTTM` (int, USD)
- `SharesStats.PercentInsiders` (float)
- `SharesStats.PercentInstitutions` (float)
- `General.Description` (str)
- All of: `Highlights` (MarketCap, EBITDA, PERatio, ROE, ROA), `Valuation` (TrailingPE, ForwardPE, EV/EBITDA)

**Prevention**: Before implementing any EODHD data extraction, verify the field exists in `docs/references/eodhd-endpoints-reference.md` against the Outputs section with actual JSON examples.

---

## BP-096 — FastAPI Route Parameters Must Not Be Under TYPE_CHECKING

**Pattern**: FastAPI route function parameters that appear in type annotations (e.g., `request: Request`) must be importable at runtime. Placing the import inside `if TYPE_CHECKING:` causes `PydanticUndefinedAnnotation` at application startup when FastAPI/Pydantic resolves the route's dependency graph.

**Symptom**:
```
pydantic.errors.PydanticUndefinedAnnotation: name 'Request' is not defined
```

**Cause**: `from __future__ import annotations` makes all annotations strings (lazy), but FastAPI's `get_dependant()` still evaluates them at route registration time via `get_type_hints()`. If `Request` (or any other route-parameter type) is only available under `TYPE_CHECKING`, this lookup fails.

**Fix**: Always import types used in route function signatures at module level (not under `TYPE_CHECKING`):
```python
# WRONG
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from fastapi import Request

@router.get("/readyz")
async def readyz(request: Request) -> Response: ...

# CORRECT
from fastapi import APIRouter, Request  # ← runtime import

@router.get("/readyz")
async def readyz(request: Request) -> Response: ...
```

**Types that CAN be under TYPE_CHECKING**: return type annotations that FastAPI doesn't inspect at registration (only if the return type is a concrete Pydantic model or `dict`), and service-specific types used only in the function body (not the signature).

**Applies to**: All FastAPI services (S1–S10) when using `from __future__ import annotations`.

---

---

## BP-100 — PRD References Non-Existent External API Field

**Category**: Process / PRD quality
**Affected areas**: Any PRD/plan that references EODHD, SnapTrade, Polymarket, DeepInfra, or other external provider fields without verification

**Symptom**: Implementation hits `KeyError`, `AttributeError`, or silent `None` at runtime because the referenced field never existed in the external provider's response. Alternatively, the field name is wrong (e.g., different nesting level, camelCase vs snake_case).

**Root cause**: The PRD author (human or agent) assumed a field exists in an external API response without verifying against actual API documentation or a live response. The assumption propagates into domain entities, DB columns, and consumers before anyone tests against the real API.

**Real examples**:
- PRD-0018 referenced `General.Officers`, `Holders.Institutions`, `Financials.Revenue_Segment` from EODHD — none exist. Replaced with Insider Transactions API endpoint.

**Prevention**:
1. `/prd` Phase 2.7 External API Reality Check — every external field must be marked `Verified: YES` with a source before the PRD is written
2. If field cannot be verified in the session, it MUST be raised as a BLOCKING open question
3. `/revise-prd` Phase 4 explicitly checks this before planning

**Fix pattern**: Remove the non-existent field from the domain entity, DB column, and Avro schema. Identify the correct field or alternative API endpoint and update the PRD.

---

---

## BP-101 — PRD Describes Stale Architecture Baseline

**Category**: Process / PRD quality
**Affected areas**: Any PRD written before an architectural change lands; any plan derived from a PRD >14 days old

**Symptom**: Implementation produces conflicting code — duplicated logic, wrong index types, migration that tries to create an already-existing column, or tests that assert the old behavior.

**Root cause**: The PRD was written based on the architecture state at a point in time. Since then, the codebase evolved (e.g., index type changed, table restructured, new pattern adopted) but the PRD was not updated to reflect the new baseline. The plan inherits the stale assumption and generates tasks that conflict with reality.

**Real examples**:
- PRD-0017 specified IVFFlat indexes for `entity_embedding_state`; the codebase had already migrated to HNSW partial indexes. PRD had to be revised before planning.

**Prevention**:
1. `/revise-prd` Phase 3 Codebase Alignment Check — reads actual source code and diffs PRD claims against current state
2. `/plan` Phase 0.5 PRD Pre-Flight Gate — flags PRDs created >14 days ago for mandatory `/revise-prd` before decomposing waves
3. After any architectural change (index, schema, pattern), run `/revise-prd --all-draft` to check all pending PRDs

**Fix pattern**: Run `/revise-prd` on the affected PRD, resolve each stale assumption with the user, and update the PRD in-place before generating or proceeding with the plan.

---

---

## BP-103 — ValkeyClient Wrapper Type Annotation Drift

**Category**: Type system / libs/messaging
**Affected areas**: Any service that accepts a Valkey/Redis client as a constructor argument

**Symptom**: mypy reports `Argument "valkey" has incompatible type "ValkeyClient"; expected "Redis"` in `app.py` when wiring components. No runtime error (ValkeyClient passes all required methods to the underlying redis.asyncio.Redis).

**Root cause**: New components are sometimes written with `import redis.asyncio as aioredis` + `aioredis.Redis` as the type hint, copying patterns from older code or redis.asyncio documentation. The project's shared `ValkeyClient` (from `libs/messaging`) wraps `redis.asyncio.Redis` but is not a subclass, so mypy rejects the assignment.

**Secondary risk**: Unstaged additions to `ValkeyClient` (e.g. `pipeline()`, `setex()`) look correct locally but the pre-commit hook stashes unstaged files — callers fail with `attr-defined` in the hook run even though the method is visible in the working tree.

**Fix**:
1. All `valkey` parameters must be typed as `ValkeyClient` (not `aioredis.Redis`):
   ```python
   # In TYPE_CHECKING block
   from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
   # In __init__ signature
   def __init__(self, valkey: ValkeyClient, ...) -> None:
   ```
2. If `ValkeyClient` is missing a needed method, add it to `libs/messaging/src/messaging/valkey/client.py` and stage the change in the **same commit** as the callers.
3. Never use `setex(key, ttl, b"1")` — `ValkeyClient.setex` expects `str`, not `bytes`.

**Prevention**: Code review checklist: reject any `aioredis.Redis` or `redis.asyncio.Redis` parameter type annotation in service code.

**First seen**: PLAN-0016 Wave B-1 fix — S1Client, LLMProviderChain, HydeExpander all had `aioredis.Redis` instead of `ValkeyClient`.

---

---

## BP-109 — Non-Atomic `ZADD` + `EXPIRE` in Valkey LSH Index Leaves Immortal Keys

**Category**: Data correctness / Valkey
**Affected areas**: Any code that writes to Redis/Valkey sorted sets and then sets a TTL as two separate commands

**Symptom**: If the process crashes or the Valkey connection drops between `ZADD` and `EXPIRE`, the sorted-set key exists with **no TTL**. These keys grow unbounded and are never evicted, consuming Valkey memory indefinitely.

**Root cause**: `await redis.zadd(key, ...)` followed by `await redis.expire(key, ttl)` is not atomic. Any failure between the two leaves the key without a TTL.

**Fix**: Use a Redis pipeline to batch both commands in a single round-trip:
```python
async with redis.pipeline(transaction=False) as pipe:
    pipe.zadd(key, {member: score})
    pipe.expire(key, ttl)
    await pipe.execute()
```
Note: `transaction=False` (MULTI/EXEC not used) is sufficient here — the key is process-local per band; the atomicity concern is crash-between-commands, not concurrent writers.

**First seen**: QA-S4S5-INFRA-001 (2026-04-07), S5 `lsh_client.py:index()`.

---

---

## BP-119 — Avro Schema Inline Drift

**Date discovered**: 2026-04-07
**Service affected**: S10 Alert (`alert/infrastructure/messaging/email_sent_event.py`)

### Symptom

The serializer uses a hardcoded inline Python dict `_EMAIL_SENT_SCHEMA = {"type": "record", "name": "AlertEmailSentV1", ...}` instead of loading from `infra/kafka/schemas/alert.email.sent.v1.avsc`. When the canonical `.avsc` file is updated (e.g., adding a field), the inline dict is not updated, causing serialization to fail at runtime or produce invalid bytes silently.

### Root cause

The inline dict was written during initial implementation to avoid the `Path` calculation required to resolve the `.avsc` file path. The `.avsc` file and the inline dict are separate sources of truth that will diverge over time.

### Fix

Replace inline dicts with `fastavro.schema.load_schema(<path>)`:

```python
from pathlib import Path
import fastavro.schema

_SCHEMA_PATH = Path(__file__).parents[N] / "infra" / "kafka" / "schemas" / "<schema>.avsc"
_PARSED_SCHEMA: Any = None

def _get_parsed_schema() -> Any:
    global _PARSED_SCHEMA
    if _PARSED_SCHEMA is None:
        _PARSED_SCHEMA = fastavro.schema.load_schema(_SCHEMA_PATH)
    return _PARSED_SCHEMA
```

The `parents[N]` depth depends on the file's location relative to the repo root. Use `load_schema` (not `parse_schema`) — it resolves `$ref` includes automatically.

### Prevention / AVRO-FILE-ONLY Rule

**All Avro schemas MUST be stored in `infra/kafka/schemas/*.avsc`.** No service may define an Avro schema as an inline Python dict. Any serializer/deserializer that currently uses an inline dict must be migrated to `fastavro.schema.load_schema`. Enforce in code review by grepping for `parse_schema({"type": "record"` or `SCHEMA = {"type": "record"` patterns.

**First seen**: PLAN-0016 Wave D-2 QA review (2026-04-07).

---

---

## BP-162 — S9 Composed Endpoints Missing `headers` Kwarg (JWT Never Forwarded)

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-19 |
| **Severity** | CRITICAL |
| **Affected areas** | S9 api-gateway composed endpoints (`clients.py`) |
| **Root cause** | Composed functions (`get_top_movers`, `get_company_overview`, `get_market_heatmap`, `_screener_for_sector`) lacked a `headers` keyword parameter. The `X-Internal-JWT` from `_auth_headers(request)` was extracted correctly by the route handler but had nowhere to go — the composed function's httpx call hardcoded `headers={"Content-Type": "application/json"}` with no JWT. |
| **Symptom** | All composed S9→S3 endpoints return 401 "Missing X-Internal-JWT header" while simple proxy-through routes (e.g. portfolios → S1) work fine. |
| **Why hard to find** | Simple proxy routes worked; only composed endpoints failed. The middleware correctly added the JWT to the request scope. The `except Exception: pass` in InternalJWTIssuerMiddleware was a red herring. |
| **Fix** | Add `*, headers: dict[str, str] | None = None` to all composed functions in `clients.py`; pass `headers=_auth_headers(request)` from proxy routes. |

### Prevention

Every composed endpoint function in `clients.py` MUST accept `*, headers: dict[str, str] | None = None` and forward it to all downstream httpx calls. Unit tests MUST assert `"X-Internal-JWT" in call_kwargs["headers"]` for every downstream call.

---

---

## BP-182 — `CanonicalOHLCVBar.from_dict` Crashes on `volume: null` from EODHD

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (`canonicalize_fatal error="int() argument must be a string, a bytes-like object or a real number, not 'NoneType'"` for AAPL) |
| **Severity** | HIGH — every null-volume bar crashes canonicalize; task is marked FAILED; bronze write succeeds but canonical + downstream are lost |
| **Affected areas** | `libs/contracts/src/contracts/canonical/ohlcv.py:CanonicalOHLCVBar.from_dict`; any provider adapter (EODHD, Yahoo, Polygon) that returns `volume: null` |
| **Root cause** | `CanonicalOHLCVBar.from_dict()` used `int(d["volume"])` unconditionally. EODHD returns `"volume": null` for bars with no recorded trades (e.g. ETFs on foreign exchanges, data gaps, pre-market stubs). `int(None)` raises `TypeError`, which is caught by `ExecuteTaskUseCase._canonicalize()` (BP-113) and re-raised as `ProviderDataError`, failing the task. |
| **Symptom** | `canonicalize_fatal error="int() argument must be a string, a bytes-like object or a real number, not 'NoneType'" provider=eodhd symbol=<TICKER>` in logs. Bronze object written successfully; canonical never written; task moves to FAILED. |
| **Fix** | `libs/contracts/src/contracts/canonical/ohlcv.py` — extract `raw_volume = d.get("volume")` and compute `volume = int(raw_volume) if raw_volume is not None else 0`. The bar is preserved with `volume=0`; downstream consumers should filter zero-volume bars if needed rather than losing the entire bar. |

### Prevention

- Any `int()` or `float()` call on a provider-supplied field must use `int(v) if v is not None else <default>`. Price fields (`open`/`high`/`low`/`close`) default is not obvious (bad data → fail is correct); volume/size fields default to 0.
- When adding new provider fields to a canonical model `from_dict`, explicitly handle `None` for every numeric field.
- The regression test `test_serialize_ohlcv_null_volume_coerces_to_zero` in `test_canonical.py` and `test_null_volume_ohlcv_succeeds_bp182` in `test_execute_task.py` guard this path.
- See also: BP-138 (same `float(None)` pattern in Kafka consumer field extraction).

---

---

## BP-182 — `market_hours_only` DB Flag Never Enforced by Scheduler

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-24 (EODHD API call explosion investigation) |
| **Severity** | CRITICAL (cost) — quote polling fires 24/7 for all 64 symbols instead of market hours only |
| **Affected areas** | `services/market-ingestion/src/market_ingestion/domain/entities/polling_policy.py`, `schedule_tasks.py`, `db/repositories/policy_repository.py`, `db/models/polling_policy.py` |
| **Root cause** | Migration 0003 added `market_hours_only` column to `polling_policies` and set it `true` for all quote policies. Migration 0004 also sets it for new quote policies. However, the `PollingPolicy` domain entity had no `market_hours_only` field, the repository's `_to_domain` did not map it, and `schedule_tasks.py` never checked it. The column existed in the DB but was completely ignored at runtime. |
| **Symptom** | 18,432 quote API calls/day instead of intended ~4,992 (74% waste). No application error — the calls succeed, the excess credits are silently consumed. |
| **Fix** | Added `market_hours_only: bool = False` to `PollingPolicy` domain entity; added `_is_market_hours_now()` helper; `is_due()` checks this flag before the watermark comparison. Wired `market_hours_only` through ORM model, `_to_domain`, `add`, and `save` in the repository. |

### Prevention

- When adding a DB column that controls runtime scheduling behavior, always update the domain entity, repository mapper, AND the use case that reads it. DB-only column additions that aren't propagated to the domain layer are silent no-ops.
- Add a test verifying that `market_hours_only=True` policies return `is_due()=False` outside market hours.

---

---

## BP-182 — Playwright `networkidle` Times Out on Pages with `AlertStreamProvider`

| Field | Value |
|-------|-------|
| **Service** | apps/worldview-web E2E tests |
| **Severity** | MINOR (test infrastructure) |
| **Discovered** | 2026-04-26 PLAN-0039 QA audit |
| **Root cause** | `AlertStreamProvider` calls `getWsToken()` (HTTP fetch to `/api/v1/auth/ws-token`) on every WebSocket reconnect attempt. If the WS connection fails (no S10 in E2E), the `onclose` handler fires → schedules a 1s reconnect → fetches ws-token again → continuous HTTP traffic. `page.waitForLoadState("networkidle")` requires 500ms with no network activity, but the reconnect loop never gives a 500ms window. |
| **Symptom** | E2E test hangs for 30s then fails with `Test timeout of 30000ms exceeded`. Only affects pages that render inside `AlertStreamProvider` (i.e., all `app/(app)/` routes). |
| **Fix** | Two changes required: (1) Replace `networkidle` with `domcontentloaded` + `waitForTimeout(800–1200ms)` in screenshot/state-capture tests. (2) Mock the ws-token endpoint to return **401** (not 200). A 401 triggers `AlertStreamProvider`'s `GatewayError status===401` path which sets `isConnected=false` and exits without scheduling reconnect — breaking the loop. A 200 response causes an immediate WS connection attempt to `ws://localhost:8010` (no S10 running) which fails, restarting the loop. |

### Prevention

All Playwright tests on `app/(app)/` routes must use `domcontentloaded` not `networkidle`. Mock `**/api/v1/auth/ws-token` to return 401 in E2E test setup to prevent the AlertStreamProvider reconnect loop from generating background traffic.

---

---

## BP-183 — Docker build fails: `ERR_PNPM_LOCKFILE_CONFIG_MISMATCH` when root `package.json` has `pnpm.overrides`

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (`make dev-rebuild` fails; worldview-web image fails at `pnpm install --frozen-lockfile`) |
| **Severity** | HIGH — blocks all Docker-based dev and CI builds for the frontend |
| **Affected areas** | `apps/worldview-web/Dockerfile`; triggered any time `pnpm.overrides` is added/changed in the root `package.json` without updating the Dockerfile |
| **Root cause** | pnpm v9 records `overrides` from the workspace root `package.json` (`pnpm.overrides`) into `pnpm-lock.yaml`. If the Dockerfile copies `pnpm-workspace.yaml` and `pnpm-lock.yaml` but **not** the root `package.json`, pnpm inside Docker finds overrides in the lockfile but no corresponding config → `ERR_PNPM_LOCKFILE_CONFIG_MISMATCH`. Introduced by commit `43249e3` (PLAN-0032 CVE remediation) which added `pnpm.overrides` for `vite`/`@eslint/plugin-kit` without updating the Dockerfile. |
| **Symptom** | `ERR_PNPM_LOCKFILE_CONFIG_MISMATCH  Cannot proceed with the frozen installation. The current "overrides" configuration doesn't match the value found in the lockfile` in Docker build output at the `pnpm install --frozen-lockfile` step. |
| **Fix** | `apps/worldview-web/Dockerfile` Stage 1 (`deps`): add root `package.json` to the COPY: `COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./` |

### Prevention

- The root `package.json` is not just a workspace marker — it carries `pnpm.overrides`, `pnpm.onlyBuiltDependencies`, and other workspace-level settings that affect lockfile resolution.
- Whenever `pnpm.overrides` or other `pnpm.*` fields are added/changed in the root `package.json`, verify that all Dockerfiles which run `pnpm install` also `COPY package.json` at the workspace root.
- The Dockerfile comment should document that the root `package.json` is required, not just `pnpm-workspace.yaml`.

---

---

## BP-183 — Budget System Ignores EODHD Per-Endpoint Credit Costs

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-24 (EODHD API call explosion investigation) |
| **Severity** | HIGH (cost) — fundamentals endpoint costs 10 credits each but budget charges 1 token |
| **Affected areas** | `services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py:_apply_budgets` |
| **Root cause** | `_apply_budgets()` calls `budget.try_consume(1.0)` for every task regardless of dataset type. EODHD charges: fundamentals=10 credits, intraday=5 credits, EOD/quotes=1 credit. Additionally, the budget `refill_rate_per_second=10.0` equates to 864,000 tokens/day — effectively unlimited, meaning the budget never actually throttled anything. |
| **Symptom** | Provider budget always had tokens available; the throttle was never invoked. Fundamentals tasks consumed 10x their "fair share" of credits without detection. |
| **Fix** | Added `_EODHD_CREDIT_COST` dict mapping `dataset_type → credit_cost` and `_INTRADAY_TIMEFRAMES` set. `_apply_budgets` now computes `cost` per task and calls `budget.try_consume(cost)`. Migration 0005 lowers `refill_rate_per_second` from 10.0 to 1.157 (matching EODHD's 100,000 credits/day limit). |

### Prevention

- When integrating with a pay-per-call API, always model the budget in terms of the API's credit unit, not request count. Different endpoints have different costs — the budget token cost must reflect this.
- Validate budget calibration: `max_tokens × 24 / refill_rate_per_second` should equal the API's daily limit.

---

---

## BP-183 — JTI Replay Destroys Cross-Service RAG Retrieval

| Field | Value |
|-------|-------|
| **Service** | rag-chat (S8) → nlp-pipeline (S6) / knowledge-graph (S7) |
| **Severity** | CRITICAL (complete silent RAG failure) |
| **Discovered** | 2026-04-26 QA pre-demo investigation |
| **Root cause** | S9 issues one `X-Internal-JWT` per user request (unique JTI). S8 validates the JWT → records `jti:{JTI}` in the shared Valkey instance. S8 then forwards the same JWT to S6/S7 via ContextVar. S6's `InternalJWTMiddleware` runs its own JTI replay check, finds the JTI already in Valkey (recorded by S8), and returns 401. All vector embedding and chunk-search calls fail silently → zero retrieved context → LLM responds entirely from pre-training data. |
| **Symptom** | `jti_replay_detected` in S6/S7 logs on every request. Chat returns plausible-sounding answers with `citations: []`. RAG retrieval metrics show 0 chunks. No error surfaced to the user. |
| **Fix** | Add `jti_replay_check_enabled: bool = False` to internal-only services (S6, S7). JTI replay enforcement belongs only at user-facing service boundaries (S8, S9). Internal services trust that the calling service already validated the JWT. Configurable via env var (`NLP_PIPELINE_JTI_REPLAY_CHECK_ENABLED`, `KNOWLEDGE_GRAPH_JTI_REPLAY_CHECK_ENABLED`). |

### Prevention

Any service that receives `X-Internal-JWT` from another *internal service* (not from S9 directly) must NOT perform JTI replay checking. Only user-facing entry points (S8, S9) should enforce JTI uniqueness. Document the `jti_replay_check_enabled` flag in every service's `.claude-context.md`.

---

---

## BP-184 — Scheduler Creates Tasks for Unregistered Providers

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (investigate skill: S2 ProviderRegistry only registers EODHD; Alpha Vantage/Polygon/Yahoo stubs not wired) |
| **Severity** | HIGH — any `polling_policy` row with a non-EODHD provider causes task creation every tick; tasks burn all retries and move to FAILED; creates permanently-failed task noise in DB |
| **Affected areas** | `services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py`; `services/market-ingestion/src/market_ingestion/infrastructure/workers/worker.py:_build_registry()`; any service whose scheduler creates tasks without validating provider registration |
| **Root cause** | `ScheduleDueTasksUseCase._build_tasks_for_policy()` creates `IngestionTask` rows for any enabled `PollingPolicy` regardless of whether its `provider` has a registered adapter in `ProviderRegistry`. The worker then calls `registry.get(task.provider)`, receives `ProviderUnavailable("No adapter registered for provider …")`, and marks the task RETRY → eventually FAILED. |
| **Symptom** | Flood of `task_retryable_error error="No adapter registered for provider 'alpha_vantage'"` in worker logs. `ingestion_tasks` table accumulates FAILED rows for non-EODHD providers every scheduler tick. |
| **Fix** | In `ScheduleDueTasksUseCase._build_tasks_for_policy()`, check `str(policy.provider) in registered_providers` before creating a task. Pass the list of registered provider values into the use case at construction time (inject from `ProviderRegistry.all_providers()`). Log a WARNING and skip if the provider is not registered. |

### Prevention

- At service startup, assert that all enabled `PollingPolicy.provider` values are present in `ProviderRegistry.all_providers()`. Emit a CRITICAL log if any are missing.
- When adding a new `Provider` enum value, either register a stub that logs a warning or add a migration that prevents enabling policies for that provider until an adapter exists.
- See also: BP-031 (backfill flag flipped before budget check — same theme of scheduler optimistically creating work that cannot be executed).

---

---

## BP-184 — Cold-Start Thundering Herd: All Policies Due Simultaneously

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-24 (EODHD API call explosion investigation) |
| **Severity** | HIGH (cost) — entire cold-start burst of ~1,000 EODHD credits in the first scheduler tick |
| **Affected areas** | `services/market-ingestion/src/market_ingestion/domain/entities/polling_policy.py:is_due` |
| **Root cause** | On a fresh DB (after `alembic upgrade`), all `ingestion_watermarks` have `last_success_at=NULL`. `is_due(None)` returns `True` unconditionally, so all 361 policies trigger in the first scheduler tick simultaneously. |
| **Symptom** | Large API credit burst immediately after platform startup. |
| **Mitigation** | Addressed indirectly: BP-183 fix makes the budget correctly account for fundamentals (10 credits) so the budget cap takes effect on cold start. Migration 0005 raises `max_tokens` to 2,000 which is still finite. True fix would be startup staggering (e.g., add `created_at`-based jitter), tracked separately. |

### Prevention

- For systems with per-call API costs, implement startup jitter: spread the initial load over N minutes by checking `(now - policy.created_at).total_seconds() % policy.base_interval_seconds` instead of treating `last_run_at=NULL` as always due.

---

---

## BP-184 — Morning Brief Route Calls Wrong Use Case Method

| Field | Value |
|-------|-------|
| **Service** | rag-chat (S8) `public_briefings.py` route |
| **Severity** | CRITICAL (endpoint returns wrong content format) |
| **Discovered** | 2026-04-26 QA pre-demo investigation |
| **Root cause** | The `GET /v1/briefings/morning` route called `uc.execute()` — the email deep-briefing use case that generates HTML-formatted portfolio risk digests using `EMAIL_DEEP_BRIEF_PROMPT`. The correct method is `uc.execute_public_morning()`, which invokes `BriefingContextGatherer`, renders `MORNING_BRIEFING` v2.1 with `{current_date}`, and returns structured markdown with 4 required sections. Because `execute()` receives empty context, it also could not gather data from S1/S3/S5/S6/S7. |
| **Symptom** | `GET /v1/briefings/morning` returns 503 (LLM providers fail trying to fill HTML email template) or returns HTML `<h2>` content instead of markdown. Context gathering never runs. |
| **Fix** | Change route to `await uc.execute_public_morning(user_id=..., tenant_id=..., internal_jwt=...)`. Map returned `content` key to `narrative` in `PublicBriefingResponse`. |

### Prevention

When adding a new public method to a use case (e.g., `execute_public_morning`, `execute_public_instrument`), immediately add a route test that asserts the correct method is called on the mock use case, not just that the route returns 200. The test for `uc.execute.called` is insufficient when there are multiple callable methods.


---

---

## BP-189 — Null Volume Coercion in CanonicalOHLCVBar

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-24 (QA finding F-002; extends BP-182) |
| **Severity** | MEDIUM — `volume=0` is semantically different from `volume=None` (no reported volume). Coercing `None` to `0` contaminates average daily volume calculations, abnormal volume signals (PRD-0020 Block 5 price_impact), and backtesting across international ETFs with data gaps. |
| **Affected areas** | `libs/contracts/src/contracts/canonical/ohlcv.py:CanonicalOHLCVBar`; `services/market-data/` storage layer (`PgOHLCVRepository.bulk_upsert_with_priority`); any downstream consumer that distinguishes zero-volume from unreported-volume bars |
| **Root cause** | BP-182 fixed the crash (`int(None)` → `TypeError`) by coercing `None` to `0`. This preserved the bar but permanently lost the null-volume signal. `CanonicalQuote` already used `volume: int | None` — an internal inconsistency. |
| **Symptom** | No crash (BP-182 is fixed). Instead, silent data quality degradation: zero-height volume bars on charts; `PriceImpactLabellingWorker` receives `Decimal(0)` instead of `None` for unreported volume; average volume deflated by false zeros. |
| **Fix** | Changed `CanonicalOHLCVBar.volume` type from `int` to `int | None`. `from_dict()` now returns `None` when the source provides null volume. DB column `ohlcv_bars.volume` remains `NOT NULL server_default="0"` (avoids high-risk hypertable migration). `None → 0` coercion is localized to `PgOHLCVRepository.bulk_upsert_with_priority` at the storage boundary. `OHLCVBarResponse.volume` on the API surface is `int | None`. |

### Prevention

- When a provider field can be absent or null, the canonical model MUST preserve the null signal (use `T | None`). Coercion to a default value should happen at the storage boundary, not in the canonical model.
- Follow the existing `CanonicalQuote.volume: int | None` pattern.
- Document historical data caveats: bars coerced to `volume=0` before this fix are permanently ambiguous — they may represent true zero-volume or unreported volume.
- See also: BP-182 (the original crash fix), BP-138 (same `float(None)` pattern in Kafka consumers).

---

---

## BP-201 — WS JWT sub=oidc_sub Instead of UUID user_id

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-24 (live-stack certification: alert WebSocket 403) |
| **Severity** | HIGH — all WebSocket alert stream connections rejected with 403 |
| **Affected areas** | `services/api-gateway/src/api_gateway/routes/auth.py:ws_token` |
| **Root cause** | `ws_token` used `user.get("sub") or user.get("user_id")`. Valkey user profile caches `sub="dev-user"` (oidc_sub). `OIDCAuthMiddleware` reads the cache and sets `user["sub"] = oidc_sub` (truthy string). `or` short-circuit prevents fallback to `user_id` (UUID). WS JWT issued with `sub:"dev-user"` → alert `UUID("dev-user")` → ValueError → close(4001) → HTTP 403. |
| **Symptom** | All `/v1/alerts/stream` WebSocket connections immediately return HTTP 403 |
| **Fix** | Changed to `user_id = user.get("user_id") or user.get("sub")` — prefer UUID field over oidc_sub. |

### Prevention

- When building user profile dicts, always include a `user_id` field containing the UUID identity. Never use `sub` as the UUID — it may contain an oidc_sub string in dev mode or external OIDC providers.
- Prefer `user.get("user_id")` over `user.get("sub")` for UUID-dependent operations (DB lookups, WebSocket user IDs, etc.).

---

---

## BP-226 — `str(None)` Produces Colliding Alias Text `"None"`

| Field | Value |
|-------|-------|
| **Service** | knowledge-graph (S7) |
| **Severity** | MAJOR |
| **Discovered** | 2026-04-26 live-infra QA |
| **Root cause** | `canonical_name = str(value.get("name", "Unknown"))` — if `name` is `null` in the Avro payload, `value.get("name")` returns Python `None`, and `str(None)` produces the string `"None"`. Multiple instruments with null names all attempt to insert `normalized_alias_text='none'` → `uidx_entity_aliases_normalized` unique constraint violation. |
| **Symptom** | `UniqueViolationError: duplicate key value violates unique constraint "uidx_entity_aliases_normalized" Key (normalized_alias_text)=(none) already exists`. |
| **Fix** | Guard against None/empty/literal-None values before alias generation: use ticker as fallback, then a UUID-based synthetic name. `if raw_name and str(raw_name).strip().lower() not in ("none", "null"): canonical_name = ...` |

### Prevention

Whenever converting an optional payload field to a string for use as a unique key or alias, always check for `None`, empty string, and the literal strings `"None"` / `"null"` / `"NULL"` before proceeding.


---

---

## BP-232 — Content-Ingestion Article Titles Null in Documents Table

| Field | Value |
|-------|-------|
| **Service** | content-ingestion (S4) → content-store (S5) pipeline |
| **Severity** | HIGH (RAG citations missing, morning brief shows no news) |
| **Discovered** | 2026-04-26 QA pre-demo investigation |
| **Root cause** | S4 fetch adapters (Finnhub, NewsAPI) populate `ArticleFetchResult.title` and `ArticleFetchResult.url`. These fields are written to `article_fetch_log.title` in S4's DB. However, S4's bronze S3 envelope stores only `raw_content` (the article body). When S5 processes the bronze object, it reconstructs the document from the bronze envelope — which contains no `title` or `source_url` fields. The `documents` table receives `title=null, source_url=null` for all articles. S6's display relevance scorer cannot build meaningful citation titles. S8 RAG output shows `title: null` citations. |
| **Symptom** | All rows in `content_store.documents`: `title=null, source_url=null`. S6 `document_source_metadata`: `title=null, url=null`. RAG citations appear as `null` titles. Morning brief news section empty (display_relevance_score ≈ 0.20 below 0.3 threshold). |
| **Fix** | S4 bronze envelope must include `title`, `url`, `author`, `published_at` alongside `raw_content`. S5 `ProcessArticleUseCase` must extract these fields from the envelope and populate `Document.title` and `Document.source_url`. Alternatively, use S4→S5 Kafka event (`content.article.stored.v1`) metadata fields to carry the title. |

### Prevention

When adding a new field to `ArticleFetchResult`, verify that the field is: (1) serialised into the S3 bronze envelope by S4, (2) deserialised and written to `documents.title` by S5, (3) tested in S4→S5 integration tests with a non-null assertion. Never assume "stored in `article_fetch_log`" means "available to downstream services".

---

---

## BP-236 — Valkey 24h Briefing Cache Masks Article Score Updates

| Field | Value |
|-------|-------|
| **Service** | rag-chat (S8) — `public_briefings.py` |
| **Severity** | LOW (demo/debugging issue, correct production behavior) |
| **Discovered** | 2026-04-26 demo readiness QA |
| **Root cause** | The morning briefing route caches responses in Valkey for 24h (key: `briefing:morning:{user_id}`). After updating article `llm_relevance_score` in the DB to populate the brief, the cached response (generated before the score update) is returned, still showing "Not available in retrieved context". The 0-second response time is the key indicator of a cache hit. |
| **Symptom** | Morning briefing returns stale "Not available" content despite 42 articles now scored above threshold. Response time is ~0ms. |
| **Fix** | `redis-cli DEL "briefing:morning:{user_id}"` to invalidate the cache key. Pattern: all Valkey briefing keys follow `briefing:{type}:{entity_id?}:{user_id}`. |

### Prevention

Document that updating article scores or context sources requires Valkey cache invalidation before the next request. For development/debugging: `redis-cli --scan --pattern "briefing:*" | xargs redis-cli DEL`.

---

---

## BP-236 — entity_embedding_state.ensure_rows_exist() Inserts NULL next_refresh_at — Rows Never Scheduled

| Field | Value |
|-------|-------|
| **Service** | knowledge-graph (S7) — `entity_embedding_state.py:ensure_rows_exist()` |
| **Severity** | HIGH (all entities with no prior embeddings silently never get embedded) |
| **Discovered** | 2026-04-27 KG pipeline investigation |
| **Root cause** | `ensure_rows_exist()` provisions placeholder rows with `next_refresh_at = NULL`. The periodic refresh workers (`DefinitionRefreshWorker`, `NarrativeRefreshWorker`, `FundamentalsRefreshWorker`) all query `WHERE next_refresh_at IS NOT NULL AND next_refresh_at < now()`. Rows with `NULL` next_refresh_at are NEVER returned by this query. The result: every entity gets its embedding row provisioned, but those rows are immediately dead-scheduled and never processed. Embeddings remain NULL forever. |
| **Symptom** | `entity_embedding_state` table has rows for every entity but `embedding IS NULL` on all of them. `DefinitionRefreshWorker` logs `refreshed=0` on every cycle despite rows existing. ANN search returns no results. |
| **Fix** | Change `ensure_rows_exist()` SQL to include `next_refresh_at = now()` in the INSERT: `INSERT INTO entity_embedding_state (entity_id, view_type, last_refreshed_at, next_refresh_at, refresh_count) VALUES (:entity_id, :view_type, now(), now(), 0) ON CONFLICT (entity_id, view_type) DO NOTHING`. |

### Prevention

Any table that uses a `next_refresh_at IS NOT NULL AND next_refresh_at < now()` query pattern for batch scheduling MUST have all rows provisioned with a concrete `next_refresh_at` (even `now()`). A `NULL` `next_refresh_at` is a **scheduling black hole** — the row can never be selected for processing. When adding new provisioning code, always verify: "Will the refresh query pick up these rows?"

---

---

## BP-239 — S3 Fundamentals Router Missing Section Endpoints Despite Enum + Use Case Support

| Field | Value |
|-------|-------|
| **Service** | market-data (S3) — `api/routers/fundamentals.py` |
| **Severity** | MEDIUM (data exists in DB, reachable via all-sections endpoint, but section-specific paths return 404) |
| **Discovered** | 2026-04-27 PLAN-0041 Wave A-1 investigation |
| **Root cause** | `FundamentalsSection` enum had 18 values; `GetFundamentalsSectionUseCase.execute()` supports all of them generically; DB had tables and data. But the FastAPI router only had handlers for 13 of 18 sections. Five sections (`TECHNICALS_SNAPSHOT`, `SHARE_STATISTICS`, `SPLITS_DIVIDENDS`, `EARNINGS_TREND`, `EARNINGS_ANNUAL_TREND`) were missing router handlers. S9 investigation revealed these gaps when trying to proxy section-specific paths. |
| **Symptom** | `GET /api/v1/fundamentals/{id}/technicals-snapshot` → 404. Data exists in `technicals_snapshots` table. No error in logs — FastAPI simply finds no matching route. |
| **Fix** | Add the missing 5 router handlers. Each follows the same 3-line pattern: call `uc.execute(instrument_id, FundamentalsSection.X)`, wrap in `FundamentalsResponse`. The use case and DB repository already support all sections. |

### Prevention

When adding a new `FundamentalsSection` enum value:
1. Immediately add the corresponding router handler — do not defer it. The router is the only layer that needs updating; enum + use case are generic.
2. Add a test in `test_fundamentals_api.py` that calls the new endpoint path and asserts `section == "new_value"` in the response.
3. Verify with `GET /api/v1/fundamentals/screen/fields` that the new section's metrics appear in the screener metadata.
4. Update `docs/services/api-gateway.md` to document the S9 proxy for the new section (if applicable).

---

---

## BP-243 — Alpaca Crypto Symbols Sent to Stock Endpoint (HTTP 400)

| Field | Value |
|-------|-------|
| **Service** | market-ingestion (S2) — `infrastructure/adapters/providers/alpaca.py` |
| **Severity** | HIGH (all crypto OHLCV tasks permanently fail) |
| **Discovered** | 2026-04-27 ingestion pipeline investigation |
| **Root cause** | `AlpacaProviderAdapter.fetch_ohlcv()` always used `/v2/stocks/bars` regardless of symbol type. Alpaca rejects crypto symbols (e.g. `BTC-USD`) with HTTP 400 `{"message":"invalid symbol"}` on the stock endpoint. Crypto requires a separate endpoint: `/v1beta3/crypto/us/bars`, and Alpaca expects slash format (`BTC/USD`) not dash (`BTC-USD`). |
| **Symptom** | All `-USD` crypto symbols fail permanently with `Alpaca client error HTTP 400`. Since `ProviderDataError` (HTTP 4xx) is non-retryable, tasks move directly to `FAILED` status. |
| **Fix** | Added `_is_crypto_symbol()` and `_to_alpaca_crypto_symbol()` helpers. `fetch_ohlcv()` and `fetch_ohlcv_batch()` now branch on symbol type: crypto → `/v1beta3/crypto/us/bars` without `feed` param; equity → `/v2/stocks/bars` with `feed=iex`. |

### Prevention

- Provider adapters that support multiple asset classes MUST detect symbol type and route to the correct endpoint.
- Add crypto symbols to the Alpaca adapter test fixture so this is caught by unit tests.
- When adding a new provider, verify all symbol formats it supports and add type-routing from day one.

---

---

## BP-243 — Decimal Fraction vs. Percentage Mismatch in S3→Frontend Data Pipeline

| Field | Value |
|-------|-------|
| **Services** | api-gateway (S9) — `clients.py` + `worldview-web` — `lib/gateway.ts` |
| **Severity** | MEDIUM (incorrect data display — SectorHeatmap shows 0.00% instead of 0.16%; TopMovers shows 0.03% instead of 3.11%) |
| **Discovered** | 2026-04-27 dashboard investigation |
| **Root cause** | S3 (market-data) stores all rate metrics (`daily_return`, etc.) as decimal fractions where 1.0 = 100%. S9's `get_market_heatmap()` in `clients.py` passed `avg_change` through directly as `change_pct` without multiplying by 100. Similarly, `gateway.ts` passed `r.metrics.daily_return` directly as `change_pct` in the top-movers transform. Both frontend widgets (`SectorHeatmapWidget`, `PreMarketMoversWidget`) call `.toFixed(2)%` treating the value as a percentage — showing 0.00% instead of 0.16%. |
| **Symptom** | Sector heatmap shows all sectors at ≈0.00% change. Top movers shows AAPL at +0.03% instead of +3.11%. The data widgets appear broken/empty even though the API calls succeed. |
| **Fix** | 1. `clients.py get_market_heatmap()`: `round(avg_change * 100, 2)` (was `round(avg_change, 4)`). 2. `gateway.ts getTopMovers()` transform: `(r.metrics?.daily_return ?? 0) * 100` (was `r.metrics?.daily_return ?? 0`). |

### Prevention

- **Contract rule**: When S3 returns a metric ending in `_return` or `_pct` that represents a rate, verify the unit (decimal fraction vs. percentage) before passing to the frontend. S3 uses decimal fractions throughout (0.031 = 3.1%).
- **Frontend convention**: All `change_pct` fields in frontend types (`Mover.change_pct`, `HeatmapSector.change_pct`) represent percentage values (3.11 for 3.11%). Any gateway transform from S3 metrics must multiply by 100.
- **Test convention**: Mock data for `daily_return` in tests should use decimal fractions (0.0523 for 5.23%), not percentage values (5.23). Assertions on `change_pct` use percentage values.

---

## BP-255 — SnapTrade v4 Callback Returns `connection_id`; Frontend/Backend Expect `authorizationId`

**Date discovered**: 2026-04-28
**Affected areas**: Portfolio brokerage connection OAuth callback flow

**Pattern**:
SnapTrade Connection Portal v4 changed the callback URL parameters:
- v3: `?authorizationId=xxx&userId=yyy&sessionId=zzz`
- v4: `?connection_id=xxx&status=SUCCESS` (no `userId`, no `sessionId`, no `authorizationId`)

Code that requires all three v3 params (validation guards, database checks, URL builders) fails silently or shows error UI for any v4 callback.

**Root cause**:
Multiple layers were hardcoded for v3 params:
1. Frontend callback page guard: `if (!connectionId || !authorizationId || !userId || !sessionId)` — fails for v4 (userId/sessionId are empty)
2. Backend route: `authorizationId: str = Query(...)` and `userId: str = Query(...)` — marked required, returned 422 for v4 params
3. Anti-spoofing check: `if cmd.snaptrade_user_id != connection.snaptrade_user_id: raise` — no null/empty guard, always raised for v4
4. Redirect URI config: `localhost:5173` (old Vite dev port) vs actual frontend port `3001`

**Fix**:
1. Backend route: all callback params optional (`str | None = Query(default=None)`). Accept `connection_id` (v4) as alias for `authorizationId` (v3) via `alias="connection_id"`.
2. Use case: anti-spoofing check only when `snaptrade_user_id` is non-empty: `if cmd.snaptrade_user_id and cmd.snaptrade_user_id != connection.snaptrade_user_id`.
3. Frontend callback page: only check `connectionId` and `authorizationId` (not userId/sessionId) in validation guard.
4. Frontend callback page: read `connection_id` as fallback for `authorizationId` in `searchParams`.
5. `docker.env` and `dev.local.env`: fix `SNAPTRADE_REDIRECT_URI` port from 5173 to 3001.

**Prevention**:
- Test brokerage callback flows against both v3 and v4 SnapTrade portal versions.
- Callback validation guards should only require fields that are guaranteed in ALL versions of the external redirect.
- When an external API changes redirect params, check all layers: frontend guard, frontend param reading, gateway.ts call, backend route params, use case logic.

---

---

## BP-266 — S3 Prediction Market List Returns `volume_24h=None` (Volume Never Displayed)

**Category**: Data pipeline / API design
**Severity**: MAJOR
**Affected areas**: Prediction markets widget, S3 market-data service
**First seen**: 2026-04-28 (PLAN-0045 QA follow-up)

**Symptoms**:
- `PredictionMarketsWidget` always shows "$0 vol" for all prediction markets
- `GET /api/v1/prediction-markets` returns `volume_24h: null` for every market
- The history endpoint (`/history`) returns correct volume per snapshot

**Root Cause**:
Volume is stored in `prediction_market_snapshots` (hypertable), not on the `prediction_markets` entity. The list and detail endpoints were written to query the markets table only. The comment explicitly says `volume_24h=None, # stored in snapshot, not on market entity` but no follow-up JOIN was implemented.

Gateway maps `null → 0`: `volume_usd: m.volume_24h ?? 0`. Frontend then formats `0 → "$0 vol"`.

**Fix Applied (partial)**:
Frontend null-guard in `PredictionMarketsWidget.tsx`: only render the volume span when `volume_usd > 0`. This prevents "$0 vol" but doesn't provide real data.

**Full Fix** (PLAN-0048 Wave D-1, 2026-04-28):
S3 `PgPredictionMarketRepository.list_markets` adds `LEFT JOIN LATERAL (SELECT volume_24h FROM prediction_market_snapshots WHERE market_id = m.market_id ORDER BY snapshot_at DESC LIMIT 1) latest ON TRUE`. The repo signature now returns `tuple[list[tuple[PredictionMarket, Decimal | None]], int]`; the use case forwards volume into `(market, prices, volume_24h)` triples; the router projects `float(volume) if volume is not None else None`. The detail endpoint also surfaces volume from the latest snapshot it already fetches for prices (no extra query). Forward-compatible: callers tolerating `volume_24h = null` continue to work.

**Prevention**:
- When an API field is intentionally left null with a `# stored elsewhere` comment, always add a TODO or a follow-up task to JOIN it from the correct table
- Frontend volume/quantity fields that display currency amounts must guard `> 0` (not just `!= null`) to prevent "$0" display

---

## BP-274 — Multi-Process Service: Scheduler State Not in API `app.state`

**Category**: Architecture / multi-process (R22)
**Severity**: MAJOR (runtime AttributeError at startup)
**Affected areas**: Any service with independent scheduler/worker processes (S3 market-ingestion, S4 content-ingestion, S6 nlp-pipeline)
**First seen**: 2026-04-29 (PLAN-0055 / revise-prd audit)

**Symptoms**:
- `AttributeError: 'State' object has no attribute 'routing_cache'` at service startup
- A startup hook placed in the API lifespan (`app.py`) tries to access scheduler-owned state

**Root Cause**:
R22 mandates independent processes for schedulers and workers. In S3, the API process (`app.py`) stores only `write_session_factory`, `read_session_factory`, `metrics`, `settings`, and `_jwt_middleware` in `app.state`. The `ProviderRoutingCache` and UoW factory live in `SchedulerProcess.__init__` and are never exposed to the API process. A plan that assumes `app.state.routing_cache` exists will always fail.

**Fix**:
Orchestration logic that needs the routing cache or UoW factory belongs in the **scheduler process** (`scheduler_main.py` / `scheduler.py`), not the API lifespan. Add startup hooks to `SchedulerProcess.run()`, which already has `_write_factory` and `_read_factory`. Construct `ProviderRoutingCache` from `settings` locally.

**Prevention**:
- Before adding any startup hook to a service, read the service's `app.py` (or `main.py`) lifespan and list every attribute stored on `app.state`. Only reference attributes that actually exist.
- In multi-process services (R22), never assume the API process has the same wired dependencies as the scheduler or worker processes.

---

## BP-342: KG entity_id passed to market-data API that expects market-data instrument_id → 404 on all fundamentals fetches

**Date discovered**: 2026-05-03
**Service affected**: `knowledge-graph` (`FundamentalsRefreshWorker`)

**Category**: API & Contracts
**Severity**: HIGH (all fundamentals fetches return 404, worker produces no output)

### Symptom

- `fundamentals_refresh_market_data_unavailable` for all ticker entities
- Debug reveals `GET /api/v1/fundamentals/{entity_id}` returns 404: "No fundamentals found for instrument: {entity_id}"
- Auth is valid (200 returned when using the correct instrument_id)

### Root Cause

The KG service (`intelligence_db`) uses UUIDs in the format `11111111-0001-7000-8000-000000000001` for its `canonical_entities.entity_id`. The market-data service (`market_data_db`) has its own UUID namespace for `instruments.id` (e.g., `01900000-0000-7000-8000-000000001001`). These are different ID spaces — KG entity_id ≠ market-data instrument_id.

The `FundamentalsRefreshWorker` was passing `entity_id` as the path parameter to market-data, which caused 404 for every entity.

### Fix

Add a `_resolve_instrument_id` method that calls `GET /api/v1/instruments/symbol/{ticker}` to look up the market-data instrument_id before calling fundamentals endpoints:

```python
async def _resolve_instrument_id(self, http: httpx.AsyncClient, ticker: str) -> UUID | None:
    data = await self._fetch_json(http, f"{self._market_data_url}/api/v1/instruments/symbol/{ticker}")
    if data is None:
        return None
    try:
        return UUID(str(data["id"]))
    except (KeyError, ValueError):
        return None
```

Then use `instrument_id` (not `entity_id`) for all market-data API calls.

### Prevention

- When a worker calls a different service's REST API using an ID from its own DB, NEVER assume the IDs are the same. Always check both services' ID schemas.
- In KG workers: `entity_id` is the KG canonical entity UUID; market-data `instrument_id` is the market-data service's own UUID. They differ and must be resolved by ticker/symbol.
- Test pattern: route mock GET calls by URL substring so that `/instruments/symbol/` and `/fundamentals/` return different fixtures.

**Regression test**: `tests/unit/infrastructure/workers/test_fundamentals_refresh_worker.py::TestFundamentalsRefreshWorkerS3Failure::test_successful_fetch_calls_upsert`

---
