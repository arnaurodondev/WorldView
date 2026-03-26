"""Fixtures for intelligence-migrations integration tests.

Requires a Postgres instance with pgvector extension available.
Set INTELLIGENCE_DB_URL env var, or defaults to localhost:5432/intelligence_test_db.
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


def _get_test_db_url() -> str:
    return os.environ.get(
        "INTELLIGENCE_DB_URL",
        "postgresql://postgres:postgres@localhost:5432/intelligence_test_db",
    )


@pytest.fixture(scope="session")
def db_url() -> str:
    return _get_test_db_url()


@pytest.fixture(scope="session")
def alembic_cfg(db_url: str) -> Config:
    """Build Alembic Config pointing at the test database."""
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    os.environ["INTELLIGENCE_DB_URL"] = db_url
    return cfg


@pytest.fixture(scope="session")
def engine(db_url: str) -> sa.engine.Engine:
    return sa.create_engine(db_url, pool_pre_ping=True)


@pytest.fixture(scope="session", autouse=True)
def run_migrations(alembic_cfg: Config, engine: sa.engine.Engine) -> None:
    """Run alembic upgrade head once per test session, then downgrade at teardown."""
    # Downgrade first in case previous run left state
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    yield  # type: ignore[misc]
    command.downgrade(alembic_cfg, "base")


@pytest.fixture()
def conn(engine: sa.engine.Engine):
    """Per-test connection with rollback."""
    with engine.connect() as connection:
        yield connection
