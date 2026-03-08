# Implementation Guide — common

## Status: Complete

Migration verified: 2026-03-07

## Modules to Implement

- [x] `common.time` — `utc_now`, `ensure_utc`, `to_iso8601`, `from_iso8601`, `parse_bar_date`, `parse_bar_datetime`
- [x] `common.ids` — `new_uuid`, `new_uuid_str`, `new_ulid`
- [x] `common.types` — `TenantId`, `UserId`, `InstrumentId`, `TransactionId`, `EventId`, `TopicName`, `JsonDict`

## Public API Exports

All modules are now wired into `common/__init__.py` with a complete `__all__`:
- `ids`: `new_uuid`, `new_uuid_str`, `new_ulid`
- `time`: `utc_now`, `ensure_utc`, `to_iso8601`, `from_iso8601`, `parse_bar_date`, `parse_bar_datetime`
- `types`: `TenantId`, `UserId`, `InstrumentId`, `TransactionId`, `EventId`, `TopicName`, `JsonDict`

## Tests

- `tests/test_time.py` — 30+ test methods covering edge cases, timezone conversion, roundtrips
- `tests/test_ids.py` — UUID v4 type/format/uniqueness, ULID length/ordering/uniqueness
- `tests/test_types.py` — NewType runtime transparency, JsonDict usage patterns

## Migration Source

- `platform_repo/libs/common/src/common/time.py` → copied as-is
- `platform_repo/libs/common/src/common/ids.py` → written fresh (was empty)
- `platform_repo/libs/common/src/common/types.py` → written fresh (was empty)
