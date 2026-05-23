"""Add description column to transactions table.

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-23

P2-E (Wave G): broker-supplied human-readable description for a transaction
(e.g. "Dividend Payment - AAPL"). The domain entity and brokerage-sync-worker
already carry this field; this migration persists it to the DB and surfaces it
via TransactionListItem in the API response.

Forward-compatibility: nullable + no default means existing rows get NULL,
which the API serialises as null (the frontend renders it as absent subline).
Rollback: simply drops the column (no data loss — the field is supplementary
annotation, not a business-critical value).
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # WHY nullable with no server_default: historical rows pre-dating this
    # migration have no description data. NULL is honest ("not populated for
    # this transaction") and matches the domain entity's `str | None` type.
    op.add_column(
        "transactions",
        sa.Column("description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transactions", "description")
