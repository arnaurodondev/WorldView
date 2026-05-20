# Common Library

> **Package**: `common` · **Path**: `libs/common/` · **Version**: 2025.6.0
> **Purpose**: Lightweight shared utilities — time helpers, ID generation, and
> type aliases. Zero or near-zero dependencies. Every service and library may
> import it freely.

---

## Purpose

`common` is the **foundation layer**: because every other service and library
can depend on it, it must never itself introduce heavyweight dependencies (no
pydantic, no SQLAlchemy, no httpx). It solves three concrete problems:

1. **Safe timestamps** — naive `datetime` objects are silent bugs (wrong timezone
   assumptions silently corrupt time-series data). Every time-returning function
   here enforces UTC-aware datetimes.
2. **Correct ID generation** — different ID types are appropriate in different
   contexts (UUIDv7 for new entity PKs, ULID for Kafka event IDs, UUIDv4 for
   legacy services). `common.ids` provides the right function for each case and
   wraps third-party ID libraries so services never import them directly.
3. **Type-safe domain IDs** — `NewType` wrappers for `TenantId`, `EntityId`, etc.
   mean mypy will catch cases where an `EntityId` is passed where a `TenantId` is
   expected. Zero runtime overhead — they compile to identity functions.

---

## Installation

```toml
# In a service's pyproject.toml:
[project]
dependencies = ["common"]

# For development:
[project.optional-dependencies]
dev = ["common[dev]"]
```

```bash
# Editable install for local development:
pip install -e "libs/common[dev]"
```

Dependencies: `python-ulid>=3.0,<4`, `uuid6>=2024.1,<2025`. Python 3.11–3.12.

---

## Public API

### Time Utilities (`common.time`)

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `utc_now` | `() -> datetime` | `datetime` (UTC, aware) | Canonical "current time". Equivalent to `datetime.now(UTC)`. |
| `ensure_utc` | `(dt: datetime) -> datetime` | `datetime` (UTC, aware) | Converts / asserts a datetime is UTC. Raises `ValueError` if naive. |
| `to_iso8601` | `(dt: datetime) -> str` | `str` | Formats to `YYYY-MM-DDTHH:MM:SS.ffffffZ`. Calls `ensure_utc` first. |
| `from_iso8601` | `(s: str) -> datetime` | `datetime` (UTC, aware) | Parses ISO-8601 string (both `Z` and `+00:00` suffixes accepted). |
| `parse_bar_date` | `(s: str) -> datetime` | `datetime` (UTC midnight) | Parses `YYYY-MM-DD` date strings to UTC midnight. Used for OHLCV bars. |
| `parse_bar_datetime` | `(s: str) -> datetime` | `datetime` (UTC) | Parses `YYYY-MM-DD HH:MM:SS` strings to UTC datetime. |

### ID Generation (`common.ids`)

| Function | Signature | Returns | When to use |
|----------|-----------|---------|------------|
| `new_uuid7` | `() -> UUID` | `UUID` (UUIDv7) | New entity PKs in ingestion pipeline (S4–S10). Time-sortable; PRD-mandated. |
| `new_uuid7_str` | `() -> str` | `str` | Same as `new_uuid7()` but as a hyphenated string (for Avro payloads, JSON). |
| `new_ulid` | `() -> str` | `str` | Kafka event IDs. Lexicographically sortable by design. |
| `new_uuid` | `() -> UUID` | `UUID` (UUIDv4) | Backwards-compatible ID for portfolio and market-ingestion services that already have UUIDv4 rows in production. |
| `new_uuid_str` | `() -> str` | `str` | Same as `new_uuid()` but as a string. |
| `uuid5_from_parts` | `(*parts: str) -> str` | `str` (UUID5, hyphenated) | Deterministic UUID from ordered string parts. Used for idempotent Kafka replay — same inputs always produce the same UUID, so `ON CONFLICT DO NOTHING` prevents duplicate rows. Uses the RFC 4122 DNS namespace UUID as the stable worldview namespace. |

**ID selection flowchart:**

```
Need a new ID?
├── Kafka event ID?             → new_ulid()
├── New entity in S4–S10?       → new_uuid7()
├── Portfolio / market-ingestion (existing UUIDv4 rows)?  → new_uuid()
└── Deterministic / idempotent key?  → uuid5_from_parts(*parts)
```

### Type Aliases (`common.types`)

All domain IDs are `NewType` wrappers — they are identity functions at runtime but
distinct types to mypy. Passing a `UserId` where a `TenantId` is expected is a
compile-time error, not a runtime one.

| Alias | Underlying type | Cross-service usage |
|-------|-----------------|---------------------|
| `TenantId` | `UUID` | Auth boundary — S1, S9 |
| `UserId` | `UUID` | Auth boundary — S1, S9 |
| `InstrumentId` | `UUID` | Market-data instrument PK — S2, S3, S9 |
| `TransactionId` | `UUID` | Portfolio transaction PK — S1 |
| `EventId` | `str` | Kafka event envelope ID — all services |
| `TopicName` | `str` | Prevents raw strings in topic routing — messaging lib |
| `DocumentId` | `UUID` | Content pipeline doc ID — S4, S5, S6, S7 |
| `EntityId` | `UUID` | Knowledge graph entity ID — S6, S7, S10 |
| `UrlHash` | `str` | SHA-256 hex of a normalised URL — S4 (compute), S5 (dedup) |
| `MinIOKey` | `str` | MinIO object key — S4 (bronze), S5 (silver), S6 (reads silver) |
| `JsonDict` | `dict[str, Any]` | Plain alias — readability shorthand, no domain meaning |

**Rule**: only types referenced by **two or more services** live in `common.types`.
Service-local IDs (`SourceId`, `SectionId`, `AlertId`, etc.) belong in each
service's own domain layer.

---

## Usage Examples

```python
# All public symbols are re-exported from the package root:
from common import utc_now, to_iso8601, new_uuid7, new_ulid, uuid5_from_parts
from common import TenantId, EntityId, DocumentId, UrlHash, MinIOKey

# --- Time ---
now = utc_now()                    # datetime(2026, 5, 17, 10, 30, tzinfo=UTC)
iso = to_iso8601(now)              # "2026-05-17T10:30:00.000000Z"
dt  = from_iso8601(iso)            # round-trips cleanly

# --- IDs: new entity in ingestion pipeline ---
doc_id: DocumentId = DocumentId(new_uuid7())
entity_id: EntityId = EntityId(new_uuid7())

# --- IDs: Kafka event ---
event_id = new_ulid()              # "01JBMHZ6Q3..." — lexicographically sortable

# --- IDs: deterministic / idempotent (avoids duplicate rows on Kafka replay) ---
stable_id = uuid5_from_parts(str(doc_id), str(entity_id), "new_evidence")
# Same three inputs always → same UUID5 string → ON CONFLICT DO NOTHING is safe

# --- Type safety ---
# mypy error: Argument of type "UserId" cannot be assigned to "TenantId"
# tenant: TenantId = UserId(new_uuid7())   # ← mypy rejects this
```

---

## Architecture Notes

### Why UUIDv7 (not UUIDv4) for entity PKs?

UUIDv7 embeds a millisecond-precision Unix timestamp in the top 48 bits and is
monotonically increasing within the same millisecond. This makes UUID-ordered
B-tree scans equivalent to time-ordered scans — no need for a separate
`created_at` index on ingestion tables. UUIDv4 is random, producing random B-tree
insertions that cause page splits and table bloat under high-insert workloads.

### Why ULID (not UUIDv7) for Kafka event IDs?

ULIDs are lexicographically sortable as plain strings (no UUID parsing required),
which simplifies log analysis and event deduplication queries that operate on
string prefixes. They carry the same timestamp resolution as UUIDv7.

### Why `NewType` (not just `TypeAlias`)?

`TypeAlias = UUID` is transparent to mypy — it will accept a `UUID` anywhere a
`TypeAlias` is expected. `NewType("TenantId", UUID)` is opaque to mypy — it
requires an explicit `TenantId(uuid_value)` cast at construction sites, making all
accidental type crossings visible at static analysis time without any runtime cost.

### Why not add pydantic / SQLAlchemy to `common`?

`common` is imported by every service and every other shared library. Adding a
heavyweight dependency here forces it into every context, including unit tests and
lightweight scripts. The dependency graph must remain a DAG, and `common` is the
root node.

---

## Configuration

`common` has no configuration. It does not read environment variables. No
pydantic-settings models.

---

## Extension Points

- **New time helpers**: add to `common/time.py` and export from `common/__init__.py`.
  Must always work with UTC-aware datetimes.
- **New ID types**: add to `common/ids.py` only if the function abstracts a
  third-party library that could change. Do not add business logic.
- **New type aliases**: add to `common/types.py` only if the type is used by
  **two or more services**. Service-local types belong in the service domain layer.

---

## Testing

```bash
cd libs/common
python -m pytest tests/ -v
```

**What the tests cover:**
- Round-trip `to_iso8601(from_iso8601(s)) == s`
- `ensure_utc` raises on naive datetimes
- `parse_bar_date` and `parse_bar_datetime` edge cases
- ULID lexicographic ordering
- `uuid5_from_parts` stability (same inputs → same output; reordered inputs → different output)

---

## Common Pitfalls

1. **`datetime.now()` without `timezone.utc`** — produces a naive datetime.
   SQLAlchemy silently accepts it; `ensure_utc()` will raise at service boundaries.
   Always use `utc_now()`.
2. **Accepting `str` instead of typed IDs** — defeats `NewType`. Function signatures
   should accept `TenantId`, not `str`.
3. **`new_uuid7()` in portfolio or market-ingestion** — those services have existing
   UUIDv4 rows in production. Mixing ID types breaks JOIN queries without a migration.
4. **Calling `uuid6.uuid7()` directly in service code** — bypasses the abstraction.
   When Python stdlib adds UUIDv7 (planned for 3.14+), the migration becomes a
   single-library change instead of a multi-service change.
5. **Defining `DocumentId` or `EntityId` locally** — duplicate `NewType` aliases
   from separate `NewType()` calls are distinct types even with the same name. mypy
   will not catch mismatches at service boundaries.
