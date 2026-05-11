"""Add ``kind`` discriminator + invariants to ``portfolios``.

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-28

PLAN-0046 Wave 3 / T-46-3-01.

Adds a ``kind`` column (manual / brokerage / root) plus three invariants:

1. ``CHECK (kind IN ('manual','brokerage','root'))`` — enum guard at the DB.
2. ``UNIQUE (owner_id) WHERE kind = 'root'`` — at most one ROOT per user
   (partial unique index — Postgres-specific).
3. ``CHECK (NOT (kind = 'root' AND status = 'archived'))`` — root portfolios
   may never enter the archived state. The domain guard
   (``Portfolio.archive`` raising ``RootPortfolioNotArchivableError``) is
   the primary enforcement; this check exists as defense-in-depth.

Forward-compatibility (R11):
    - The new column is added with ``server_default='manual'`` so all
      pre-existing rows backfill atomically (BP-126).
    - The default is dropped after backfill so future writes must explicitly
      provide ``kind`` — preventing silent BROKERAGE→MANUAL drift if the ORM
      ever forgets to map the field.

Downgrade is fully reversible: the partial index + checks are dropped, then
the column. Dropping ``kind`` is a destructive change, but the rollback path
is symmetric and the migration is intended to ship paired with application
code that reads/writes ``kind``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Step 1: add the column with default so historical rows backfill ──
    op.add_column(
        "portfolios",
        sa.Column(
            "kind",
            sa.String(length=16),
            nullable=False,
            server_default="manual",
        ),
    )

    # ── Step 2: enum guard ──────────────────────────────────────────────
    # WHY a CHECK constraint (not a Postgres ENUM type): CHECK constraints
    # are easier to evolve forward (just rewrite the constraint) than ENUM
    # types (which need ALTER TYPE … ADD VALUE and special handling for
    # rolling deploys). The full enum is small and stable so a CHECK is
    # the simpler choice.
    op.create_check_constraint(
        "ck_portfolios_kind_valid",
        "portfolios",
        "kind IN ('manual','brokerage','root')",
    )

    # ── Step 3: at most one ROOT per owner (partial unique index) ───────
    # Postgres-specific: partial indexes let us enforce "one row matching
    # predicate P" without forbidding multiple non-matching rows.
    op.create_index(
        "uq_portfolios_owner_root",
        "portfolios",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'root'"),
    )

    # ── Step 4: root may never be archived ──────────────────────────────
    op.create_check_constraint(
        "ck_portfolios_root_not_archived",
        "portfolios",
        "NOT (kind = 'root' AND status = 'archived')",
    )

    # ── Step 5: drop the server default so future inserts must specify ──
    # WHY: the default existed only to backfill historical rows. Leaving it
    # in place would let buggy callers silently insert ``kind='manual'`` for
    # rows that should be BROKERAGE or ROOT. Removing it forces every code
    # path to be explicit (mapped_column carries default='manual' for
    # Python-side construction, which is fine — the ORM still emits the
    # value in INSERTs).
    op.alter_column("portfolios", "kind", server_default=None)


def downgrade() -> None:
    # Drop in reverse order: constraints/index first, then column.
    op.drop_constraint("ck_portfolios_root_not_archived", "portfolios", type_="check")
    op.drop_index("uq_portfolios_owner_root", table_name="portfolios")
    op.drop_constraint("ck_portfolios_kind_valid", "portfolios", type_="check")
    op.drop_column("portfolios", "kind")
