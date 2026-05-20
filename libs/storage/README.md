# storage

S3-compatible object storage abstraction (MinIO, AWS S3, Ceph RGW).

Enforces canonical key formats via `KeyBuilder` and provides an async interface
for the claim-check pattern. Wraps boto3 in `asyncio.to_thread()` so FastAPI
event loops are never blocked.

See [docs/libs/storage.md](../../docs/libs/storage.md) for full documentation.

## Install (editable, for development)

```bash
pip install -e ".[dev]"
```

## Run tests

```bash
python -m pytest tests/ -v                   # unit tests (KeyBuilder)
python -m pytest tests/ -v -m integration    # requires MinIO (testcontainers)
```
