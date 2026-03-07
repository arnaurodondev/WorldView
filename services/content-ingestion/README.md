# content-ingestion

RSS/API polling for news, domain allowlists, rate limiting, relay fallback, raw article storage

See [docs/services/content-ingestion.md](../../docs/services/content-ingestion.md) for full documentation.

## Quick Start

```bash
make run       # Start with hot-reload on port 8004
make test      # Run unit tests
make lint      # Ruff + mypy
make migrate   # Alembic upgrade head
```
