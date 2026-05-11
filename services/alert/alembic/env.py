"""Alembic environment configuration for alert_db."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from alert.config import Settings as _Settings
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

# DB URL resolution: ALEMBIC_URL → ALERT_DATABASE_URL → alembic.ini fallback
# SecretStr guard: pydantic SecretStr must be unwrapped before passing to alembic
_db_url_raw = os.environ.get("ALEMBIC_URL") or _Settings().database_url
_db_url = _db_url_raw.get_secret_value() if hasattr(_db_url_raw, "get_secret_value") else str(_db_url_raw)
if _db_url:
    config.set_main_option("sqlalchemy.url", _db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from alert.infrastructure.db.models import Base  # noqa: E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
