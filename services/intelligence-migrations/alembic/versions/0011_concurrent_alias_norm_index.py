"""Recreate idx_entity_aliases_norm_stage2 CONCURRENTLY.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-01

PLAN-0057 follow-up Wave A — closes investigation finding D-005.

Background: migration 0010 added ``idx_entity_aliases_norm_stage2`` via plain
``CREATE INDEX IF NOT EXISTS``. On a development DB (~38 alias rows) this
completes in microseconds and nobody noticed; on a production-scale
``entity_aliases`` table (~100k+ rows) the same statement takes an
``ACCESS EXCLUSIVE`` lock and blocks every concurrent INSERT/UPDATE for
seconds-to-minutes — a self-DOS pattern.

This migration drops the existing index and recreates it with
``CREATE INDEX CONCURRENTLY``, which uses ``SHARE UPDATE EXCLUSIVE`` instead
and lets writes proceed while the index builds. The brief no-index window
between DROP and CREATE only degrades Stage-2 resolution latency (seq scan
~50-100ms on 100k rows) — it does not break correctness.

Implementation notes:
  * ``CREATE INDEX CONCURRENTLY`` cannot run inside a transaction. We use
    ``op.get_context().autocommit_block()`` to switch the connection to
    autocommit for the duration of these statements.
  * The index definition (columns, partial WHERE) MUST match 0010 exactly so
    rolling forward from a fresh DB produces the same end state.
  * Forward-only: we never try to recreate the non-CONCURRENTLY variant on
    downgrade; the downgrade just drops the index.
"""

from __future__ import annotations

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop and recreate the Stage-2 alias index CONCURRENTLY (no write lock)."""
    # CONCURRENTLY requires autocommit — Alembic normally wraps everything in a tx.
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX IF EXISTS idx_entity_aliases_norm_stage2")
        # NOTE: the column list, partial predicate, and index name MUST match
        # the definition added in migration 0010. The only difference is the
        # CONCURRENTLY keyword.
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entity_aliases_norm_stage2
                ON entity_aliases (normalized_alias_text, alias_type)
                WHERE is_active = true
                  AND alias_type IN ('TICKER', 'PRIMARY_TICKER', 'ISIN')
            """
        )


def downgrade() -> None:
    """Drop the index. Idempotent — safe to run repeatedly."""
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX IF EXISTS idx_entity_aliases_norm_stage2")
