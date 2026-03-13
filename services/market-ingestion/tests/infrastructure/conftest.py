"""Shared fixtures for infrastructure-layer tests.

The `settings` fixture provides a real `Settings()` instance populated from
the process environment (which `make test-integration` loads from
`configs/dev.local.env` via `set -a && . ./configs/dev.local.env && set +a`).

Integration tests that require live infra (Postgres, Kafka) must use this
fixture and guard themselves with an appropriate `pytest.mark.skipif` check
(see `tests/integration/` for the established pattern).

NOTE: scope="session" is correct — Settings is read-only config that never
      changes within a test session. Building it once avoids redundant env reads
      and keeps integration tests fast.
"""

from __future__ import annotations

import pytest
from market_ingestion.config import Settings


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Real Settings() instance, populated from MARKET_INGESTION_* env vars.

    Populated by `make test-integration` / `make test-all` via:
        set -a && . ./configs/dev.local.env && set +a

    In CI, the same env vars are injected directly into the process environment.
    """
    return Settings()
