"""Integration tests for migration 0035 — add source_name/source_type to relation_evidence_raw.

Migration 0035 (``0035``) addresses T-A-05 (PRD-0074 §8.7):

  1. Adds two nullable columns to ``relation_evidence_raw``:
       - ``source_name TEXT``
       - ``source_type TEXT``
  2. Best-effort backfill from ``document_source_metadata`` (may be a noop
     when running against a standalone intelligence_db without cross-DB access).
  3. Creates a composite partial index for the ConfidenceWorker corroboration
     query:
       ``(canonical_type, source_type, source_name) WHERE processed = true``

downgrade() drops the index and both columns.

Mark: integration (requires running Postgres with pgvector).
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import text

pytestmark = pytest.mark.integration

# ── Constants ─────────────────────────────────────────────────────────────────

_TABLE_NAME = "relation_evidence_raw"
_INDEX_NAME = "idx_relation_evidence_source_diversity"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _column_exists(conn: sa.engine.Connection, table: str, column: str) -> bool:
    """Return True if ``column`` exists on ``table`` in the public schema."""
    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "  AND table_name = :tbl "
            "  AND column_name = :col"
        ),
        {"tbl": table, "col": column},
    ).fetchone()
    return row is not None


def _index_exists(conn: sa.engine.Connection, index_name: str) -> bool:
    """Return True if ``index_name`` is listed in pg_indexes."""
    row = conn.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = :idx"),
        {"idx": index_name},
    ).fetchone()
    return row is not None


def _get_indexdef(conn: sa.engine.Connection, index_name: str) -> str | None:
    """Return the indexdef string for index_name, or None if not found."""
    row = conn.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = :idx"),
        {"idx": index_name},
    ).fetchone()
    return row[0] if row is not None else None


# ── Upgrade contract — column existence ───────────────────────────────────────


def test_upgrade_adds_source_name_column(conn: sa.engine.Connection) -> None:
    """After upgrade: ``relation_evidence_raw.source_name`` must exist."""
    assert _column_exists(
        conn, _TABLE_NAME, "source_name"
    ), f"Column ``{_TABLE_NAME}.source_name`` missing — 0035 upgrade failed"


def test_upgrade_adds_source_type_column(conn: sa.engine.Connection) -> None:
    """After upgrade: ``relation_evidence_raw.source_type`` must exist."""
    assert _column_exists(
        conn, _TABLE_NAME, "source_type"
    ), f"Column ``{_TABLE_NAME}.source_type`` missing — 0035 upgrade failed"


def test_upgrade_source_name_is_nullable(conn: sa.engine.Connection) -> None:
    """``source_name`` must be nullable (no NOT NULL constraint).

    The migration explicitly adds the columns without a NOT NULL constraint
    (BP-126 compliance): rows inserted before the migration retain NULL values.
    """
    row = conn.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "  AND table_name = :tbl "
            "  AND column_name = 'source_name'"
        ),
        {"tbl": _TABLE_NAME},
    ).fetchone()
    assert row is not None, f"Column ``{_TABLE_NAME}.source_name`` not found"
    assert row[0] == "YES", f"``{_TABLE_NAME}.source_name`` must be nullable; got is_nullable={row[0]!r}"


def test_upgrade_source_type_is_nullable(conn: sa.engine.Connection) -> None:
    """``source_type`` must be nullable (no NOT NULL constraint)."""
    row = conn.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "  AND table_name = :tbl "
            "  AND column_name = 'source_type'"
        ),
        {"tbl": _TABLE_NAME},
    ).fetchone()
    assert row is not None, f"Column ``{_TABLE_NAME}.source_type`` not found"
    assert row[0] == "YES", f"``{_TABLE_NAME}.source_type`` must be nullable; got is_nullable={row[0]!r}"


# ── Upgrade contract — index ───────────────────────────────────────────────────


def test_upgrade_creates_source_diversity_index(conn: sa.engine.Connection) -> None:
    """After upgrade: ``idx_relation_evidence_source_diversity`` must exist."""
    assert _index_exists(conn, _INDEX_NAME), f"Index {_INDEX_NAME!r} not found in pg_indexes — 0035 upgrade failed"


def test_upgrade_source_diversity_index_is_partial(conn: sa.engine.Connection) -> None:
    """The diversity index must be a partial index on ``processed = true``."""
    indexdef = _get_indexdef(conn, _INDEX_NAME)
    assert indexdef is not None, f"Index {_INDEX_NAME!r} not found"
    assert "processed" in indexdef, (
        f"Index {_INDEX_NAME!r} missing ``processed`` partial predicate.\n" f"Got: {indexdef}"
    )


def test_upgrade_source_diversity_index_covers_canonical_type(conn: sa.engine.Connection) -> None:
    """The diversity index must cover ``canonical_type`` for the GROUP BY query."""
    indexdef = _get_indexdef(conn, _INDEX_NAME)
    assert indexdef is not None, f"Index {_INDEX_NAME!r} not found"
    assert "canonical_type" in indexdef, (
        f"Index {_INDEX_NAME!r} must include ``canonical_type`` column.\n" f"Got: {indexdef}"
    )


def test_upgrade_source_diversity_index_on_correct_table(conn: sa.engine.Connection) -> None:
    """The diversity index must be on ``relation_evidence_raw``."""
    row = conn.execute(
        text("SELECT tablename FROM pg_indexes WHERE indexname = :idx"),
        {"idx": _INDEX_NAME},
    ).fetchone()
    assert row is not None, f"Index {_INDEX_NAME!r} not found"
    assert row[0] == _TABLE_NAME, f"Index {_INDEX_NAME!r} is on {row[0]!r}, expected {_TABLE_NAME!r}"


# ── Forward-compat: write a row with new columns ──────────────────────────────


def test_forward_compat_source_columns_accept_text_values(conn: sa.engine.Connection) -> None:
    """source_name and source_type columns accept TEXT values — column type contract.

    This test verifies the column data type is 'text' so a future schema
    change (e.g., ENUM, restricted length, NOT NULL) fails here before
    reaching production.  We use information_schema rather than a live INSERT
    to avoid FK / mandatory-column complexity on relation_evidence_raw.
    """
    for col in ("source_name", "source_type"):
        row = conn.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "  AND table_name = :tbl "
                "  AND column_name = :col"
            ),
            {"tbl": _TABLE_NAME, "col": col},
        ).fetchone()
        assert row is not None, f"Column ``{_TABLE_NAME}.{col}`` not found"
        assert row[0] == "text", f"Column ``{_TABLE_NAME}.{col}`` expected type 'text', got {row[0]!r}"


def test_forward_compat_null_source_fields_accepted(conn: sa.engine.Connection) -> None:
    """Rows where source_name and source_type are NULL must still be insertable.

    The backfill is best-effort; rows from before the migration retain NULL.
    A future NOT NULL constraint on these columns would break old data.
    """
    # Verify via the schema inspection: is_nullable = YES (already checked
    # above) means NULL is accepted. We also verify column data_type = text.
    rows = conn.execute(
        text(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "  AND table_name = :tbl "
            "  AND column_name IN ('source_name', 'source_type') "
            "ORDER BY column_name"
        ),
        {"tbl": _TABLE_NAME},
    ).fetchall()
    # Both columns exist and have type 'text'.
    assert len(rows) == 2, f"Expected 2 source_* columns, found {len(rows)}"
    for col_name, data_type, is_nullable in rows:
        assert data_type == "text", f"Column ``{col_name}`` expected type 'text', got {data_type!r}"
        assert is_nullable == "YES", f"Column ``{col_name}`` must be nullable (best-effort backfill contract)"


# ── Downgrade contract ────────────────────────────────────────────────────────


def test_downgrade_sql_removes_index(conn: sa.engine.Connection) -> None:
    """Running the downgrade SQL must remove the diversity index.

    We execute the downgrade statements inside a rolled-back transaction to
    verify they produce the expected result without permanently modifying the
    session-scoped schema state.

    Note: ``DROP INDEX CONCURRENTLY`` requires autocommit outside a transaction
    block; the actual alembic downgrade() wraps it in autocommit_block().  For
    test purposes we use the non-CONCURRENTLY form to keep the test inside a
    regular transaction.
    """
    # Pre-condition: index must exist.
    assert _index_exists(conn, _INDEX_NAME), f"Pre-condition: {_INDEX_NAME!r} must exist"

    # Simulate downgrade — drop the index (non-CONCURRENTLY for test isolation).
    conn.execute(text(f"DROP INDEX IF EXISTS {_INDEX_NAME}"))

    # Index must be gone.
    assert not _index_exists(conn, _INDEX_NAME), f"Index {_INDEX_NAME!r} still present after downgrade SQL"

    # Roll back so the session-scoped fixture remains intact.
    conn.rollback()


def test_downgrade_sql_removes_source_columns(conn: sa.engine.Connection) -> None:
    """Running the downgrade DROP COLUMN statements removes both new columns.

    We roll back immediately so the session-scoped fixture stays valid.
    """
    # Pre-conditions.
    assert _column_exists(conn, _TABLE_NAME, "source_name"), "Pre-condition: source_name must exist"
    assert _column_exists(conn, _TABLE_NAME, "source_type"), "Pre-condition: source_type must exist"

    # Simulate downgrade.
    conn.execute(text(f"DROP INDEX IF EXISTS {_INDEX_NAME}"))
    conn.execute(
        text(f"ALTER TABLE {_TABLE_NAME} " "DROP COLUMN IF EXISTS source_name, " "DROP COLUMN IF EXISTS source_type")
    )

    assert not _column_exists(
        conn, _TABLE_NAME, "source_name"
    ), "Column ``source_name`` still present after downgrade SQL"
    assert not _column_exists(
        conn, _TABLE_NAME, "source_type"
    ), "Column ``source_type`` still present after downgrade SQL"

    conn.rollback()
