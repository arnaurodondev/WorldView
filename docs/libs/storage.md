# Storage Library

> **Package**: `storage` · **Path**: `libs/storage/` · **Version**: 2025.6.0
> **Purpose**: S3-compatible object storage abstraction (MinIO, AWS S3, Ceph RGW).
> Enforces canonical key formats and provides a clean async interface for the
> claim-check pattern.

---

## Purpose

Kafka messages have a practical size limit (~1 MB default). Raw OHLCV datasets,
news corpora, and NLP artifacts easily exceed this. The **claim-check pattern**
solves this: store the large payload in MinIO/S3 and put only a *pointer* (bucket
+ key) in the Kafka event. Consumers fetch the payload from object storage.

`storage` provides:
- A uniform async interface (`ObjectStorage` ABC) that works against MinIO, AWS S3,
  and Ceph RGW.
- A canonical key format enforced by `KeyBuilder`, so keys are parseable and
  prefix-listable.
- Async wrapping of boto3 (which is synchronous) via `asyncio.to_thread()` so
  FastAPI event loops are never blocked.

---

## Installation

```toml
[project]
dependencies = ["storage"]
```

```bash
pip install -e "libs/storage"
```

Dependencies: `boto3>=1.34`, `botocore>=1.34`. Python 3.11–3.12.

---

## Public API

### `ObjectStorage` (Abstract Base Class)

All service code must depend on this interface, never on `S3ObjectStorage` directly.
The backend is a deployment detail — tests swap in a fake implementation.

| Method | Signature | Description |
|--------|-----------|-------------|
| `put_bytes` | `(bucket, key, data, content_type?)` → `None` | Upload raw bytes. |
| `get_bytes` | `(bucket, key)` → `bytes` | Download object. Raises `ObjectNotFoundError` if missing. |
| `delete` | `(bucket, key)` → `None` | Delete an object. |
| `list_keys` | `(bucket, prefix?)` → `list[str]` | List object keys under a prefix. |
| `exists` | `(bucket, key)` → `bool` | Check if a key exists (HEAD request). |
| `delete_prefix` | `(bucket, prefix)` → `int` | Delete all objects under a prefix. Returns count deleted. |
| `put_json` | `(bucket, key, data)` → `None` | Serializes dict to JSON and uploads. |
| `get_json` | `(bucket, key)` → `dict` | Downloads and deserializes JSON object. |

### `S3ObjectStorage`

Concrete implementation backed by boto3. Wraps every boto3 call in
`asyncio.to_thread()` to keep the event loop non-blocking.

```python
from storage import build_object_storage   # preferred: reads env vars
# or directly:
from storage.s3_adapter import S3ObjectStorage
```

### `build_object_storage()` — Factory

```python
from storage import build_object_storage

store = build_object_storage()   # reads STORAGE_* env vars
```

### `KeyBuilder`

Enforces the canonical key format: `{service}/{domain}/{resource_id}/{artifact}/{version}.{ext}`

| Method | Signature | Description |
|--------|-----------|-------------|
| `KeyBuilder.build(...)` | `(service, domain, resource_id, artifact, version?, extension?)` → `str` | Build a valid canonical key. |
| `KeyBuilder.validate(key)` | `(key: str)` → `None` | Raises `InvalidObjectKeyError` if format is invalid. |
| `KeyBuilder.parse(key)` | `(key: str)` → `KeyComponents` | Parse key into named tuple (`service`, `domain`, `resource_id`, `artifact`, `version`, `extension`). |
| `KeyBuilder.build_prefix(service, domain?)` | `(...)` → `str` | Build a prefix for `list_keys` scans. |

### `check_storage_health(store, bucket)` — Health Check

```python
from storage.health import check_storage_health

is_healthy = await check_storage_health(store, "market-data")
# → True if a HEAD request to the bucket succeeds; never raises
```

### Exceptions

| Exception | When raised |
|-----------|-------------|
| `StorageError` | Base class for all storage errors |
| `ObjectNotFoundError` | `get_bytes` / `get_json` — key doesn't exist |
| `BucketNotFoundError` | Bucket doesn't exist |
| `StoragePermissionError` | Access denied (403) |
| `StorageUnavailableError` | MinIO/S3 unreachable (network error, 5xx) |
| `InvalidObjectKeyError` | Key violates naming convention (also a `ValueError`) |

### Settings (`storage.settings.StorageSettings`)

Automatically read by `build_object_storage()`. Pydantic-settings model with
`STORAGE_` env prefix.

| Field | Env var | Default | Description |
|-------|---------|---------|-------------|
| `endpoint` | `STORAGE_ENDPOINT` | `None` | MinIO endpoint URL (omit for AWS S3) |
| `access_key` | `STORAGE_ACCESS_KEY` | — | Access key ID (required) |
| `secret_key` | `STORAGE_SECRET_KEY` | — | Secret access key (required, `SecretStr`) |
| `region` | `STORAGE_REGION` | `"us-east-1"` | AWS region or MinIO region |
| `use_ssl` | `STORAGE_USE_SSL` | `True` | Enable HTTPS |
| `default_bucket` | `STORAGE_DEFAULT_BUCKET` | `None` | Default bucket name |

---

## Usage Examples

### Basic Put / Get

```python
from storage import build_object_storage, KeyBuilder

store = build_object_storage()   # reads STORAGE_* env vars

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

# Upload
await store.put_bytes("market-data", key, parquet_bytes, content_type="application/octet-stream")

# Download
data = await store.get_bytes("market-data", key)

# JSON convenience helpers
await store.put_json("content-store", key, {"url": "...", "text": "..."})
article = await store.get_json("content-store", key)
```

### Claim-Check Producer

```python
# Producer side (S4 content-ingestion):
key = KeyBuilder.build(service="content-ingestion", domain="article",
                       resource_id=article_id, artifact="raw", extension="json")
await store.put_json("content-raw", key, article_dict)
# Emit Kafka event with pointer only:
await outbox.add(OutboxRecord(
    event_type="content.article.raw",
    topic="content.article.raw.v1",
    payload={"bucket": "content-raw", "key": key, "article_id": article_id},
))
```

### Claim-Check Consumer

```python
# Consumer side (S5 content-store):
async def process_message(self, key, value, headers):
    bucket = value["bucket"]
    obj_key = value["key"]
    try:
        data = await self._storage.get_bytes(bucket, obj_key)
    except ObjectNotFoundError:
        raise FatalError(f"Object missing: {bucket}/{obj_key}")
    except StorageUnavailableError as exc:
        raise RetryableError("object storage unavailable") from exc
    article = json.loads(data)
    await self._repo.upsert(article)
```

### Health Check in FastAPI Lifespan

```python
from storage.health import check_storage_health

@asynccontextmanager
async def lifespan(app):
    ok = await check_storage_health(store, "market-data")
    if not ok:
        logger.warning("storage_health_check_failed")
    yield
```

---

## Key Builder Anatomy

Canonical key format: `{service}/{domain}/{resource_id}/{artifact}/{version}.{ext}`

| Segment | Meaning | Example values |
|---------|---------|----------------|
| `service` | Owning service name (matches service directory) | `market-ingestion`, `content-store`, `nlp-pipeline` |
| `domain` | Data domain within the service | `ohlcv`, `fundamentals`, `article`, `embedding` |
| `resource_id` | Identifies the specific resource; may contain `/` for hierarchy | `AAPL.US/2024-01-01_2024-12-31`, `reuters/20260101-abc123` |
| `artifact` | What kind of artifact is stored | `canonical`, `raw`, `normalized`, `embedding` |
| `version` | Artifact version string | `v1`, `v2`, `snapshot-20260101` |
| `ext` | File extension (no leading dot) | `parquet`, `jsonl`, `json`, `bin` |

**Full examples:**

```
market-ingestion/ohlcv/AAPL.US/2024-01-01_2024-12-31/canonical/v2.parquet
content-store/article/reuters/20260101-abc123/normalized/v1.json
nlp-pipeline/embedding/reuters/20260101-abc123/bge-large/v1.bin
```

---

## Architecture Notes

### Why async wrapping of boto3?

boto3 is a synchronous library. Calling `boto3.client.get_object()` directly inside
an `async def` blocks the event loop, stalling all concurrent requests in the
service. `S3ObjectStorage` wraps every boto3 call in `asyncio.to_thread()` (which
uses `loop.run_in_executor(None, ...)` internally), keeping the event loop free.

### Why a canonical key format?

Ad-hoc key strings make it impossible to:
- List all artifacts for a specific resource (`list_keys(bucket, prefix="market-ingestion/ohlcv/AAPL.US/")`).
- Parse keys back into structured fields for observability and debugging.
- Enforce ownership boundaries (which service wrote this object?).

`KeyBuilder` makes all of this trivial and prevents two services from accidentally
writing to the same key.

### Bucket ownership

Each service owns its bucket(s). A service must never write to another service's
bucket. Bucket names are part of the service contract — they should be configured
via environment variables, not hardcoded.

---

## Configuration

```bash
# .env (local development with MinIO)
STORAGE_ENDPOINT=http://localhost:7480
STORAGE_ACCESS_KEY=minioadmin
STORAGE_SECRET_KEY=minioadmin
STORAGE_REGION=us-east-1
STORAGE_USE_SSL=false

# .env (AWS S3)
# STORAGE_ENDPOINT=   (omit for S3)
STORAGE_ACCESS_KEY=AKIA...
STORAGE_SECRET_KEY=...
STORAGE_REGION=eu-west-1
STORAGE_USE_SSL=true
```

---

## Extension Points

- **New storage backend**: implement `ObjectStorage` ABC (e.g., GCS, Azure Blob).
  Register in `build_object_storage()` factory.
- **Streaming support**: `get_bytes()` loads entire objects into RAM. For objects
  > 100 MB, a streaming download method is needed. File an issue and use multipart
  download as a workaround until implemented.

---

## Testing

```bash
cd libs/storage
python -m pytest tests/ -v                          # unit tests (KeyBuilder)
python -m pytest tests/ -v -m integration           # requires MinIO (testcontainers)
```

Unit tests cover `KeyBuilder` build/validate/parse, and exception hierarchy.
Integration tests run against a real MinIO container and verify all `ObjectStorage`
methods including `delete_prefix` and `exists`.

---

## Common Pitfalls

1. **Direct boto3 imports in services** — always use `ObjectStorage` interface.
   Tests swap in a fake implementation that would be bypassed.
2. **Ad-hoc key strings** — always use `KeyBuilder`. Ad-hoc strings will fail
   `validate()` and make prefix-list scans impossible.
3. **Large objects in RAM** — `get_bytes()` loads the full object. For files
   > 100 MB, use multipart download or a streaming API.
4. **Calling boto3 directly in async context** — blocks the event loop. Always go
   through `S3ObjectStorage`.
5. **Writing to another service's bucket** — each service owns its buckets.
   Cross-service bucket writes are an architecture violation.
6. **Not catching `ObjectNotFoundError`** — `get_bytes()` raises, not returns `None`.
   Always handle this exception or check `exists()` first.
