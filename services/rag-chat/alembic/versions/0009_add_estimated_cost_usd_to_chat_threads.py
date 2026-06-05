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
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "threads",
        sa.Column(
            "estimated_cost_usd",
            sa.Numeric(12, 6),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("threads", "estimated_cost_usd")
