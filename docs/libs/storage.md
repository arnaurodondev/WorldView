# Storage Library

> **Package**: `storage` · **Path**: `libs/storage/`
> **Purpose**: S3-compatible object storage abstraction (MinIO, AWS S3, Ceph RGW).
> Enforces canonical key formats and provides a clean interface for claim-check pattern.

---

## Public API

| Class/Function | Purpose |
|----------------|---------|
| `ObjectStorage` (ABC) | Interface: `put_bytes`, `get_bytes`, `delete`, `list_keys`, `exists`, `delete_prefix`, `put_json`, `get_json` |
| `S3ObjectStorage` | boto3 implementation supporting MinIO, AWS S3, Ceph RGW |
| `StorageSettings` | Pydantic settings with `STORAGE_` env prefix |
| `build_object_storage()` | Factory function (reads `StorageSettings` from env) |
| `KeyBuilder` | Enforces canonical key format: `{service}/{domain}/{resource_id}/{artifact}/{version?}` |
| `validate_key(key)` | Validates key against naming convention |
| `check_storage_health()` | Lightweight health check (HEAD bucket) |

### Exceptions

| Exception | When |
|-----------|------|
| `ObjectNotFoundError` | Key doesn't exist |
| `BucketNotFoundError` | Bucket doesn't exist |
| `StoragePermissionError` | Access denied |
| `StorageUnavailableError` | MinIO/S3 unreachable |
| `InvalidObjectKeyError` | Key violates naming convention |

---

## How to Use

```python
from storage import build_object_storage, KeyBuilder

store = build_object_storage()  # reads STORAGE_* env vars

# Build a canonical key
key = KeyBuilder.build(
    service="market-ingestion",
    domain="ohlcv",
    resource_id="AAPL.US/2024-01-01_2024-12-31",
    artifact="canonical",
    version="v2",
    extension="parquet"
)
# → "market-ingestion/ohlcv/AAPL.US/2024-01-01_2024-12-31/canonical/v2.parquet"

# Store data
await store.put_bytes("market-data", key, data, content_type="application/octet-stream")

# Retrieve data
data = await store.get_bytes("market-data", key)

# Health check
is_healthy = await check_storage_health(store, "market-data")
```

---

## Configuration

```bash
# .env
STORAGE_ENDPOINT=http://localhost:7480    # MinIO endpoint (omit for AWS S3)
STORAGE_ACCESS_KEY=minioadmin
STORAGE_SECRET_KEY=minioadmin
STORAGE_REGION=us-east-1
STORAGE_USE_SSL=false
```

---

## Common Pitfalls

1. **Direct boto3 imports**: Services must use `ObjectStorage` interface only. Backend is a deployment detail.
2. **Invalid keys**: Always use `KeyBuilder` — ad-hoc key strings will fail validation.
3. **Large file reads in memory**: For files > 100MB, consider streaming (not implemented yet; add if needed).

---

## Testing Strategy

- **Unit**: `KeyBuilder` validation, key format enforcement
- **Integration**: `S3ObjectStorage` against MinIO (testcontainers)

---

## Implementation Status

**Wave-02 (2026-03-07)**: All modules implemented and tested.

- `storage.exceptions` — complete: `StorageError`, `ObjectNotFoundError`, `BucketNotFoundError`,
  `StoragePermissionError`, `StorageUnavailableError`, `InvalidObjectKeyError`
- `storage.interface` — `ObjectStorage` ABC with `put_json`/`get_json` helpers
- `storage.s3_adapter` — `S3ObjectStorage` using `asyncio.to_thread` for async boto3 wrapping
- `storage.settings` — expanded with `default_bucket`, `endpoint_url`, `is_aws` computed fields
- `storage.key_builder` — `KeyBuilder` with build/validate/parse/build_prefix + `KeyComponents`
- `storage.factory` — `build_object_storage()` factory
- `storage.health` — `check_storage_health()` (never raises)

`InvalidObjectKeyError` is now in `storage.exceptions`; it inherits from both `StorageError`
and `ValueError` for backward compatibility.

See `libs/storage/IMPLEMENTATION.md`.
