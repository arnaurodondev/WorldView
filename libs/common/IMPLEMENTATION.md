# Implementation Guide — common

## Status: Scaffold

This file tracks implementation progress for the `common` library.

## Modules to Implement

- [ ] `common.time` — `utc_now`, `ensure_utc`, `to_iso8601`, `from_iso8601`, `parse_bar_date`, `parse_bar_datetime`
- [ ] `common.ids` — `new_uuid`, `new_uuid_str`, `new_ulid`
- [ ] `common.types` — `TenantId`, `UserId`, `InstrumentId`, `TransactionId`, `EventId`, `TopicName`, `JsonDict`

## Migration Source

- `platform_repo/libs/common/src/common/time.py` → copy as-is
- `platform_repo/libs/common/src/common/ids.py` → write fresh (was empty)
- `platform_repo/libs/common/src/common/types.py` → write fresh (was empty)
