# Common Library

> **Package**: `common` · **Path**: `libs/common/`
> **Purpose**: Lightweight shared utilities — time helpers, ID generation,
> type aliases. Zero or near-zero dependencies.

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

### Type Aliases (`common.types`)

| Alias | Definition |
|-------|------------|
| `TenantId` | `NewType("TenantId", UUID)` |
| `UserId` | `NewType("UserId", UUID)` |
| `InstrumentId` | `NewType("InstrumentId", UUID)` |
| `TransactionId` | `NewType("TransactionId", UUID)` |
| `EventId` | `NewType("EventId", str)` |
| `TopicName` | `NewType("TopicName", str)` |
| `JsonDict` | `dict[str, Any]` |

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

1. **No heavy dependencies**: This library must remain < 3 external deps.
   Allowed: `python-ulid`. Not allowed: `pydantic`, `sqlalchemy`, etc.
2. **All datetimes are UTC**: `utc_now()` is the only way to get "now".
   Never call `datetime.now()` without `timezone.utc`.
3. **NewType usage**: Type aliases like `TenantId` are `NewType` wrappers —
   they provide type-checker safety at zero runtime cost.

---

## Testing Strategy

- **Unit**: Round-trip `to_iso8601(from_iso8601(s)) == s`, `ensure_utc` raises
  on naive datetimes, `parse_bar_date` edge cases, ULID ordering.
