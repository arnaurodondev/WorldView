# Common Library

> **Package**: `common` · **Path**: `libs/common/`
> **Purpose**: Lightweight shared utilities — time helpers, ID generation,
> type aliases. Zero or near-zero dependencies.

---

## Design Philosophy

`common` is the **foundation layer**: every service and library may import it, so it
must never introduce its own service-level dependencies. Three rules govern every
addition to this library:

1. **Zero heavy deps** — the only permitted external dependency is `python-ulid`.
   No pydantic, no SQLAlchemy, no httpx.
2. **UTC everywhere** — naive datetimes are silent bugs. Every time-returning
   function here produces timezone-aware UTC. Callers that supply naive datetimes
   get a `ValueError`.
3. **Type safety at zero runtime cost** — `NewType` wrappers for domain IDs mean
   the type-checker will catch `UserId` passed where `TenantId` is expected, at no
   performance cost (they compile to identity functions at runtime).

---

## Public API

### Time Utilities (`common.time`)

| Function | Purpose |
|----------|---------|
| `utc_now()` | `datetime.now(timezone.utc)` — canonical "current time" |
| `ensure_utc(dt)` | Converts / asserts a datetime is UTC; raises `ValueError` if naive |
| `to_iso8601(dt)` | Formats to `YYYY-MM-DDTHH:MM:SS.ffffffZ` |
| `from_iso8601(s)` | Parses ISO-8601 string → UTC datetime |
| `parse_bar_date(s)` | Parses `YYYY-MM-DD` date strings (OHLCV bars) |
| `parse_bar_datetime(s)` | Parses `YYYY-MM-DD HH:MM:SS` date-time strings |

### ID Generation (`common.ids`)

| Function | Purpose |
|----------|---------|
| `new_uuid()` | `uuid.uuid4()` — returns `UUID` object |
| `new_uuid_str()` | `str(uuid.uuid4())` — returns string |
| `new_ulid()` | Time-sortable ULID (useful for event IDs) |

**UUID vs ULID — when to use which:**

| Scenario | Use |
|----------|-----|
| Entity primary keys (DB rows) | `new_uuid()` — UUIDv4, random, index-friendly with uuid-ossp |
| Kafka event IDs (`event_id` envelope field) | `new_ulid()` — lexicographically sortable by creation time, easier to debug |
| Outbox record IDs | Either; prefer `new_uuid()` for DB FK compatibility |

> **AGENTS.md says** UUIDv7 for all entity IDs. `new_ulid()` is the current
> implementation. Both are time-sortable; the practical difference is negligible
> for this project. Use `new_ulid()` for event IDs and `new_uuid()` for DB PKs.

### Type Aliases (`common.types`)

| Alias | Definition | Why `NewType` and not a plain alias |
|-------|------------|-------------------------------------|
| `TenantId` | `NewType("TenantId", UUID)` | Prevents passing `UserId` where `TenantId` expected |
| `UserId` | `NewType("UserId", UUID)` | ↑ |
| `InstrumentId` | `NewType("InstrumentId", UUID)` | ↑ |
| `TransactionId` | `NewType("TransactionId", UUID)` | ↑ |
| `EventId` | `NewType("EventId", str)` | Prevents bare `str` leaking into event ID slots |
| `TopicName` | `NewType("TopicName", str)` | Makes topic names opaque; prevents arbitrary string injection |
| `JsonDict` | `dict[str, Any]` | Plain alias — no domain meaning, just a readability shorthand |

`NewType` creates a **distinct type at the type-checker level but is an identity
function at runtime**. Mypy strict mode will reject `UserId(user_uuid)` passed
where `TenantId` is required, catching a whole class of ID-confusion bugs for free.

---

## Usage

```python
# All public symbols are re-exported from the package root:
from common import utc_now, to_iso8601, new_uuid, TenantId

# Or from sub-modules directly:
from common.time import utc_now, to_iso8601
from common.ids import new_uuid, new_uuid_str, new_ulid
from common.types import TenantId

now = utc_now()
event_time = to_iso8601(now)
tenant = TenantId(new_uuid())
```

---

## Guidelines

1. **No heavy dependencies** — this library must remain < 3 external deps.
   Allowed: `python-ulid`. Not allowed: `pydantic`, `sqlalchemy`, etc.
2. **All datetimes are UTC** — `utc_now()` is the only way to get "now".
   Never call `datetime.now()` without `timezone.utc`. The mypy config enforces
   `--disallow-untyped-defs`; adding `ensure_utc()` calls at service boundaries
   is the safety net for data arriving from external sources.
3. **NewType usage** — type aliases like `TenantId` are `NewType` wrappers;
   they provide type-checker safety at zero runtime cost.
4. **No business logic** — this library must not contain domain rules. If you
   find yourself adding a function that makes decisions, it belongs in a service
   or in `libs/contracts`.

---

## Common Pitfalls

1. **Calling `datetime.now()` directly** — produces a naive datetime silently
   accepted by SQLAlchemy but rejected by `ensure_utc()`. Always use `utc_now()`.
2. **Using `str` instead of typed IDs in function signatures** — defeats the
   purpose of `NewType`. Accept `TenantId`, not `str`, in your use-case constructors.
3. **Comparing ULIDs as strings vs UUIDs as UUIDs** — `new_ulid()` returns a
   `str`; `new_uuid()` returns a `UUID`. Never mix them in the same field without
   explicit conversion.
4. **Adding `pydantic` as a dependency to `common`** — once pydantic is here,
   every service that imports `common` in a minimal environment will drag in
   pydantic. Keep it in service-level `pyproject.toml` only.

---

## Testing Strategy

- **Unit**: Round-trip `to_iso8601(from_iso8601(s)) == s`, `ensure_utc` raises
  on naive datetimes, `parse_bar_date` edge cases, ULID ordering.
