# Implementation Guide — storage

## Status: Complete (wave-02, 2026-03-07)

## Modules Implemented

- [x] `storage.exceptions` — `StorageError`, `ObjectNotFoundError`, `BucketNotFoundError`, `StoragePermissionError`, `StorageUnavailableError`, `InvalidObjectKeyError`
- [x] `storage.interface` — `ObjectStorage` ABC (`put_bytes`, `get_bytes`, `delete`, `list_keys`, `exists`, `delete_prefix`, `put_json`, `get_json`)
- [x] `storage.s3_adapter` — `S3ObjectStorage` (boto3 + asyncio.to_thread, full error mapping)
- [x] `storage.settings` — `StorageSettings` (pydantic-settings, `STORAGE_` prefix, `endpoint_url` + `is_aws` computed fields)
- [x] `storage.key_builder` — `KeyBuilder` (build, validate, parse, build_prefix) + `KeyComponents` frozen dataclass
- [x] `storage.factory` — `build_object_storage(settings?)` factory
- [x] `storage.health` — `check_storage_health(store, bucket)` async health probe

## Public Exports (`storage.__init__`)

```python
from storage import (
    BucketNotFoundError,
    InvalidObjectKeyError,
    KeyBuilder,
    KeyComponents,
    ObjectNotFoundError,
    ObjectStorage,
    S3ObjectStorage,
    StorageError,
    StoragePermissionError,
    StorageSettings,
    StorageUnavailableError,
    build_object_storage,
    check_storage_health,
)
```

## Tests

- `tests/test_exceptions.py` — 11 tests (hierarchy, catch-as-StorageError, catch-as-ValueError)
- `tests/test_interface.py` — 16 tests (ABC, put/get, JSON helper, exists, delete, list)
- `tests/test_keys.py` — 16 tests (build, validate, parse, roundtrip, prefix, components)
- `tests/test_settings.py` — 12 tests (defaults, computed fields, env vars)
- `tests/test_health.py` — 5 tests (success, StorageError, unexpected, never-raises)
- `tests/test_s3_adapter.py` — 14 tests (init, put/get/delete/exists/list/delete_prefix, error mapping)

## Key Design Decisions

- `InvalidObjectKeyError` inherits from both `StorageError` and `ValueError` for backward compatibility.
- `S3ObjectStorage` uses `asyncio.to_thread` to wrap all synchronous boto3 calls.
- `StorageSettings.endpoint_url` returns `None` when endpoint is empty (AWS S3 mode).
- `KeyBuilder.build()` now validates each component; `validate()` checks the full key pattern.
- Health check never raises — logs and returns `False` on any error.

## Migration Source

- `platform_repo/libs/storage/` — extracted patterns; reimplemented for async + pydantic v2
