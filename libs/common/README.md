# common

Lightweight shared utilities — UTC time helpers, ID generation (UUIDv7, ULID,
UUIDv4, UUID5), and `NewType` domain type aliases.

The foundation layer: every service and library may depend on it. Zero heavy
dependencies (`python-ulid`, `uuid6` only).

See [docs/libs/common.md](../../docs/libs/common.md) for full documentation.

## Install (editable, for development)

```bash
pip install -e ".[dev]"
```

## Run tests

```bash
python -m pytest tests/ -v
```
