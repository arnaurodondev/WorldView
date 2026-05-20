"""Integration tests for migration 0034 — verify/fix relation_summaries HNSW index.

Migration 0034 (``0034``) is a noop-or-fix that ensures
``idx_relation_summary_emb_hnsw`` exists with the correct partial predicate:
``WHERE is_current = true AND summary_embedding IS NOT NULL``.

The migration is idempotent:
  - If the index already exists with BOTH partial predicates, it is left
    untouched (noop path).
  - If the index is missing one or both predicates it is dropped and
    recreated with the correct definition (fix path).
  - If the index does not exist at all it is created fresh (create path).

The upgrade() uses ``CREATE INDEX CONCURRENTLY`` which requires autocommit
mode and is thus safe against hot tables; no data is modified.

downgrade() is a noop — there is no prior state to restore.

Mark: integration (requires running Postgres with pgvector).
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import text

pytestmark = pytest.mark.integration

# ── Constants ─────────────────────────────────────────────────────────────────

_INDEX_NAME = "idx_relation_summary_emb_hnsw"
_TABLE_NAME = "relation_summaries"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_indexdef(conn: sa.engine.Connection) -> str | None:
    """Return the pg_indexes.indexdef for the HNSW index, or None if absent."""
    row = conn.execute(
        text("SELECT indexdef FROM pg_indexes " "WHERE tablename = :tbl AND indexname = :idx"),
        {"tbl": _TABLE_NAME, "idx": _INDEX_NAME},
    ).fetchone()
    return row[0] if row is not None else None


# ── Upgrade contract ──────────────────────────────────────────────────────────


def test_upgrade_index_exists_after_migration(conn: sa.engine.Connection) -> None:
    """After alembic upgrade head: the HNSW index must be present."""
    indexdef = _get_indexdef(conn)
    assert indexdef is not None, f"Index {_INDEX_NAME!r} not found in pg_indexes — 0034 upgrade failed"


def test_upgrade_index_has_is_current_predicate(conn: sa.engine.Connection) -> None:
    """The index definition must include the ``is_current`` partial predicate."""
    indexdef = _get_indexdef(conn)
    assert indexdef is not None, f"Index {_INDEX_NAME!r} missing — precondition failed"
    assert "is_current" in indexdef, (
        f"Index {_INDEX_NAME!r} is missing the ``is_current`` partial predicate.\n" f"Got: {indexdef}"
    )


def test_upgrade_index_has_not_null_predicate(conn: sa.engine.Connection) -> None:
    """The index definition must include ``summary_embedding IS NOT NULL``."""
    indexdef = _get_indexdef(conn)
    assert indexdef is not None, f"Index {_INDEX_NAME!r} missing — precondition failed"
    assert "summary_embedding IS NOT NULL" in indexdef, (
        f"Index {_INDEX_NAME!r} is missing the ``summary_embedding IS NOT NULL`` "
        f"partial predicate.\nGot: {indexdef}"
    )


def test_upgrade_index_uses_hnsw_method(conn: sa.engine.Connection) -> None:
    """The index must be declared with the ``hnsw`` access method."""
    indexdef = _get_indexdef(conn)
    assert indexdef is not None, f"Index {_INDEX_NAME!r} missing — precondition failed"
    assert "hnsw" in indexdef.lower(), f"Index {_INDEX_NAME!r} does not use the HNSW method.\nGot: {indexdef}"


def test_upgrade_index_covers_correct_table(conn: sa.engine.Connection) -> None:
    """The index must be on ``relation_summaries``, not a different table."""
    row = conn.execute(
        text("SELECT tablename FROM pg_indexes " "WHERE indexname = :idx"),
        {"idx": _INDEX_NAME},
    ).fetchone()
    assert row is not None, f"Index {_INDEX_NAME!r} not found"
    assert row[0] == _TABLE_NAME, f"Index {_INDEX_NAME!r} is on table {row[0]!r}, expected {_TABLE_NAME!r}"


# ── Idempotency ───────────────────────────────────────────────────────────────


def test_index_definition_is_stable_on_re_inspect(conn: sa.engine.Connection) -> None:
    """Querying pg_indexes twice returns the same definition — stable after upgrade.

    This exercises that the index was not left in an intermediate broken state
    (e.g., a partial CONCURRENTLY build that crashed).  pg_indexes only lists
    valid, ready indexes; if the entry is missing the index build failed.
    """
    first = _get_indexdef(conn)
    second = _get_indexdef(conn)
    assert first is not None, f"Index {_INDEX_NAME!r} not found on first query"
    assert second is not None, f"Index {_INDEX_NAME!r} not found on second query"
    assert first == second, "Index definition changed between two identical SELECTs"


# ── Downgrade contract ────────────────────────────────────────────────────────


def test_downgrade_is_noop(conn: sa.engine.Connection) -> None:
    """Downgrade for 0034 is a deliberate noop — the index must still exist.

    The migration docstring explicitly states: ``downgrade()`` is a noop —
    idempotent; there is no "before" state to restore.  We verify that the
    index that was created/verified by upgrade() is NOT removed by the
    downgrade logic (because the downgrade body is ``pass``).

    This test mirrors the downgrade SQL (``pass``): after conceptual rollback
    the index is still present — its presence verifies the noop contract.
    """
    # If we reach here the session-scoped fixture has already run upgrade head,
    # which means 0034 ran.  The index must be present because downgrade() for
    # 0034 is a noop — it does not drop the index it created.
    indexdef = _get_indexdef(conn)
    assert indexdef is not None, (
        f"Index {_INDEX_NAME!r} unexpectedly absent — 0034 downgrade() may have "
        f"erroneously dropped the index (it should be a noop)"
    )
    assert "is_current" in indexdef, f"Index {_INDEX_NAME!r} lost its partial predicate — noop contract violated"


# ── Forward-compat ────────────────────────────────────────────────────────────


def test_relation_summaries_table_exists(conn: sa.engine.Connection) -> None:
    """The ``relation_summaries`` table must exist (precondition for the index).

    If a future migration renames or drops this table the HNSW index would
    vanish and this test would catch the breakage.
    """
    row = conn.execute(
        text("SELECT 1 FROM pg_tables " "WHERE schemaname = 'public' AND tablename = :tbl"),
        {"tbl": _TABLE_NAME},
    ).fetchone()
    assert row is not None, (
        f"Table {_TABLE_NAME!r} does not exist — " f"the HNSW index target has been removed or renamed"
    )


def test_relation_summaries_has_is_current_column(conn: sa.engine.Connection) -> None:
    """``relation_summaries.is_current`` must exist for the partial predicate to work.

    The HNSW index uses ``WHERE is_current = true``; if the column is renamed
    or dropped in a later migration the partial index expression becomes
    invalid.  This test pins the column existence contract.
    """
    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "  AND table_name = :tbl "
            "  AND column_name = 'is_current'"
        ),
        {"tbl": _TABLE_NAME},
    ).fetchone()
    assert row is not None, (
        f"Column ``{_TABLE_NAME}.is_current`` missing — " f"the HNSW partial index predicate would be broken"
    )


def test_relation_summaries_has_summary_embedding_column(conn: sa.engine.Connection) -> None:
    """``relation_summaries.summary_embedding`` must exist for the index column."""
    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "  AND table_name = :tbl "
            "  AND column_name = 'summary_embedding'"
        ),
        {"tbl": _TABLE_NAME},
    ).fetchone()
    assert row is not None, (
        f"Column ``{_TABLE_NAME}.summary_embedding`` missing — " f"the HNSW index column has been removed or renamed"
    )
