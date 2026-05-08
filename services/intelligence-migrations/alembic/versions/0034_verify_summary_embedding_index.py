"""Verify (or fix) the ``relation_summaries`` HNSW index partial condition.

Revision ID: 0034
Revises: 0033
Create Date: 2026-05-08

WHY (T-A-04 — PRD-0074 §8.6):
  Migration 0001 Block K created ``idx_relation_summary_emb_hnsw`` with the
  correct partial predicate ``WHERE is_current = true AND summary_embedding IS NOT NULL``.

  However, some older or manually-patched environments may have the index
  without the partial clause (e.g., created before the predicate was added to
  the schema spec), which causes:
    - HNSW scans to include stale/non-current summaries (wrong results).
    - Larger index size (all rows instead of only current ones).

  This migration is a noop-or-fix:
    - If the index already has BOTH ``is_current`` and ``summary_embedding IS NOT NULL``
      in its definition, the migration logs and exits (noop).
    - If the index is missing either condition, it is DROPped and recreated with
      the correct definition.

  ``downgrade()`` is a noop — idempotent; there is no "before" state to restore.

FORWARD-COMPATIBILITY (R5):
  Additive or noop — no existing data affected.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None

_INDEX_NAME = "idx_relation_summary_emb_hnsw"
_TABLE_NAME = "relation_summaries"


def upgrade() -> None:
    bind = op.get_bind()

    # Query pg_indexes for the current index definition.
    row = bind.execute(
        text("SELECT indexdef FROM pg_indexes " "WHERE tablename = :tbl AND indexname = :idx"),
        {"tbl": _TABLE_NAME, "idx": _INDEX_NAME},
    ).fetchone()

    if row is None:
        # Index does not exist at all — create it with the correct definition.
        with op.get_context().autocommit_block():
            op.execute(f"""
CREATE INDEX CONCURRENTLY {_INDEX_NAME}
    ON {_TABLE_NAME}
    USING hnsw (summary_embedding vector_cosine_ops)
    WHERE is_current = true AND summary_embedding IS NOT NULL
""")
        return

    indexdef: str = row[0]
    has_is_current = "is_current" in indexdef
    has_not_null = "summary_embedding IS NOT NULL" in indexdef

    if has_is_current and has_not_null:
        # Index is already correct — noop.
        return

    # Index exists but is missing one or both partial predicates: drop and recreate.
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}")
        op.execute(f"""
CREATE INDEX CONCURRENTLY {_INDEX_NAME}
    ON {_TABLE_NAME}
    USING hnsw (summary_embedding vector_cosine_ops)
    WHERE is_current = true AND summary_embedding IS NOT NULL
""")


def downgrade() -> None:
    # Noop — idempotent migration; there is no previous index state to restore.
    pass
