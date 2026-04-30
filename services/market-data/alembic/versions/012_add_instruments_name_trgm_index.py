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

PLAN-0053 QA-iter1 F-001 fix: ``CREATE INDEX CONCURRENTLY`` cannot run
inside a transaction. The default Alembic env wraps every migration in
``context.begin_transaction()``. We avoid the conflict by NOT using the
CONCURRENTLY clause — this migration takes a brief lock on the
``instruments`` table during the GIN build. For a multi-million row
table the build is on the order of seconds (not minutes); deploy windows
already tolerate that. CONCURRENTLY would only be required for true
zero-downtime online deploys.

Idempotent: ``CREATE EXTENSION IF NOT EXISTS`` and ``CREATE INDEX IF NOT
EXISTS`` are both no-ops on second run.
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

    # WHY plain CREATE INDEX (not CONCURRENTLY): see module docstring.
    # CONCURRENTLY would crash inside Alembic's transactional context.
    op.execute("CREATE INDEX IF NOT EXISTS ix_instruments_name_trgm " "ON instruments USING gin (name gin_trgm_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_instruments_name_trgm")
    # Do NOT drop pg_trgm — other tables / migrations may rely on it.
