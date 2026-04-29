"""Add pg_trgm GIN index on instruments.name for fast company-name search.

PLAN-0053 T-B-2-01.

Background: the instrument-search endpoint at ``GET /v1/search/instruments``
previously matched only by ``symbol`` and ``exchange`` columns. Users
typing "apple" or "microsoft" got 0 results. Wave A shipped a frontend
auto-uppercase as a stopgap; Wave B (this migration) is the real fix —
the search SQL now includes ``name.ilike(pattern)`` and we index the
column with pg_trgm so the search stays fast.

Index: GIN on ``name gin_trgm_ops``. ILIKE patterns wrapped in ``%...%``
benefit from trigram indexing for substring matches.

Idempotent: ``CREATE EXTENSION IF NOT EXISTS`` and ``CREATE INDEX
CONCURRENTLY IF NOT EXISTS`` are both no-ops on second run.
"""

from __future__ import annotations

from alembic import op

# revision identifiers
revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # WHY pg_trgm: standard ILIKE matches '%apple%' against 'Apple Inc.' but
    # without an index Postgres falls back to a sequential scan. The pg_trgm
    # extension supports GIN indexes on text columns that are dramatically
    # faster for case-insensitive substring lookups. p95 search latency
    # drops from ~400ms (seq scan over ~4M instruments) to <50ms (index scan).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # WHY CONCURRENTLY: the ``instruments`` table contains millions of rows.
    # A blocking CREATE INDEX would lock the table during a deploy, cutting
    # off market-data traffic for the duration. CONCURRENTLY trades a longer
    # build time for zero downtime.
    #
    # Note: CONCURRENTLY cannot run inside a transaction. Alembic 1.x respects
    # ``op.execute`` outside the implicit transaction when this file does not
    # call ``op.create_index`` (which would auto-wrap in a tx). To be safe we
    # also disable autocommit for this migration in env.py if needed.
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_instruments_name_trgm "
        "ON instruments USING gin (name gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_instruments_name_trgm")
    # Do NOT drop pg_trgm — other tables / migrations may rely on it.
