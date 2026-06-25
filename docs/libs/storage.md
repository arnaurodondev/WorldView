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

Dependencies: `boto3>=1.34,<2`, `pydantic>=2.5,<3`, `pydantic-settings>=2.1,<3`,
`structlog>=25.0,<26`. Python 3.11–3.12. (`botocore` is pulled in transitively by
boto3 and imported lazily inside the adapter.)

---

## Public API

### `ObjectStorage` (Abstract Base Class)

All service code must depend on this interface, never on `S3ObjectStorage` directly.
The backend is a deployment detail — tests swap in a fake implementation.

All methods are `async`. `bucket` is typed `str | BucketTier` on `put_bytes` /
`get_bytes` (raw strings still work); the remaining methods take a plain `str`.

| Method | Signature | Description |
|--------|-----------|-------------|
| `put_bytes` | `(bucket: str \| BucketTier, key: str, data: bytes, content_type: str = "application/octet-stream")` → `str \| None` | Upload raw bytes. Returns the object's ETag (quotes stripped) when the backend reports one, else `None`. |
| `get_bytes` | `(bucket: str \| BucketTier, key: str, *, expected_etag: str \| None = None)` → `bytes` | Download object. Raises `ObjectNotFoundError` if missing. When `expected_etag` is set, raises `ETagMismatchError` if the stored ETag differs. |
| `delete` | `(bucket: str, key: str)` → `None` | Delete an object (no-op if the key is absent — S3 delete semantics). |
| `list_keys` | `(bucket: str, prefix: str = "")` → `list[str]` | List object keys under a prefix (sorted, paginated internally). |
| `exists` | `(bucket: str, key: str)` → `bool` | Check if a key exists (HEAD request on the object). |
| `delete_prefix` | `(bucket: str, prefix: str)` → `int` | Delete all objects under a prefix (batched, max 1000/call). Returns count deleted. |
| `put_json` | `(bucket: str, key: str, data: dict[str, Any])` → `None` | Serializes dict to UTF-8 JSON and uploads with `application/json` content type (concrete helper on the ABC). |
| `get_json` | `(bucket: str, key: str)` → `dict[str, Any]` | Downloads and deserializes JSON object (concrete helper on the ABC). |

> `put_json` / `get_json` are concrete convenience helpers implemented directly on
> the `ObjectStorage` ABC (built on `put_bytes` / `get_bytes`); subclasses only
> implement the abstract methods.

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

store = build_object_storage()                 # reads STORAGE_* env vars
# or inject a pre-built settings object (useful in tests):
store = build_object_storage(StorageSettings(access_key="...", secret_key="..."))
```

Signature: `build_object_storage(settings: StorageSettings | None = None) -> ObjectStorage`.
When `settings` is `None` (the default) the factory constructs `StorageSettings()`,
which reads the `STORAGE_*` environment variables.

### `BucketTier` (StrEnum)

Typed alias for the platform's three canonical MinIO buckets, so callers don't
have to hand-type bucket-name strings into `put_bytes` / `get_bytes`. Because it
subclasses `str` (`enum.StrEnum`), members coerce cleanly to their string value
and existing string callers keep working unchanged.

| Member | Value | Tier |
|--------|-------|------|
| `BucketTier.BRONZE` | `"worldview-bronze"` | Raw provider payloads — never mutated after first write |
| `BucketTier.SILVER` | `"worldview-silver"` | Canonicalized, schema-validated, normalized records |
| `BucketTier.GOLD` | `"worldview-gold"` | Analysis-ready aggregates and derived datasets |

```python
from storage import BucketTier

await store.put_bytes(BucketTier.BRONZE, key, data)
# equivalent to:
await store.put_bytes("worldview-bronze", key, data)
```

### `KeyBuilder`

Enforces the canonical key format: `{service}/{domain}/{resource_id}/{artifact}/{version}.{ext}`

All methods are static/class methods — `KeyBuilder` is never instantiated.

| Method | Signature | Description |
|--------|-----------|-------------|
| `KeyBuilder.build` | `(service: str, domain: str, resource_id: str, artifact: str, version: str = "v1", extension: str = "parquet")` → `str` | Build and validate a canonical key. `version` must match `v{N}`. |
| `KeyBuilder.validate` | `(key: str)` → `None` | Raises `InvalidObjectKeyError` if format is invalid. |
| `KeyBuilder.parse` | `(key: str)` → `KeyComponents` | Parse key into a frozen `KeyComponents` dataclass (`service`, `domain`, `resource_id`, `artifact`, `version`, `extension`; plus a `full_key` property). |
| `KeyBuilder.build_prefix` | `(service: str, domain: str \| None = None)` → `str` | Build a prefix (ending in `/`) for `list_keys` scans. |
| `KeyBuilder.is_valid_silver_key` | `(key: str)` → `bool` | Return `True` for content-store MinIO keys that pre-date the canonical format: `silver/<source>/<YYYY>/<MM>/<DD>/<uuid>.txt` (legacy news) or `content-store/canonical/<uuid>/body.json` (PLAN-0086). Never raises. |

`KeyComponents` is exported from the package root (`from storage import KeyComponents`).

### `check_storage_health(store, bucket)` — Health Check

```python
from storage import check_storage_health   # also: from storage.health import check_storage_health

is_healthy = await check_storage_health(store, "market-data")
# → True if a lightweight list_keys(bucket, prefix="__health__") succeeds.
#   Never raises: StorageError → logs warning + returns False; any other
#   exception → logs error + returns False.
```

### Exceptions

| Exception | When raised |
|-----------|-------------|
| `StorageError` | Base class for all storage errors |
| `ObjectNotFoundError` | `get_bytes` / `get_json` — key doesn't exist (`NoSuchKey`/`404`) |
| `BucketNotFoundError` | Bucket doesn't exist (`NoSuchBucket`) |
| `StoragePermissionError` | Access denied (`AccessDenied`/`403`) |
| `StorageUnavailableError` | MinIO/S3 unreachable (network/endpoint error, other client errors) |
| `InvalidObjectKeyError` | Key violates naming convention (also a `ValueError`) |
| `ETagMismatchError` | `get_bytes(..., expected_etag=...)` — stored ETag differs from the expected one |

All exceptions subclass `StorageError`. `ETagMismatchError` is *not* exported from
`storage.exceptions` only — it is also re-exported from the package root, alongside
the others, so `from storage import ETagMismatchError` works.

### Settings (`storage.settings.StorageSettings`)

Automatically read by `build_object_storage()`. Pydantic-settings model with
`STORAGE_` env prefix.

| Field | Env var | Type | Default | Description |
|-------|---------|------|---------|-------------|
| `endpoint` | `STORAGE_ENDPOINT` | `str` | `"http://localhost:7480"` | S3-compatible endpoint URL. Set to empty string to use AWS S3's default endpoint resolution. |
| `access_key` | `STORAGE_ACCESS_KEY` | `str` | — (required) | AWS access key ID / MinIO access key |
| `secret_key` | `STORAGE_SECRET_KEY` | `str` | — (required) | AWS secret access key / MinIO secret key |
| `region` | `STORAGE_REGION` | `str` | `"us-east-1"` | AWS region or MinIO region |
| `use_ssl` | `STORAGE_USE_SSL` | `bool` | `False` | Enable HTTPS for the endpoint connection |
| `default_bucket` | `STORAGE_DEFAULT_BUCKET` | `str` | `"worldview"` | Default bucket name used by the factory/health logging |
| `max_pool_connections` | `STORAGE_MAX_POOL_CONNECTIONS` | `int` | `50` | urllib3/botocore connection-pool size. Raise to match a consumer's concurrency (botocore default 10 floods "Connection pool is full" logs under dataset replay). |

Computed (read-only) properties:

- `endpoint_url` → `str | None` — returns the stripped `endpoint`, or `None` when
  empty (so boto3 falls back to AWS default endpoint resolution).
- `is_aws` → `bool` — `True` when no custom endpoint is set.

> Note: `secret_key` is a plain `str`, not a `SecretStr`. Treat the settings object
> as sensitive and never log it directly.

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
        # get_json deserialises for us; use get_bytes for non-JSON payloads.
        article = await self._storage.get_json(bucket, obj_key)
    except ObjectNotFoundError:
        raise FatalError(f"Object missing: {bucket}/{obj_key}")
    except StorageUnavailableError as exc:
        raise RetryableError("object storage unavailable") from exc
    await self._repo.upsert(article)
```

### ETag Verification (tamper / overwrite detection)

`put_bytes` returns the object's ETag; a producer can persist it in the Kafka
pointer, and the consumer can pass it back via `expected_etag` to detect an
overwrite or corruption between produce and consume.

```python
from storage import ETagMismatchError

# Producer: capture the ETag and ship it in the event pointer.
etag = await store.put_bytes("content-raw", obj_key, payload)
await outbox.add(OutboxRecord(
    event_type="content.article.raw",
    topic="content.article.raw.v1",
    payload={"bucket": "content-raw", "key": obj_key, "etag": etag},
))

# Consumer: verify the object hasn't changed since it was produced.
try:
    data = await store.get_bytes("content-raw", obj_key, expected_etag=value["etag"])
except ETagMismatchError:
    raise FatalError("object overwritten between produce and consume")
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
| `version` | Artifact version string — **must** match `v{N}` | `v1`, `v2`, `v10` |
| `ext` | File extension (no leading dot), lowercase alphanumeric | `parquet`, `jsonl`, `json`, `bin` |

> The strict `v{N}` version rule is enforced by both `KeyBuilder.build()` and the
> full-key regex used by `validate()` / `parse()`. Date-stamped or labelled version
> strings (e.g. `snapshot-20260101`) are **rejected** with `InvalidObjectKeyError`.
> Encode such information in `resource_id` instead.

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
STORAGE_ENDPOINT=        # empty string → boto3 uses AWS default endpoint
STORAGE_ACCESS_KEY=AKIA...
STORAGE_SECRET_KEY=...
STORAGE_REGION=eu-west-1
STORAGE_USE_SSL=true
STORAGE_DEFAULT_BUCKET=worldview
```

> Note the field defaults: `STORAGE_ENDPOINT` defaults to the local MinIO URL
> (`http://localhost:7480`) and `STORAGE_USE_SSL` defaults to `False`. For AWS S3
> you must explicitly set `STORAGE_ENDPOINT=` (empty) and `STORAGE_USE_SSL=true`.

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
