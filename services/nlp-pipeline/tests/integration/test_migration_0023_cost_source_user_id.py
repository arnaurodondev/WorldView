"""Integration test — nlp_db migration 0023 adds cost_source + user_id (PLAN-0117 W2, T-A-2-03).

Spins a throwaway Postgres testcontainer, seeds a minimal ``llm_usage_log`` table
stamped at the PRIOR alembic head (0022), then runs the real nlp-pipeline Alembic
``upgrade head`` (which applies ONLY 0023) and asserts both new columns exist,
are NULLABLE, a pre-migration row reads NULL, and ``downgrade -1`` reverses it.

nlp_db DDL is owned by S6 nlp-pipeline itself (this alembic lineage) — the
intelligence_db copy of these columns is added separately by
intelligence-migrations 0064.

Skips gracefully when Docker / testcontainers / asyncpg / alembic are absent.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from collections.abc import Iterator

import pytest

pytestmark = pytest.mark.integration

# nlp-pipeline env.py resolves the DB URL from ALEMBIC_URL first (asyncpg URL).
_ALEMBIC_ENV_VAR = "ALEMBIC_URL"
_PRIOR_HEAD = "0022"


@pytest.fixture(scope="module")
def _pg_url() -> Iterator[str]:
    pytest.importorskip("testcontainers", reason="testcontainers not installed")
    pytest.importorskip("asyncpg", reason="asyncpg not installed")
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-not-found]

    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg.get_connection_url().replace("psycopg2", "asyncpg")


def _service_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _run_alembic(url: str, *args: str) -> None:
    alembic_bin = shutil.which("alembic")
    if not alembic_bin:  # pragma: no cover - env guard
        pytest.skip("alembic not on PATH")
    result = subprocess.run(
        [alembic_bin, *args],
        cwd=_service_dir(),
        capture_output=True,
        text=True,
        env={**os.environ, _ALEMBIC_ENV_VAR: url},
    )
    if result.returncode != 0:  # pragma: no cover - surfaced as test failure
        raise RuntimeError(f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")


async def _columns(engine, table: str) -> dict[str, str]:
    from sqlalchemy import text

    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT column_name, is_nullable FROM information_schema.columns " "WHERE table_name = :t"),
            {"t": table},
        )
        return {r[0]: r[1] for r in rows.fetchall()}


async def test_migration_0023_adds_nullable_columns(_pg_url: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_pg_url)
    try:
        legacy_id = str(uuid.uuid4())
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE TABLE llm_usage_log ("
                    "  log_id UUID PRIMARY KEY,"
                    "  estimated_cost_usd NUMERIC(12, 6)"
                    ")"
                )
            )
            await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            await conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
                {"v": _PRIOR_HEAD},
            )
            await conn.execute(
                text("INSERT INTO llm_usage_log (log_id, estimated_cost_usd) VALUES (:i, 0.5)"),
                {"i": legacy_id},
            )

        _run_alembic(_pg_url, "upgrade", "head")

        cols = await _columns(engine, "llm_usage_log")
        assert "cost_source" in cols
        assert "user_id" in cols
        assert cols["cost_source"] == "YES"
        assert cols["user_id"] == "YES"

        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT cost_source, user_id FROM llm_usage_log WHERE log_id = :i"),
                    {"i": legacy_id},
                )
            ).fetchone()
        assert row == (None, None)

        _run_alembic(_pg_url, "downgrade", "-1")
        cols_after = await _columns(engine, "llm_usage_log")
        assert "cost_source" not in cols_after
        assert "user_id" not in cols_after
    finally:
        await engine.dispose()
