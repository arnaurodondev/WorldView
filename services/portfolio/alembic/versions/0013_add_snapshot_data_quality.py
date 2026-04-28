"""Add ``data_quality`` column to ``portfolio_value_snapshots``.

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-28

PLAN-0046 iter-4 / F-401.

Why this column exists:
    Before this column the snapshot worker had no way to record that
    one or more holdings were priced from a stale (or unavailable) bar.
    A missing OHLCV bar silently zeroed that holding's contribution
    and the persisted ``total_value`` therefore drifted away from the
    live exposure card without any user-visible signal.

    With ``data_quality`` we can surface three states:
      * ``"ok"`` — every holding had a fresh close on ``snapshot_date``.
      * ``"partial_prices"`` — at least one holding was priced from a
        prior trading day (lookback fallback) OR from cost basis.
      * (reserved) ``"empty"`` — no holdings; written for future use.

Forward-compatibility (R11):
    * NOT NULL with ``server_default = 'ok'`` so the column is safe to
      apply on a populated DB without an UPDATE statement. Rows written
      before this migration default to ``ok`` (correct in aggregate —
      the iter-3/iter-4 snapshot pipeline never recorded fallbacks, so
      pre-existing rows are by definition either correct ok rows or
      undercounts that we cannot retroactively reclassify; defaulting
      ``ok`` keeps the read path simple and the catch-up backfill is
      what fixes any historical undercounts).
    * VARCHAR(32) gives us room to add states like ``stale_quotes`` or
      ``backfill_pending`` later without another migration.

Idempotency:
    The forward DDL is wrapped in a guard so re-running the migration on
    a DB that already had this column applied is a no-op. This matches
    the iter-2 hardening pattern used elsewhere in this service.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Idempotent guard — older dev DBs may have a previous half-applied
    # iteration of this migration. Skipping the ADD COLUMN when the column
    # already exists keeps ``alembic upgrade head`` stable across resyncs.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("portfolio_value_snapshots")}
    if "data_quality" in columns:
        return

    op.add_column(
        "portfolio_value_snapshots",
        sa.Column(
            "data_quality",
            sa.String(length=32),
            nullable=False,
            # ``server_default`` is required for the NOT NULL constraint
            # to be applied without an explicit UPDATE on existing rows
            # (BP-126 — NOT NULL Alembic columns must have server_default).
            server_default="ok",
        ),
    )


def downgrade() -> None:
    op.drop_column("portfolio_value_snapshots", "data_quality")
