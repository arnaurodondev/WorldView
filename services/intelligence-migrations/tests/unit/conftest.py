"""Conftest for static-only tests (no live PG required).

The parent ``tests/conftest.py`` registers a session-scoped, autouse
``run_migrations`` fixture that connects to Postgres and runs alembic
upgrade head. Tests in this subdir do pure source-inspection (read
migration files as text, parse imports, etc.) and must NOT require a
live DB. We override the parent fixture with a no-op so it does not
fail on missing infra.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session", autouse=True)
def run_migrations() -> Iterator[None]:
    """No-op override of the parent autouse fixture.

    Static tests in this subdir inspect migration source files only; they
    do not need alembic to run against a live database.
    """
    yield
