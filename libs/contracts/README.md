# contracts

Canonical data models and schema versions. Single source of truth for the shape
of data crossing service boundaries — OHLCV bars, articles, entities, events,
Kafka event envelopes, trust authority scores.

Zero runtime external dependencies (only `structlog`; optional `pyarrow` for
Parquet I/O).

See [docs/libs/contracts.md](../../docs/libs/contracts.md) for full documentation.

## Install (editable, for development)

```bash
pip install -e ".[dev]"
pip install -e ".[parquet]"   # optional Parquet I/O support
```

## Run tests

```bash
python -m pytest tests/ -v
```
