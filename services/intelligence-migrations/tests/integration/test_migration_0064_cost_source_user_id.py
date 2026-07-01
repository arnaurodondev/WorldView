"""Integration test — intelligence_db migration 0064 adds cost_source + user_id (PLAN-0117 W2, T-A-2-03).

Follows the existing ``test_migration_apply.py`` structure: the session-scoped
autouse ``run_migrations`` fixture runs ``alembic downgrade base`` →
``alembic upgrade head`` against ``INTELLIGENCE_DB_URL`` (skipping gracefully
when unreachable), which applies migration 0064. This test then asserts, against
the live post-``upgrade head`` schema, that:

  * ``llm_usage_log.cost_source`` and ``llm_usage_log.user_id`` exist;
  * both are NULLABLE (Hard Rule 11 forward-compat — pre-0117 rows read NULL);
  * their SQL types are ``character varying`` (VARCHAR(16)) and ``uuid``.

intelligence_db DDL is owned exclusively by intelligence-migrations (R24/R32);
S7 knowledge-graph owns no lineage. The migration head itself is verified by
``test_migration_apply.py::test_alembic_version_matches_disk_head`` (auto-detects
0064 as the sole on-disk head — proving the 0063→0064 chain stays linear).
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import text

pytestmark = pytest.mark.integration


def _column(conn: sa.engine.Connection, table: str, column: str) -> tuple[str, str] | None:
    """Return ``(data_type, is_nullable)`` for a column, or None if absent."""
    row = conn.execute(
        text(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return (row[0], row[1]) if row is not None else None


def test_0064_adds_cost_source_column(live_db_ready: None, conn: sa.engine.Connection) -> None:
    """``cost_source`` exists, is nullable VARCHAR after ``upgrade head``."""
    col = _column(conn, "llm_usage_log", "cost_source")
    assert col is not None, "cost_source missing from intelligence_db.llm_usage_log"
    data_type, is_nullable = col
    assert data_type == "character varying", f"cost_source type={data_type!r}, expected VARCHAR"
    assert is_nullable == "YES", "cost_source must be nullable (R11)"


def test_0064_adds_user_id_column(live_db_ready: None, conn: sa.engine.Connection) -> None:
    """``user_id`` exists, is nullable UUID after ``upgrade head``."""
    col = _column(conn, "llm_usage_log", "user_id")
    assert col is not None, "user_id missing from intelligence_db.llm_usage_log"
    data_type, is_nullable = col
    assert data_type == "uuid", f"user_id type={data_type!r}, expected uuid"
    assert is_nullable == "YES", "user_id must be nullable (R11)"
