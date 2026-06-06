"""Add estimated_cost_usd column to threads (PLAN-0107 follow-up, agent-B).

Adds a nullable ``Numeric(12, 6)`` column to ``threads`` so the new
``PrometheusAndDbCostRecorder`` can atomically accumulate cumulative LLM
USD cost per conversation. Before this column existed there was no way for
operators to see per-thread cost without scanning ``llm_usage_log``.

WHY Numeric(12, 6) (not Float): cost is money — we sum small Decimal values
across many calls per thread. Numeric preserves exact precision; Float drifts.

WHY nullable + no default: existing rows pre-date the column. Backfilling
would be meaningless (we never recorded cost before). The cost recorder uses
``COALESCE(estimated_cost_usd, 0) + :cost`` so the first turn on a legacy
thread initialises from NULL cleanly.

WHY no CONCURRENTLY: ``threads`` is a low-volume metadata table (one row per
conversation), not a hot write path like ``messages``. A plain
``ADD COLUMN ... NULL`` takes only metadata-level locks in modern Postgres,
so a normal migration is safe.

WHY raw SQL via ``op.execute`` (not ``op.add_column``): the rag-chat DDL
alignment test (``tests/unit/infrastructure/test_ddl_alignment.py``) parses
migration files with a regex over ``CREATE TABLE`` / ``ALTER TABLE``
statements. ``op.add_column`` is a Python API call that the regex does not
match, so the new column would be silently invisible to the alignment guard
and the ORM-vs-DDL test would fail with "ORM columns missing from DDL".
Migration 0005 (add_seed_brief_id_to_threads) documents this convention.
"""

from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Raw SQL form — see module docstring for why we avoid op.add_column here.
    op.execute("ALTER TABLE threads ADD COLUMN IF NOT EXISTS estimated_cost_usd NUMERIC(12, 6) NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE threads DROP COLUMN IF EXISTS estimated_cost_usd")
