# messaging

Kafka producer/consumer abstractions, Avro serialization, transactional outbox
dispatcher, Valkey/Redis client, PostgreSQL advisory locks, and shared EODHD
quota enforcement.

The backbone of all inter-service communication on the worldview platform.

See [docs/libs/messaging.md](../../docs/libs/messaging.md) for full documentation.

## Install (editable, for development)

```bash
pip install -e ".[dev]"
pip install -e ".[pg]"   # adds SQLAlchemy for pg_advisory_lock support
```

## Run tests

```bash
python -m pytest tests/ -v                   # unit tests (no infra needed)
python -m pytest tests/ -v -m integration    # requires Kafka + Valkey
```
