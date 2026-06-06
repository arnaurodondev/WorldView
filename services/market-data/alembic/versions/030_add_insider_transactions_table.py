"""Add insider_transactions table + snapshot column + L-4b screen field seed.

Revision ID: 030
Revises: 024
Create Date: 2026-05-28

PLAN-0089 Wave L-4b (T-WL4B-01, T-WL4B-06).

WHY down_revision="024" (skipping 025-029):
  Migrations 025-029 are produced in parallel sibling worktrees (L-4a → 025,
  L-5c → 028, L-3 → 029). Same skip-pattern as the L-3 migration; the
  integrator linearises on merge. The DDL touched here is independent of
  any change in 025-029 (we create a brand-new table, add a new nullable
  column, and seed one new screen_field_metadata row), so the skip is safe.

WHY THREE-IN-ONE (table + column + seed):
  All three changes are logically a single L-4b unit — the snapshot column
  and the seed row only make sense once the table they describe exists.
  Splitting would force a brittle dependency chain (032 requires 031 which
  requires 030) without any rollback safety benefit.

LOCK-STEP REQUIREMENT (CRITICAL):
  The ``insider_net_buy_90d`` screen_field_metadata row inserted below MUST
  be byte-identical to the L-4b entry appended to
  ``_get_static_screen_fields()`` in ``app.py``. Divergence causes the 6-hour
  refresh loop to silently overwrite this migration's row with different
  values. See ``services/market-data/.claude-context.md`` pitfall L-4b.

DOWNGRADE: drop the screen field row, then the snapshot column, then the
  insider_transactions table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the insider_transactions table, snapshot column and seed row."""
    # ── 1. insider_transactions table ────────────────────────────────────────
    # IF NOT EXISTS guards re-run on partially-applied dev volumes (BP-126).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS insider_transactions (
            id                UUID         NOT NULL PRIMARY KEY,
            instrument_id     UUID         NOT NULL
                              REFERENCES instruments (id) ON DELETE CASCADE,
            filer_name        VARCHAR(255) NOT NULL,
            filer_title       VARCHAR(255) NULL,
            transaction_date  DATE         NOT NULL,
            transaction_type  VARCHAR(16)  NOT NULL,
            shares            NUMERIC(20,4) NOT NULL,
            price_per_share   NUMERIC(20,4) NULL,
            -- Derived: shares * price; sign reflects direction (negative for SELL/GIFT).
            net_value_usd     NUMERIC(20,2) NULL,
            source            VARCHAR(32)  NOT NULL DEFAULT 'EODHD',
            ingested_at       TIMESTAMPTZ  NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
            CONSTRAINT ck_insider_transactions_type
                CHECK (transaction_type IN ('BUY', 'SELL', 'GIFT', 'OTHER')),
            CONSTRAINT uq_insider_transactions_natural_key
                UNIQUE (instrument_id, filer_name, transaction_date, transaction_type, shares)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_insider_transactions_instrument_date
        ON insider_transactions (instrument_id, transaction_date DESC)
        """
    )

    # ── 2. instrument_fundamentals_snapshot.insider_net_buy_90d column ──────
    # ADD COLUMN IF NOT EXISTS is supported by Postgres 9.6+; idempotent so
    # re-runs after partial application are safe.
    op.execute(
        """
        ALTER TABLE instrument_fundamentals_snapshot
        ADD COLUMN IF NOT EXISTS insider_net_buy_90d NUMERIC(20,2) NULL
        """
    )

    # ── 3. screen_field_metadata seed (lock-step with app.py) ───────────────
    # field_type='numeric' (CHECK constraint admits only 'numeric'/'text'),
    # unit='currency_compact' (frontend renders $1.2M / $5B). Matches the
    # L-4b entry in ``_get_static_screen_fields()``.
    sql = (
        "INSERT INTO screen_field_metadata "
        "(field_name, label, field_type, unit, description, null_fraction) "
        "VALUES (:field_name, :label, :field_type, :unit, :description, 0) "
        "ON CONFLICT (field_name) DO NOTHING"
    )
    op.execute(
        sa.text(sql).bindparams(
            field_name="insider_net_buy_90d",
            label="INSIDER 90D",
            field_type="numeric",
            unit="currency_compact",
            description="Trailing 90-day net dollar value of insider transactions",
        )
    )


def downgrade() -> None:
    """Drop seed row, snapshot column, then the insider_transactions table."""
    op.execute(
        sa.text("DELETE FROM screen_field_metadata WHERE field_name = :field_name").bindparams(
            field_name="insider_net_buy_90d"
        )
    )
    op.execute("ALTER TABLE instrument_fundamentals_snapshot " "DROP COLUMN IF EXISTS insider_net_buy_90d")
    op.execute("DROP INDEX IF EXISTS ix_insider_transactions_instrument_date")
    op.execute("DROP TABLE IF EXISTS insider_transactions")
